-- Daily operating metrics: the input for trend charts, weekly KPIs and anomaly detection.
-- Each source is aggregated BEFORE joining to the calendar (avoids fan-out and keeps scans single-pass).
CREATE OR REPLACE TABLE marts.fct_daily_metrics AS
WITH signups AS (
    SELECT CAST(signup_ts AS DATE) AS d, COUNT(*) AS signups,
           SUM(CASE WHEN acquisition_channel IN ('paid_search', 'paid_social', 'affiliate') THEN 1 ELSE 0 END) AS paid_signups
    FROM core.customers GROUP BY 1
),
kyc_backend AS (
    SELECT CAST(kyc_completed_ts AS DATE) AS d, COUNT(*) AS kyc_completions_backend
    FROM core.customers WHERE kyc_completed_ts IS NOT NULL GROUP BY 1
),
kyc_tracked AS (
    SELECT CAST(event_ts AS DATE) AS d, COUNT(DISTINCT user_id) AS kyc_completions_tracked
    FROM core.product_events WHERE event_name = 'kyc_completed' GROUP BY 1
),
app_start AS (
    SELECT CAST(started_ts AS DATE) AS d, COUNT(*) AS applications_started FROM core.applications GROUP BY 1
),
app_submit AS (
    SELECT CAST(submitted_ts AS DATE) AS d, COUNT(*) AS applications_submitted
    FROM core.applications WHERE submitted_ts IS NOT NULL GROUP BY 1
),
decisions AS (
    SELECT CAST(decision_ts AS DATE) AS d,
           SUM(CASE WHEN decision = 'approved' THEN 1 ELSE 0 END) AS approvals,
           SUM(CASE WHEN decision = 'rejected' THEN 1 ELSE 0 END) AS rejections
    FROM core.applications WHERE decision_ts IS NOT NULL GROUP BY 1
),
disbursals AS (
    SELECT CAST(disbursed_ts AS DATE) AS d, COUNT(*) AS loans_disbursed,
           SUM(principal_amount) AS disbursed_amount,
           SUM(CASE WHEN is_repeat_loan THEN 1 ELSE 0 END) AS repeat_loans
    FROM core.loans GROUP BY 1
),
payments AS (
    SELECT CAST(txn_ts AS DATE) AS d,
           SUM(CASE WHEN txn_type = 'emi_payment' AND txn_status = 'success' THEN 1 ELSE 0 END)      AS payments_success,
           SUM(CASE WHEN txn_type = 'emi_payment' AND txn_status = 'failed'  THEN 1 ELSE 0 END)      AS payments_failed,
           SUM(CASE WHEN txn_type = 'emi_payment' AND txn_status = 'success' THEN amount ELSE 0 END) AS collections_amount
    FROM core.transactions GROUP BY 1
),
tickets AS (
    SELECT CAST(created_ts AS DATE) AS d, COUNT(*) AS support_tickets,
           SUM(CASE WHEN category = 'payment_failure' THEN 1 ELSE 0 END) AS payment_failure_tickets,
           SUM(CASE WHEN category = 'kyc_issue' THEN 1 ELSE 0 END)       AS kyc_tickets
    FROM core.support_tickets GROUP BY 1
),
dau AS (
    SELECT CAST(event_ts AS DATE) AS d, COUNT(DISTINCT user_id) AS dau
    FROM core.product_events WHERE platform <> 'server' GROUP BY 1
)
SELECT
    dd.date_day,
    dd.week_start,
    dd.month_start,
    dd.iso_dow,
    COALESCE(s.signups, 0)                      AS signups,
    COALESCE(s.paid_signups, 0)                 AS paid_signups,
    COALESCE(kb.kyc_completions_backend, 0)     AS kyc_completions_backend,
    COALESCE(kt.kyc_completions_tracked, 0)     AS kyc_completions_tracked,
    COALESCE(a1.applications_started, 0)        AS applications_started,
    COALESCE(a2.applications_submitted, 0)      AS applications_submitted,
    COALESCE(de.approvals, 0)                   AS approvals,
    COALESCE(de.rejections, 0)                  AS rejections,
    de.approvals * 1.0 / NULLIF(de.approvals + de.rejections, 0)                       AS approval_rate,
    COALESCE(db.loans_disbursed, 0)             AS loans_disbursed,
    COALESCE(db.disbursed_amount, 0)            AS disbursed_amount,
    COALESCE(db.repeat_loans, 0)                AS repeat_loans,
    COALESCE(py.payments_success, 0)            AS payments_success,
    COALESCE(py.payments_failed, 0)             AS payments_failed,
    py.payments_failed * 1.0 / NULLIF(py.payments_success + py.payments_failed, 0)     AS payment_failure_rate,
    COALESCE(py.collections_amount, 0)          AS collections_amount,
    COALESCE(tk.support_tickets, 0)             AS support_tickets,
    COALESCE(tk.payment_failure_tickets, 0)     AS payment_failure_tickets,
    COALESCE(tk.kyc_tickets, 0)                 AS kyc_tickets,
    COALESCE(dau.dau, 0)                        AS dau
FROM marts.dim_date dd
LEFT JOIN signups     s   ON s.d   = dd.date_day
LEFT JOIN kyc_backend kb  ON kb.d  = dd.date_day
LEFT JOIN kyc_tracked kt  ON kt.d  = dd.date_day
LEFT JOIN app_start   a1  ON a1.d  = dd.date_day
LEFT JOIN app_submit  a2  ON a2.d  = dd.date_day
LEFT JOIN decisions   de  ON de.d  = dd.date_day
LEFT JOIN disbursals  db  ON db.d  = dd.date_day
LEFT JOIN payments    py  ON py.d  = dd.date_day
LEFT JOIN tickets     tk  ON tk.d  = dd.date_day
LEFT JOIN dau             ON dau.d = dd.date_day
ORDER BY dd.date_day;
