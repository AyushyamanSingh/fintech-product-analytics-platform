"""Generate docs/data_dictionary.md from the data contracts + live warehouse metadata.

The dictionary is never hand-edited: contracts.yaml is the source of truth for the core layer,
information_schema for the marts. Re-run after any contract change.

    python -m python.build_data_dictionary
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
import yaml

from python.config import PROJECT_ROOT, Settings, get_settings
from python.kpi_definitions import KPIS

MART_DESCRIPTIONS = {
    "run_params": "Single-row table holding the extract (as-of) date and window start used by every query.",
    "dim_date": "Calendar dimension with ISO week, month, quarter and Indian fiscal year (Apr-Mar).",
    "fct_customer_funnel": "One row per customer with every onboarding/lending milestone, time-bounded conversion flags and maturity flags.",
    "fct_loan_performance": "One row per loan: economics (interest, fees, credit loss), repayment behaviour, DPD bucket, FPD30, vintage fields.",
    "fct_user_activity_monthly": "Customer x month activity counts (client events, logins, sessions, payments, feature events).",
    "fct_daily_metrics": "Daily operating metrics used for trends, weekly KPIs and anomaly detection.",
    "fct_portfolio_monthly": "Point-in-time month-end portfolio snapshot by product (outstanding, PAR30, NPA, write-offs).",
    "customer_360": "One row per customer combining profile, lending, repayment, engagement, support and acquisition cost.",
    "fct_revenue_events": "Revenue ledger at recognition date (interest, fees, credit losses) - the single source for revenue metrics.",
}


def build(settings: Optional[Settings] = None) -> Path:
    settings = settings or get_settings()
    contracts = yaml.safe_load(open(settings.contracts_path, encoding="utf-8"))
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        counts = {t: con.execute("SELECT COUNT(*) FROM core.%s" % t).fetchone()[0] for t in contracts["tables"]}
        marts = con.execute("""SELECT table_name, column_name, data_type FROM information_schema.columns
                               WHERE table_schema = 'marts' ORDER BY table_name, ordinal_position""").df()
        mart_counts = {t: con.execute("SELECT COUNT(*) FROM marts.%s" % t).fetchone()[0] for t in marts["table_name"].unique()}
    finally:
        con.close()

    L = ["# Data Dictionary", "",
         "> **All data is synthetic** (fictional lender *Vittora Credit*). Generated from "
         "`data_quality/contracts.yaml` and warehouse metadata by `python/build_data_dictionary.py` - do not edit by hand.",
         "", "Contract version: `%s` - extract window %s to %s." % (contracts["version"], settings.start_date, settings.end_date),
         "", "## Core layer (curated source tables)", "",
         "| Table | Grain | Source system | Rows | Primary key |", "|---|---|---|---:|---|"]
    for t, spec in contracts["tables"].items():
        L.append("| [`core.%s`](#core%s) | %s | %s | %s | `%s` |" % (t, t.replace("_", ""), spec.get("grain", ""),
                                                                    spec.get("source_system", ""), format(counts[t], ","),
                                                                    ", ".join(spec["primary_key"])))
    L += ["", "Relationships (enforced as foreign keys in `sql/ddl/01_core_schema.sql`):", "", "```mermaid", "erDiagram"]
    rels = []
    for t, spec in contracts["tables"].items():
        for col, cs in spec["columns"].items():
            if "fk" in cs:
                parent = cs["fk"].split(".")[0]
                rels.append("    %s ||--o{ %s : \"%s\"" % (parent.upper(), t.upper(), col))
    L += sorted(set(rels)) + ["```", ""]
    for t, spec in contracts["tables"].items():
        L += ['<a id="core%s"></a>' % t.replace("_", ""), "### core.%s" % t, "", spec["description"], ""]
        L += ["| Column | Type | Nullable | Rules | Description |", "|---|---|---|---|---|"]
        for col, cs in spec["columns"].items():
            rules = []
            if "accepted_values" in cs:
                vals = ", ".join(str(v) for v in cs["accepted_values"])
                rules.append("in {%s}" % (vals if len(vals) < 90 else vals[:87] + "..."))
            if "min" in cs or "max" in cs:
                rules.append("range [%s, %s]" % (cs.get("min", ""), cs.get("max", "")))
            if "pattern" in cs:
                rules.append("pattern `%s`" % cs["pattern"])
            if "fk" in cs:
                rules.append("FK -> `%s`" % cs["fk"])
            if cs.get("outlier"):
                rules.append("outlier check")
            if cs.get("derived"):
                rules.append("derived in ETL")
            if cs.get("severity") == "warning":
                rules.append("warning-level")
            L.append("| `%s` | %s | %s | %s | %s |" % (col, contracts["types"][cs["type"]], "yes" if cs.get("nullable", True) else "no",
                                                      "; ".join(rules), cs.get("description", "")))
        extra = []
        for a, b in spec.get("date_order", []):
            extra.append("`%s <= %s`" % (a, b))
        for r in spec.get("cross_field", []):
            extra.append("`%s` (%s)" % (r["expr"], r.get("severity", "critical")))
        for r in spec.get("conditional", []):
            extra.append("when `%s` then `%s` not null (%s)" % (r["when"], r["require_not_null"], r.get("severity", "critical")))
        if extra:
            L += ["", "Table rules: " + "; ".join(extra) + "."]
        L.append("")
    L += ["## Marts layer (analytics-ready)", "", "Built by `sql/marts/*.sql` on every pipeline run.", ""]
    for t, grp in marts.groupby("table_name", sort=False):
        L += ["### marts.%s" % t, "", MART_DESCRIPTIONS.get(t, ""), "", "Rows: %s" % format(mart_counts[t], ","), "",
              "| Column | Type |", "|---|---|"]
        L += ["| `%s` | %s |" % (r.column_name, r.data_type) for r in grp.itertuples()]
        L.append("")
    L += ["## Governed KPIs", "", "Full definitions: [metric_definitions.md](metric_definitions.md).", "",
          "| KPI | Category | Unit | Definition |", "|---|---|---|---|"]
    L += ["| %s | %s | %s | %s |" % (k["name"], k["category"], k["unit"], k["definition"]) for k in KPIS]
    docs = PROJECT_ROOT / "docs" if settings.base_dir == PROJECT_ROOT else settings.base_dir / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "data_dictionary.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    build_metric_definitions(docs / "metric_definitions.md")
    return path


def build_metric_definitions(path: Path) -> Path:
    unit_label = {"pct": "% (ratio 0-1)", "inr": "INR", "count": "count", "ratio": "ratio", "score": "score (1-5)"}
    direction = {"up_good": "higher is better", "down_good": "lower is better", "neutral": "context-dependent"}
    L = ["# Metric definitions (governed KPIs)", "",
         "> Generated from `python/kpi_definitions.py` by `python/build_data_dictionary.py`. The same registry feeds "
         "the KPI tables, the Power BI measures and the AI analyst's fact sheet, so a KPI means the same thing everywhere. "
         "Synthetic data.", ""]
    for cat in dict.fromkeys(k["category"] for k in KPIS):
        L += ["## %s" % cat, "", "| KPI | Definition | Formula | Unit | Direction | Target | Notes |",
              "|---|---|---|---|---|---|---|"]
        for k in [k for k in KPIS if k["category"] == cat]:
            tgt = ""
            if k.get("target"):
                v, op = k["target"]
                tgt = "%s %s" % (op, "%.1f%%" % (100 * v) if k["unit"] == "pct" else format(v, ","))
            L.append("| **%s** (`%s`) | %s | `%s` | %s | %s | %s | %s |" % (
                k["name"], k["id"], k["definition"], k["formula"], unit_label[k["unit"]], direction[k["direction"]], tgt,
                k.get("lag_note", "")))
        L.append("")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    print(build())
