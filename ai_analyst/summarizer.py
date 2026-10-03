"""Weekly executive summary: Claude writes it from the fact sheet, the grounding checker verifies it.

Flow: build fact sheet -> Claude (structured JSON) -> numeric validation -> up to 2 targeted retries
-> drop anything still unverified -> render Markdown with a citation for every statement.
Without credentials (or with --offline) a deterministic, template-based summariser produces the same
structure from the same facts, so the pipeline always ships a summary.

    python -m ai_analyst.cli summary [--offline]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ai_analyst.fact_sheet import build_fact_sheet, facts_for_prompt, save_fact_sheet
from ai_analyst.grounding import drop_ungrounded, summary_items, validate_summary
from ai_analyst.llm import MODEL, LLMUnavailable, create_message, text_of
from ai_analyst.prompts import RETRY_USER, SUMMARY_SCHEMA, SUMMARY_SYSTEM, SUMMARY_USER
from python.config import COMPANY_NAME, Settings, get_settings
from python.io_utils import write_json

log = logging.getLogger(__name__)
SECTIONS = [("highlights", "Highlights"), ("kpi_movements", "KPI movements"), ("anomalies", "Anomalies"),
            ("experiments", "Experiments"), ("risks", "Risks"), ("recommendations", "Recommendations"),
            ("data_caveats", "Data caveats")]


# ------------------------------------------------------------------ Claude path
def _llm_summary(sheet: Dict, max_retries: int = 2) -> Tuple[Dict, Dict, Dict]:
    system = [{"type": "text", "text": SUMMARY_SYSTEM, "cache_control": {"type": "ephemeral"}}]
    week = sheet.get("reporting_week") or {}
    user = SUMMARY_USER.format(month=sheet["reporting_month"], week="%s to %s" % (week.get("start"), week.get("end")),
                               as_of=sheet["as_of_date"], facts=facts_for_prompt(sheet))
    messages: List[Dict] = [{"role": "user", "content": user}]
    meta = {"model": MODEL, "attempts": 0, "usage": []}
    summary, validation = None, None
    for attempt in range(max_retries + 1):
        resp = create_message(system, messages, json_schema=SUMMARY_SCHEMA, effort="high")
        meta["attempts"] += 1
        meta["usage"].append(resp["usage"])
        meta["model"] = resp["model"]
        summary = json.loads(text_of(resp["content"]))
        validation = validate_summary(summary, sheet["facts"])
        if validation["grounded"] or attempt == max_retries:
            break
        problems = "\n".join("- [%s] %s -> %s: %s" % (p["section"], p["text"], p["issue"], ", ".join(map(str, p["detail"])))
                             for p in validation["problems"])
        messages.append({"role": "assistant", "content": resp["content"]})
        messages.append({"role": "user", "content": RETRY_USER.format(problems=problems)})
    removed: List[str] = []
    if not validation["grounded"]:
        summary, removed = drop_ungrounded(summary, validation)
        validation = validate_summary(summary, sheet["facts"])
    validation["removed_items"] = removed
    return summary, validation, meta


# ------------------------------------------------------------------ deterministic path
RECOMMENDATIONS = {
    # kpi_id: (text, owner, extra fact topics to cite)
    "kyc_completion_rate_7d": ("Extend the redesigned onboarding (trust signals, DigiLocker one-tap, progress bar) to the "
                               "web flow, where KYC completion trails the apps, and A/B test it there first.",
                               "Growth & Onboarding", ("funnel", "experiment")),
    "payment_failure_rate": ("Make autopay mandate set-up the default step at disbursal and schedule debit retries around "
                             "salary-credit dates; autopay borrowers repay on time more often.",
                             "Collections & Repayments", ("repayments",)),
    "collection_efficiency": ("Add pre-due-date reminders (three days and one day before the EMI date) and same-day "
                              "retries for failed auto-debits.",
                              "Collections & Repayments", ()),
    "csat_avg": ("Attack the top ticket drivers (KYC issues, payment failures) with in-app self-serve fixes and a "
                 "first-response SLA; CSAT is below target.", "Customer Support", ()),
    "par30_rate": ("Review cut-offs for the highest-risk segments before the next festive campaign.", "Credit Risk", ("risk",)),
    "npa_rate": ("Increase early-stage collections capacity (accounts in their first month past due) to stop "
                 "roll-forward into NPA.", "Collections", ()),
    "fpd30_rate": ("Add a first-EMI reminder and autopay check for new-to-credit borrowers.", "Credit Risk", ()),
    "cost_per_new_borrower": ("Shift paid budget from affiliate and paid social towards referral and employer partnerships, "
                              "which return the most value per rupee of acquisition cost.", "Marketing", ("unit_economics",)),
}


def _first(facts: List[Dict], topic: str, pred=lambda f: True) -> Optional[Dict]:
    return next((f for f in facts if f["topic"] == topic and pred(f)), None)


def deterministic_summary(sheet: Dict) -> Dict:
    facts = sheet["facts"]
    kpi = {f["data"]["kpi"]: f for f in facts if f["topic"] == "kpi_monthly"}
    month = pd.Timestamp(sheet["reporting_month"] + "-01").strftime("%b %Y")

    def short(k: str) -> str:
        d = kpi[k]["data"]
        return "%s %s (%s vs prior month)" % (d["name"], d["value_fmt"], d["delta_fmt"])

    off = [f for f in kpi.values() if f["data"]["target_status"] == "off_track"]
    head_ids = [kpi[k]["id"] for k in ("gross_revenue", "loans_disbursed") if k in kpi]
    head = "%s: %s; %s." % (month, short("gross_revenue"), short("loans_disbursed"))
    if off:
        head = head[:-1] + "; %s remains below target at %s." % (off[0]["data"]["name"], off[0]["data"]["value_fmt"])
        head_ids.append(off[0]["id"])
    summary: Dict = {"headline": {"text": head, "fact_ids": head_ids}}

    hl = []
    weekly = {f["data"]["kpi"]: f for f in facts if f["topic"] == "kpi_weekly"}
    wk = [k for k in ("loans_disbursed", "disbursed_amount", "collections_amount", "payment_failure_rate") if k in weekly]
    if wk:
        week = (sheet.get("reporting_week") or {}).get("start")
        label = pd.Timestamp(week).strftime("%d %b") if week else "this week"
        hl.append({"text": "Week of %s: " % label + "; ".join(
            "%s %s (%s week on week)" % (weekly[k]["data"]["name"], weekly[k]["data"]["value_fmt"], weekly[k]["data"]["delta_fmt"])
            for k in wk) + ".", "fact_ids": [weekly[k]["id"] for k in wk]})
    for group in (("disbursed_amount", "net_revenue"), ("kyc_completion_rate_7d", "approval_rate"),
                  ("par30_rate", "npa_rate"), ("mau", "repeat_loan_share")):
        present = [k for k in group if k in kpi]
        if present:
            hl.append({"text": "; ".join(short(k) for k in present) + ".",
                       "fact_ids": [kpi[k]["id"] for k in present]})
    exp = _first(facts, "experiment", lambda f: "relative uplift" in f["statement"])
    if exp:
        hl.append({"text": "Onboarding redesign experiment: " + exp["statement"].split(": ", 1)[1], "fact_ids": [exp["id"]]})
    summary["highlights"] = hl

    moves = [f for f in kpi.values() if f["data"]["notable"] or f["data"]["assessment"] in ("improved", "worsened")]
    summary["kpi_movements"] = [{"text": "%s: %s (%s vs prior month) - %s." % (f["data"]["name"], f["data"]["value_fmt"],
                                                                              f["data"]["delta_fmt"], f["data"]["assessment"]),
                                 "fact_ids": [f["id"]]} for f in moves][:8]

    an_sum = _first(facts, "anomaly_summary")
    recent = [f for f in facts if f["topic"] == "anomaly" and f["data"].get("recent")]
    incidents = [f for f in facts if f["topic"] == "anomaly" and f["data"]["classification"] == "investigate"
                 and f["data"]["severity"] == "high"]
    an_items = [{"text": f["statement"], "fact_ids": [f["id"]]} for f in recent]
    if an_sum and not recent:
        an_items.append({"text": "No anomaly episodes in the last 8 weeks; the monitor remains active.", "fact_ids": [an_sum["id"]]})
    an_items += [{"text": "Past incident for context: " + f["statement"], "fact_ids": [f["id"]]} for f in incidents[:3]]
    summary["anomalies"] = an_items

    summary["experiments"] = [{"text": f["statement"], "fact_ids": [f["id"]]} for f in facts
                              if f["topic"] == "experiment" and "Decision:" in f["statement"]]

    risks = [{"text": "%s is off target: %s (%s)." % (f["data"]["name"], f["data"]["value_fmt"],
                                                     f["statement"].split("; target ")[1].split(";")[0]),
              "fact_ids": [f["id"]]} for f in off]
    fest = _first(facts, "risk")
    if fest:
        risks.append({"text": "Festive-season credit dilution: " + fest["statement"], "fact_ids": [fest["id"]]})
    mk = _first(facts, "marketing")
    if mk:
        risks.append({"text": "Acquisition fraud exposure: " + mk["statement"], "fact_ids": [mk["id"]]})
    summary["risks"] = risks

    recs = []
    triggered = [k for k, f in kpi.items() if f["data"]["target_status"] == "off_track"
                 or (f["data"]["assessment"] == "worsened" and f["data"]["notable"])]
    for k in triggered + ["cost_per_new_borrower"]:
        if k in RECOMMENDATIONS and k in kpi and not any(r.get("_k") == k for r in recs):
            text, owner, topics = RECOMMENDATIONS[k]
            ids = [kpi[k]["id"]] + [f["id"] for t in topics for f in [_first(facts, t)] if f]
            recs.append({"text": text, "owner": owner, "fact_ids": ids, "_k": k})
    if mk:
        recs.append({"text": "Add device and velocity rules for affiliate traffic and pay affiliates on funded, performing "
                             "loans instead of signups.", "owner": "Risk & Marketing", "fact_ids": [mk["id"]]})
    for r in recs:
        r.pop("_k", None)
    summary["recommendations"] = recs[:5]

    caveats = []
    dq = _first(facts, "data_quality", lambda f: f["statement"].startswith("Data quality"))
    if dq:
        caveats.append({"text": dq["statement"], "fact_ids": [dq["id"]]})
    for f in [f for f in facts if f["topic"] == "data_quality" and "Open data-quality issue" in f["statement"]][:3]:
        caveats.append({"text": f["statement"], "fact_ids": [f["id"]]})
    lag = [f for f in kpi.values() if "Latest available period" in f["statement"]]
    if lag:
        caveats.append({"text": "Cohort-based KPIs report with a lag: %s." % ", ".join(
            "%s refers to %s" % (f["data"]["name"], pd.Timestamp(f["data"]["period"] + "-01").strftime("%b %Y")) for f in lag),
            "fact_ids": [f["id"] for f in lag]})
    caveats.append({"text": "All figures are synthetic and generated for demonstration.", "fact_ids": []})
    summary["data_caveats"] = caveats
    return summary


# ------------------------------------------------------------------ rendering
def render_markdown(summary: Dict, sheet: Dict, mode: str, validation: Dict, meta: Optional[Dict] = None) -> str:
    by_id = {f["id"]: f for f in sheet["facts"]}
    cite = lambda ids: " " + "".join("[%s]" % i for i in ids) if ids else ""
    week = sheet.get("reporting_week") or {}
    engine = "Claude (%s)" % (meta or {}).get("model", MODEL) if mode == "claude" else "deterministic template (no LLM call)"
    status = "PASSED" if validation["grounded"] else "FAILED"
    L = ["# Weekly Business Summary - week of %s" % pd.Timestamp(week.get("start", sheet["as_of_date"])).strftime("%d %b %Y"), "",
         "_%s (fictional) - synthetic data - generated %s - engine: %s - numeric verification: **%s** (%d numbers in %d "
         "items checked against the cited facts)_" % (COMPANY_NAME, datetime.now().strftime("%Y-%m-%d %H:%M"), engine, status,
                                                      validation["numbers_checked"], validation["items_checked"]), "",
         "> **%s**%s" % (summary["headline"]["text"], cite(summary["headline"]["fact_ids"])), ""]
    for key, title in SECTIONS:
        items = summary.get(key, [])
        if not items:
            continue
        L += ["## %s" % title, ""]
        if key == "recommendations":
            L += ["| # | Recommendation | Owner | Evidence |", "|---|---|---|---|"]
            for i, it in enumerate(items, 1):
                L.append("| %d | %s | %s | %s |" % (i, it["text"], it.get("owner", ""), cite(it["fact_ids"]).strip()))
        else:
            L += ["- %s%s" % (it["text"], cite(it["fact_ids"])) for it in items]
        L.append("")
    if validation.get("removed_items"):
        L += ["> %d item(s) were removed because their numbers could not be verified against the fact sheet." %
              len(validation["removed_items"]), ""]
    used = sorted({i for it in summary_items(summary) for i in it["fact_ids"] if i in by_id}, key=lambda x: int(x[1:]))
    L += ["## Sources", "", "Every bracketed reference points to a fact computed by the pipeline:", ""]
    L += ["- **[%s]** %s _(source: `%s`)_" % (i, by_id[i]["statement"], by_id[i]["source"]) for i in used]
    return "\n".join(L) + "\n"


def generate_summary(settings: Optional[Settings] = None, offline: bool = False) -> Dict:
    settings = settings or get_settings()
    sheet = build_fact_sheet(settings)
    save_fact_sheet(sheet, settings)
    mode, meta, note = "deterministic", None, None
    summary, validation = None, None
    if not offline:
        try:
            summary, validation, meta = _llm_summary(sheet)
            mode = "claude"
        except LLMUnavailable as exc:
            note = "LLM unavailable (%s) - deterministic summary used." % exc
            log.warning(note)
    if summary is None:
        summary = deterministic_summary(sheet)
        validation = validate_summary(summary, sheet["facts"])
        validation["removed_items"] = []
    md = render_markdown(summary, sheet, mode, validation, meta)
    out = settings.outputs_dir / "ai"
    out.mkdir(parents=True, exist_ok=True)
    (out / "executive_summary.md").write_text(md, encoding="utf-8")
    write_json({"mode": mode, "note": note, "meta": meta, "summary": summary, "validation": validation},
               out / "executive_summary.json")
    return {"mode": mode, "note": note, "validation": validation, "facts_used": len(sheet["facts"]),
            "path": str(out / "executive_summary.md")}
