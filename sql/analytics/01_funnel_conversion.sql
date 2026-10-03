-- =============================================================================
-- 01 FUNNEL CONVERSION
-- Business question: where do new customers fall out between signup and first disbursal,
-- and how does conversion differ by acquisition cohort and channel?
-- Conventions: customer-level funnel (furthest stage reached); cohorts must be >= 30 days
-- old so every customer had the same window to convert (no right-censoring bias).
-- Each "-- @query:" block is executed separately by python/run_sql_analytics.py.
-- =============================================================================

-- @query: funnel_overall
WITH base AS (
    SELECT f.*
    FROM marts.fct_customer_funnel f
    WHERE f.is_mature_30d
),
agg AS (
    SELECT
        COUNT(*)                                                                    AS signed_up,
        SUM(CASE WHEN kyc_started_ts IS NOT NULL THEN 1 ELSE 0 END)                 AS kyc_started,
        SUM(CASE WHEN kyc_completed_ts IS NOT NULL THEN 1 ELSE 0 END)               AS kyc_completed,
        SUM(CASE WHEN first_app_started_ts IS NOT NULL THEN 1 ELSE 0 END)           AS application_started,
        SUM(CASE WHEN first_app_submitted_ts IS NOT NULL THEN 1 ELSE 0 END)         AS application_submitted,
        SUM(CASE WHEN first_approved_ts IS NOT NULL THEN 1 ELSE 0 END)              AS approved,
        SUM(CASE WHEN first_disbursed_ts IS NOT NULL THEN 1 ELSE 0 END)             AS disbursed
    FROM base
),
stages AS (
    SELECT 1 AS stage_order, 'Signed up' AS stage, signed_up AS customers FROM agg
    UNION ALL SELECT 2, 'KYC started',           kyc_started           FROM agg
    UNION ALL SELECT 3, 'KYC completed',         kyc_completed         FROM agg
    UNION ALL SELECT 4, 'Application started',   application_started   FROM agg
    UNION ALL SELECT 5, 'Application submitted', application_submitted FROM agg
    UNION ALL SELECT 6, 'Approved',              approved              FROM agg
    UNION ALL SELECT 7, 'Disbursed',             disbursed             FROM agg
)
SELECT
    stage_order,
    stage,
    customers,
    ROUND(100.0 * customers / FIRST_VALUE(customers) OVER (ORDER BY stage_order), 2) AS pct_of_signups,
    ROUND(100.0 * customers / LAG(customers) OVER (ORDER BY stage_order), 2)         AS step_conversion_pct,
    LAG(customers) OVER (ORDER BY stage_order) - customers                            AS lost_vs_previous_stage
FROM stages
ORDER BY stage_order;

-- @query: funnel_by_cohort_month
-- Time-bounded conversion (7d KYC, 14d application, 30d disbursal) so cohorts are comparable.
SELECT
    cohort_month,
    COUNT(*)                                                                              AS signups,
    ROUND(100.0 * AVG(CASE WHEN kyc_completed_7d THEN 1 ELSE 0 END), 2)                  AS kyc_7d_pct,
    ROUND(100.0 * AVG(CASE WHEN app_submitted_14d THEN 1 ELSE 0 END), 2)                 AS app_submitted_14d_pct,
    ROUND(100.0 * AVG(CASE WHEN disbursed_30d THEN 1 ELSE 0 END), 2)                     AS disbursed_30d_pct,
    ROUND(100.0 * AVG(CASE WHEN disbursed_30d THEN 1 ELSE 0 END)
          - LAG(100.0 * AVG(CASE WHEN disbursed_30d THEN 1 ELSE 0 END)) OVER (ORDER BY cohort_month), 2) AS disbursed_30d_mom_pp
FROM marts.fct_customer_funnel
WHERE is_mature_30d
GROUP BY cohort_month
ORDER BY cohort_month;

-- @query: funnel_by_channel
SELECT
    acquisition_channel,
    COUNT(*)                                                                              AS signups,
    ROUND(100.0 * AVG(CASE WHEN kyc_completed_7d THEN 1 ELSE 0 END), 2)                  AS kyc_7d_pct,
    ROUND(100.0 * SUM(CASE WHEN app_submitted_14d THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN kyc_completed_ts IS NOT NULL THEN 1 ELSE 0 END), 0), 2) AS kyc_to_app_14d_pct,
    ROUND(100.0 * AVG(CASE WHEN disbursed_30d THEN 1 ELSE 0 END), 2)                     AS signup_to_disbursal_30d_pct,
    RANK() OVER (ORDER BY AVG(CASE WHEN disbursed_30d THEN 1 ELSE 0 END) DESC)           AS conversion_rank
FROM marts.fct_customer_funnel
WHERE is_mature_30d
GROUP BY acquisition_channel
ORDER BY conversion_rank;
