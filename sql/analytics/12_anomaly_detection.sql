-- =============================================================================
-- 12 ANOMALY DETECTION (SQL screen)
-- Business question: which days broke from normal, and by how much?
-- Baseline = mean/stddev of the same weekday over the previous 8 weeks (seasonality-aware,
-- excludes the current day so a spike cannot mask itself). Flag |z| >= 3 AND |dev| >= 25%.
-- The Python detector (python/anomaly_detection.py) adds robust statistics, episode grouping,
-- driver attribution and business-calendar annotation on top of this screen.
-- =============================================================================

-- @query: daily_metric_anomalies
WITH long AS (
    SELECT date_day, iso_dow, 'signups' AS metric, CAST(signups AS DOUBLE) AS value FROM marts.fct_daily_metrics
    UNION ALL SELECT date_day, iso_dow, 'applications_submitted', applications_submitted FROM marts.fct_daily_metrics
    UNION ALL SELECT date_day, iso_dow, 'approval_rate', approval_rate FROM marts.fct_daily_metrics
    UNION ALL SELECT date_day, iso_dow, 'loans_disbursed', loans_disbursed FROM marts.fct_daily_metrics
    UNION ALL SELECT date_day, iso_dow, 'payment_failure_rate', payment_failure_rate FROM marts.fct_daily_metrics
    UNION ALL SELECT date_day, iso_dow, 'support_tickets', support_tickets FROM marts.fct_daily_metrics
    UNION ALL SELECT date_day, iso_dow, 'kyc_tracking_ratio',
                     kyc_completions_tracked * 1.0 / NULLIF(kyc_completions_backend, 0) FROM marts.fct_daily_metrics
),
baseline AS (
    SELECT *,
           AVG(value)         OVER w AS expected,
           STDDEV_SAMP(value) OVER w AS sd,
           COUNT(value)       OVER w AS n_obs
    FROM long
    WINDOW w AS (PARTITION BY metric, iso_dow ORDER BY date_day ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING)
)
SELECT
    date_day,
    metric,
    ROUND(value, 4)                                              AS value,
    ROUND(expected, 4)                                           AS expected,
    ROUND((value - expected) / NULLIF(sd, 0), 2)                 AS z_score,
    ROUND(100.0 * (value - expected) / NULLIF(expected, 0), 1)   AS deviation_pct,
    CASE WHEN value > expected THEN 'spike' ELSE 'drop' END      AS direction
FROM baseline
WHERE n_obs >= 6
  AND ABS((value - expected) / NULLIF(sd, 0)) >= 3
  AND ABS((value - expected) / NULLIF(expected, 0)) >= 0.25
ORDER BY date_day, metric;
