"""Natural-language Q&A over the warehouse.

Claude answers by calling ``run_sql`` (guarded, read-only DuckDB) and ``get_metric_definitions``.
The final answer is structured JSON and every number in it is checked against the rows the
queries actually returned. Offline mode answers KPI questions from the governed KPI snapshot.

    python -m ai_analyst.cli ask "What was the approval rate for Salary Advance last month?"
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

import duckdb
import pandas as pd

from ai_analyst.grounding import validate_answer
from ai_analyst.llm import MODEL, LLMUnavailable, create_message, text_of
from ai_analyst.prompts import QA_ANSWER_SCHEMA, QA_SYSTEM, QA_TOOLS
from ai_analyst.sql_guard import SQLGuardError, allowed_tables_from, validate_sql
from python.config import Settings, get_settings
from python.io_utils import read_json
from python.kpi_definitions import KPIS


def describe_schema(con) -> str:
    cols = con.execute("""SELECT table_schema, table_name, string_agg(column_name || ' ' || data_type, ', ' ORDER BY ordinal_position)
                          FROM information_schema.columns WHERE table_schema IN ('marts', 'core')
                          GROUP BY 1, 2 ORDER BY 1 DESC, 2""").fetchall()
    return "\n".join("- %s.%s(%s)" % r for r in cols)


def _connect(settings: Settings):
    return duckdb.connect(str(settings.warehouse_path), read_only=True, config={"enable_external_access": False})


def _run_tool(con, name: str, args: Dict, allowed: List[str], results: Dict) -> Dict:
    if name == "get_metric_definitions":
        defs = [{k: v for k, v in kp.items() if k in ("id", "name", "unit", "direction", "definition", "formula", "target")}
                for kp in KPIS]
        return {"content": json.dumps(defs, default=str)}
    if name != "run_sql":
        return {"content": "unknown tool %s" % name, "is_error": True}
    try:
        sql = validate_sql(args.get("sql", ""), allowed)
        df = con.execute(sql).df()
    except SQLGuardError as exc:
        return {"content": "Query rejected by guard: %s" % exc, "is_error": True}
    except duckdb.Error as exc:
        return {"content": "SQL error: %s" % str(exc).splitlines()[0], "is_error": True}
    qid = "Q%d" % (len(results) + 1)
    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    results[qid] = {"sql": args.get("sql"), "purpose": args.get("purpose"), "rows": rows}
    return {"content": json.dumps({"query_id": qid, "columns": list(df.columns), "row_count": len(rows), "rows": rows},
                                  default=str)}


def ask(question: str, settings: Optional[Settings] = None, offline: bool = False, max_turns: int = 8) -> Dict:
    settings = settings or get_settings()
    if offline:
        return offline_answer(question, settings)
    con = _connect(settings)
    try:
        allowed = allowed_tables_from(con)
        system = [{"type": "text", "text": QA_SYSTEM + describe_schema(con), "cache_control": {"type": "ephemeral"}}]
        messages: List[Dict] = [{"role": "user", "content": question}]
        results: Dict[str, Dict] = {}
        for _ in range(max_turns):
            resp = create_message(system, messages, json_schema=QA_ANSWER_SCHEMA, tools=QA_TOOLS, effort="medium")
            messages.append({"role": "assistant", "content": resp["content"]})
            calls = [b for b in resp["content"] if b.get("type") == "tool_use"]
            if resp["stop_reason"] == "tool_use" and calls:
                tool_results = []
                for b in calls:
                    out = _run_tool(con, b["name"], b.get("input") or {}, allowed, results)
                    tr = {"type": "tool_result", "tool_use_id": b["id"], "content": out["content"]}
                    if out.get("is_error"):
                        tr["is_error"] = True
                    tool_results.append(tr)
                messages.append({"role": "user", "content": tool_results})
                continue
            answer = json.loads(text_of(resp["content"]))
            validation = validate_answer(answer["answer"], results)
            return {"mode": "claude", "model": resp["model"], "question": question, "answer": answer,
                    "queries": results, "validation": validation}
        raise LLMUnavailable("no final answer within %d turns" % max_turns)
    finally:
        con.close()


# ------------------------------------------------------------------ offline fallback
SYNONYMS = {"approval": "approval_rate", "approve": "approval_rate", "kyc": "kyc_completion_rate_7d",
            "revenue": "gross_revenue", "disburs": "loans_disbursed", "loans": "loans_disbursed", "par": "par30_rate",
            "delinquen": "par30_rate", "npa": "npa_rate", "fpd": "fpd30_rate", "first payment": "fpd30_rate",
            "mau": "mau", "active user": "mau", "csat": "csat_avg", "satisfaction": "csat_avg", "ticket": "support_tickets",
            "cac": "blended_cac", "acquisition cost": "blended_cac", "autopay": "autopay_adoption_rate",
            "collection": "collection_efficiency", "failure": "payment_failure_rate", "repeat": "repeat_loan_share",
            "signup": "new_customers", "new customer": "new_customers", "aum": "outstanding_principal",
            "outstanding": "outstanding_principal", "ticket size": "avg_ticket_size", "spend": "marketing_spend"}


def offline_answer(question: str, settings: Settings) -> Dict:
    snap = read_json(settings.outputs_dir / "kpis" / "kpi_snapshot.json")
    q = question.lower()
    hits = []
    for key, kid in SYNONYMS.items():
        if key in q and kid not in hits:
            hits.append(kid)
    for kp in KPIS:
        if kp["name"].lower() in q and kp["id"] not in hits:
            hits.insert(0, kp["id"])
    monthly = {k["id"]: k for k in snap["monthly"]}
    found = [monthly[h] for h in hits if h in monthly]
    if not found:
        return {"mode": "offline", "question": question,
                "answer": {"answer": "Offline mode can only answer questions about the governed KPIs (e.g. approval rate, "
                                     "PAR30, revenue, KYC completion). Set ANTHROPIC_API_KEY (or run `ant auth login`) "
                                     "to ask ad-hoc questions that need new SQL.", "key_numbers": [], "caveats": []},
                "queries": {}, "validation": {"grounded": True, "numbers_checked": 0, "ungrounded_numbers": []}}
    parts = []
    for k in found[:3]:
        txt = "%s for %s was %s (prior month %s, %s)." % (k["name"], pd.Timestamp(k["period"] + "-01").strftime("%b %Y"),
                                                          k["value_fmt"], k["previous_fmt"], k["delta_fmt"])
        if k["target_status"]:
            txt += " Target %s %s: %s." % (k["target_op"], k["target_fmt"], k["target_status"].replace("_", " "))
        txt += " Definition: %s" % k["definition"]
        parts.append(txt)
    return {"mode": "offline", "question": question,
            "answer": {"answer": " ".join(parts), "key_numbers": [{"value_text": k["value_fmt"], "query_id": "kpi_snapshot"}
                                                                  for k in found[:3]],
                       "caveats": ["Answered from the governed KPI snapshot (offline mode); synthetic data."]},
            "queries": {}, "validation": {"grounded": True, "numbers_checked": len(found[:3]), "ungrounded_numbers": []}}
