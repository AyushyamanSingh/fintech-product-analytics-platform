-- =============================================================================
-- 13 MARKETING EFFICIENCY & CAC
-- Business question: what does a signup, a verified customer and a funded borrower cost
-- per channel - and which campaigns bought volume that never converted (or defaulted)?
-- Campaign spend is pro-rated by day across each flight, then rolled up to months.
-- =============================================================================

-- @query: cac_by_channel_month
WITH campaign_days AS (
    SELECT mc.channel, d.month_start,
           mc.spend_inr / (date_diff('day', mc.start_date, mc.end_date) + 1) AS daily_spend
    FROM core.marketing_campaigns mc
    JOIN marts.dim_date d ON d.date_day BETWEEN mc.start_date AND mc.end_date
),
spend AS (
    SELECT month_start, channel, SUM(daily_spend) AS spend FROM campaign_days GROUP BY 1, 2
),
acq AS (
    SELECT cohort_month AS month_start, acquisition_channel AS channel,
           COUNT(*)                                            AS signups,
           SUM(CASE WHEN kyc_completed_7d THEN 1 ELSE 0 END)   AS kyc_7d,
           SUM(CASE WHEN disbursed_30d THEN 1 ELSE 0 END)      AS funded_30d,
           BOOL_AND(is_mature_30d)                             AS fully_mature
    FROM marts.fct_customer_funnel
    GROUP BY 1, 2
)
SELECT
    a.month_start,
    a.channel,
    ROUND(COALESCE(s.spend, 0), 0)                          AS spend,
    a.signups,
    a.kyc_7d,
    a.funded_30d,
    ROUND(s.spend / NULLIF(a.signups, 0), 0)                AS cost_per_signup,
    ROUND(s.spend / NULLIF(a.kyc_7d, 0), 0)                 AS cost_per_verified_customer,
    ROUND(s.spend / NULLIF(a.funded_30d, 0), 0)             AS cost_per_funded_customer,
    a.fully_mature
FROM acq a
LEFT JOIN spend s ON s.month_start = a.month_start AND s.channel = a.channel
WHERE a.channel <> 'organic'
ORDER BY a.month_start, a.channel;

-- @query: blended_cac_monthly
WITH campaign_days AS (
    SELECT d.month_start, mc.spend_inr / (date_diff('day', mc.start_date, mc.end_date) + 1) AS daily_spend
    FROM core.marketing_campaigns mc
    JOIN marts.dim_date d ON d.date_day BETWEEN mc.start_date AND mc.end_date
),
spend AS (SELECT month_start, SUM(daily_spend) AS spend FROM campaign_days GROUP BY 1),
acq AS (
    SELECT cohort_month AS month_start, COUNT(*) AS signups,
           SUM(CASE WHEN acquisition_channel <> 'organic' THEN 1 ELSE 0 END) AS paid_signups
    FROM marts.fct_customer_funnel GROUP BY 1
),
funded AS (   -- first-ever loans disbursed in the month (new borrowers), regardless of signup month
    SELECT disbursal_month AS month_start, COUNT(*) AS new_borrowers
    FROM marts.fct_loan_performance WHERE loan_sequence_number = 1 GROUP BY 1
)
SELECT a.month_start,
       ROUND(s.spend, 0)                                           AS marketing_spend,
       a.signups,
       ROUND(100.0 * a.paid_signups / a.signups, 1)                AS paid_share_pct,
       ROUND(s.spend / NULLIF(a.signups, 0), 0)                    AS blended_cac_per_signup,
       ROUND(s.spend / NULLIF(a.paid_signups, 0), 0)               AS paid_cac_per_signup,
       f.new_borrowers,
       ROUND(s.spend / NULLIF(f.new_borrowers, 0), 0)              AS cost_per_new_borrower
FROM acq a
LEFT JOIN spend s  ON s.month_start = a.month_start
LEFT JOIN funded f ON f.month_start = a.month_start
ORDER BY a.month_start;

-- @query: campaign_scorecard
WITH funnel AS (
    SELECT campaign_id,
           COUNT(*)                                                AS signups,
           AVG(CASE WHEN kyc_completed_7d THEN 1.0 ELSE 0 END)     AS kyc_rate,
           SUM(CASE WHEN disbursed_30d THEN 1 ELSE 0 END)          AS funded
    FROM marts.fct_customer_funnel
    WHERE campaign_id IS NOT NULL
    GROUP BY campaign_id
),
risk AS (
    SELECT f.campaign_id,
           COUNT(*)                                                AS matured_first_loans,
           AVG(CASE WHEN lp.is_fpd30 THEN 1.0 ELSE 0 END)          AS fpd30_rate
    FROM marts.fct_customer_funnel f
    JOIN marts.fct_loan_performance lp
      ON lp.customer_id = f.customer_id AND lp.loan_sequence_number = 1 AND lp.fpd30_mature
    GROUP BY f.campaign_id
),
scored AS (
    SELECT mc.campaign_id, mc.campaign_name, mc.channel, mc.start_date,
           mc.spend_inr, f.signups, f.kyc_rate, f.funded, r.fpd30_rate, r.matured_first_loans,
           mc.spend_inr / NULLIF(f.funded, 0)                                                     AS cost_per_funded,
           MEDIAN(mc.spend_inr / NULLIF(f.funded, 0)) OVER (PARTITION BY mc.channel)              AS channel_median_cost_per_funded
    FROM core.marketing_campaigns mc
    JOIN funnel f      ON f.campaign_id = mc.campaign_id
    LEFT JOIN risk r   ON r.campaign_id = mc.campaign_id
)
SELECT
    campaign_id, campaign_name, channel, start_date,
    ROUND(spend_inr, 0)                                          AS spend,
    signups,
    ROUND(spend_inr / signups, 0)                                AS cost_per_signup,
    ROUND(100 * kyc_rate, 2)                                     AS kyc_7d_pct,
    funded,
    ROUND(cost_per_funded, 0)                                    AS cost_per_funded,
    ROUND(100 * fpd30_rate, 2)                                   AS first_loan_fpd30_pct,
    matured_first_loans,
    CASE WHEN cost_per_funded > 2 * channel_median_cost_per_funded OR funded = 0 THEN 'inefficient_spend'
         WHEN fpd30_rate > 0.10 AND matured_first_loans >= 20                    THEN 'credit_risk'
         ELSE 'ok' END                                           AS review_flag
FROM scored
ORDER BY review_flag, cost_per_funded DESC NULLS FIRST;
