"""Cross-table reconciliations: the checks that catch problems no single table reveals."""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from data_quality.checks import CheckResult, _result, as_datetime, as_numeric

# Reconciliation breaks on fewer than this share of loans are reported to Finance Ops
# but do not block publishing (documented operating policy, see docs/technical_documentation.md).
LEDGER_BREAK_TOLERANCE = 0.005


def _ledger_vs_repayments(stage, t) -> CheckResult:
    tx, rp = t["transactions"], t["repayments"]
    ok = (tx["txn_type"] == "emi_payment") & (tx["txn_status"] == "success")
    ledger = as_numeric(tx.loc[ok, "amount"]).groupby(tx.loc[ok, "loan_id"]).sum()
    sched = as_numeric(rp["amount_paid"]).groupby(rp["loan_id"]).sum()
    idx = ledger.index.union(sched.index)
    diff = (ledger.reindex(idx, fill_value=0) - sched.reindex(idx, fill_value=0)).abs()
    bad = diff[diff > 1]
    return _result(stage, "transactions", "reconciliation:ledger_vs_repayments", "amount", "critical", len(bad),
                   len(idx), "loans whose successful EMI ledger total differs from repayments.amount_paid by > INR 1 "
                   "(total gap INR %s)" % format(round(float(bad.sum())), ","), bad.index[:5].tolist(),
                   threshold=LEDGER_BREAK_TOLERANCE)


def _disbursement_vs_loans(stage, t) -> CheckResult:
    tx, lo = t["transactions"], t["loans"]
    d = tx[tx["txn_type"] == "disbursement"]
    ledger = as_numeric(d["amount"]).groupby(d["loan_id"]).sum()
    loans = as_numeric(lo["net_disbursed_amount"]).groupby(lo["loan_id"]).sum()
    diff = (ledger.reindex(loans.index, fill_value=0) - loans).abs()
    bad = diff[diff > 1]
    return _result(stage, "transactions", "reconciliation:disbursement_vs_loans", "amount", "critical", len(bad),
                   len(loans), "loans whose disbursement ledger entry does not match net_disbursed_amount",
                   bad.index[:5].tolist(), threshold=LEDGER_BREAK_TOLERANCE)


def _loans_vs_applications(stage, t) -> CheckResult:
    ap, lo = t["applications"], t["loans"]
    disbursed = set(ap.loc[ap["application_status"] == "disbursed", "application_id"].astype(str))
    linked = set(lo["application_id"].dropna().astype(str))
    missing = disbursed - linked
    orphan = linked - set(ap["application_id"].astype(str))
    unlinked = int(lo["application_id"].isna().sum())
    failed = len(missing) + len(orphan) + unlinked
    return _result(stage, "loans", "reconciliation:loans_vs_applications", "application_id", "warning", failed,
                   max(len(lo), 1), "%d disbursed applications without a loan, %d loans pointing at unknown "
                   "applications, %d loans with no application link" % (len(missing), len(orphan), unlinked),
                   sorted(orphan)[:5] or sorted(missing)[:5], threshold=0.001)


def _kyc_events_vs_backend(stage, t) -> CheckResult:
    cu, ev = t["customers"], t["product_events"]
    backend = as_datetime(cu["kyc_completed_ts"]).dt.normalize().value_counts()
    k = ev[ev["event_name"] == "kyc_completed"]
    tracked = as_datetime(k["event_ts"]).dt.normalize().groupby(k["user_id"]).min()  # dedupe per user
    tracked = tracked.value_counts()
    days = backend[backend >= 20].index
    ratio = tracked.reindex(days, fill_value=0) / backend.reindex(days)
    bad = ratio[ratio < 0.90].sort_values()
    sample = ["%s (%.0f%%)" % (d.date(), 100 * r) for d, r in bad.items()][:5]
    return _result(stage, "product_events", "reconciliation:kyc_events_vs_backend", "event_name", "warning", len(bad),
                   len(days), "days where tracked kyc_completed events < 90% of backend KYC completions "
                   "(instrumentation gap, not a business change)", sample)


def _channel_vs_campaign(stage, t) -> CheckResult:
    cu, mc = t["customers"], t["marketing_campaigns"]
    camp_channel = cu["campaign_id"].map(mc.set_index("campaign_id")["channel"])
    label = cu["acquisition_channel"].astype(str)
    bad = (cu["campaign_id"].isna() & (label != "organic")) | (camp_channel.notna() & (camp_channel != label))
    return _result(stage, "customers", "reconciliation:channel_vs_campaign", "acquisition_channel", "warning",
                   int(bad.sum()), len(cu), "acquisition_channel label contradicts the campaign tag "
                   "(paid channel without campaign, or campaign of another channel)",
                   cu.loc[bad, "customer_id"].head(5).tolist())


def run_reconciliations(stage: str, tables: Dict[str, pd.DataFrame]) -> List[CheckResult]:
    needed = {"transactions", "repayments", "loans", "applications", "customers", "product_events", "marketing_campaigns"}
    if not needed.issubset(tables):
        return []
    return [
        _ledger_vs_repayments(stage, tables),
        _disbursement_vs_loans(stage, tables),
        _loans_vs_applications(stage, tables),
        _kyc_events_vs_backend(stage, tables),
        _channel_vs_campaign(stage, tables),
    ]
