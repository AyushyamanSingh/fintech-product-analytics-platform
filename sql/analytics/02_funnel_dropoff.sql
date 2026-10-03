-- =============================================================================
-- 02 DROP-OFF ANALYSIS
-- Business question: which customer segments leak most at KYC, how big is the gap to the
-- best segment, and how fast do converters move through onboarding?
-- =============================================================================

-- @query: kyc_dropoff_by_segment
-- GROUPING SETS computes every segment cut in a single scan of the funnel mart.
WITH cuts AS (
    SELECT
        CASE WHEN GROUPING(signup_platform) = 0     THEN 'platform'
             WHEN GROUPING(city_tier) = 0           THEN 'city_tier'
             WHEN GROUPING(employment_type) = 0     THEN 'employment_type'
             WHEN GROUPING(acquisition_channel) = 0 THEN 'acquisition_channel'
             ELSE 'is_ntc' END                                                            AS dimension,
        COALESCE(signup_platform, city_tier, employment_type, acquisition_channel,
                 CASE WHEN is_ntc THEN 'new_to_credit' ELSE 'has_bureau_score' END)       AS segment,
        COUNT(*)                                                                          AS signups,
        AVG(CASE WHEN kyc_started_ts IS NOT NULL THEN 1.0 ELSE 0 END)                    AS kyc_start_rate,
        AVG(CASE WHEN kyc_completed_7d THEN 1.0 ELSE 0 END)                              AS kyc_7d_rate
    FROM marts.fct_customer_funnel
    WHERE is_mature_7d
    GROUP BY GROUPING SETS ((signup_platform), (city_tier), (employment_type), (acquisition_channel), (is_ntc))
)
SELECT
    dimension,
    segment,
    signups,
    ROUND(100 * kyc_start_rate, 2)                                                       AS kyc_start_pct,
    ROUND(100 * kyc_7d_rate, 2)                                                          AS kyc_7d_pct,
    ROUND(100 * (MAX(kyc_7d_rate) OVER (PARTITION BY dimension) - kyc_7d_rate), 2)       AS gap_to_best_pp,
    RANK() OVER (PARTITION BY dimension ORDER BY kyc_7d_rate ASC)                        AS worst_rank,
    -- customers who would complete KYC if this segment matched the best segment in its dimension
    CAST(ROUND(signups * (MAX(kyc_7d_rate) OVER (PARTITION BY dimension) - kyc_7d_rate)) AS INTEGER) AS recoverable_customers
FROM cuts
ORDER BY dimension, worst_rank;

-- @query: biggest_leak_by_month
-- Which funnel step loses the most customers each month (mature 30-day cohorts)?
WITH m AS (
    SELECT cohort_month,
           COUNT(*)                                                                AS s0,
           SUM(CASE WHEN kyc_completed_ts IS NOT NULL THEN 1 ELSE 0 END)           AS s1,
           SUM(CASE WHEN first_app_submitted_ts IS NOT NULL THEN 1 ELSE 0 END)     AS s2,
           SUM(CASE WHEN first_approved_ts IS NOT NULL THEN 1 ELSE 0 END)          AS s3,
           SUM(CASE WHEN first_disbursed_ts IS NOT NULL THEN 1 ELSE 0 END)         AS s4
    FROM marts.fct_customer_funnel
    WHERE is_mature_30d
    GROUP BY cohort_month
),
steps AS (
    SELECT cohort_month, 'signup -> KYC completed' AS step, s0 - s1 AS lost, 1 - s1 * 1.0 / NULLIF(s0, 0) AS loss_rate FROM m
    UNION ALL SELECT cohort_month, 'KYC -> application submitted', s1 - s2, 1 - s2 * 1.0 / NULLIF(s1, 0) FROM m
    UNION ALL SELECT cohort_month, 'submitted -> approved',        s2 - s3, 1 - s3 * 1.0 / NULLIF(s2, 0) FROM m
    UNION ALL SELECT cohort_month, 'approved -> disbursed',        s3 - s4, 1 - s4 * 1.0 / NULLIF(s3, 0) FROM m
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY cohort_month ORDER BY lost DESC) AS rn
    FROM steps
)
SELECT cohort_month, step AS biggest_leak, lost AS customers_lost, ROUND(100 * loss_rate, 2) AS step_loss_pct
FROM ranked
WHERE rn = 1
ORDER BY cohort_month;

-- @query: time_to_convert
-- Median and tail conversion speed by platform (only customers who reached each milestone).
SELECT
    signup_platform,
    COUNT(minutes_signup_to_kyc)                                                         AS kyc_completers,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY minutes_signup_to_kyc), 1)         AS median_minutes_to_kyc,
    ROUND(percentile_cont(0.9) WITHIN GROUP (ORDER BY minutes_signup_to_kyc) / 60.0, 1)  AS p90_hours_to_kyc,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY hours_kyc_to_application), 1)      AS median_hours_kyc_to_application,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY days_signup_to_disbursal), 1)      AS median_days_to_disbursal,
    ROUND(percentile_cont(0.9) WITHIN GROUP (ORDER BY days_signup_to_disbursal), 1)      AS p90_days_to_disbursal
FROM marts.fct_customer_funnel
GROUP BY signup_platform
ORDER BY signup_platform;

-- @query: kyc_weekly_trend
-- Weekly 7-day KYC completion for app signups: shows the step change after the redesign shipped (2 Mar 2026).
SELECT
    signup_week,
    COUNT(*)                                                                             AS app_signups,
    ROUND(100.0 * AVG(CASE WHEN kyc_completed_7d THEN 1 ELSE 0 END), 2)                 AS kyc_7d_pct,
    ROUND(AVG(100.0 * AVG(CASE WHEN kyc_completed_7d THEN 1 ELSE 0 END))
          OVER (ORDER BY signup_week ROWS BETWEEN 3 PRECEDING AND CURRENT ROW), 2)       AS kyc_7d_pct_4wk_avg,
    CASE WHEN signup_week >= DATE '2026-03-02' THEN 'post_redesign'
         WHEN signup_week >= DATE '2026-01-12' THEN 'experiment'
         ELSE 'pre_redesign' END                                                         AS period
FROM marts.fct_customer_funnel
WHERE signup_platform <> 'web' AND is_mature_7d
GROUP BY signup_week
ORDER BY signup_week;
