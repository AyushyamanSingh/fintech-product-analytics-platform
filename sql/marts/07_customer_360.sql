-- Customer 360: one row per customer with profile, funnel, lending, repayment, engagement, support and
-- acquisition-cost features. Feeds segmentation (python/segmentation.py) and the Power BI customer dimension.
CREATE OR REPLACE TABLE marts.customer_360 AS
WITH loans AS (
    SELECT
        customer_id,
        COUNT(*)                                                                         AS n_loans,
        SUM(CASE WHEN is_repeat_loan THEN 1 ELSE 0 END)                                  AS n_repeat_loans,
        COUNT(DISTINCT product_id)                                                       AS n_products,
        SUM(principal_amount)                                                            AS total_disbursed,
        AVG(principal_amount)                                                            AS avg_ticket,
        MIN(disbursed_ts)                                                                AS first_loan_ts,
        MAX(disbursed_ts)                                                                AS last_loan_ts,
        SUM(total_revenue)                                                               AS total_revenue,
        SUM(credit_loss)                                                                 AS credit_loss,
        SUM(installments_due)                                                            AS installments_due,
        SUM(installments_on_time)                                                        AS installments_on_time,
        MAX(max_dpd)                                                                     AS max_dpd_ever,
        MAX(current_dpd)                                                                 AS current_dpd,
        SUM(CASE WHEN loan_status IN ('active', 'delinquent', 'npa') THEN outstanding_principal ELSE 0 END) AS outstanding_principal,
        MAX(CASE WHEN loan_status IN ('active', 'delinquent', 'npa') THEN 1 ELSE 0 END) = 1 AS has_open_loan,
        MAX(CASE WHEN loan_status = 'written_off' THEN 1 ELSE 0 END) = 1                 AS has_written_off_loan,
        MAX(CASE WHEN autopay_enabled THEN 1 ELSE 0 END) = 1                             AS autopay_ever
    FROM marts.fct_loan_performance
    GROUP BY customer_id
),
activity AS (
    SELECT
        e.user_id                                                                            AS customer_id,
        SUM(CASE WHEN e.platform <> 'server' AND e.event_ts >= p.as_of_date - INTERVAL 89 DAY THEN 1 ELSE 0 END) AS client_events_90d,
        SUM(CASE WHEN e.event_name = 'login' AND e.event_ts >= p.as_of_date - INTERVAL 89 DAY THEN 1 ELSE 0 END)  AS logins_90d,
        COUNT(DISTINCT CASE WHEN e.platform <> 'server' THEN date_trunc('month', e.event_ts) END)                 AS active_months,
        MAX(CASE WHEN e.platform <> 'server' THEN e.event_ts END)                            AS last_active_ts,
        MAX(CASE WHEN e.event_name = 'credit_score_viewed' THEN 1 ELSE 0 END) = 1            AS used_credit_score,
        MAX(CASE WHEN e.event_name = 'emi_calculator_used' THEN 1 ELSE 0 END) = 1            AS used_emi_calculator,
        SUM(CASE WHEN e.event_name = 'referral_shared' THEN 1 ELSE 0 END)                    AS referrals_shared
    FROM core.product_events e
    CROSS JOIN marts.run_params p
    GROUP BY e.user_id
),
support AS (
    SELECT customer_id,
           COUNT(*)                                                       AS support_tickets,
           AVG(csat_score)                                                AS avg_csat,
           SUM(CASE WHEN category = 'collections' THEN 1 ELSE 0 END)      AS collections_tickets
    FROM core.support_tickets
    GROUP BY customer_id
),
cac AS (    -- campaign spend allocated evenly across the campaign's attributed signups
    SELECT c.customer_id,
           mc.spend_inr / COUNT(*) OVER (PARTITION BY c.campaign_id)      AS acquisition_cost
    FROM core.customers c
    JOIN core.marketing_campaigns mc ON mc.campaign_id = c.campaign_id
)
SELECT
    f.customer_id, f.signup_ts, f.cohort_month, f.acquisition_channel, f.campaign_id, f.signup_platform,
    f.city_tier, f.state, f.employment_type, f.age, f.age_band, f.monthly_income, f.credit_score, f.is_ntc,
    f.kyc_status, f.onb_variant,
    CASE WHEN f.monthly_income IS NULL THEN 'unknown'
         WHEN f.monthly_income < 20000 THEN '<20k'
         WHEN f.monthly_income < 40000 THEN '20-40k'
         WHEN f.monthly_income < 75000 THEN '40-75k'
         ELSE '75k+' END                                                           AS income_band,
    COALESCE(l.n_loans, 0)                                                         AS n_loans,
    COALESCE(l.n_repeat_loans, 0)                                                  AS n_repeat_loans,
    COALESCE(l.n_products, 0)                                                      AS n_products,
    COALESCE(l.total_disbursed, 0)                                                 AS total_disbursed,
    l.avg_ticket,
    l.first_loan_ts,
    l.last_loan_ts,
    COALESCE(l.total_revenue, 0)                                                   AS total_revenue,
    COALESCE(l.credit_loss, 0)                                                     AS credit_loss,
    COALESCE(l.total_revenue, 0) - COALESCE(l.credit_loss, 0)                      AS net_revenue,
    COALESCE(cac.acquisition_cost, 0)                                              AS acquisition_cost,
    COALESCE(l.installments_due, 0)                                                AS installments_due,
    CASE WHEN l.installments_due > 0 THEN l.installments_on_time * 1.0 / l.installments_due END AS on_time_rate,
    COALESCE(l.max_dpd_ever, 0)                                                    AS max_dpd_ever,
    COALESCE(l.current_dpd, 0)                                                     AS current_dpd,
    COALESCE(l.outstanding_principal, 0)                                           AS outstanding_principal,
    COALESCE(l.has_open_loan, FALSE)                                               AS has_open_loan,
    COALESCE(l.has_written_off_loan, FALSE)                                        AS has_written_off_loan,
    COALESCE(l.autopay_ever, FALSE)                                                AS autopay_ever,
    COALESCE(a.client_events_90d, 0)                                               AS client_events_90d,
    COALESCE(a.logins_90d, 0)                                                      AS logins_90d,
    COALESCE(a.active_months, 0)                                                   AS active_months,
    a.last_active_ts,
    COALESCE(a.used_credit_score, FALSE)                                           AS used_credit_score,
    COALESCE(a.used_emi_calculator, FALSE)                                         AS used_emi_calculator,
    COALESCE(a.referrals_shared, 0)                                                AS referrals_shared,
    COALESCE(s.support_tickets, 0)                                                 AS support_tickets,
    s.avg_csat,
    COALESCE(s.collections_tickets, 0)                                             AS collections_tickets,
    date_diff('day', f.signup_ts, CAST(p.as_of_date AS TIMESTAMP))                 AS tenure_days,
    date_diff('day', a.last_active_ts, CAST(p.as_of_date AS TIMESTAMP))            AS days_since_last_active,
    date_diff('day', l.last_loan_ts, CAST(p.as_of_date AS TIMESTAMP))              AS days_since_last_loan,
    CASE
        WHEN f.kyc_status <> 'verified'                         THEN 'onboarding_dropoff'
        WHEN COALESCE(l.n_loans, 0) = 0                         THEN 'verified_never_borrowed'
        WHEN COALESCE(l.has_written_off_loan, FALSE)            THEN 'written_off'
        WHEN COALESCE(l.has_open_loan, FALSE)                   THEN 'active_borrower'
        ELSE 'repaid_no_open_loan'
    END                                                                            AS lifecycle_stage
FROM marts.fct_customer_funnel f
LEFT JOIN loans    l   ON l.customer_id   = f.customer_id
LEFT JOIN activity a   ON a.customer_id   = f.customer_id
LEFT JOIN support  s   ON s.customer_id   = f.customer_id
LEFT JOIN cac          ON cac.customer_id = f.customer_id
CROSS JOIN marts.run_params p;
