"""KPI registry: one governed definition per metric (the "semantic layer").

The same definitions drive the KPI tables, the Power BI measure documentation, the AI
analyst's fact sheet (so the LLM only ever sees governed numbers) and docs/metric_definitions.md.

unit:       count | pct (stored as 0-1 ratio) | inr | ratio | score
direction:  up_good | down_good | neutral
target:     optional (value, comparator) used for RAG status
lag_note:   why the latest month may be unavailable (maturity windows)
"""
from __future__ import annotations

from typing import Dict, List

KPIS: List[Dict] = [
    # ---------------------------------------------------------------- acquisition & funnel
    {"id": "new_customers", "name": "New customers", "category": "Acquisition", "unit": "count", "direction": "up_good",
     "definition": "Customers who created an account in the month.", "formula": "COUNT(customers) by signup month"},
    {"id": "kyc_completion_rate_7d", "name": "KYC completion (7-day)", "category": "Onboarding", "unit": "pct",
     "direction": "up_good", "target": (0.62, ">="),
     "definition": "Share of the month's signups that completed KYC within 7 days of signup.",
     "formula": "signups with kyc_completed_ts <= signup_ts + 7d / mature signups",
     "lag_note": "Signups from the last 7 days are excluded until their window closes."},
    {"id": "signup_to_disbursal_30d", "name": "Activation rate (first loan in 30 days)", "category": "Onboarding", "unit": "pct",
     "direction": "up_good", "target": (0.15, ">="),
     "definition": "Activation: share of the month's signups that received a first loan within 30 days of signup.",
     "formula": "signups with first_disbursed_ts <= signup_ts + 30d / mature signups",
     "lag_note": "Needs 30 days of observation, so the current month is reported next month."},
    {"id": "applications_submitted", "name": "Applications submitted", "category": "Lending", "unit": "count",
     "direction": "up_good", "definition": "Loan applications submitted for underwriting in the month.",
     "formula": "COUNT(applications) by submitted month"},
    {"id": "approval_rate", "name": "Approval rate", "category": "Lending", "unit": "pct", "direction": "neutral",
     "target": (0.50, ">="), "definition": "Approved decisions / all decisions made in the month.",
     "formula": "approved / (approved + rejected) by decision month"},
    {"id": "offer_acceptance_rate", "name": "Offer acceptance (disbursal rate)", "category": "Lending", "unit": "pct",
     "direction": "up_good", "target": (0.85, ">="),
     "definition": "Share of approvals in the month that were disbursed.", "formula": "disbursed / approved by decision month"},
    # ---------------------------------------------------------------- lending volume
    {"id": "loans_disbursed", "name": "Loans disbursed", "category": "Lending", "unit": "count", "direction": "up_good",
     "definition": "Loans disbursed in the month.", "formula": "COUNT(loans) by disbursal month"},
    {"id": "disbursed_amount", "name": "Disbursed amount", "category": "Lending", "unit": "inr", "direction": "up_good",
     "definition": "Principal disbursed in the month (gross of processing fees).", "formula": "SUM(principal_amount)"},
    {"id": "avg_ticket_size", "name": "Average ticket size", "category": "Lending", "unit": "inr", "direction": "neutral",
     "definition": "Average principal per disbursed loan.", "formula": "AVG(principal_amount)"},
    {"id": "new_borrowers", "name": "New borrowers", "category": "Lending", "unit": "count", "direction": "up_good",
     "definition": "Customers whose first-ever loan was disbursed in the month.", "formula": "COUNT(loans WHERE loan_sequence_number = 1)"},
    {"id": "repeat_loan_share", "name": "Repeat-loan share", "category": "Retention", "unit": "pct", "direction": "up_good",
     "definition": "Share of the month's disbursals that went to returning borrowers.", "formula": "repeat loans / loans"},
    {"id": "autopay_adoption_rate", "name": "Autopay adoption", "category": "Repayments", "unit": "pct",
     "direction": "up_good", "target": (0.60, ">="),
     "definition": "Share of the month's new loans with an active NACH/UPI-Autopay mandate.", "formula": "loans with autopay / loans"},
    # ---------------------------------------------------------------- revenue
    {"id": "gross_revenue", "name": "Gross revenue", "category": "Revenue", "unit": "inr", "direction": "up_good",
     "definition": "Interest collected (balance-sheet products) + processing, late and foreclosure fees recognised in the month.",
     "formula": "SUM(fct_revenue_events.amount) excluding credit_loss"},
    {"id": "credit_losses", "name": "Credit losses (write-offs)", "category": "Revenue", "unit": "inr", "direction": "down_good",
     "definition": "Principal written off in the month (180+ DPD, company-funded products).", "formula": "SUM(credit_loss) by write-off month"},
    {"id": "net_revenue", "name": "Net revenue", "category": "Revenue", "unit": "inr", "direction": "up_good",
     "definition": "Gross revenue minus credit losses.", "formula": "gross_revenue - credit_losses"},
    # ---------------------------------------------------------------- risk & collections
    {"id": "outstanding_principal", "name": "Outstanding principal (AUM)", "category": "Portfolio", "unit": "inr",
     "direction": "up_good", "definition": "Principal outstanding on loans on book at month end (excl. written off).",
     "formula": "SUM(outstanding) from month-end snapshot"},
    {"id": "par30_rate", "name": "PAR30", "category": "Risk", "unit": "pct", "direction": "down_good", "target": (0.06, "<="),
     "definition": "Outstanding principal on loans 30-179 DPD / total outstanding at month end.",
     "formula": "SUM(par30_outstanding) / SUM(outstanding_principal)"},
    {"id": "npa_rate", "name": "NPA (90+ DPD)", "category": "Risk", "unit": "pct", "direction": "down_good", "target": (0.035, "<="),
     "definition": "Outstanding principal on loans 90-179 DPD / total outstanding at month end (RBI NPA definition).",
     "formula": "SUM(npa_outstanding) / SUM(outstanding_principal)"},
    {"id": "fpd30_rate", "name": "First-payment default (FPD30)", "category": "Risk", "unit": "pct", "direction": "down_good",
     "target": (0.03, "<="), "definition": "Share of loans disbursed in the month whose first EMI went 30+ days past due.",
     "formula": "loans with first instalment DPD >= 30 / matured loans",
     "lag_note": "Needs first due date + 30 days, so the latest value refers to loans disbursed ~2 months ago."},
    {"id": "collection_efficiency", "name": "Collection efficiency", "category": "Repayments", "unit": "pct",
     "direction": "up_good", "target": (0.95, ">="),
     "definition": "Amount collected by month end against instalments falling due in the month.",
     "formula": "SUM(amount_paid by month end) / SUM(total_due) for instalments due in month"},
    {"id": "payment_failure_rate", "name": "Payment failure rate", "category": "Repayments", "unit": "pct",
     "direction": "down_good", "target": (0.08, "<="),
     "definition": "Failed EMI debit attempts / all EMI debit attempts.", "formula": "failed / (failed + success)"},
    # ---------------------------------------------------------------- engagement & support
    {"id": "mau", "name": "Monthly active users", "category": "Engagement", "unit": "count", "direction": "up_good",
     "definition": "Distinct customers with at least one client-side (app/web) event in the month.",
     "formula": "COUNT(DISTINCT user_id) WHERE platform <> 'server'"},
    {"id": "support_tickets", "name": "Support tickets", "category": "Support", "unit": "count", "direction": "down_good",
     "definition": "Tickets created in the month.", "formula": "COUNT(support_tickets)"},
    {"id": "tickets_per_1k_mau", "name": "Tickets per 1k MAU", "category": "Support", "unit": "ratio", "direction": "down_good",
     "definition": "Support tickets per thousand monthly active users.", "formula": "tickets * 1000 / MAU"},
    {"id": "csat_avg", "name": "CSAT", "category": "Support", "unit": "score", "direction": "up_good", "target": (4.0, ">="),
     "definition": "Average post-resolution satisfaction score (1-5).", "formula": "AVG(csat_score)"},
    # ---------------------------------------------------------------- marketing
    {"id": "marketing_spend", "name": "Marketing spend", "category": "Marketing", "unit": "inr", "direction": "neutral",
     "definition": "Paid acquisition spend, pro-rated by day across campaign flights.", "formula": "SUM(spend_inr / flight days)"},
    {"id": "blended_cac", "name": "Blended CAC", "category": "Marketing", "unit": "inr", "direction": "down_good",
     "definition": "Marketing spend / all new customers (incl. organic).", "formula": "marketing_spend / new_customers"},
    {"id": "cost_per_new_borrower", "name": "Cost per new borrower", "category": "Marketing", "unit": "inr",
     "direction": "down_good", "target": (2500, "<="),
     "definition": "Marketing spend / customers taking their first loan in the month.", "formula": "marketing_spend / new_borrowers"},
]

WEEKLY_KPIS: List[Dict] = [
    {"id": "new_customers", "name": "New customers", "unit": "count", "direction": "up_good"},
    {"id": "kyc_completions", "name": "KYC completions", "unit": "count", "direction": "up_good"},
    {"id": "applications_submitted", "name": "Applications submitted", "unit": "count", "direction": "up_good"},
    {"id": "approval_rate", "name": "Approval rate", "unit": "pct", "direction": "neutral"},
    {"id": "loans_disbursed", "name": "Loans disbursed", "unit": "count", "direction": "up_good"},
    {"id": "disbursed_amount", "name": "Disbursed amount", "unit": "inr", "direction": "up_good"},
    {"id": "collections_amount", "name": "EMI collections", "unit": "inr", "direction": "up_good"},
    {"id": "payment_failure_rate", "name": "Payment failure rate", "unit": "pct", "direction": "down_good"},
    {"id": "gross_revenue", "name": "Gross revenue", "unit": "inr", "direction": "up_good"},
    {"id": "support_tickets", "name": "Support tickets", "unit": "count", "direction": "down_good"},
    {"id": "csat_avg", "name": "CSAT", "unit": "score", "direction": "up_good"},
    {"id": "avg_dau", "name": "Average DAU", "unit": "count", "direction": "up_good"},
]

KPI_BY_ID = {k["id"]: k for k in KPIS}
