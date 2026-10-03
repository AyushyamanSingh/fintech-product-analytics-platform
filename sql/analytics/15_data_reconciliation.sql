-- =============================================================================
-- 15 DATA RECONCILIATION
-- Business question: can we trust the numbers? Product-analytics events are reconciled to
-- the KYC backend, and the payment ledger to the repayment schedule.
-- =============================================================================

-- @query: kyc_tracking_gap_daily
SELECT
    date_day,
    kyc_completions_backend,
    kyc_completions_tracked,
    kyc_completions_backend - kyc_completions_tracked                                        AS untracked,
    ROUND(100.0 * kyc_completions_tracked / NULLIF(kyc_completions_backend, 0), 1)          AS tracked_pct,
    CASE WHEN kyc_completions_tracked < 0.9 * kyc_completions_backend
          AND kyc_completions_backend >= 20 THEN TRUE ELSE FALSE END                         AS tracking_gap
FROM marts.fct_daily_metrics
WHERE date_day BETWEEN DATE '2025-05-01' AND DATE '2025-06-15'
ORDER BY date_day;

-- @query: kyc_tracking_by_app_version
-- Root cause: tracked share of backend KYC completions by the app version that started KYC.
WITH completed AS (
    SELECT c.customer_id, c.kyc_completed_ts
    FROM core.customers c
    WHERE c.kyc_completed_ts BETWEEN TIMESTAMP '2025-05-05' AND TIMESTAMP '2025-06-10'
),
started_version AS (
    SELECT e.user_id, e.platform, e.app_version,
           ROW_NUMBER() OVER (PARTITION BY e.user_id ORDER BY e.event_ts) AS rn
    FROM core.product_events e
    WHERE e.event_name = 'kyc_started'
),
tracked AS (
    SELECT DISTINCT user_id FROM core.product_events WHERE event_name = 'kyc_completed'
)
SELECT
    sv.platform,
    sv.app_version,
    COUNT(*)                                                                         AS backend_kyc_completions,
    SUM(CASE WHEN t.user_id IS NOT NULL THEN 1 ELSE 0 END)                           AS tracked_kyc_completions,
    ROUND(100.0 * AVG(CASE WHEN t.user_id IS NOT NULL THEN 1 ELSE 0 END), 1)        AS tracked_pct
FROM completed c
JOIN started_version sv ON sv.user_id = c.customer_id AND sv.rn = 1
LEFT JOIN tracked t     ON t.user_id = c.customer_id
GROUP BY sv.platform, sv.app_version
HAVING COUNT(*) >= 20
ORDER BY tracked_pct, backend_kyc_completions DESC;

-- @query: ledger_vs_schedule
-- Loans whose successful EMI ledger entries do not add up to the repayment schedule.
WITH ledger AS (
    SELECT loan_id, SUM(amount) AS ledger_emi
    FROM core.transactions
    WHERE txn_type = 'emi_payment' AND txn_status = 'success' AND loan_id IS NOT NULL
    GROUP BY loan_id
),
sched AS (
    SELECT loan_id, SUM(amount_paid) AS schedule_paid FROM core.repayments GROUP BY loan_id
)
SELECT
    COUNT(*)                                                                                   AS loans_compared,
    SUM(CASE WHEN ABS(COALESCE(l.ledger_emi, 0) - s.schedule_paid) > 1 THEN 1 ELSE 0 END)      AS loans_with_break,
    ROUND(SUM(ABS(COALESCE(l.ledger_emi, 0) - s.schedule_paid)), 2)                            AS total_abs_difference,
    ROUND(100.0 * SUM(CASE WHEN ABS(COALESCE(l.ledger_emi, 0) - s.schedule_paid) > 1 THEN 1 ELSE 0 END) / COUNT(*), 3) AS break_rate_pct
FROM sched s
LEFT JOIN ledger l ON l.loan_id = s.loan_id;
