-- =============================================================================
-- 05 CUSTOMER LIFETIME VALUE & UNIT ECONOMICS
-- Business question: which acquisition channels create customers worth more than they cost?
-- Net value = recognised revenue (interest + fees) - credit losses, where loans now in NPA
-- (90+ DPD) are treated as lost alongside write-offs (conservative, provisioning-style).
-- Only cohorts with >= 12 months of history are compared, so young channels are not penalised.
-- =============================================================================

-- @query: ltv_cac_by_channel
WITH cohort AS (
    SELECT f.customer_id, f.acquisition_channel, f.n_loans
    FROM marts.fct_customer_funnel f
    CROSS JOIN marts.run_params p
    WHERE f.signup_ts < CAST(p.as_of_date AS TIMESTAMP) - INTERVAL 12 MONTH
),
revenue AS (
    SELECT customer_id, SUM(amount) AS revenue
    FROM marts.fct_revenue_events
    WHERE component <> 'credit_loss'
    GROUP BY customer_id
),
losses AS (
    SELECT customer_id,
           SUM(CASE WHEN revenue_model = 'interest_and_fees' AND loan_status IN ('npa', 'written_off')
                    THEN outstanding_principal ELSE 0 END)            AS credit_loss
    FROM marts.fct_loan_performance
    GROUP BY customer_id
),
per_customer AS (
    SELECT c.acquisition_channel,
           c.customer_id,
           c.n_loans,
           COALESCE(r.revenue, 0)                                     AS revenue,
           COALESCE(l.credit_loss, 0)                                 AS credit_loss,
           COALESCE(r.revenue, 0) - COALESCE(l.credit_loss, 0)        AS net_value,
           COALESCE(x.acquisition_cost, 0)                            AS acquisition_cost
    FROM cohort c
    LEFT JOIN revenue r            ON r.customer_id = c.customer_id
    LEFT JOIN losses l             ON l.customer_id = c.customer_id
    LEFT JOIN marts.customer_360 x ON x.customer_id = c.customer_id
)
SELECT
    acquisition_channel,
    COUNT(*)                                                                         AS customers,
    SUM(CASE WHEN n_loans > 0 THEN 1 ELSE 0 END)                                     AS borrowers,
    ROUND(100.0 * SUM(CASE WHEN n_loans > 0 THEN 1 ELSE 0 END) / COUNT(*), 2)        AS borrower_rate_pct,
    ROUND(AVG(revenue), 0)                                                           AS revenue_per_customer,
    ROUND(AVG(credit_loss), 0)                                                       AS credit_loss_per_customer,
    ROUND(AVG(net_value), 0)                                                         AS net_value_per_customer,
    ROUND(SUM(net_value) / NULLIF(SUM(CASE WHEN n_loans > 0 THEN 1 ELSE 0 END), 0), 0) AS net_value_per_borrower,
    ROUND(AVG(acquisition_cost), 0)                                                  AS cac_per_signup,
    ROUND(SUM(acquisition_cost) / NULLIF(SUM(CASE WHEN n_loans > 0 THEN 1 ELSE 0 END), 0), 0) AS cac_per_borrower,
    ROUND(SUM(net_value) / NULLIF(SUM(acquisition_cost), 0), 2)                      AS ltv_to_cac
FROM per_customer
GROUP BY acquisition_channel
ORDER BY ltv_to_cac DESC NULLS LAST;

-- @query: cumulative_value_curve
-- Cumulative net revenue per acquired customer by months since signup, per signup quarter.
WITH cohort AS (
    SELECT customer_id, signup_ts, CAST(date_trunc('quarter', signup_ts) AS DATE) AS signup_quarter
    FROM marts.fct_customer_funnel
),
sizes AS (
    SELECT signup_quarter, COUNT(*) AS customers FROM cohort GROUP BY 1
),
monthly AS (
    SELECT c.signup_quarter,
           date_diff('month', CAST(c.signup_ts AS DATE), r.revenue_date) AS month_number,
           SUM(r.amount)                                                 AS net_revenue
    FROM cohort c
    JOIN marts.fct_revenue_events r ON r.customer_id = c.customer_id
    GROUP BY 1, 2
)
SELECT
    m.signup_quarter,
    m.month_number,
    s.customers,
    ROUND(SUM(m.net_revenue) OVER (PARTITION BY m.signup_quarter ORDER BY m.month_number
                                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) / s.customers, 2) AS cum_net_revenue_per_customer
FROM monthly m
JOIN sizes s ON s.signup_quarter = m.signup_quarter
WHERE m.month_number BETWEEN 0 AND 18
ORDER BY m.signup_quarter, m.month_number;

-- @query: value_concentration
-- How concentrated is value? Share of net revenue from the top decile of borrowers (NTILE).
WITH b AS (
    SELECT customer_id, net_revenue, NTILE(10) OVER (ORDER BY net_revenue DESC) AS decile
    FROM marts.customer_360
    WHERE n_loans > 0
)
SELECT decile,
       COUNT(*)                                                                  AS borrowers,
       ROUND(SUM(net_revenue), 0)                                                AS net_revenue,
       ROUND(100.0 * SUM(net_revenue) / SUM(SUM(net_revenue)) OVER (), 2)       AS share_of_net_revenue_pct,
       ROUND(100.0 * SUM(SUM(net_revenue)) OVER (ORDER BY decile)
             / SUM(SUM(net_revenue)) OVER (), 2)                                 AS cumulative_share_pct
FROM b
GROUP BY decile
ORDER BY decile;
