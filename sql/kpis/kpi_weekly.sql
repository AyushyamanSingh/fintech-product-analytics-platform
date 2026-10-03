-- KPI layer, weekly grain (ISO weeks, complete weeks only). Feeds the weekly business summary.
WITH w AS (
    SELECT
        week_start,
        COUNT(*)                                          AS days_in_week,
        SUM(signups)                                      AS new_customers,
        SUM(kyc_completions_backend)                      AS kyc_completions,
        SUM(applications_submitted)                       AS applications_submitted,
        SUM(approvals)                                    AS approvals,
        SUM(rejections)                                   AS rejections,
        SUM(loans_disbursed)                              AS loans_disbursed,
        SUM(disbursed_amount)                             AS disbursed_amount,
        SUM(collections_amount)                           AS collections_amount,
        SUM(payments_success)                             AS payments_success,
        SUM(payments_failed)                              AS payments_failed,
        SUM(support_tickets)                              AS support_tickets,
        AVG(dau)                                          AS avg_dau
    FROM marts.fct_daily_metrics
    GROUP BY week_start
),
rev AS (
    SELECT CAST(date_trunc('week', revenue_date) AS DATE) AS week_start,
           SUM(CASE WHEN component <> 'credit_loss' THEN amount ELSE 0 END) AS gross_revenue
    FROM marts.fct_revenue_events GROUP BY 1
),
csat AS (
    SELECT CAST(date_trunc('week', created_ts) AS DATE) AS week_start, AVG(csat_score) AS csat_avg
    FROM core.support_tickets GROUP BY 1
)
SELECT
    w.week_start,
    w.new_customers,
    w.kyc_completions,
    w.applications_submitted,
    w.approvals * 1.0 / NULLIF(w.approvals + w.rejections, 0)              AS approval_rate,
    w.loans_disbursed,
    w.disbursed_amount,
    w.collections_amount,
    w.payments_failed * 1.0 / NULLIF(w.payments_success + w.payments_failed, 0) AS payment_failure_rate,
    rev.gross_revenue,
    w.support_tickets,
    csat.csat_avg,
    w.avg_dau
FROM w
LEFT JOIN rev  ON rev.week_start  = w.week_start
LEFT JOIN csat ON csat.week_start = w.week_start
WHERE w.days_in_week = 7
ORDER BY w.week_start;
