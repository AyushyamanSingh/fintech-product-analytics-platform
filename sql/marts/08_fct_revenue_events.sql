-- Revenue ledger at recognition date (cash basis): interest when collected, fees when charged,
-- credit losses (negative) on the write-off date. One row per loan x component x date.
-- P2P interest is excluded: on the marketplace the platform earns fees, lenders earn interest.
CREATE OR REPLACE TABLE marts.fct_revenue_events AS
SELECT CAST(r.paid_date AS DATE) AS revenue_date, r.customer_id, r.loan_id, l.product_id,
       'interest_income' AS component, r.interest_paid AS amount
FROM core.repayments r
JOIN core.loans l    ON l.loan_id = r.loan_id
JOIN core.products p ON p.product_id = l.product_id
WHERE r.interest_paid > 0 AND p.revenue_model = 'interest_and_fees'

UNION ALL
SELECT CAST(l.disbursed_ts AS DATE), l.customer_id, l.loan_id, l.product_id, 'processing_fee', l.processing_fee
FROM core.loans l

UNION ALL
SELECT CAST(r.paid_date AS DATE), r.customer_id, r.loan_id, l.product_id, 'late_fee', r.late_fee
FROM core.repayments r
JOIN core.loans l ON l.loan_id = r.loan_id
WHERE r.late_fee > 0

UNION ALL
SELECT CAST(t.txn_ts AS DATE), t.customer_id, t.loan_id, l.product_id, 'foreclosure_fee', t.amount
FROM core.transactions t
JOIN core.loans l ON l.loan_id = t.loan_id
WHERE t.txn_type = 'foreclosure_fee' AND t.txn_status = 'success'

UNION ALL
SELECT write_off_date, customer_id, loan_id, product_id, 'credit_loss', -credit_loss
FROM marts.fct_loan_performance
WHERE credit_loss > 0;
