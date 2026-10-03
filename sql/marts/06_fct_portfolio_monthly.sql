-- Month-end portfolio snapshots by product, reconstructed from the instalment history
-- (point-in-time correct: a payment made after the month end does not cure that month's DPD).
--   PAR30 = outstanding principal on loans 30+ DPD / total outstanding
--   NPA   = 90-179 DPD (RBI definition); 180+ DPD loans are written off and leave the book.
CREATE OR REPLACE TABLE marts.fct_portfolio_monthly AS
WITH month_ends AS (
    SELECT DISTINCT
           d.month_start,
           LEAST(CAST(d.month_start + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE), p.as_of_date) AS month_end
    FROM marts.dim_date d
    CROSS JOIN marts.run_params p
),
loan_book AS (                       -- loans disbursed and not yet closed at each month end
    SELECT me.month_start, me.month_end, l.loan_id, l.product_id, l.principal_amount
    FROM month_ends me
    JOIN core.loans l
      ON CAST(l.disbursed_ts AS DATE) <= me.month_end
     AND (l.closed_date IS NULL OR l.closed_date > me.month_end)
),
inst AS (                            -- point-in-time repayment state per loan and month end
    SELECT lb.month_start,
           lb.loan_id,
           SUM(CASE WHEN r.paid_date <= lb.month_end THEN r.principal_paid ELSE 0 END) AS principal_repaid,
           MIN(CASE WHEN r.due_date <= lb.month_end
                     AND (r.paid_date IS NULL OR r.paid_date > lb.month_end OR r.amount_paid < r.total_due)
                    THEN r.due_date END)                                                AS oldest_unpaid_due
    FROM loan_book lb
    JOIN core.repayments r ON r.loan_id = lb.loan_id
    GROUP BY lb.month_start, lb.loan_id
),
snap AS (
    SELECT lb.month_start,
           lb.month_end,
           lb.product_id,
           GREATEST(lb.principal_amount - COALESCE(i.principal_repaid, 0), 0)          AS outstanding,
           COALESCE(date_diff('day', i.oldest_unpaid_due, lb.month_end), 0)             AS dpd
    FROM loan_book lb
    LEFT JOIN inst i ON i.month_start = lb.month_start AND i.loan_id = lb.loan_id
),
writeoffs AS (
    SELECT CAST(date_trunc('month', write_off_date) AS DATE) AS month_start, product_id,
           COUNT(*) AS loans_written_off, SUM(outstanding_principal) AS written_off_principal
    FROM marts.fct_loan_performance
    WHERE write_off_date IS NOT NULL
    GROUP BY 1, 2
)
SELECT
    s.month_start,
    s.month_end,
    s.product_id,
    SUM(CASE WHEN s.dpd < 180 THEN 1 ELSE 0 END)                                AS loans_on_book,
    SUM(CASE WHEN s.dpd < 180 THEN s.outstanding ELSE 0 END)                    AS outstanding_principal,
    SUM(CASE WHEN s.dpd BETWEEN 1 AND 29 THEN s.outstanding ELSE 0 END)         AS dpd_1_29_outstanding,
    SUM(CASE WHEN s.dpd BETWEEN 30 AND 179 THEN s.outstanding ELSE 0 END)       AS par30_outstanding,
    SUM(CASE WHEN s.dpd BETWEEN 90 AND 179 THEN s.outstanding ELSE 0 END)       AS npa_outstanding,
    SUM(CASE WHEN s.dpd BETWEEN 30 AND 179 THEN 1 ELSE 0 END)                   AS par30_loans,
    SUM(CASE WHEN s.dpd BETWEEN 90 AND 179 THEN 1 ELSE 0 END)                   AS npa_loans,
    COALESCE(MAX(w.loans_written_off), 0)                                       AS loans_written_off,
    COALESCE(MAX(w.written_off_principal), 0)                                   AS written_off_principal
FROM snap s
LEFT JOIN writeoffs w ON w.month_start = s.month_start AND w.product_id = s.product_id
GROUP BY s.month_start, s.month_end, s.product_id
ORDER BY s.month_start, s.product_id;
