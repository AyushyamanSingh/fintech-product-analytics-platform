-- KPI layer, monthly grain (wide). Definitions, units, targets and owners live in
-- python/kpi_definitions.py; python/kpis.py melts this to long format and computes deltas.
-- Cohort-based rates only use customers/loans whose observation window is complete (maturity).
WITH months AS (
    SELECT DISTINCT month_start FROM marts.dim_date
),
acq AS (
    SELECT cohort_month AS month_start,
           COUNT(*)                                                                                   AS new_customers,
           SUM(CASE WHEN is_mature_7d AND kyc_completed_7d THEN 1 ELSE 0 END) * 1.0
               / NULLIF(SUM(CASE WHEN is_mature_7d THEN 1 ELSE 0 END), 0)                             AS kyc_completion_rate_7d,
           SUM(CASE WHEN is_mature_30d AND disbursed_30d THEN 1 ELSE 0 END) * 1.0
               / NULLIF(SUM(CASE WHEN is_mature_30d THEN 1 ELSE 0 END), 0)                            AS signup_to_disbursal_30d
    FROM marts.fct_customer_funnel
    GROUP BY 1
),
apps AS (
    SELECT CAST(date_trunc('month', submitted_ts) AS DATE) AS month_start, COUNT(*) AS applications_submitted
    FROM core.applications WHERE submitted_ts IS NOT NULL GROUP BY 1
),
decisions AS (
    SELECT CAST(date_trunc('month', decision_ts) AS DATE) AS month_start,
           AVG(CASE WHEN decision = 'approved' THEN 1.0 ELSE 0 END)                                   AS approval_rate,
           SUM(CASE WHEN decision = 'approved' AND application_status = 'disbursed' THEN 1 ELSE 0 END) * 1.0
               / NULLIF(SUM(CASE WHEN decision = 'approved' THEN 1 ELSE 0 END), 0)                    AS offer_acceptance_rate
    FROM core.applications WHERE decision_ts IS NOT NULL GROUP BY 1
),
loans AS (
    SELECT disbursal_month AS month_start,
           COUNT(*)                                                                    AS loans_disbursed,
           SUM(principal_amount)                                                       AS disbursed_amount,
           AVG(principal_amount)                                                       AS avg_ticket_size,
           SUM(CASE WHEN loan_sequence_number = 1 THEN 1 ELSE 0 END)                   AS new_borrowers,
           AVG(CASE WHEN is_repeat_loan THEN 1.0 ELSE 0 END)                           AS repeat_loan_share,
           AVG(CASE WHEN autopay_enabled THEN 1.0 ELSE 0 END)                          AS autopay_adoption_rate,
           SUM(CASE WHEN fpd30_mature AND is_fpd30 THEN 1 ELSE 0 END) * 1.0
               / NULLIF(SUM(CASE WHEN fpd30_mature THEN 1 ELSE 0 END), 0)              AS fpd30_rate
    FROM marts.fct_loan_performance GROUP BY 1
),
revenue AS (
    SELECT CAST(date_trunc('month', revenue_date) AS DATE) AS month_start,
           SUM(CASE WHEN component <> 'credit_loss' THEN amount ELSE 0 END)           AS gross_revenue,
           SUM(amount)                                                                AS net_revenue,
           SUM(CASE WHEN component = 'credit_loss' THEN -amount ELSE 0 END)           AS credit_losses
    FROM marts.fct_revenue_events GROUP BY 1
),
portfolio AS (
    SELECT month_start,
           SUM(outstanding_principal)                                                 AS outstanding_principal,
           SUM(par30_outstanding) / NULLIF(SUM(outstanding_principal), 0)             AS par30_rate,
           SUM(npa_outstanding)   / NULLIF(SUM(outstanding_principal), 0)             AS npa_rate
    FROM marts.fct_portfolio_monthly GROUP BY 1
),
collections AS (
    -- share of the amount falling due in the month that was collected by the end of that month
    SELECT CAST(date_trunc('month', r.due_date) AS DATE) AS month_start,
           SUM(CASE WHEN r.paid_date <= CAST(date_trunc('month', r.due_date) + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE)
                    THEN r.amount_paid ELSE 0 END) / NULLIF(SUM(r.total_due), 0)       AS collection_efficiency
    FROM core.repayments r
    CROSS JOIN marts.run_params p
    WHERE r.due_date <= p.as_of_date
    GROUP BY 1
),
payments AS (
    SELECT month_start,
           SUM(payments_failed) * 1.0 / NULLIF(SUM(payments_success + payments_failed), 0) AS payment_failure_rate
    FROM marts.fct_daily_metrics GROUP BY 1
),
mau AS (
    SELECT activity_month AS month_start, COUNT(DISTINCT customer_id) AS mau
    FROM marts.fct_user_activity_monthly WHERE client_events > 0 GROUP BY 1
),
support AS (
    SELECT CAST(date_trunc('month', created_ts) AS DATE) AS month_start,
           COUNT(*) AS support_tickets, AVG(csat_score) AS csat_avg
    FROM core.support_tickets GROUP BY 1
),
spend AS (
    SELECT d.month_start, SUM(mc.spend_inr / (date_diff('day', mc.start_date, mc.end_date) + 1)) AS marketing_spend
    FROM core.marketing_campaigns mc
    JOIN marts.dim_date d ON d.date_day BETWEEN mc.start_date AND mc.end_date
    GROUP BY 1
)
SELECT
    m.month_start,
    acq.new_customers,
    acq.kyc_completion_rate_7d,
    acq.signup_to_disbursal_30d,
    apps.applications_submitted,
    decisions.approval_rate,
    decisions.offer_acceptance_rate,
    loans.loans_disbursed,
    loans.disbursed_amount,
    loans.avg_ticket_size,
    loans.new_borrowers,
    loans.repeat_loan_share,
    loans.autopay_adoption_rate,
    loans.fpd30_rate,
    revenue.gross_revenue,
    revenue.net_revenue,
    revenue.credit_losses,
    portfolio.outstanding_principal,
    portfolio.par30_rate,
    portfolio.npa_rate,
    collections.collection_efficiency,
    payments.payment_failure_rate,
    mau.mau,
    support.support_tickets,
    support.support_tickets * 1000.0 / NULLIF(mau.mau, 0)              AS tickets_per_1k_mau,
    support.csat_avg,
    spend.marketing_spend,
    spend.marketing_spend / NULLIF(acq.new_customers, 0)               AS blended_cac,
    spend.marketing_spend / NULLIF(loans.new_borrowers, 0)             AS cost_per_new_borrower
FROM months m
LEFT JOIN acq         ON acq.month_start         = m.month_start
LEFT JOIN apps        ON apps.month_start        = m.month_start
LEFT JOIN decisions   ON decisions.month_start   = m.month_start
LEFT JOIN loans       ON loans.month_start       = m.month_start
LEFT JOIN revenue     ON revenue.month_start     = m.month_start
LEFT JOIN portfolio   ON portfolio.month_start   = m.month_start
LEFT JOIN collections ON collections.month_start = m.month_start
LEFT JOIN payments    ON payments.month_start    = m.month_start
LEFT JOIN mau         ON mau.month_start         = m.month_start
LEFT JOIN support     ON support.month_start     = m.month_start
LEFT JOIN spend       ON spend.month_start       = m.month_start
ORDER BY m.month_start;
