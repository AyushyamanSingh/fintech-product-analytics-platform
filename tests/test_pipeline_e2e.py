"""End-to-end: run the real pipeline on a small dataset and check business invariants."""
import json

import duckdb
import pandas as pd
import pytest


def con(e2e):
    return duckdb.connect(str(e2e["settings"].warehouse_path), read_only=True)


def test_pipeline_succeeds(e2e):
    failed = [s for s in e2e["manifest"]["steps"] if s["status"] != "success"]
    assert e2e["ok"], failed


def test_curated_layer_has_no_critical_issues(e2e):
    res = pd.read_csv(e2e["settings"].outputs_dir / "data_quality" / "dq_results_clean.csv")
    crit = res[(res["status"] == "fail") & (res["severity"] == "critical")]
    assert crit.empty, crit[["table", "check", "column", "details"]]


def test_every_planted_defect_is_detected(e2e):
    recall = pd.read_csv(e2e["settings"].outputs_dir / "data_quality" / "injected_issue_recall.csv")
    missed = recall[~recall["detected"]]
    assert missed.empty, missed[["table", "column", "issue"]]


def test_warehouse_matches_processed_layer(e2e):
    s = e2e["settings"]
    c = con(e2e)
    try:
        for t, df in e2e["state"]["clean"].items():
            assert c.execute("SELECT COUNT(*) FROM core.%s" % t).fetchone()[0] == len(df), t
        n_cust = c.execute("SELECT COUNT(*) FROM core.customers").fetchone()[0]
        assert c.execute("SELECT COUNT(*) FROM marts.fct_customer_funnel").fetchone()[0] == n_cust
        assert c.execute("SELECT COUNT(*) FROM marts.customer_360").fetchone()[0] == n_cust
    finally:
        c.close()


def test_all_sql_queries_ran(e2e):
    man = pd.read_csv(e2e["settings"].outputs_dir / "sql_results" / "_manifest.csv")
    assert len(man) >= 45
    must_have_rows = ["01_funnel_conversion__funnel_overall", "03_cohort_retention__activity_retention_matrix",
                      "05_customer_ltv__ltv_cac_by_channel", "06_revenue_analysis__monthly_revenue",
                      "07_delinquency__vintage_curves", "09_repeat_borrowing__repeat_rate_by_product",
                      "14_experiment_readout__onboarding_experiment_metrics"]
    rows = man.set_index("query")["rows"]
    for q in must_have_rows:
        assert rows[q] > 0, q


def test_funnel_is_monotonic(e2e):
    f = pd.read_csv(e2e["settings"].outputs_dir / "sql_results" / "01_funnel_conversion__funnel_overall.csv")
    assert (f["customers"].diff().dropna() <= 0).all()
    assert f["pct_of_signups"].iloc[0] == 100


def test_retention_month_zero_is_complete(e2e):
    r = pd.read_csv(e2e["settings"].outputs_dir / "sql_results" / "03_cohort_retention__activity_retention_matrix.csv")
    # every customer fires a client-side signup event in the signup month; it can only be missing when the
    # ETL quarantined that event (e.g. a future-dated device clock), so allow a sliver below 100%
    assert (r.loc[r["month_number"] == 0, "retention_pct"] >= 99).all()
    assert (r["retention_pct"] <= 100).all()
    piv = r.pivot(index="cohort_month", columns="month_number", values="retention_pct")
    later = piv.drop(columns=0).max(axis=1).dropna()
    assert (later <= piv.loc[later.index, 0]).all()  # no cohort is "more retained" later than in its signup month


def test_revenue_reconciles_across_marts(e2e):
    c = con(e2e)
    try:
        ledger = c.execute("SELECT SUM(amount) FROM marts.fct_revenue_events WHERE component <> 'credit_loss'").fetchone()[0]
        loans = c.execute("SELECT SUM(total_revenue) FROM marts.fct_loan_performance").fetchone()[0]
        losses_l = c.execute("SELECT -SUM(amount) FROM marts.fct_revenue_events WHERE component = 'credit_loss'").fetchone()[0] or 0
        losses_p = c.execute("SELECT SUM(credit_loss) FROM marts.fct_loan_performance").fetchone()[0] or 0
    finally:
        c.close()
    assert abs(float(ledger) - float(loans)) < 1.0
    assert abs(float(losses_l) - float(losses_p)) < 1.0


def test_portfolio_snapshot_is_sane(e2e):
    c = con(e2e)
    try:
        p = c.execute("SELECT * FROM marts.fct_portfolio_monthly").df()
        disbursed = c.execute("SELECT SUM(principal_amount) FROM core.loans").fetchone()[0]
    finally:
        c.close()
    assert (p["par30_outstanding"] <= p["outstanding_principal"] + 1).all()
    assert (p["npa_outstanding"] <= p["par30_outstanding"] + 1).all()
    assert p.groupby("month_start")["outstanding_principal"].sum().max() <= float(disbursed)


def test_kpi_snapshot_complete_and_in_range(e2e):
    snap = json.loads((e2e["settings"].outputs_dir / "kpis" / "kpi_snapshot.json").read_text(encoding="utf-8"))
    ids = {k["id"] for k in snap["monthly"]}
    assert {"loans_disbursed", "gross_revenue", "approval_rate", "par30_rate", "kyc_completion_rate_7d"} <= ids
    for k in snap["monthly"]:
        if k["unit"] == "pct":
            assert 0 <= k["value"] <= 1, k["id"]


def test_experiment_results_structure(e2e):
    res = json.loads((e2e["settings"].outputs_dir / "experiments" / "experiment_results.json").read_text(encoding="utf-8"))
    assert set(res) == {"EXP-ONB-2026-01", "EXP-RPY-2025-11", "EXP-PRC-2025-06"}
    onb = res["EXP-ONB-2026-01"]
    assert onb["srm"]["control_n"] > 0 and onb["srm"]["treatment_n"] > 0
    assert onb["primary"]["ci_low"] <= onb["primary"]["diff_abs"] <= onb["primary"]["ci_high"]


def test_ai_summary_is_grounded(e2e):
    out = json.loads((e2e["settings"].outputs_dir / "ai" / "executive_summary.json").read_text(encoding="utf-8"))
    assert out["validation"]["grounded"], out["validation"]["problems"]
    assert out["validation"]["numbers_checked"] > 10


def test_powerbi_extract_written(e2e):
    d = e2e["settings"].powerbi_data_dir
    for name in ("dim_date", "dim_customer", "fct_loans", "fct_kpi_monthly", "fct_experiment_results"):
        assert (d / (name + ".csv")).exists(), name


def test_dashboard_embeds_pipeline_data(e2e):
    html = (e2e["settings"].base_dir / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert "/*__DASHBOARD_DATA__*/" not in html
    payload = html.split('<script id="dash-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    data = json.loads(payload)
    for key in ("kpis", "funnel", "revenue", "portfolio", "retention", "experiments", "dq"):
        assert data[key], key
    assert data["meta"]["as_of"] == e2e["settings"].end_date
    for m in data["experiments_meta"]:  # dates must survive serialisation (no epoch-1970 artefacts)
        assert m["start_date"][:4] >= "2024", m
