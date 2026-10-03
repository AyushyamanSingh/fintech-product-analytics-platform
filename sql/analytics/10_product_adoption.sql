-- =============================================================================
-- 10 PRODUCT & FEATURE ADOPTION
-- Business question: how is the product mix shifting, is the Flexi Credit Line (P07, launched
-- Apr 2025) winning new or existing customers, and which app features go with better
-- repayment behaviour?
-- =============================================================================

-- @query: product_adoption_monthly
WITH ranked AS (
    SELECT disbursal_month, product_id, customer_id,
           ROW_NUMBER() OVER (PARTITION BY customer_id, product_id ORDER BY disbursed_ts) AS nth_loan_of_product
    FROM marts.fct_loan_performance
)
SELECT
    disbursal_month,
    product_id,
    COUNT(*)                                                                  AS loans,
    SUM(CASE WHEN nth_loan_of_product = 1 THEN 1 ELSE 0 END)                  AS first_time_product_users,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY disbursal_month), 2) AS share_of_month_loans_pct
FROM ranked
GROUP BY disbursal_month, product_id
ORDER BY disbursal_month, product_id;

-- @query: credit_line_launch
-- P07 adoption by month since launch and where its borrowers come from.
WITH p07 AS (
    SELECT lp.disbursal_month, lp.customer_id, lp.loan_sequence_number,
           EXISTS (SELECT 1 FROM marts.fct_loan_performance prev
                   WHERE prev.customer_id = lp.customer_id AND prev.disbursed_ts < lp.disbursed_ts
                     AND prev.product_id = 'P01')                                   AS had_personal_loan_before
    FROM marts.fct_loan_performance lp
    WHERE lp.product_id = 'P07'
),
all_new AS (
    SELECT disbursal_month, COUNT(*) AS all_loans FROM marts.fct_loan_performance GROUP BY 1
)
SELECT
    p.disbursal_month,
    COUNT(*)                                                                         AS p07_loans,
    ROUND(100.0 * COUNT(*) / a.all_loans, 2)                                         AS p07_share_of_loans_pct,
    ROUND(100.0 * AVG(CASE WHEN p.loan_sequence_number = 1 THEN 1 ELSE 0 END), 2)  AS from_new_borrowers_pct,
    ROUND(100.0 * AVG(CASE WHEN p.had_personal_loan_before THEN 1 ELSE 0 END), 2)  AS from_prior_personal_loan_pct
FROM p07 p
JOIN all_new a ON a.disbursal_month = p.disbursal_month
GROUP BY p.disbursal_month, a.all_loans
ORDER BY p.disbursal_month;

-- @query: feature_adoption_impact
-- Adoption of app features among borrowers, and repayment outcomes for adopters vs non-adopters.
-- Correlation, not causation: engaged customers both adopt features and repay better.
WITH b AS (
    SELECT * FROM marts.customer_360 WHERE n_loans > 0 AND installments_due > 0
),
features AS (
    SELECT 'autopay' AS feature, autopay_ever AS adopted, on_time_rate, n_loans, max_dpd_ever FROM b
    UNION ALL SELECT 'credit_score_view', used_credit_score, on_time_rate, n_loans, max_dpd_ever FROM b
    UNION ALL SELECT 'emi_calculator',    used_emi_calculator, on_time_rate, n_loans, max_dpd_ever FROM b
    UNION ALL SELECT 'referral_share',    referrals_shared > 0, on_time_rate, n_loans, max_dpd_ever FROM b
)
SELECT
    feature,
    ROUND(100.0 * AVG(CASE WHEN adopted THEN 1 ELSE 0 END), 2)                                         AS adoption_pct,
    ROUND(100.0 * AVG(CASE WHEN adopted THEN on_time_rate END), 2)                                     AS on_time_pct_adopters,
    ROUND(100.0 * AVG(CASE WHEN NOT adopted THEN on_time_rate END), 2)                                 AS on_time_pct_non_adopters,
    ROUND(100.0 * AVG(CASE WHEN adopted THEN (max_dpd_ever >= 30)::INTEGER END), 2)                    AS ever30_pct_adopters,
    ROUND(100.0 * AVG(CASE WHEN NOT adopted THEN (max_dpd_ever >= 30)::INTEGER END), 2)                AS ever30_pct_non_adopters,
    ROUND(AVG(CASE WHEN adopted THEN n_loans END), 2)                                                  AS loans_per_adopter,
    ROUND(AVG(CASE WHEN NOT adopted THEN n_loans END), 2)                                              AS loans_per_non_adopter
FROM features
GROUP BY feature
ORDER BY adoption_pct DESC;

-- @query: sessionization_last_month
-- Rebuild sessions from raw client events with a 30-minute inactivity rule (LAG + running SUM)
-- and compare with the SDK's own session ids. Scoped to the latest month to bound the scan.
WITH ev AS (
    SELECT e.user_id, e.platform, e.event_ts, e.session_id
    FROM core.product_events e
    CROSS JOIN marts.run_params p
    WHERE e.platform <> 'server'
      AND e.event_ts >= CAST(date_trunc('month', p.as_of_date) AS TIMESTAMP)
),
gaps AS (
    SELECT *,
           CASE WHEN LAG(event_ts) OVER (PARTITION BY user_id ORDER BY event_ts) IS NULL
                  OR event_ts - LAG(event_ts) OVER (PARTITION BY user_id ORDER BY event_ts) > INTERVAL 30 MINUTE
                THEN 1 ELSE 0 END AS new_session
    FROM ev
),
numbered AS (
    SELECT *, SUM(new_session) OVER (PARTITION BY user_id ORDER BY event_ts
                                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_seq
    FROM gaps
),
sessions AS (
    SELECT user_id, session_seq, MIN(platform) AS platform, COUNT(*) AS events,
           date_diff('second', MIN(event_ts), MAX(event_ts)) / 60.0 AS session_minutes
    FROM numbered
    GROUP BY user_id, session_seq
)
SELECT platform,
       COUNT(*)                                                                  AS derived_sessions,
       (SELECT COUNT(DISTINCT session_id) FROM ev WHERE ev.platform = s.platform) AS sdk_sessions,
       ROUND(AVG(events), 2)                                                     AS events_per_session,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY session_minutes), 2)    AS median_session_minutes
FROM sessions s
GROUP BY platform
ORDER BY derived_sessions DESC;
