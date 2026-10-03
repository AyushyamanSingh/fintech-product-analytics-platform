-- =============================================================================
-- Core (curated) layer of the Vittora Credit analytics warehouse.  SYNTHETIC DATA.
-- Dialect: DuckDB (PostgreSQL-compatible DDL). Executed by etl/load.py.
--
-- Keys
--   * Every table has a surrogate/business PRIMARY KEY.
--   * FOREIGN KEYs are enforced at load time: if the ETL lets an orphan through,
--     the load fails loudly instead of producing silently wrong joins.
--   * Column names/types must match data_quality/contracts.yaml
--     (asserted by tests/test_contracts.py).
-- Indexing: DuckDB builds ART indexes for PK/FK and uses min-max zone maps for range
-- filters, so no extra indexes are needed here. sql/ddl/02_postgres_indexes.sql lists
-- the indexes used when the same model runs on PostgreSQL.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE core.products (
    product_id            VARCHAR       PRIMARY KEY,
    product_name          VARCHAR       NOT NULL,
    product_category      VARCHAR       NOT NULL,
    min_amount            DECIMAL(18,2) NOT NULL,
    max_amount            DECIMAL(18,2) NOT NULL,
    min_tenure_months     BIGINT        NOT NULL,
    max_tenure_months     BIGINT        NOT NULL,
    base_apr_pct          DOUBLE        NOT NULL,
    processing_fee_pct    DOUBLE        NOT NULL,
    revenue_model         VARCHAR       NOT NULL,
    launch_date           DATE          NOT NULL,
    is_secured            BOOLEAN       NOT NULL,
    is_active             BOOLEAN       NOT NULL,
    CHECK (min_amount <= max_amount)
);

CREATE TABLE core.marketing_campaigns (
    campaign_id           VARCHAR       PRIMARY KEY,
    campaign_name         VARCHAR       NOT NULL,
    channel               VARCHAR       NOT NULL,
    objective             VARCHAR       NOT NULL,
    target_product_id     VARCHAR       REFERENCES core.products (product_id),
    start_date            DATE          NOT NULL,
    end_date              DATE          NOT NULL,
    budget_inr            DECIMAL(18,2) NOT NULL,
    spend_inr             DECIMAL(18,2) NOT NULL,
    impressions           BIGINT        NOT NULL,
    clicks                BIGINT        NOT NULL,
    CHECK (start_date <= end_date)
);

CREATE TABLE core.customers (
    customer_id           VARCHAR       PRIMARY KEY,
    signup_ts             TIMESTAMP     NOT NULL,
    acquisition_channel   VARCHAR       NOT NULL,
    campaign_id           VARCHAR       REFERENCES core.marketing_campaigns (campaign_id),
    signup_platform       VARCHAR       NOT NULL,
    city                  VARCHAR,                       -- nullable in practice (DQ warning)
    state                 VARCHAR       NOT NULL,
    city_tier             VARCHAR       NOT NULL,
    age                   BIGINT,                        -- impossible ages nulled by ETL
    employment_type       VARCHAR       NOT NULL,
    monthly_income        DECIMAL(18,2),                 -- self-declared, may be missing
    credit_score          BIGINT,                        -- NULL = new to credit (see is_ntc)
    kyc_status            VARCHAR       NOT NULL,
    kyc_started_ts        TIMESTAMP,
    kyc_completed_ts      TIMESTAMP,
    kyc_method            VARCHAR,
    marketing_opt_in      BOOLEAN       NOT NULL,
    is_ntc                BOOLEAN       NOT NULL
);

CREATE TABLE core.applications (
    application_id          VARCHAR       PRIMARY KEY,
    customer_id             VARCHAR       NOT NULL REFERENCES core.customers (customer_id),
    product_id              VARCHAR       NOT NULL REFERENCES core.products (product_id),
    started_ts              TIMESTAMP     NOT NULL,
    submitted_ts            TIMESTAMP,
    requested_amount        DECIMAL(18,2) NOT NULL,
    requested_tenure_months BIGINT        NOT NULL,
    loan_purpose            VARCHAR       NOT NULL,
    application_platform    VARCHAR       NOT NULL,
    is_repeat_customer      BOOLEAN       NOT NULL,
    internal_risk_score     DOUBLE,
    risk_band               VARCHAR,
    decision                VARCHAR,
    decision_ts             TIMESTAMP,
    rejection_reason        VARCHAR,
    sanctioned_amount       DECIMAL(18,2),
    application_status      VARCHAR       NOT NULL
);

CREATE TABLE core.loans (
    loan_id               VARCHAR       PRIMARY KEY,
    application_id        VARCHAR       REFERENCES core.applications (application_id),  -- lineage gaps nulled + flagged
    customer_id           VARCHAR       NOT NULL REFERENCES core.customers (customer_id),
    product_id            VARCHAR       NOT NULL REFERENCES core.products (product_id),
    disbursed_ts          TIMESTAMP     NOT NULL,
    principal_amount      DECIMAL(18,2) NOT NULL,
    processing_fee        DECIMAL(18,2) NOT NULL,
    net_disbursed_amount  DECIMAL(18,2) NOT NULL,
    interest_rate_apr     DOUBLE        NOT NULL,
    tenure_months         BIGINT        NOT NULL,
    emi_amount            DECIMAL(18,2) NOT NULL,
    risk_band             VARCHAR       NOT NULL,
    autopay_enabled       BOOLEAN       NOT NULL,
    loan_sequence_number  BIGINT        NOT NULL,
    is_repeat_loan        BOOLEAN       NOT NULL,
    maturity_date         DATE          NOT NULL,
    loan_status           VARCHAR       NOT NULL,
    current_dpd           BIGINT        NOT NULL,
    max_dpd               BIGINT        NOT NULL,
    outstanding_principal DECIMAL(18,2) NOT NULL,
    closed_date           DATE,
    closure_type          VARCHAR,
    CHECK (current_dpd <= max_dpd)
);

CREATE TABLE core.repayments (
    repayment_id          VARCHAR       PRIMARY KEY,
    loan_id               VARCHAR       NOT NULL REFERENCES core.loans (loan_id),
    customer_id           VARCHAR       NOT NULL REFERENCES core.customers (customer_id),
    installment_number    BIGINT        NOT NULL,
    due_date              DATE          NOT NULL,
    principal_due         DECIMAL(18,2) NOT NULL,
    interest_due          DECIMAL(18,2) NOT NULL,
    total_due             DECIMAL(18,2) NOT NULL,
    amount_paid           DECIMAL(18,2) NOT NULL,
    principal_paid        DECIMAL(18,2) NOT NULL,
    interest_paid         DECIMAL(18,2) NOT NULL,
    paid_date             DATE,
    payment_status        VARCHAR       NOT NULL,
    days_past_due         BIGINT        NOT NULL,
    late_fee              DECIMAL(18,2) NOT NULL,
    UNIQUE (loan_id, installment_number)
);

CREATE TABLE core.transactions (
    transaction_id        VARCHAR       PRIMARY KEY,
    customer_id           VARCHAR       NOT NULL REFERENCES core.customers (customer_id),
    loan_id               VARCHAR       REFERENCES core.loans (loan_id),
    repayment_id          VARCHAR       REFERENCES core.repayments (repayment_id),
    txn_ts                TIMESTAMP     NOT NULL,
    txn_type              VARCHAR       NOT NULL,
    amount                DECIMAL(18,2) NOT NULL,
    payment_method        VARCHAR       NOT NULL,
    txn_status            VARCHAR       NOT NULL,
    failure_reason        VARCHAR
);

CREATE TABLE core.product_events (
    event_id              VARCHAR       PRIMARY KEY,
    user_id               VARCHAR       NOT NULL REFERENCES core.customers (customer_id),
    event_name            VARCHAR       NOT NULL,
    event_ts              TIMESTAMP     NOT NULL,
    session_id            VARCHAR,
    platform              VARCHAR       NOT NULL,
    app_version           VARCHAR,
    properties            VARCHAR       NOT NULL,
    prop_product_id       VARCHAR,
    prop_amount           DOUBLE,
    prop_variant          VARCHAR,
    prop_reason           VARCHAR,
    prop_category         VARCHAR,
    prop_method           VARCHAR,
    prop_on_time          BOOLEAN
);

CREATE TABLE core.support_tickets (
    ticket_id              VARCHAR      PRIMARY KEY,
    customer_id            VARCHAR      NOT NULL REFERENCES core.customers (customer_id),
    loan_id                VARCHAR      REFERENCES core.loans (loan_id),
    created_ts             TIMESTAMP    NOT NULL,
    channel                VARCHAR      NOT NULL,
    category               VARCHAR      NOT NULL,
    priority               VARCHAR      NOT NULL,
    first_response_minutes DOUBLE       NOT NULL,
    resolved_ts            TIMESTAMP,
    ticket_status          VARCHAR      NOT NULL,
    csat_score             DOUBLE
);

CREATE TABLE core.experiments (
    experiment_id         VARCHAR       PRIMARY KEY,
    experiment_name       VARCHAR       NOT NULL,
    feature_area          VARCHAR       NOT NULL,
    hypothesis            VARCHAR       NOT NULL,
    unit                  VARCHAR       NOT NULL,
    allocation_pct        BIGINT        NOT NULL,
    start_date            DATE          NOT NULL,
    end_date              DATE          NOT NULL,
    primary_metric        VARCHAR       NOT NULL,
    secondary_metrics     VARCHAR,
    guardrail_metrics     VARCHAR,
    status                VARCHAR       NOT NULL,
    owner_team            VARCHAR       NOT NULL
);

CREATE TABLE core.experiment_assignments (
    assignment_id         VARCHAR       PRIMARY KEY,
    experiment_id         VARCHAR       NOT NULL REFERENCES core.experiments (experiment_id),
    customer_id           VARCHAR       NOT NULL REFERENCES core.customers (customer_id),
    variant               VARCHAR       NOT NULL,
    assigned_ts           TIMESTAMP     NOT NULL,
    platform              VARCHAR       NOT NULL,
    UNIQUE (experiment_id, customer_id)
);
