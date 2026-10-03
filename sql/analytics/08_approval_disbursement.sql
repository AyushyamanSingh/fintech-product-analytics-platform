-- =============================================================================
-- 08 APPROVAL & DISBURSEMENT
-- Business question: are we approving the right volume, why are applicants rejected, and
-- how many approved customers never take the money?
-- Approval rate = approved / decided (by decision month).
-- Disbursal rate (offer acceptance) = disbursed / approved (by approval month).
-- =============================================================================

-- @query: approval_disbursal_monthly
WITH decided AS (
    SELECT CAST(date_trunc('month', decision_ts) AS DATE)                         AS month_start,
           COUNT(*)                                                               AS decisions,
           SUM(CASE WHEN decision = 'approved' THEN 1 ELSE 0 END)                 AS approvals,
           SUM(CASE WHEN decision = 'approved' AND application_status = 'disbursed' THEN 1 ELSE 0 END) AS disbursed_from_approvals,
           SUM(CASE WHEN decision = 'approved' AND application_status = 'offer_expired' THEN 1 ELSE 0 END) AS offers_expired
    FROM core.applications
    WHERE decision_ts IS NOT NULL
    GROUP BY 1
),
submitted AS (
    SELECT CAST(date_trunc('month', submitted_ts) AS DATE) AS month_start, COUNT(*) AS submitted
    FROM core.applications
    WHERE submitted_ts IS NOT NULL
    GROUP BY 1
)
SELECT
    d.month_start,
    s.submitted,
    d.decisions,
    d.approvals,
    ROUND(100.0 * d.approvals / d.decisions, 2)                                               AS approval_rate_pct,
    ROUND(100.0 * d.approvals / d.decisions
          - LAG(100.0 * d.approvals / d.decisions) OVER (ORDER BY d.month_start), 2)          AS approval_rate_mom_pp,
    ROUND(100.0 * d.disbursed_from_approvals / NULLIF(d.approvals, 0), 2)                     AS disbursal_rate_pct,
    ROUND(100.0 * d.offers_expired / NULLIF(d.approvals, 0), 2)                               AS offer_expired_pct
FROM decided d
LEFT JOIN submitted s ON s.month_start = d.month_start
ORDER BY d.month_start;

-- @query: approval_by_product_and_band
SELECT
    a.product_id,
    a.risk_band,
    COUNT(*)                                                                      AS decisions,
    ROUND(100.0 * AVG(CASE WHEN a.decision = 'approved' THEN 1 ELSE 0 END), 2)   AS approval_rate_pct,
    ROUND(AVG(a.internal_risk_score), 2)                                          AS avg_model_pd_pct
FROM core.applications a
WHERE a.decision IS NOT NULL
GROUP BY a.product_id, a.risk_band
ORDER BY a.product_id, a.risk_band;

-- @query: rejection_reason_mix
WITH r AS (
    SELECT CAST(date_trunc('month', decision_ts) AS DATE) AS month_start, rejection_reason, COUNT(*) AS rejections
    FROM core.applications
    WHERE decision = 'rejected' AND decision_ts IS NOT NULL
    GROUP BY 1, 2
)
SELECT month_start, rejection_reason, rejections,
       ROUND(100.0 * rejections / SUM(rejections) OVER (PARTITION BY month_start), 2) AS share_of_rejections_pct
FROM r
ORDER BY month_start, rejections DESC;

-- @query: turnaround_times
WITH t AS (
    SELECT a.product_id,
           date_diff('second', a.submitted_ts, a.decision_ts) / 60.0      AS minutes_to_decision,
           date_diff('second', a.decision_ts, lo.disbursed_ts) / 3600.0   AS hours_approval_to_cash
    FROM core.applications a
    LEFT JOIN core.loans lo ON lo.application_id = a.application_id
    WHERE a.decision_ts IS NOT NULL AND a.submitted_ts IS NOT NULL
)
SELECT
    product_id,
    COUNT(*)                                                                                AS decided_applications,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY minutes_to_decision), 1)              AS median_minutes_to_decision,
    ROUND(percentile_cont(0.9) WITHIN GROUP (ORDER BY minutes_to_decision) / 60.0, 1)       AS p90_hours_to_decision,
    ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY hours_approval_to_cash), 1)           AS median_hours_approval_to_cash
FROM t
GROUP BY product_id
ORDER BY product_id;
