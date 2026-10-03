-- =============================================================================
-- 04 ACTIVE USERS (MAU / DAU / growth accounting)
-- Business question: is the active base growing because we acquire, retain or resurrect users?
-- MAU = distinct customers with >= 1 client-side event in the calendar month.
-- =============================================================================

-- @query: mau_growth_accounting
WITH m AS (
    SELECT DISTINCT customer_id, activity_month
    FROM marts.fct_user_activity_monthly
    WHERE client_events > 0
),
flagged AS (
    SELECT
        customer_id,
        activity_month,
        LAG(activity_month) OVER (PARTITION BY customer_id ORDER BY activity_month) AS prev_active_month,
        MIN(activity_month) OVER (PARTITION BY customer_id)                         AS first_active_month
    FROM m
),
monthly AS (
    SELECT
        activity_month,
        COUNT(*)                                                                                   AS mau,
        SUM(CASE WHEN activity_month = first_active_month THEN 1 ELSE 0 END)                       AS new_users,
        SUM(CASE WHEN prev_active_month = CAST(activity_month - INTERVAL 1 MONTH AS DATE) THEN 1 ELSE 0 END) AS retained_users,
        SUM(CASE WHEN activity_month <> first_active_month
                  AND prev_active_month < CAST(activity_month - INTERVAL 1 MONTH AS DATE) THEN 1 ELSE 0 END) AS resurrected_users
    FROM flagged
    GROUP BY activity_month
)
SELECT
    activity_month,
    mau,
    new_users,
    retained_users,
    resurrected_users,
    LAG(mau) OVER (ORDER BY activity_month) - retained_users                                    AS churned_users,
    ROUND(100.0 * retained_users / NULLIF(LAG(mau) OVER (ORDER BY activity_month), 0), 2)       AS month_over_month_retention_pct,
    -- quick ratio > 1 means the base grows faster than it churns
    ROUND((new_users + resurrected_users) * 1.0
          / NULLIF(LAG(mau) OVER (ORDER BY activity_month) - retained_users, 0), 2)              AS quick_ratio,
    ROUND(100.0 * (mau - LAG(mau) OVER (ORDER BY activity_month))
          / NULLIF(LAG(mau) OVER (ORDER BY activity_month), 0), 2)                               AS mau_mom_growth_pct
FROM monthly
ORDER BY activity_month;

-- @query: stickiness
-- Average DAU / MAU: how many days a month the typical active customer opens the app.
WITH dau AS (
    SELECT month_start, AVG(dau) AS avg_dau
    FROM marts.fct_daily_metrics
    GROUP BY month_start
),
mau AS (
    SELECT activity_month AS month_start, COUNT(DISTINCT customer_id) AS mau
    FROM marts.fct_user_activity_monthly
    WHERE client_events > 0
    GROUP BY 1
)
SELECT d.month_start, ROUND(d.avg_dau, 0) AS avg_dau, m.mau,
       ROUND(100.0 * d.avg_dau / NULLIF(m.mau, 0), 2) AS dau_mau_pct
FROM dau d
JOIN mau m ON m.month_start = d.month_start
ORDER BY d.month_start;

-- @query: active_users_by_platform_latest_month
SELECT
    e.platform,
    COUNT(DISTINCT e.user_id)                                         AS active_users,
    COUNT(DISTINCT e.session_id)                                      AS sessions,
    ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT e.user_id), 2)              AS events_per_user
FROM core.product_events e
CROSS JOIN marts.run_params p
WHERE e.platform <> 'server'
  AND e.event_ts >= CAST(date_trunc('month', p.as_of_date) AS TIMESTAMP)
GROUP BY e.platform
ORDER BY active_users DESC;
