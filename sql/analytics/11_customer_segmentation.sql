-- =============================================================================
-- 11 CUSTOMER SEGMENTATION (SQL, rules-based)
-- Business question: which borrower groups should CRM retain, grow, nurture or watch?
-- RFM on borrowers: Recency (days since last loan), Frequency (loans), Monetary (net revenue),
-- each scored 1-5 with NTILE. Complements the K-Means clustering in python/segmentation.py.
-- =============================================================================

-- @query: rfm_segments
WITH b AS (
    SELECT customer_id, days_since_last_loan, n_loans, net_revenue, max_dpd_ever, current_dpd, has_open_loan
    FROM marts.customer_360
    WHERE n_loans > 0
),
scored AS (
    SELECT *,
           NTILE(5) OVER (ORDER BY days_since_last_loan DESC) AS r_score,   -- recent = 5
           NTILE(5) OVER (ORDER BY n_loans ASC)               AS f_score,
           NTILE(5) OVER (ORDER BY net_revenue ASC)           AS m_score
    FROM b
),
labelled AS (
    SELECT *,
           CASE
               WHEN current_dpd >= 30 OR max_dpd_ever >= 90           THEN 'Credit risk watchlist'
               WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4    THEN 'Champions'
               WHEN f_score >= 4 AND m_score >= 3                     THEN 'Loyal repeat borrowers'
               WHEN r_score >= 4 AND f_score <= 2                     THEN 'New borrowers'
               WHEN r_score <= 2 AND f_score >= 3                     THEN 'At risk of churn'
               WHEN r_score <= 2                                      THEN 'Dormant one-timers'
               ELSE 'Developing'
           END AS rfm_segment
    FROM scored
)
SELECT
    rfm_segment,
    COUNT(*)                                                                    AS borrowers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                          AS share_of_borrowers_pct,
    ROUND(AVG(n_loans), 2)                                                      AS avg_loans,
    ROUND(AVG(net_revenue), 0)                                                  AS avg_net_revenue,
    ROUND(100.0 * SUM(net_revenue) / SUM(SUM(net_revenue)) OVER (), 2)          AS share_of_net_revenue_pct,
    ROUND(AVG(days_since_last_loan), 0)                                         AS avg_days_since_last_loan,
    ROUND(100.0 * AVG(CASE WHEN has_open_loan THEN 1 ELSE 0 END), 2)           AS with_open_loan_pct
FROM labelled
GROUP BY rfm_segment
ORDER BY avg_net_revenue DESC;
