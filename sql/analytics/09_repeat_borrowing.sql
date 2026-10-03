-- =============================================================================
-- 09 REPEAT BORROWING
-- Business question: how many good customers come back, how quickly, for which product,
-- and what predicts a second loan?
-- Repeat rate = loans closed in good standing (max DPD < 30) at least 90 days before the
-- extract date whose borrower took another loan within 90 days of closure.
-- =============================================================================

-- @query: repeat_rate_by_product
WITH seq AS (
    SELECT
        customer_id, loan_id, product_id, product_name, loan_status, max_dpd, closed_date, autopay_enabled,
        LEAD(disbursed_ts) OVER (PARTITION BY customer_id ORDER BY disbursed_ts) AS next_loan_ts
    FROM marts.fct_loan_performance
)
SELECT
    s.product_id,
    s.product_name,
    COUNT(*)                                                                                      AS closed_good_loans,
    SUM(CASE WHEN s.next_loan_ts <= s.closed_date + INTERVAL 90 DAY THEN 1 ELSE 0 END)            AS repeat_within_90d,
    ROUND(100.0 * AVG(CASE WHEN s.next_loan_ts <= s.closed_date + INTERVAL 90 DAY THEN 1 ELSE 0 END), 2) AS repeat_90d_pct
FROM seq s
CROSS JOIN marts.run_params p
WHERE s.loan_status = 'closed' AND s.max_dpd < 30
  AND s.closed_date <= p.as_of_date - INTERVAL 90 DAY
GROUP BY s.product_id, s.product_name
ORDER BY repeat_90d_pct DESC;

-- @query: days_to_next_loan
WITH seq AS (
    SELECT product_id, closed_date,
           LEAD(disbursed_ts) OVER (PARTITION BY customer_id ORDER BY disbursed_ts) AS next_loan_ts
    FROM marts.fct_loan_performance
)
SELECT product_id,
       COUNT(*)                                                                                      AS repeat_events,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY date_diff('day', closed_date, CAST(next_loan_ts AS DATE))), 1) AS median_days_closure_to_next,
       ROUND(percentile_cont(0.9) WITHIN GROUP (ORDER BY date_diff('day', closed_date, CAST(next_loan_ts AS DATE))), 1) AS p90_days_closure_to_next
FROM seq
WHERE closed_date IS NOT NULL AND next_loan_ts IS NOT NULL AND CAST(next_loan_ts AS DATE) >= closed_date
GROUP BY product_id
ORDER BY product_id;

-- @query: cross_sell_matrix
WITH seq AS (
    SELECT product_id,
           LEAD(product_id) OVER (PARTITION BY customer_id ORDER BY disbursed_ts) AS next_product_id
    FROM marts.fct_loan_performance
)
SELECT product_id AS from_product,
       next_product_id AS to_product,
       COUNT(*) AS transitions,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY product_id), 2) AS share_of_from_product_pct
FROM seq
WHERE next_product_id IS NOT NULL
GROUP BY product_id, next_product_id
ORDER BY from_product, transitions DESC;

-- @query: repeat_drivers
-- Repeat rate by behaviour on the previous loan (correlational - see docs for causal caveats).
WITH seq AS (
    SELECT lp.*, LEAD(lp.disbursed_ts) OVER (PARTITION BY lp.customer_id ORDER BY lp.disbursed_ts) AS next_loan_ts
    FROM marts.fct_loan_performance lp
),
eligible AS (
    SELECT s.*, CASE WHEN s.next_loan_ts <= s.closed_date + INTERVAL 90 DAY THEN 1.0 ELSE 0 END AS repeated
    FROM seq s
    CROSS JOIN marts.run_params p
    WHERE s.loan_status = 'closed' AND s.max_dpd < 30 AND s.closed_date <= p.as_of_date - INTERVAL 90 DAY
)
SELECT 'autopay_enabled' AS driver, CAST(autopay_enabled AS VARCHAR) AS value, COUNT(*) AS loans, ROUND(100 * AVG(repeated), 2) AS repeat_90d_pct
FROM eligible GROUP BY autopay_enabled
UNION ALL
SELECT 'all_instalments_on_time', CAST(installments_late = 0 AS VARCHAR), COUNT(*), ROUND(100 * AVG(repeated), 2)
FROM eligible GROUP BY installments_late = 0
UNION ALL
SELECT 'acquisition_channel', acquisition_channel, COUNT(*), ROUND(100 * AVG(repeated), 2)
FROM eligible GROUP BY acquisition_channel
UNION ALL
SELECT 'closure_type', closure_type, COUNT(*), ROUND(100 * AVG(repeated), 2)
FROM eligible GROUP BY closure_type
ORDER BY driver, repeat_90d_pct DESC;

-- @query: repeat_share_monthly
SELECT
    disbursal_month,
    COUNT(*)                                                                                  AS loans,
    SUM(CASE WHEN is_repeat_loan THEN 1 ELSE 0 END)                                           AS repeat_loans,
    ROUND(100.0 * AVG(CASE WHEN is_repeat_loan THEN 1 ELSE 0 END), 2)                        AS repeat_loan_share_pct,
    ROUND(100.0 * SUM(CASE WHEN is_repeat_loan THEN principal_amount ELSE 0 END) / SUM(principal_amount), 2) AS repeat_amount_share_pct
FROM marts.fct_loan_performance
GROUP BY disbursal_month
ORDER BY disbursal_month;
