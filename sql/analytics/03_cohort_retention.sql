-- =============================================================================
-- 03 COHORT RETENTION
-- Business question: do customers keep coming back after signup, and is cohort quality
-- (conversion and early credit performance) stable or being diluted by growth campaigns?
-- Activity = at least one client-side (app/web) event in the month.
-- =============================================================================

-- @query: activity_retention_matrix
WITH cohorts AS (
    SELECT customer_id, cohort_month FROM marts.fct_customer_funnel
),
sizes AS (
    SELECT cohort_month, COUNT(*) AS cohort_size FROM cohorts GROUP BY cohort_month
),
active AS (
    SELECT c.cohort_month,
           date_diff('month', c.cohort_month, a.activity_month)      AS month_number,
           COUNT(DISTINCT a.customer_id)                             AS active_customers
    FROM cohorts c
    JOIN marts.fct_user_activity_monthly a
      ON a.customer_id = c.customer_id
     AND a.client_events > 0
     AND a.activity_month >= c.cohort_month
    GROUP BY 1, 2
)
SELECT
    a.cohort_month,
    s.cohort_size,
    a.month_number,
    a.active_customers,
    ROUND(100.0 * a.active_customers / s.cohort_size, 2)                                  AS retention_pct
FROM active a
JOIN sizes s ON s.cohort_month = a.cohort_month
ORDER BY a.cohort_month, a.month_number;

-- @query: retention_curve_by_borrower_status
-- Same curve split by whether the customer ever borrowed: borrowing is what keeps users in the app.
WITH cohorts AS (
    SELECT customer_id, cohort_month, CASE WHEN n_loans > 0 THEN 'borrower' ELSE 'non_borrower' END AS borrower_status
    FROM marts.fct_customer_funnel
),
sizes AS (
    SELECT borrower_status, COUNT(*) AS customers FROM cohorts GROUP BY 1
),
active AS (
    SELECT c.borrower_status,
           date_diff('month', c.cohort_month, a.activity_month) AS month_number,
           COUNT(DISTINCT a.customer_id)                        AS active_customers
    FROM cohorts c
    JOIN marts.fct_user_activity_monthly a ON a.customer_id = c.customer_id AND a.client_events > 0
    GROUP BY 1, 2
),
eligible AS (     -- customers whose cohort is old enough to observe month N
    SELECT c.borrower_status, m.month_number, COUNT(*) AS eligible_customers
    FROM cohorts c
    CROSS JOIN (SELECT DISTINCT month_number FROM active) m
    CROSS JOIN marts.run_params p
    WHERE date_diff('month', c.cohort_month, p.as_of_date) >= m.month_number
    GROUP BY 1, 2
)
SELECT a.borrower_status, a.month_number, e.eligible_customers, a.active_customers,
       ROUND(100.0 * a.active_customers / e.eligible_customers, 2) AS retention_pct
FROM active a
JOIN eligible e ON e.borrower_status = a.borrower_status AND e.month_number = a.month_number
WHERE a.month_number <= 12
ORDER BY a.borrower_status, a.month_number;

-- @query: cohort_quality
-- Conversion and first-loan risk per signup cohort: festive-season cohorts convert but default more.
WITH first_loans AS (
    SELECT lp.customer_id, lp.is_fpd30, lp.fpd30_mature
    FROM marts.fct_loan_performance lp
    WHERE lp.loan_sequence_number = 1
)
SELECT
    f.cohort_month,
    COUNT(*)                                                                               AS signups,
    ROUND(100.0 * AVG(CASE WHEN f.kyc_completed_7d THEN 1 ELSE 0 END), 2)                 AS kyc_7d_pct,
    ROUND(100.0 * AVG(CASE WHEN f.disbursed_30d THEN 1 ELSE 0 END), 2)                    AS disbursed_30d_pct,
    SUM(CASE WHEN fl.fpd30_mature THEN 1 ELSE 0 END)                                       AS first_loans_matured,
    ROUND(100.0 * SUM(CASE WHEN fl.fpd30_mature AND fl.is_fpd30 THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN fl.fpd30_mature THEN 1 ELSE 0 END), 0), 2)                AS first_loan_fpd30_pct,
    ROUND(100.0 * SUM(CASE WHEN f.acquisition_channel IN ('paid_social', 'affiliate') THEN 1 ELSE 0 END)
          / COUNT(*), 1)                                                                   AS paid_social_affiliate_share_pct
FROM marts.fct_customer_funnel f
LEFT JOIN first_loans fl ON fl.customer_id = f.customer_id
WHERE f.is_mature_30d
GROUP BY f.cohort_month
ORDER BY f.cohort_month;
