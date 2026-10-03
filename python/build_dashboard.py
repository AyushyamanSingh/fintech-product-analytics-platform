"""Build the interactive HTML dashboard (dashboard/index.html) from the pipeline outputs.

The page is self-contained: every number is embedded as JSON and charts are drawn as SVG by
plain JavaScript, so it opens offline in any browser (Google Fonts fall back to system fonts).
Eight pages mirror the Power BI spec. Rebuilt by the pipeline's `dashboard` step, or:

    python -m python.build_dashboard
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

import duckdb
import pandas as pd

from python.config import COMPANY_NAME, PROJECT_ROOT, Settings, get_settings
from python.io_utils import read_json

TEMPLATE = PROJECT_ROOT / "dashboard" / "template.html"
PLACEHOLDER = "/*__DASHBOARD_DATA__*/null"


def _records(df: pd.DataFrame) -> list:
    return json.loads(df.round(4).to_json(orient="records", date_format="iso"))


def _safe(fn: Callable, default):
    try:
        return fn()
    except (FileNotFoundError, KeyError, pd.errors.EmptyDataError, ValueError):
        return default


def collect(settings: Settings) -> Dict:
    o = settings.outputs_dir

    def sql(name: str) -> list:
        return _safe(lambda: _records(pd.read_csv(o / "sql_results" / (name + ".csv"))), [])

    snap = read_json(o / "kpis" / "kpi_snapshot.json")
    monthly = pd.read_csv(o / "kpis" / "kpi_monthly.csv").round(6)
    monthly_cols = {c: json.loads(monthly[c].to_json(orient="values")) for c in monthly.columns}

    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        events = _records(con.execute(
            """SELECT event_name, COUNT(*) AS events, COUNT(DISTINCT user_id) AS users
               FROM core.product_events CROSS JOIN marts.run_params p
               WHERE event_ts >= CAST(p.as_of_date AS TIMESTAMP) - INTERVAL 89 DAY
               GROUP BY 1 ORDER BY events DESC""").df())
        experiments_meta = _records(con.execute(
            "SELECT experiment_id, experiment_name, hypothesis, CAST(start_date AS VARCHAR) AS start_date, "
            "CAST(end_date AS VARCHAR) AS end_date, owner_team, status FROM core.experiments").df())
        products = _records(con.execute("SELECT product_id, product_name FROM core.products ORDER BY 1").df())
    finally:
        con.close()

    cac = _safe(lambda: pd.read_csv(o / "sql_results" / "13_marketing_cac__cac_by_channel_month.csv"), pd.DataFrame())
    if len(cac):
        mature = cac[cac["fully_mature"].astype(str).str.lower() == "true"]
        cac = (mature.groupby("channel")[["spend", "signups", "funded_30d"]].sum().reset_index())
        cac["cost_per_funded"] = cac["spend"] / cac["funded_30d"].where(cac["funded_30d"] > 0)
        cac["cost_per_signup"] = cac["spend"] / cac["signups"]

    dq_clean = _safe(lambda: pd.read_csv(o / "data_quality" / "dq_results_clean.csv"), pd.DataFrame())
    dq_raw = _safe(lambda: pd.read_csv(o / "data_quality" / "dq_results_raw.csv"), pd.DataFrame())
    clog = _safe(lambda: pd.read_csv(o / "data_quality" / "cleaning_log.csv"), pd.DataFrame())
    recall = _safe(lambda: pd.read_csv(o / "data_quality" / "injected_issue_recall.csv"), pd.DataFrame())

    def failed_by_table(df: pd.DataFrame) -> Dict:
        if df.empty:
            return {}
        return df[df["status"] == "fail"].groupby("table").size().to_dict()

    ai = _safe(lambda: read_json(o / "ai" / "executive_summary.json"), {})
    gen = _safe(lambda: read_json(settings.raw_dir / "_generation_summary.json"), {})

    return {
        "meta": {"company": COMPANY_NAME, "as_of": settings.end_date, "start": settings.start_date,
                 "reporting_month": snap.get("reporting_month"), "reporting_week": snap.get("reporting_week"),
                 "total_rows": gen.get("total_rows"), "built": datetime.now().strftime("%Y-%m-%d %H:%M")},
        "kpis": snap["monthly"],
        "weekly": snap["weekly"],
        "monthly": monthly_cols,
        "products": products,
        "funnel": sql("01_funnel_conversion__funnel_overall"),
        "funnel_channel": sql("01_funnel_conversion__funnel_by_channel"),
        "kyc_segments": sql("02_funnel_dropoff__kyc_dropoff_by_segment"),
        "kyc_weekly": sql("02_funnel_dropoff__kyc_weekly_trend"),
        "retention": sql("03_cohort_retention__activity_retention_matrix"),
        "retention_curve": sql("03_cohort_retention__retention_curve_by_borrower_status"),
        "cohort_quality": sql("03_cohort_retention__cohort_quality"),
        "mau": sql("04_active_users__mau_growth_accounting"),
        "stickiness": sql("04_active_users__stickiness"),
        "ltv": sql("05_customer_ltv__ltv_cac_by_channel"),
        "deciles": sql("05_customer_ltv__value_concentration"),
        "revenue": sql("06_revenue_analysis__monthly_revenue"),
        "product_econ": sql("06_revenue_analysis__product_economics"),
        "yield": sql("06_revenue_analysis__portfolio_yield"),
        "dpd": sql("07_delinquency__dpd_distribution_current"),
        "portfolio": sql("07_delinquency__portfolio_quality_trend"),
        "vintage": sql("07_delinquency__vintage_curves"),
        "risk_segments": sql("07_delinquency__risk_by_segment"),
        "approval": sql("08_approval_disbursement__approval_disbursal_monthly"),
        "repeat": sql("09_repeat_borrowing__repeat_rate_by_product"),
        "product_mix": sql("10_product_adoption__product_adoption_monthly"),
        "features": sql("10_product_adoption__feature_adoption_impact"),
        "events_90d": events,
        "cac": _records(cac) if len(cac) else [],
        "campaigns": [r for r in sql("13_marketing_cac__campaign_scorecard") if r.get("review_flag") != "ok"][:8],
        "segments": _safe(lambda: _records(pd.read_csv(o / "segments" / "business_segments.csv")), []),
        "clusters": _safe(lambda: _records(pd.read_csv(o / "segments" / "cluster_profiles.csv")), []),
        "kmeans": _safe(lambda: read_json(o / "segments" / "segmentation_summary.json")["kmeans"], {}),
        "experiments": _safe(lambda: read_json(o / "experiments" / "experiment_results.json"), {}),
        "experiments_meta": experiments_meta,
        "dq": {
            "summary": _safe(lambda: read_json(o / "data_quality" / "dq_summary.json"), {}),
            "failed_raw": failed_by_table(dq_raw),
            "failed_clean": failed_by_table(dq_clean),
            "open_issues": _records(dq_clean[dq_clean["status"] == "fail"][
                ["severity", "table", "check", "column", "failed_rows", "details"]]) if len(dq_clean) else [],
            "cleaning_log": _records(clog[clog["rows_affected"] > 0][["table", "rule", "action", "rows_affected"]])
            if len(clog) else [],
            "quarantined": int(clog.loc[clog["action"] == "quarantine", "rows_affected"].sum()) if len(clog) else 0,
            "recall": _records(recall[["table", "column", "issue", "rows_affected", "detected", "detected_by"]])
            if len(recall) else [],
        },
        "anomalies": _safe(lambda: read_json(o / "anomalies" / "anomaly_episodes.json")["episodes"], []),
        "ai": {"mode": ai.get("mode"), "summary": ai.get("summary", {}),
               "validation": {k: ai.get("validation", {}).get(k) for k in ("grounded", "numbers_checked", "items_checked")}},
    }


def _split_fragment(html: str) -> str:
    """The artifact host supplies <html>/<head>/<body>; keep only our head content + body content."""
    head = html.split("<!--FRAGMENT-START-->", 1)[1].split("<!--HEAD-END-->", 1)[0]
    body = html.split("<!--BODY-START-->", 1)[1].split("<!--FRAGMENT-END-->", 1)[0]
    return head.strip() + "\n" + body.strip() + "\n"


def build(settings: Optional[Settings] = None, fragment_path: Optional[Path] = None) -> Path:
    settings = settings or get_settings()
    payload = json.dumps(collect(settings), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, payload)
    out = settings.base_dir / "dashboard" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if fragment_path:
        Path(fragment_path).write_text(_split_fragment(html), encoding="utf-8")
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build dashboard/index.html from pipeline outputs (synthetic data).")
    ap.add_argument("--fragment", help="also write a body-only copy (for hosts that supply <html>/<head>)")
    args = ap.parse_args()
    print(build(fragment_path=Path(args.fragment) if args.fragment else None))
