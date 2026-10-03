"""The synthetic data must be internally consistent before any defects are injected."""
import numpy as np
import pandas as pd
import pytest

from python.config import TABLES, get_settings
from python.generate_data import LendingSimulator, inject_dq_issues


@pytest.fixture(scope="module")
def clean_tables():
    return LendingSimulator(get_settings(n_customers=3000, seed=11, inject_dq_issues=False)).run()


def test_all_tables_generated(clean_tables):
    assert set(clean_tables) == set(TABLES)
    assert all(len(df) > 0 for df in clean_tables.values())


@pytest.mark.parametrize("table,key", [("customers", "customer_id"), ("applications", "application_id"),
                                       ("loans", "loan_id"), ("repayments", "repayment_id"),
                                       ("transactions", "transaction_id"), ("product_events", "event_id"),
                                       ("support_tickets", "ticket_id"), ("experiment_assignments", "assignment_id")])
def test_primary_keys_unique(clean_tables, table, key):
    assert clean_tables[table][key].is_unique


def test_referential_integrity(clean_tables):
    t = clean_tables
    cust = set(t["customers"]["customer_id"])
    assert set(t["applications"]["customer_id"]) <= cust
    assert set(t["loans"]["application_id"]) <= set(t["applications"]["application_id"])
    assert set(t["repayments"]["loan_id"]) <= set(t["loans"]["loan_id"])
    assert set(t["product_events"]["user_id"]) <= cust
    assert set(t["transactions"]["loan_id"].dropna()) <= set(t["loans"]["loan_id"])
    camps = set(t["marketing_campaigns"]["campaign_id"])
    assert set(t["customers"]["campaign_id"].dropna()) <= camps


def test_lifecycle_ordering(clean_tables):
    c = clean_tables["customers"]
    assert (c["kyc_started_ts"].dropna() >= c.loc[c["kyc_started_ts"].notna(), "signup_ts"]).all()
    done = c["kyc_completed_ts"].notna()
    assert (c.loc[done, "kyc_completed_ts"] >= c.loc[done, "kyc_started_ts"]).all()
    a = clean_tables["applications"]
    sub = a["submitted_ts"].notna()
    assert (a.loc[sub, "submitted_ts"] >= a.loc[sub, "started_ts"]).all()
    dec = a["decision_ts"].notna()
    assert (a.loc[dec, "decision_ts"] >= a.loc[dec, "submitted_ts"]).all()
    # nobody applies before finishing KYC
    first_app = a.groupby("customer_id")["started_ts"].min()
    kyc = c.set_index("customer_id").loc[first_app.index, "kyc_completed_ts"]
    assert (first_app.values >= kyc.values).all()


def test_amortisation_schedule_repays_principal(clean_tables):
    lo = clean_tables["loans"].set_index("loan_id")
    rp = clean_tables["repayments"]
    full = lo[lo["closure_type"] != "foreclosure"]
    principal_sched = rp[rp["loan_id"].isin(full.index)].groupby("loan_id")["principal_due"].sum()
    diff = (principal_sched - full.loc[principal_sched.index, "principal_amount"]).abs()
    assert diff.max() < 1.0


def test_payment_amounts_consistent(clean_tables):
    rp = clean_tables["repayments"]
    assert (rp["amount_paid"] <= rp["total_due"] + 0.01).all()
    assert np.allclose(rp["principal_paid"] + rp["interest_paid"], rp["amount_paid"], atol=0.02)
    tx = clean_tables["transactions"]
    ok = tx[(tx["txn_type"] == "emi_payment") & (tx["txn_status"] == "success")]
    ledger = ok.groupby("loan_id")["amount"].sum()
    sched = rp.groupby("loan_id")["amount_paid"].sum()
    joined = pd.concat([ledger, sched], axis=1).fillna(0)
    assert (joined.iloc[:, 0] - joined.iloc[:, 1]).abs().max() < 1.0


def test_deterministic_with_seed():
    s = get_settings(n_customers=800, seed=3, inject_dq_issues=False)
    a = LendingSimulator(s).run()["customers"]
    b = LendingSimulator(s).run()["customers"]
    pd.testing.assert_frame_equal(a, b)


def test_injection_records_answer_key(clean_tables):
    corrupted, manifest = inject_dq_issues(clean_tables, seed=1)
    assert len(manifest) >= 20
    assert len(corrupted["customers"]) > len(clean_tables["customers"])  # duplicates added
    assert corrupted["support_tickets"]["csat_score"].dtype == object  # type drift: numbers as text + 'N/A'
    assert (corrupted["loans"]["interest_rate_apr"] > 100).any()       # APR in basis points
