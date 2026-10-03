-- =============================================================================
-- 14 EXPERIMENT READOUTS (SQL layer)
-- Metric tables per variant for the three registered experiments. Statistical inference
-- (confidence intervals, power, SRM p-values, Bayesian probability) lives in
-- python/experiment_analysis.py, which consumes the same definitions.
-- =============================================================================

-- @query: onboarding_experiment_metrics
-- EXP-ONB-2026-01: unit = new app signup; all windows are fully observed (test ended 22 Feb 2026).
WITH units AS (
    SELECT f.*, a.variant
    FROM core.experiment_assignments a
    JOIN marts.fct_customer_funnel f ON f.customer_id = a.customer_id
    WHERE a.experiment_id = 'EXP-ONB-2026-01'
),
first_loans AS (
    SELECT customer_id, is_fpd30, fpd30_mature FROM marts.fct_loan_performance WHERE loan_sequence_number = 1
),
kyc_tickets AS (
    SELECT DISTINCT t.customer_id
    FROM core.support_tickets t
    JOIN units u ON u.customer_id = t.customer_id
    WHERE t.category = 'kyc_issue' AND t.created_ts <= u.signup_ts + INTERVAL 7 DAY
),
submitted AS (
    SELECT a.customer_id,
           SUM(CASE WHEN a.decision IS NOT NULL THEN 1 ELSE 0 END)       AS decisions,
           SUM(CASE WHEN a.decision = 'approved' THEN 1 ELSE 0 END)      AS approvals
    FROM core.applications a
    JOIN units u ON u.customer_id = a.customer_id
    WHERE a.submitted_ts <= u.signup_ts + INTERVAL 30 DAY
    GROUP BY a.customer_id
)
SELECT
    u.variant,
    COUNT(*)                                                                      AS users,
    SUM(CASE WHEN u.kyc_completed_7d THEN 1 ELSE 0 END)                           AS kyc_7d,
    ROUND(100.0 * AVG(CASE WHEN u.kyc_completed_7d THEN 1 ELSE 0 END), 2)        AS kyc_7d_pct,
    SUM(CASE WHEN u.app_submitted_14d THEN 1 ELSE 0 END)                          AS app_submitted_14d,
    ROUND(100.0 * AVG(CASE WHEN u.app_submitted_14d THEN 1 ELSE 0 END), 2)       AS app_submitted_14d_pct,
    SUM(CASE WHEN u.disbursed_30d THEN 1 ELSE 0 END)                              AS disbursed_30d,
    ROUND(100.0 * AVG(CASE WHEN u.disbursed_30d THEN 1 ELSE 0 END), 2)           AS disbursed_30d_pct,
    SUM(s.decisions)                                                              AS decisions_30d,
    ROUND(100.0 * SUM(s.approvals) / NULLIF(SUM(s.decisions), 0), 2)              AS approval_rate_pct,
    SUM(CASE WHEN fl.fpd30_mature THEN 1 ELSE 0 END)                              AS matured_first_loans,
    ROUND(100.0 * SUM(CASE WHEN fl.fpd30_mature AND fl.is_fpd30 THEN 1 ELSE 0 END)
          / NULLIF(SUM(CASE WHEN fl.fpd30_mature THEN 1 ELSE 0 END), 0), 2)       AS fpd30_pct,
    ROUND(100.0 * AVG(CASE WHEN kt.customer_id IS NOT NULL THEN 1 ELSE 0 END), 2) AS kyc_ticket_rate_7d_pct
FROM units u
LEFT JOIN first_loans fl ON fl.customer_id = u.customer_id
LEFT JOIN kyc_tickets kt ON kt.customer_id = u.customer_id
LEFT JOIN submitted  s   ON s.customer_id  = u.customer_id
GROUP BY u.variant
ORDER BY u.variant;

-- @query: sample_ratio_check
-- Chi-square statistic for a 50/50 split per experiment (p-value computed in Python).
WITH c AS (
    SELECT experiment_id, variant, COUNT(*) AS n FROM core.experiment_assignments GROUP BY 1, 2
),
t AS (
    SELECT experiment_id, SUM(n) AS total FROM c GROUP BY 1
)
SELECT c.experiment_id,
       SUM(CASE WHEN c.variant = 'control' THEN c.n END)                AS control_n,
       SUM(CASE WHEN c.variant = 'treatment' THEN c.n END)              AS treatment_n,
       ROUND(SUM(POWER(c.n - t.total / 2.0, 2) / (t.total / 2.0)), 3)   AS chi_square_stat
FROM c
JOIN t ON t.experiment_id = c.experiment_id
GROUP BY c.experiment_id
ORDER BY c.experiment_id;

-- @query: autopay_experiment_metrics
-- EXP-RPY-2025-11: unit = customer at first disbursal in the window.
WITH units AS (
    SELECT a.variant, l.*
    FROM core.experiment_assignments a
    JOIN marts.fct_loan_performance l
      ON l.customer_id = a.customer_id AND l.disbursed_ts = a.assigned_ts
    WHERE a.experiment_id = 'EXP-RPY-2025-11'
)
SELECT variant,
       COUNT(*)                                                                         AS users,
       ROUND(100.0 * AVG(CASE WHEN autopay_enabled THEN 1 ELSE 0 END), 2)              AS autopay_enabled_pct,
       ROUND(100.0 * AVG(CASE WHEN first_installment_dpd = 0 THEN 1 ELSE 0 END), 2)    AS first_emi_on_time_pct
FROM units
GROUP BY variant
ORDER BY variant;

-- @query: fee_transparency_experiment_metrics
-- EXP-PRC-2025-06: unit = approved applicant shown the offer screen.
SELECT a.variant,
       COUNT(*)                                                                                 AS users,
       ROUND(100.0 * AVG(CASE WHEN ap.application_status = 'disbursed' THEN 1 ELSE 0 END), 2) AS offer_acceptance_pct
FROM core.experiment_assignments a
JOIN core.applications ap ON ap.customer_id = a.customer_id AND ap.decision_ts = a.assigned_ts
WHERE a.experiment_id = 'EXP-PRC-2025-06'
GROUP BY a.variant
ORDER BY a.variant;
