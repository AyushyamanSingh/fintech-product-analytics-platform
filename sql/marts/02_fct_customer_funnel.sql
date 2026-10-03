-- One row per customer with every onboarding/lending milestone, time-bounded conversion flags
-- (fair comparison across cohorts) and maturity flags (so young cohorts are not under-reported).
CREATE OR REPLACE TABLE marts.fct_customer_funnel AS
WITH first_app AS (
    SELECT customer_id,
           MIN(started_ts)                                            AS first_app_started_ts,
           MIN(submitted_ts)                                          AS first_app_submitted_ts,
           MIN(CASE WHEN decision = 'approved' THEN decision_ts END)  AS first_approved_ts,
           COUNT(*)                                                   AS n_applications
    FROM core.applications
    GROUP BY customer_id
),
first_loan AS (
    SELECT customer_id,
           MIN(disbursed_ts)        AS first_disbursed_ts,
           COUNT(*)                 AS n_loans,
           SUM(principal_amount)    AS total_disbursed
    FROM core.loans
    GROUP BY customer_id
),
onb AS (
    SELECT customer_id, variant AS onb_variant
    FROM core.experiment_assignments
    WHERE experiment_id = 'EXP-ONB-2026-01'
)
SELECT
    c.customer_id,
    c.signup_ts,
    CAST(c.signup_ts AS DATE)                                       AS signup_date,
    CAST(date_trunc('week', c.signup_ts) AS DATE)                   AS signup_week,
    CAST(date_trunc('month', c.signup_ts) AS DATE)                  AS cohort_month,
    c.acquisition_channel,
    c.campaign_id,
    c.signup_platform,
    c.city_tier,
    c.state,
    c.employment_type,
    c.is_ntc,
    c.credit_score,
    c.age,
    CASE WHEN c.age IS NULL THEN 'unknown'
         WHEN c.age < 25 THEN '18-24' WHEN c.age < 35 THEN '25-34'
         WHEN c.age < 45 THEN '35-44' ELSE '45+' END                AS age_band,
    c.monthly_income,
    c.kyc_status,
    c.kyc_started_ts,
    c.kyc_completed_ts,
    fa.first_app_started_ts,
    fa.first_app_submitted_ts,
    fa.first_approved_ts,
    fl.first_disbursed_ts,
    COALESCE(fa.n_applications, 0)                                  AS n_applications,
    COALESCE(fl.n_loans, 0)                                         AS n_loans,
    COALESCE(fl.total_disbursed, 0)                                 AS total_disbursed,
    onb.onb_variant,
    -- time-bounded conversion flags
    COALESCE(c.kyc_completed_ts <= c.signup_ts + INTERVAL 7 DAY, FALSE)            AS kyc_completed_7d,
    COALESCE(fa.first_app_submitted_ts <= c.signup_ts + INTERVAL 14 DAY, FALSE)    AS app_submitted_14d,
    COALESCE(fl.first_disbursed_ts <= c.signup_ts + INTERVAL 30 DAY, FALSE)        AS disbursed_30d,
    -- maturity: has the customer had the full window to convert?
    c.signup_ts < CAST(p.as_of_date AS TIMESTAMP) - INTERVAL 6 DAY                 AS is_mature_7d,
    c.signup_ts < CAST(p.as_of_date AS TIMESTAMP) - INTERVAL 13 DAY                AS is_mature_14d,
    c.signup_ts < CAST(p.as_of_date AS TIMESTAMP) - INTERVAL 29 DAY                AS is_mature_30d,
    -- speed
    date_diff('minute', c.signup_ts, c.kyc_completed_ts)                           AS minutes_signup_to_kyc,
    date_diff('minute', c.kyc_completed_ts, fa.first_app_started_ts) / 60.0       AS hours_kyc_to_application,
    date_diff('hour', c.signup_ts, fl.first_disbursed_ts) / 24.0                   AS days_signup_to_disbursal
FROM core.customers c
LEFT JOIN first_app  fa  ON fa.customer_id  = c.customer_id
LEFT JOIN first_loan fl  ON fl.customer_id  = c.customer_id
LEFT JOIN onb            ON onb.customer_id = c.customer_id
CROSS JOIN marts.run_params p;
