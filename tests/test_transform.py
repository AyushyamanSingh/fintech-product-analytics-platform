"""ETL repair rules: each rule fixes exactly the defect it targets and logs what it did."""
import pandas as pd
import pytest

from etl.transform import Transformer
from python.config import get_settings
from python.generate_data import LendingSimulator, inject_dq_issues


@pytest.fixture(scope="module")
def run(contracts):
    clean = LendingSimulator(get_settings(n_customers=2500, seed=5, inject_dq_issues=False)).run()
    raw, manifest = inject_dq_issues(clean, seed=9)
    # simulate the CSV round trip: timestamps become strings, as in data/raw/
    for df in raw.values():
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].dt.strftime("%Y-%m-%d %H:%M:%S")
    t = Transformer(contracts, pd.Timestamp("2026-06-30"))
    out, log, quarantine = t.transform(raw)
    return {"clean": clean, "raw": raw, "out": out, "log": log, "quarantine": quarantine, "manifest": manifest}


def rows(log, needle):
    m = log[log["rule"].str.contains(needle, regex=False)]
    return int(m["rows_affected"].sum())


def test_duplicates_removed(run):
    for t in ("customers", "applications", "transactions", "product_events"):
        key = {"customers": "customer_id", "applications": "application_id", "transactions": "transaction_id",
               "product_events": "event_id"}[t]
        assert run["out"][t][key].is_unique


def test_channel_standardised_and_matches_campaign(run):
    c = run["out"]["customers"]
    assert set(c["acquisition_channel"]) <= {"organic", "paid_search", "paid_social", "affiliate", "referral", "partnerships"}
    camp = run["out"]["marketing_campaigns"].set_index("campaign_id")["channel"]
    tagged = c["campaign_id"].notna()
    assert (c.loc[tagged, "campaign_id"].map(camp) == c.loc[tagged, "acquisition_channel"]).all()
    assert (c.loc[~tagged, "acquisition_channel"] == "organic").all()


def test_timezone_repair_restores_order(run):
    c = run["out"]["customers"]
    both = c["kyc_started_ts"].notna() & c["kyc_completed_ts"].notna()
    assert (c.loc[both, "kyc_completed_ts"] >= c.loc[both, "kyc_started_ts"]).all()
    assert rows(run["log"], "UTC") > 0


def test_apr_basis_points_repaired(run):
    assert run["out"]["loans"]["interest_rate_apr"].max() <= 60
    assert rows(run["log"], "basis points") > 0


def test_type_drift_and_schema_drift(run):
    st = run["out"]["support_tickets"]
    assert "agent_id" not in st.columns
    assert pd.api.types.is_float_dtype(st["csat_score"])
    assert st["csat_score"].dropna().between(1, 5).all()


def test_test_accounts_quarantined_not_dropped(run):
    q = run["quarantine"]["product_events"]
    assert (q["user_id"].str.startswith("TEST-")).any()
    assert not run["out"]["product_events"]["user_id"].str.startswith("TEST-").any()


def test_is_ntc_not_polluted_by_bad_scores(run):
    c = run["out"]["customers"]
    clean = run["clean"]["customers"].drop_duplicates("customer_id").set_index("customer_id")
    expected_ntc = clean.loc[c["customer_id"], "credit_score"].isna().values
    assert (c["is_ntc"].values == expected_ntc).all()


def test_every_rule_logged(run):
    assert {"table", "rule", "action", "rows_affected"} <= set(run["log"].columns)
    assert (run["log"]["rows_affected"] >= 0).all()
