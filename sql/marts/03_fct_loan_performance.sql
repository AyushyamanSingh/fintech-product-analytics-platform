-- Loan-level performance and economics (one row per disbursed loan).
-- Revenue recognition: P2P loans (revenue_model = 'platform_fee') earn fees only; interest belongs to lenders,
-- and so do their credit losses. Credit loss = principal outstanding on written-off (180+ DPD) loans.
CREATE OR REPLACE TABLE marts.fct_loan_performance AS
WITH rp AS (
    SELECT
        loan_id,
        SUM(interest_paid)                                                          AS interest_collected,
        SUM(principal_paid)                                                         AS principal_collected,
        SUM(late_fee)                                                               AS late_fees,
        SUM(amount_paid)                                                            AS emi_collected,
        SUM(CASE WHEN payment_status <> 'scheduled' THEN 1 ELSE 0 END)              AS installments_due,
        SUM(CASE WHEN payment_status = 'paid_on_time' THEN 1 ELSE 0 END)            AS installments_on_time,
        SUM(CASE WHEN payment_status = 'paid_late' THEN 1 ELSE 0 END)               AS installments_late,
        SUM(CASE WHEN payment_status IN ('overdue', 'partially_paid') THEN 1 ELSE 0 END) AS installments_unpaid,
        MAX(CASE WHEN installment_number = 1 THEN due_date END)                     AS first_due_date,
        MAX(CASE WHEN installment_number = 1 THEN days_past_due END)                AS first_installment_dpd,
        MIN(CASE WHEN days_past_due >= 30 THEN due_date + INTERVAL 30 DAY END)      AS first_30dpd_date,
        MIN(CASE WHEN payment_status IN ('overdue', 'partially_paid') THEN due_date END) AS oldest_unpaid_due_date
    FROM core.repayments
    GROUP BY loan_id
),
fees AS (
    SELECT loan_id,
           SUM(CASE WHEN txn_type = 'foreclosure_fee' THEN amount ELSE 0 END)     AS foreclosure_fees
    FROM core.transactions
    WHERE txn_status = 'success' AND loan_id IS NOT NULL
    GROUP BY loan_id
),
base AS (
    SELECT
        l.*,
        p.product_name,
        p.product_category,
        p.revenue_model,
        c.acquisition_channel,
        c.signup_platform,
        c.city_tier,
        c.employment_type,
        c.is_ntc,
        COALESCE(rp.interest_collected, 0)      AS interest_collected,
        COALESCE(rp.principal_collected, 0)     AS principal_collected,
        COALESCE(rp.late_fees, 0)               AS late_fees,
        COALESCE(rp.emi_collected, 0)           AS emi_collected,
        COALESCE(f.foreclosure_fees, 0)         AS foreclosure_fees,
        COALESCE(rp.installments_due, 0)        AS installments_due,
        COALESCE(rp.installments_on_time, 0)    AS installments_on_time,
        COALESCE(rp.installments_late, 0)       AS installments_late,
        COALESCE(rp.installments_unpaid, 0)     AS installments_unpaid,
        rp.first_due_date,
        rp.first_installment_dpd,
        rp.first_30dpd_date,
        rp.oldest_unpaid_due_date,
        pr.as_of_date
    FROM core.loans l
    JOIN core.products p   ON p.product_id = l.product_id
    JOIN core.customers c  ON c.customer_id = l.customer_id
    LEFT JOIN rp           ON rp.loan_id = l.loan_id
    LEFT JOIN fees f       ON f.loan_id = l.loan_id
    CROSS JOIN marts.run_params pr
)
SELECT
    loan_id, application_id, customer_id, product_id, product_name, product_category, revenue_model,
    disbursed_ts,
    CAST(disbursed_ts AS DATE)                                        AS disbursal_date,
    CAST(date_trunc('month', disbursed_ts) AS DATE)                   AS disbursal_month,
    CAST(date_trunc('quarter', disbursed_ts) AS DATE)                 AS vintage_quarter,
    principal_amount, processing_fee, net_disbursed_amount, interest_rate_apr, tenure_months, emi_amount,
    risk_band, autopay_enabled, loan_sequence_number, is_repeat_loan, loan_status, current_dpd, max_dpd,
    outstanding_principal, closed_date, closure_type,
    acquisition_channel, signup_platform, city_tier, employment_type, is_ntc,
    interest_collected, principal_collected, late_fees, foreclosure_fees, emi_collected,
    installments_due, installments_on_time, installments_late, installments_unpaid,
    CASE WHEN installments_due > 0 THEN installments_on_time * 1.0 / installments_due END   AS on_time_rate,
    CASE WHEN revenue_model = 'platform_fee' THEN 0 ELSE interest_collected END              AS interest_income,
    processing_fee + late_fees + foreclosure_fees                                             AS fee_income,
    CASE WHEN revenue_model = 'platform_fee' THEN 0 ELSE interest_collected END
        + processing_fee + late_fees + foreclosure_fees                                       AS total_revenue,
    CASE WHEN loan_status = 'written_off' AND revenue_model <> 'platform_fee'
         THEN outstanding_principal ELSE 0 END                                                AS credit_loss,
    CASE WHEN loan_status = 'written_off' THEN CAST(oldest_unpaid_due_date + INTERVAL 180 DAY AS DATE) END AS write_off_date,
    CASE WHEN current_dpd = 0   THEN '0 current'
         WHEN current_dpd < 30  THEN '1-29'
         WHEN current_dpd < 60  THEN '30-59'
         WHEN current_dpd < 90  THEN '60-89'
         WHEN current_dpd < 180 THEN '90-179'
         ELSE '180+' END                                                                      AS dpd_bucket,
    first_due_date,
    first_installment_dpd,
    -- FPD30 = first instalment 30+ days past due; only measurable once the first due date is 30+ days old
    first_due_date <= as_of_date - INTERVAL 30 DAY                                            AS fpd30_mature,
    COALESCE(first_installment_dpd >= 30, FALSE)                                              AS is_fpd30,
    max_dpd >= 30                                                                             AS ever_30dpd,
    max_dpd >= 90                                                                             AS ever_90dpd,
    CAST(first_30dpd_date AS DATE)                                                            AS first_30dpd_date,
    date_diff('month', CAST(disbursed_ts AS DATE), CAST(first_30dpd_date AS DATE))           AS mob_at_first_30dpd,
    date_diff('month', CAST(disbursed_ts AS DATE), as_of_date)                                AS months_on_book
FROM base;
