"""Export a star-schema extract for the Power BI report (powerbi/data/*.csv).

Facts are pre-aggregated where the report never needs row-level detail (events -> daily),
so the .pbix stays small and refreshes fast. Relationships are documented in
powerbi/model/data_model.md and loaded by the Power Query scripts in powerbi/power_query/.

    python -m python.powerbi_export
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import pandas as pd

from python.config import Settings, get_settings

QUERIES: Dict[str, str] = {
    "dim_date": "SELECT * FROM marts.dim_date",
    "dim_product": "SELECT * FROM core.products",
    "dim_channel": """
        SELECT DISTINCT acquisition_channel AS channel,
               CASE acquisition_channel WHEN 'organic' THEN 'Organic' WHEN 'paid_search' THEN 'Paid Search'
                    WHEN 'paid_social' THEN 'Paid Social' WHEN 'affiliate' THEN 'Affiliate'
                    WHEN 'referral' THEN 'Referral' ELSE 'Partnerships' END AS channel_label,
               acquisition_channel <> 'organic' AS is_paid
        FROM core.customers""",
    "dim_campaign": "SELECT * FROM core.marketing_campaigns",
    "dim_customer": """
        SELECT c.customer_id, c.cohort_month, c.acquisition_channel, c.campaign_id, c.signup_platform, c.city_tier,
               c.state, c.employment_type, c.age_band, c.income_band, c.is_ntc, c.kyc_status, c.lifecycle_stage,
               c.n_loans, c.total_disbursed, c.net_revenue, c.acquisition_cost, c.on_time_rate, c.max_dpd_ever,
               c.outstanding_principal, c.logins_90d, c.days_since_last_active
        FROM marts.customer_360 c""",
    "fct_funnel": """
        SELECT customer_id, signup_date, cohort_month, acquisition_channel, signup_platform, city_tier, employment_type,
               is_ntc, kyc_started_ts IS NOT NULL AS reached_kyc_started, kyc_completed_ts IS NOT NULL AS reached_kyc_completed,
               first_app_started_ts IS NOT NULL AS reached_app_started, first_app_submitted_ts IS NOT NULL AS reached_app_submitted,
               first_approved_ts IS NOT NULL AS reached_approved, first_disbursed_ts IS NOT NULL AS reached_disbursed,
               kyc_completed_7d, app_submitted_14d, disbursed_30d, is_mature_7d, is_mature_30d,
               minutes_signup_to_kyc, days_signup_to_disbursal, onb_variant
        FROM marts.fct_customer_funnel""",
    "fct_applications": """
        SELECT application_id, customer_id, product_id, CAST(started_ts AS DATE) AS started_date,
               CAST(submitted_ts AS DATE) AS submitted_date, CAST(decision_ts AS DATE) AS decision_date,
               requested_amount, requested_tenure_months, application_platform, is_repeat_customer, risk_band,
               internal_risk_score, decision, rejection_reason, sanctioned_amount, application_status
        FROM core.applications""",
    "fct_loans": "SELECT * EXCLUDE (disbursed_ts) FROM marts.fct_loan_performance",
    "fct_repayments": """
        SELECT repayment_id, loan_id, customer_id, installment_number, due_date, paid_date, total_due, amount_paid,
               interest_paid, principal_paid, late_fee, payment_status, days_past_due
        FROM core.repayments""",
    "fct_revenue": "SELECT * FROM marts.fct_revenue_events",
    "fct_portfolio_monthly": "SELECT * FROM marts.fct_portfolio_monthly",
    "fct_daily_metrics": "SELECT * FROM marts.fct_daily_metrics",
    "fct_events_daily": """
        SELECT CAST(event_ts AS DATE) AS event_date, event_name, platform, COALESCE(app_version, 'n/a') AS app_version,
               COUNT(*) AS events, COUNT(DISTINCT user_id) AS users
        FROM core.product_events GROUP BY 1, 2, 3, 4""",
    "fct_user_activity_monthly": "SELECT * FROM marts.fct_user_activity_monthly",
    "fct_support_tickets": """
        SELECT ticket_id, customer_id, CAST(created_ts AS DATE) AS created_date, channel, category, priority,
               first_response_minutes, date_diff('minute', created_ts, resolved_ts) / 60.0 AS resolution_hours,
               ticket_status, csat_score
        FROM core.support_tickets""",
    "fct_experiment_assignments": "SELECT * FROM core.experiment_assignments",
}

FROM_OUTPUTS = {
    "fct_kpi_monthly": ("kpis", "kpi_monthly_long.csv"),
    "fct_kpi_weekly": ("kpis", "kpi_weekly.csv"),
    "fct_cohort_retention": ("sql_results", "03_cohort_retention__activity_retention_matrix.csv"),
    "fct_vintage_curves": ("sql_results", "07_delinquency__vintage_curves.csv"),
    "fct_channel_economics": ("sql_results", "05_customer_ltv__ltv_cac_by_channel.csv"),
    "fct_cac_monthly": ("sql_results", "13_marketing_cac__cac_by_channel_month.csv"),
    "fct_anomaly_episodes": ("anomalies", "anomaly_episodes.csv"),
    "fct_dq_results_raw": ("data_quality", "dq_results_raw.csv"),
    "fct_dq_results_clean": ("data_quality", "dq_results_clean.csv"),
    "fct_cleaning_log": ("data_quality", "cleaning_log.csv"),
    "fct_segments": ("segments", "customer_segments.csv"),
    "dim_business_segment": ("segments", "business_segments.csv"),
    "dim_cluster": ("segments", "cluster_profiles.csv"),
    "fct_experiment_weekly_effect": ("experiments", "onboarding_weekly_effect.csv"),
}


def _experiment_table(settings: Settings) -> pd.DataFrame:
    path = settings.outputs_dir / "experiments" / "experiment_results.json"
    if not path.exists():
        return pd.DataFrame()
    res = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for exp_id, r in res.items():
        metrics = [("primary", r.get("primary_metric", "kyc_completion_7d"), r["primary"])]
        metrics += [("secondary", k, v) for k, v in r.get("secondary", {}).items()]
        metrics += [("guardrail", k, v) for k, v in r.get("guardrails", {}).items()]
        for role, name, m in metrics:
            rows.append({"experiment_id": exp_id, "metric_role": role, "metric": name,
                         "control_n": m["control_n"], "control_rate": m["control_rate"],
                         "treatment_n": m["treatment_n"], "treatment_rate": m["treatment_rate"],
                         "diff_abs": m["diff_abs"], "ci_low": m["ci_low"], "ci_high": m["ci_high"],
                         "relative_uplift": m["relative_uplift"], "p_value": m["p_value"],
                         "significant": m["significant"], "guardrail_status": m.get("status"),
                         "decision": r["decision"]})
    return pd.DataFrame(rows)


def export(settings: Optional[Settings] = None) -> List[Path]:
    settings = settings or get_settings()
    out_dir = settings.powerbi_data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        for name, sql in QUERIES.items():
            path = out_dir / (name + ".csv")
            con.execute("COPY (%s) TO '%s' (HEADER, DELIMITER ',')" % (sql, path.as_posix()))
            files.append(path)
    finally:
        con.close()
    for name, (folder, fname) in FROM_OUTPUTS.items():
        src = settings.outputs_dir / folder / fname
        if src.exists():
            path = out_dir / (name + ".csv")
            try:
                pd.read_csv(src).to_csv(path, index=False)
            except pd.errors.EmptyDataError:  # an empty result is valid (e.g. no anomaly episodes)
                path.write_text("", encoding="utf-8")
            files.append(path)
    exp = _experiment_table(settings)
    if len(exp):
        path = out_dir / "fct_experiment_results.csv"
        exp.to_csv(path, index=False)
        files.append(path)
    return files


if __name__ == "__main__":
    for f in export():
        print(f)
