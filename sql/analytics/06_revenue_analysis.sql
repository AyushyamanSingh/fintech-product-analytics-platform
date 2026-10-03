-- =============================================================================
-- 06 REVENUE
-- Business question: how fast is revenue growing, what is it made of, which products drive it
-- and is the yield on the book holding up?
-- Source: marts.fct_revenue_events (cash-basis recognition; P2P interest excluded).
-- =============================================================================

-- @query: monthly_revenue
WITH m AS (
    SELECT
        CAST(date_trunc('month', revenue_date) AS DATE)                               AS month_start,
        SUM(CASE WHEN component = 'interest_income' THEN amount ELSE 0 END)           AS interest_income,
        SUM(CASE WHEN component = 'processing_fee'  THEN amount ELSE 0 END)           AS processing_fees,
        SUM(CASE WHEN component = 'late_fee'        THEN amount ELSE 0 END)           AS late_fees,
        SUM(CASE WHEN component = 'foreclosure_fee' THEN amount ELSE 0 END)           AS foreclosure_fees,
        SUM(CASE WHEN component <> 'credit_loss'    THEN amount ELSE 0 END)           AS gross_revenue,
        SUM(CASE WHEN component = 'credit_loss'     THEN -amount ELSE 0 END)          AS credit_losses
    FROM marts.fct_revenue_events
    GROUP BY 1
)
SELECT
    m.month_start,
    d.fiscal_year,
    ROUND(interest_income, 0)                                                         AS interest_income,
    ROUND(processing_fees, 0)                                                         AS processing_fees,
    ROUND(late_fees + foreclosure_fees, 0)                                            AS other_fees,
    ROUND(gross_revenue, 0)                                                           AS gross_revenue,
    ROUND(credit_losses, 0)                                                           AS credit_losses,
    ROUND(gross_revenue - credit_losses, 0)                                           AS net_revenue,
    ROUND(100.0 * (gross_revenue / NULLIF(LAG(gross_revenue) OVER (ORDER BY m.month_start), 0) - 1), 2)     AS gross_revenue_mom_pct,
    ROUND(100.0 * (gross_revenue / NULLIF(LAG(gross_revenue, 12) OVER (ORDER BY m.month_start), 0) - 1), 2) AS gross_revenue_yoy_pct,
    ROUND(SUM(gross_revenue) OVER (PARTITION BY d.fiscal_year ORDER BY m.month_start
                                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), 0)                   AS gross_revenue_fytd
FROM m
JOIN marts.dim_date d ON d.date_day = m.month_start
ORDER BY m.month_start;

-- @query: revenue_mix_by_product
WITH pm AS (
    SELECT CAST(date_trunc('month', r.revenue_date) AS DATE) AS month_start,
           r.product_id,
           SUM(CASE WHEN r.component <> 'credit_loss' THEN r.amount ELSE 0 END) AS gross_revenue
    FROM marts.fct_revenue_events r
    GROUP BY 1, 2
)
SELECT
    pm.month_start,
    pm.product_id,
    p.product_name,
    ROUND(pm.gross_revenue, 0)                                                                   AS gross_revenue,
    ROUND(100.0 * pm.gross_revenue / SUM(pm.gross_revenue) OVER (PARTITION BY pm.month_start), 2) AS share_of_month_pct,
    RANK() OVER (PARTITION BY pm.month_start ORDER BY pm.gross_revenue DESC)                     AS rank_in_month
FROM pm
JOIN core.products p ON p.product_id = pm.product_id
ORDER BY pm.month_start, rank_in_month;

-- @query: product_economics
-- Lifetime economics per product: volume, pricing, revenue, losses and risk-adjusted margin.
SELECT
    product_id,
    product_name,
    revenue_model,
    COUNT(*)                                                                         AS loans,
    ROUND(SUM(principal_amount), 0)                                                  AS disbursed,
    ROUND(AVG(principal_amount), 0)                                                  AS avg_ticket,
    ROUND(AVG(interest_rate_apr), 2)                                                 AS avg_apr_pct,
    ROUND(SUM(total_revenue), 0)                                                     AS revenue,
    ROUND(SUM(credit_loss), 0)                                                       AS credit_loss,
    ROUND(100.0 * SUM(total_revenue - credit_loss) / NULLIF(SUM(principal_amount), 0), 2) AS net_margin_on_disbursed_pct,
    ROUND(100.0 * SUM(total_revenue) / SUM(SUM(total_revenue)) OVER (), 2)           AS revenue_share_pct
FROM marts.fct_loan_performance
GROUP BY product_id, product_name, revenue_model
ORDER BY revenue DESC;

-- @query: portfolio_yield
-- Annualised interest yield on average outstanding principal (company-funded book only).
WITH book AS (
    SELECT pm.month_start, SUM(pm.outstanding_principal) AS outstanding
    FROM marts.fct_portfolio_monthly pm
    JOIN core.products p ON p.product_id = pm.product_id
    WHERE p.revenue_model = 'interest_and_fees'
    GROUP BY 1
),
interest AS (
    SELECT CAST(date_trunc('month', revenue_date) AS DATE) AS month_start, SUM(amount) AS interest_income
    FROM marts.fct_revenue_events
    WHERE component = 'interest_income'
    GROUP BY 1
)
SELECT b.month_start,
       ROUND(b.outstanding, 0)                                                         AS closing_outstanding,
       ROUND((b.outstanding + LAG(b.outstanding) OVER (ORDER BY b.month_start)) / 2, 0) AS avg_outstanding,
       ROUND(i.interest_income, 0)                                                     AS interest_income,
       ROUND(100.0 * 12 * i.interest_income
             / NULLIF((b.outstanding + LAG(b.outstanding) OVER (ORDER BY b.month_start)) / 2, 0), 2) AS annualised_yield_pct
FROM book b
LEFT JOIN interest i ON i.month_start = b.month_start
ORDER BY b.month_start;
