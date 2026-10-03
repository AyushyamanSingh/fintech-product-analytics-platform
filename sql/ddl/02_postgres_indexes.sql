-- =============================================================================
-- Reference only: indexes used when the core model is deployed on PostgreSQL.
-- (DuckDB, used in this repo, relies on ART indexes for keys + zone maps instead.)
-- Each index is justified by a query pattern in sql/analytics/.
-- =============================================================================

-- Funnel & cohort queries filter/join customers by signup date and channel
CREATE INDEX IF NOT EXISTS ix_customers_signup_ts          ON core.customers (signup_ts);
CREATE INDEX IF NOT EXISTS ix_customers_channel_signup     ON core.customers (acquisition_channel, signup_ts);

-- First application / decision look-ups per customer (MIN(...) GROUP BY customer_id)
CREATE INDEX IF NOT EXISTS ix_applications_customer_start  ON core.applications (customer_id, started_ts);
CREATE INDEX IF NOT EXISTS ix_applications_decision_ts     ON core.applications (decision_ts) WHERE decision IS NOT NULL;

-- Loan-level portfolio queries and repeat-borrowing window functions (PARTITION BY customer ORDER BY disbursed_ts)
CREATE INDEX IF NOT EXISTS ix_loans_customer_disbursed     ON core.loans (customer_id, disbursed_ts);
CREATE INDEX IF NOT EXISTS ix_loans_product_disbursed      ON core.loans (product_id, disbursed_ts);

-- Month-end delinquency snapshots scan instalments by due/paid date
CREATE INDEX IF NOT EXISTS ix_repayments_loan_due          ON core.repayments (loan_id, due_date);
CREATE INDEX IF NOT EXISTS ix_repayments_due_unpaid        ON core.repayments (due_date) WHERE payment_status IN ('overdue', 'partially_paid');

-- Ledger reconciliation and daily payment-failure monitoring
CREATE INDEX IF NOT EXISTS ix_transactions_loan_type       ON core.transactions (loan_id, txn_type, txn_status);
CREATE INDEX IF NOT EXISTS ix_transactions_ts              ON core.transactions (txn_ts);

-- Event analytics: the event table is range-partitioned by month in production
--   CREATE TABLE core.product_events (...) PARTITION BY RANGE (event_ts);
CREATE INDEX IF NOT EXISTS ix_events_name_ts               ON core.product_events (event_name, event_ts);
CREATE INDEX IF NOT EXISTS ix_events_user_ts               ON core.product_events (user_id, event_ts);
