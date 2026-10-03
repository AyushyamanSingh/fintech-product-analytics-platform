-- Customer x month activity. "Active" = at least one client-side (app/web) event; server-side events
-- (decisions, disbursals, auto-debits) are recorded separately so passive autopay users are not counted as engaged.
CREATE OR REPLACE TABLE marts.fct_user_activity_monthly AS
SELECT
    user_id                                                                    AS customer_id,
    CAST(date_trunc('month', event_ts) AS DATE)                                AS activity_month,
    SUM(CASE WHEN platform <> 'server' THEN 1 ELSE 0 END)                      AS client_events,
    SUM(CASE WHEN event_name = 'login' THEN 1 ELSE 0 END)                      AS logins,
    COUNT(DISTINCT session_id)                                                 AS sessions,
    COUNT(DISTINCT CASE WHEN platform <> 'server' THEN CAST(event_ts AS DATE) END) AS active_days,
    SUM(CASE WHEN event_name = 'payment_made' THEN 1 ELSE 0 END)               AS payments,
    SUM(CASE WHEN event_name IN ('credit_score_viewed', 'emi_calculator_used',
                                 'autopay_enabled', 'referral_shared') THEN 1 ELSE 0 END) AS feature_events,
    COUNT(*)                                                                   AS total_events
FROM core.product_events
GROUP BY 1, 2;
