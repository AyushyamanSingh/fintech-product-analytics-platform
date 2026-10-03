# Metric definitions (governed KPIs)

> Generated from `python/kpi_definitions.py` by `python/build_data_dictionary.py`. The same registry feeds the KPI tables, the Power BI measures and the AI analyst's fact sheet, so a KPI means the same thing everywhere. Synthetic data.

## Acquisition

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **New customers** (`new_customers`) | Customers who created an account in the month. | `COUNT(customers) by signup month` | count | higher is better |  |  |

## Onboarding

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **KYC completion (7-day)** (`kyc_completion_rate_7d`) | Share of the month's signups that completed KYC within 7 days of signup. | `signups with kyc_completed_ts <= signup_ts + 7d / mature signups` | % (ratio 0-1) | higher is better | >= 62.0% | Signups from the last 7 days are excluded until their window closes. |
| **Activation rate (first loan in 30 days)** (`signup_to_disbursal_30d`) | Activation: share of the month's signups that received a first loan within 30 days of signup. | `signups with first_disbursed_ts <= signup_ts + 30d / mature signups` | % (ratio 0-1) | higher is better | >= 15.0% | Needs 30 days of observation, so the current month is reported next month. |

## Lending

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Applications submitted** (`applications_submitted`) | Loan applications submitted for underwriting in the month. | `COUNT(applications) by submitted month` | count | higher is better |  |  |
| **Approval rate** (`approval_rate`) | Approved decisions / all decisions made in the month. | `approved / (approved + rejected) by decision month` | % (ratio 0-1) | context-dependent | >= 50.0% |  |
| **Offer acceptance (disbursal rate)** (`offer_acceptance_rate`) | Share of approvals in the month that were disbursed. | `disbursed / approved by decision month` | % (ratio 0-1) | higher is better | >= 85.0% |  |
| **Loans disbursed** (`loans_disbursed`) | Loans disbursed in the month. | `COUNT(loans) by disbursal month` | count | higher is better |  |  |
| **Disbursed amount** (`disbursed_amount`) | Principal disbursed in the month (gross of processing fees). | `SUM(principal_amount)` | INR | higher is better |  |  |
| **Average ticket size** (`avg_ticket_size`) | Average principal per disbursed loan. | `AVG(principal_amount)` | INR | context-dependent |  |  |
| **New borrowers** (`new_borrowers`) | Customers whose first-ever loan was disbursed in the month. | `COUNT(loans WHERE loan_sequence_number = 1)` | count | higher is better |  |  |

## Retention

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Repeat-loan share** (`repeat_loan_share`) | Share of the month's disbursals that went to returning borrowers. | `repeat loans / loans` | % (ratio 0-1) | higher is better |  |  |

## Repayments

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Autopay adoption** (`autopay_adoption_rate`) | Share of the month's new loans with an active NACH/UPI-Autopay mandate. | `loans with autopay / loans` | % (ratio 0-1) | higher is better | >= 60.0% |  |
| **Collection efficiency** (`collection_efficiency`) | Amount collected by month end against instalments falling due in the month. | `SUM(amount_paid by month end) / SUM(total_due) for instalments due in month` | % (ratio 0-1) | higher is better | >= 95.0% |  |
| **Payment failure rate** (`payment_failure_rate`) | Failed EMI debit attempts / all EMI debit attempts. | `failed / (failed + success)` | % (ratio 0-1) | lower is better | <= 8.0% |  |

## Revenue

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Gross revenue** (`gross_revenue`) | Interest collected (balance-sheet products) + processing, late and foreclosure fees recognised in the month. | `SUM(fct_revenue_events.amount) excluding credit_loss` | INR | higher is better |  |  |
| **Credit losses (write-offs)** (`credit_losses`) | Principal written off in the month (180+ DPD, company-funded products). | `SUM(credit_loss) by write-off month` | INR | lower is better |  |  |
| **Net revenue** (`net_revenue`) | Gross revenue minus credit losses. | `gross_revenue - credit_losses` | INR | higher is better |  |  |

## Portfolio

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Outstanding principal (AUM)** (`outstanding_principal`) | Principal outstanding on loans on book at month end (excl. written off). | `SUM(outstanding) from month-end snapshot` | INR | higher is better |  |  |

## Risk

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **PAR30** (`par30_rate`) | Outstanding principal on loans 30-179 DPD / total outstanding at month end. | `SUM(par30_outstanding) / SUM(outstanding_principal)` | % (ratio 0-1) | lower is better | <= 6.0% |  |
| **NPA (90+ DPD)** (`npa_rate`) | Outstanding principal on loans 90-179 DPD / total outstanding at month end (RBI NPA definition). | `SUM(npa_outstanding) / SUM(outstanding_principal)` | % (ratio 0-1) | lower is better | <= 3.5% |  |
| **First-payment default (FPD30)** (`fpd30_rate`) | Share of loans disbursed in the month whose first EMI went 30+ days past due. | `loans with first instalment DPD >= 30 / matured loans` | % (ratio 0-1) | lower is better | <= 3.0% | Needs first due date + 30 days, so the latest value refers to loans disbursed ~2 months ago. |

## Engagement

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Monthly active users** (`mau`) | Distinct customers with at least one client-side (app/web) event in the month. | `COUNT(DISTINCT user_id) WHERE platform <> 'server'` | count | higher is better |  |  |

## Support

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Support tickets** (`support_tickets`) | Tickets created in the month. | `COUNT(support_tickets)` | count | lower is better |  |  |
| **Tickets per 1k MAU** (`tickets_per_1k_mau`) | Support tickets per thousand monthly active users. | `tickets * 1000 / MAU` | ratio | lower is better |  |  |
| **CSAT** (`csat_avg`) | Average post-resolution satisfaction score (1-5). | `AVG(csat_score)` | score (1-5) | higher is better | >= 4.0 |  |

## Marketing

| KPI | Definition | Formula | Unit | Direction | Target | Notes |
|---|---|---|---|---|---|---|
| **Marketing spend** (`marketing_spend`) | Paid acquisition spend, pro-rated by day across campaign flights. | `SUM(spend_inr / flight days)` | INR | context-dependent |  |  |
| **Blended CAC** (`blended_cac`) | Marketing spend / all new customers (incl. organic). | `marketing_spend / new_customers` | INR | lower is better |  |  |
| **Cost per new borrower** (`cost_per_new_borrower`) | Marketing spend / customers taking their first loan in the month. | `marketing_spend / new_borrowers` | INR | lower is better | <= 2,500 |  |

