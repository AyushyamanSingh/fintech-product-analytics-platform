-- =============================================================================
-- 07 DELINQUENCY & PORTFOLIO QUALITY
-- Business question: how healthy is the book, is credit quality deteriorating, and which
-- vintages / segments are driving losses?
-- Definitions: DPD = days past due; PAR30 = principal on 30+ DPD loans / outstanding;
-- NPA = 90-179 DPD; written off at 180 DPD; FPD30 = first instalment 30+ DPD.
-- =============================================================================

-- @query: dpd_distribution_current
SELECT
    product_id,
    dpd_bucket,
    COUNT(*)                                                                                   AS loans,
    ROUND(SUM(outstanding_principal), 0)                                                       AS outstanding,
    ROUND(100.0 * SUM(outstanding_principal)
          / SUM(SUM(outstanding_principal)) OVER (PARTITION BY product_id), 2)                 AS share_of_product_book_pct
FROM marts.fct_loan_performance
WHERE loan_status IN ('active', 'delinquent', 'npa')
GROUP BY product_id, dpd_bucket
ORDER BY product_id, dpd_bucket;

-- @query: portfolio_quality_trend
WITH m AS (
    SELECT month_start,
           SUM(outstanding_principal) AS outstanding,
           SUM(par30_outstanding)     AS par30,
           SUM(npa_outstanding)       AS npa,
           SUM(written_off_principal) AS written_off
    FROM marts.fct_portfolio_monthly
    GROUP BY month_start
)
SELECT
    month_start,
    ROUND(outstanding, 0)                                                         AS outstanding_principal,
    ROUND(100.0 * par30 / NULLIF(outstanding, 0), 2)                              AS par30_pct,
    ROUND(100.0 * npa / NULLIF(outstanding, 0), 2)                                AS npa_pct,
    ROUND(written_off, 0)                                                         AS written_off_principal,
    ROUND(AVG(100.0 * par30 / NULLIF(outstanding, 0)) OVER (ORDER BY month_start
          ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)                           AS par30_pct_3m_avg
FROM m
ORDER BY month_start;

-- @query: vintage_curves
-- Cumulative share of each quarterly vintage that has hit 30+ DPD by month-on-book N.
-- A vintage is plotted only up to the MOB that EVERY loan in it has reached, so each point uses the
-- whole vintage (no censoring bias, and no composition drift from late-quarter loans dropping out).
WITH loans AS (
    SELECT vintage_quarter, loan_id, mob_at_first_30dpd, months_on_book,
           MIN(months_on_book) OVER (PARTITION BY vintage_quarter) AS vintage_min_mob
    FROM marts.fct_loan_performance
),
mobs AS (
    SELECT generate_series AS mob FROM generate_series(1, 12)
),
grid AS (
    SELECT l.vintage_quarter,
           m.mob,
           COUNT(*)                                                                        AS loans_observable,
           SUM(CASE WHEN l.mob_at_first_30dpd IS NOT NULL AND l.mob_at_first_30dpd <= m.mob THEN 1 ELSE 0 END) AS loans_30dpd
    FROM loans l
    JOIN mobs m ON m.mob <= l.vintage_min_mob
    GROUP BY l.vintage_quarter, m.mob
)
SELECT vintage_quarter, mob, loans_observable, loans_30dpd,
       ROUND(100.0 * loans_30dpd / loans_observable, 2) AS cum_30dpd_pct
FROM grid
WHERE loans_observable >= 50
ORDER BY vintage_quarter, mob;

-- @query: risk_by_segment
WITH seg AS (
    SELECT
        CASE WHEN GROUPING(acquisition_channel) = 0 THEN 'acquisition_channel'
             WHEN GROUPING(risk_band) = 0           THEN 'risk_band'
             WHEN GROUPING(employment_type) = 0     THEN 'employment_type'
             WHEN GROUPING(autopay_enabled) = 0     THEN 'autopay_enabled'
             ELSE 'is_ntc' END                                                              AS dimension,
        COALESCE(acquisition_channel, risk_band, employment_type,
                 CASE WHEN GROUPING(autopay_enabled) = 0 THEN CAST(autopay_enabled AS VARCHAR) END,
                 CAST(is_ntc AS VARCHAR))                                                   AS segment,
        COUNT(*)                                                                            AS matured_loans,
        AVG(CASE WHEN is_fpd30 THEN 1.0 ELSE 0 END)                                        AS fpd30_rate,
        AVG(CASE WHEN ever_30dpd THEN 1.0 ELSE 0 END)                                      AS ever30_rate,
        AVG(CASE WHEN loan_status IN ('npa', 'written_off') THEN 1.0 ELSE 0 END)           AS npa_or_wo_rate
    FROM marts.fct_loan_performance
    WHERE fpd30_mature
    GROUP BY GROUPING SETS ((acquisition_channel), (risk_band), (employment_type), (autopay_enabled), (is_ntc))
)
SELECT dimension, segment, matured_loans,
       ROUND(100 * fpd30_rate, 2)     AS fpd30_pct,
       ROUND(100 * ever30_rate, 2)    AS ever_30dpd_pct,
       ROUND(100 * npa_or_wo_rate, 2) AS npa_or_written_off_pct,
       ROUND(fpd30_rate / NULLIF(AVG(fpd30_rate) OVER (PARTITION BY dimension), 0), 2) AS fpd30_index_vs_dimension_avg
FROM seg
ORDER BY dimension, fpd30_pct DESC;

-- @query: festive_season_risk
-- Did the Oct-Nov 2025 festive push dilute credit quality? Compare with the preceding 4 months.
SELECT
    CASE WHEN disbursal_date BETWEEN DATE '2025-10-01' AND DATE '2025-11-30' THEN 'festive_oct_nov_2025'
         ELSE 'baseline_jun_sep_2025' END                                                  AS period,
    acquisition_channel,
    COUNT(*)                                                                               AS loans,
    ROUND(100.0 * AVG(CASE WHEN is_fpd30 THEN 1 ELSE 0 END), 2)                           AS fpd30_pct,
    ROUND(100.0 * AVG(CASE WHEN ever_30dpd THEN 1 ELSE 0 END), 2)                         AS ever_30dpd_pct
FROM marts.fct_loan_performance
WHERE disbursal_date BETWEEN DATE '2025-06-01' AND DATE '2025-11-30'
  AND loan_sequence_number = 1
GROUP BY 1, 2
ORDER BY acquisition_channel, period;
