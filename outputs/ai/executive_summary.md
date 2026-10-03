# Weekly Business Summary - week of 22 Jun 2026

_Vittora Credit (fictional) - synthetic data - generated 2026-10-03 03:19 - engine: deterministic template (no LLM call) - numeric verification: **PASSED** (116 numbers in 37 items checked against the cited facts)_

> **Jun 2026: Gross revenue ₹59.30 L (+1.6% vs prior month); Loans disbursed 1,293 (-2.1% vs prior month); Collection efficiency remains below target at 93.9%.** [F13][F07][F20]

## Highlights

- Week of 22 Jun: Loans disbursed 317 (+7.1% week on week); Disbursed amount ₹1.41 Cr (+4.7% week on week); EMI collections ₹1.38 Cr (+16.6% week on week); Payment failure rate 11.2% (+0.8 pp week on week). [F33][F34][F35][F36]
- Disbursed amount ₹5.86 Cr (+1.3% vs prior month); Net revenue ₹33.96 L (-17.2% vs prior month). [F08][F15]
- KYC completion (7-day) 62.3% (-0.9 pp vs prior month); Approval rate 62.2% (-2.4 pp vs prior month). [F02][F05]
- PAR30 3.6% (-0.2 pp vs prior month); NPA (90+ DPD) 2.0% (-0.5 pp vs prior month). [F17][F18]
- Monthly active users 14,918 (+1.4% vs prior month); Repeat-loan share 34.9% (-3.7 pp vs prior month). [F22][F11]
- Onboarding redesign experiment: 7-day KYC completion 61.78% treatment vs 58.51% control, difference +3.26 pp (95% CI +0.54 to +5.99 pp), relative uplift +5.6%, p-value 0.0191; P(treatment better) 99.0%. [F50]

## KPI movements

- Approval rate: 62.2% (-2.4 pp vs prior month) - down. [F05]
- Repeat-loan share: 34.9% (-3.7 pp vs prior month) - worsened. [F11]
- Credit losses (write-offs): ₹25.34 L (+46.1% vs prior month) - worsened. [F14]
- Net revenue: ₹33.96 L (-17.2% vs prior month) - worsened. [F15]
- Support tickets: 361 (+7.8% vs prior month) - worsened. [F23]
- Tickets per 1k MAU: 24.20 (+6.2% vs prior month) - worsened. [F24]
- Marketing spend: ₹11.62 L (+7.4% vs prior month) - up. [F26]

## Anomalies

- No anomaly episodes in the last 8 weeks; the monitor remains active. [F41]
- Past incident for context: EMI payment failure rate spiked to 47.1% on 15 Aug 2025 (expected 8.9%, robust z 15.6); main driver: failure reason (excess failed debits) = gateway_timeout (96% of the deviation). Window 2025-08-14 to 2025-08-15, 2 day(s) flagged, severity high (no known business event - investigate). [F46]
- Past incident for context: Signups spiked to 222 on 15 Sep 2025 (expected 113, robust z 6.8); main driver: acquisition channel = affiliate (87% of the deviation). Window 2025-09-08 to 2025-09-21, 14 day(s) flagged, severity high (no known business event - investigate). [F47]
- Past incident for context: Daily active users spiked to 920 on 16 Sep 2025 (expected 692, robust z 5.8); main driver: platform = android (94% of the deviation). Window 2025-09-13 to 2025-09-20, 6 day(s) flagged, severity high (no known business event - investigate). [F48]

## Experiments

- EXP-ONB-2026-01 guardrails: approval rate +3.13 pp (pass), FPD30 -1.48 pp (pass), KYC support tickets +0.16 pp (inconclusive). Decision: SHIP with post-launch monitoring of kyc_support_ticket_rate. [F52]
- EXP-RPY-2025-11 (Autopay nudge at disbursal): autopay 64.28% treatment vs 46.62% control, difference +17.65 pp (95% CI +12.76 to +22.54 pp), p-value 0.0000. Decision: SHIP. [F54]
- EXP-PRC-2025-06 (Upfront fee transparency on the offer screen): accepted 90.98% treatment vs 88.78% control, difference +2.20 pp (95% CI -1.93 to +6.32 pp), p-value 0.2974. Decision: INCONCLUSIVE - underpowered: needed 1,530 users per arm for a 3.0 pp MDE, had 410. [F55]

## Risks

- Collection efficiency is off target: 93.9% (>= 95.0% -> off track). [F20]
- Payment failure rate is off target: 10.3% (<= 8.0% -> off track). [F21]
- CSAT is off target: 3.46 (>= 4.00 -> off track). [F25]
- Festive-season credit dilution: First-loan FPD30 for loans disbursed in the Oct-Nov 2025 festive season vs Jun-Sep 2025: affiliate 4.49% vs 1.71%, paid social 5.42% vs 3.67%, partnerships 2.40% vs 3.25%. [F59]
- Acquisition fraud exposure: Campaign CMP-202509-AFFNB (Affiliate Network B, Sep 2025): spend ₹5.56 L, 1,258 signups, 4 funded customers, cost per funded customer ₹1.39 L; flagged 'inefficient_spend'. [F61]

## Recommendations

| # | Recommendation | Owner | Evidence |
|---|---|---|---|
| 1 | Add pre-due-date reminders (three days and one day before the EMI date) and same-day retries for failed auto-debits. | Collections & Repayments | [F20] |
| 2 | Make autopay mandate set-up the default step at disbursal and schedule debit retries around salary-credit dates; autopay borrowers repay on time more often. | Collections & Repayments | [F21][F60] |
| 3 | Attack the top ticket drivers (KYC issues, payment failures) with in-app self-serve fixes and a first-response SLA; CSAT is below target. | Customer Support | [F25] |
| 4 | Shift paid budget from affiliate and paid social towards referral and employer partnerships, which return the most value per rupee of acquisition cost. | Marketing | [F28][F58] |
| 5 | Add device and velocity rules for affiliate traffic and pay affiliates on funded, performing loans instead of signups. | Risk & Marketing | [F61] |

## Data caveats

- Data quality: DQ score 92.0 on the raw extract and 99.1 on the curated layer; critical failures 22 -> 0; 9 warnings remain (documented open issues); 27 of 27 planted defect types detected. [F64]
- Open data-quality issue (warning): marketing_campaigns.budget_inr,spend_inr cross_field:spend_within_budget - 1 rows (spend_inr <= 1.5 * budget_inr). [F65]
- Open data-quality issue (warning): customers.city not_null - 974 rows (nulls in a non-nullable column). [F66]
- Open data-quality issue (warning): customers.age not_null - 65 rows (nulls in a non-nullable column). [F67]
- Cohort-based KPIs report with a lag: Activation rate (first loan in 30 days) refers to May 2026, First-payment default (FPD30) refers to Apr 2026. [F03][F19]
- All figures are synthetic and generated for demonstration.

## Sources

Every bracketed reference points to a fact computed by the pipeline:

- **[F02]** KYC completion (7-day) (Jun 2026): 62.3%; prior month 63.2% (-0.9 pp); same month last year 56.3% (+6.0 pp); target >= 62.0% -> on track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F03]** Activation rate (first loan in 30 days) (May 2026): 17.0%; prior month 18.0% (-1.0 pp); same month last year 15.7% (+1.3 pp); target >= 15.0% -> on track; assessment: stable. (Latest available period: Needs 30 days of observation, so the current month is reported next month..) _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F05]** Approval rate (Jun 2026): 62.2%; prior month 64.6% (-2.4 pp); same month last year 60.5% (+1.7 pp); target >= 50.0% -> on track; assessment: down, notable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F07]** Loans disbursed (Jun 2026): 1,293; prior month 1,321 (-2.1%); same month last year 786 (+64.5%); assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F08]** Disbursed amount (Jun 2026): ₹5.86 Cr; prior month ₹5.78 Cr (+1.3%); same month last year ₹3.28 Cr (+78.6%); assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F11]** Repeat-loan share (Jun 2026): 34.9%; prior month 38.6% (-3.7 pp); same month last year 33.5% (+1.4 pp); assessment: worsened, notable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F13]** Gross revenue (Jun 2026): ₹59.30 L; prior month ₹58.38 L (+1.6%); same month last year ₹31.34 L (+89.2%); assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F14]** Credit losses (write-offs) (Jun 2026): ₹25.34 L; prior month ₹17.35 L (+46.1%); same month last year ₹7.41 L (+241.9%); assessment: worsened, notable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F15]** Net revenue (Jun 2026): ₹33.96 L; prior month ₹41.03 L (-17.2%); same month last year ₹23.93 L (+41.9%); assessment: worsened, notable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F17]** PAR30 (Jun 2026): 3.6%; prior month 3.8% (-0.2 pp); same month last year 2.1% (+1.5 pp); target <= 6.0% -> on track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F18]** NPA (90+ DPD) (Jun 2026): 2.0%; prior month 2.5% (-0.5 pp); same month last year 1.2% (+0.8 pp); target <= 3.5% -> on track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F19]** First-payment default (FPD30) (Apr 2026): 1.5%; prior month 1.8% (-0.4 pp); same month last year 2.2% (-0.7 pp); target <= 3.0% -> on track; assessment: stable. (Latest available period: Needs first due date + 30 days, so the latest value refers to loans disbursed ~2 months ago..) _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F20]** Collection efficiency (Jun 2026): 93.9%; prior month 93.5% (+0.4 pp); same month last year 95.3% (-1.3 pp); target >= 95.0% -> off track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F21]** Payment failure rate (Jun 2026): 10.3%; prior month 10.0% (+0.3 pp); same month last year 8.0% (+2.3 pp); target <= 8.0% -> off track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F22]** Monthly active users (Jun 2026): 14,918; prior month 14,705 (+1.4%); same month last year 9,245 (+61.4%); assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F23]** Support tickets (Jun 2026): 361; prior month 335 (+7.8%); same month last year 248 (+45.6%); assessment: worsened. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F24]** Tickets per 1k MAU (Jun 2026): 24.20; prior month 22.78 (+6.2%); same month last year 26.83 (-9.8%); assessment: worsened. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F25]** CSAT (Jun 2026): 3.46; prior month 3.48 (-0.7%); same month last year 3.58 (-3.5%); target >= 4.00 -> off track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F26]** Marketing spend (Jun 2026): ₹11.62 L; prior month ₹10.82 L (+7.4%); same month last year ₹7.93 L (+46.6%); assessment: up, notable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F28]** Cost per new borrower (Jun 2026): ₹1,380; prior month ₹1,334 (+3.5%); same month last year ₹1,516 (-8.9%); target <= ₹2,500 -> on track; assessment: stable. _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F33]** Loans disbursed (week of 22 Jun 2026): 317; prior week 296 (+7.1%); 4-week average 299 (+6.1%). _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F34]** Disbursed amount (week of 22 Jun 2026): ₹1.41 Cr; prior week ₹1.34 Cr (+4.7%); 4-week average ₹1.34 Cr (+4.6%). _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F35]** EMI collections (week of 22 Jun 2026): ₹1.38 Cr; prior week ₹1.18 Cr (+16.6%); 4-week average ₹1.10 Cr (+26.1%). _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F36]** Payment failure rate (week of 22 Jun 2026): 11.2%; prior week 10.4% (+0.8 pp); 4-week average 9.9% (+1.3 pp). _(source: `outputs/kpis/kpi_snapshot.json`)_
- **[F41]** Anomaly monitor: 8 episodes flagged across the 24-month history; 0 in the last 8 weeks (since 05 May 2026). _(source: `outputs/anomalies/anomaly_episodes.json`)_
- **[F46]** EMI payment failure rate spiked to 47.1% on 15 Aug 2025 (expected 8.9%, robust z 15.6); main driver: failure reason (excess failed debits) = gateway_timeout (96% of the deviation). Window 2025-08-14 to 2025-08-15, 2 day(s) flagged, severity high (no known business event - investigate). _(source: `outputs/anomalies/anomaly_episodes.json`)_
- **[F47]** Signups spiked to 222 on 15 Sep 2025 (expected 113, robust z 6.8); main driver: acquisition channel = affiliate (87% of the deviation). Window 2025-09-08 to 2025-09-21, 14 day(s) flagged, severity high (no known business event - investigate). _(source: `outputs/anomalies/anomaly_episodes.json`)_
- **[F48]** Daily active users spiked to 920 on 16 Sep 2025 (expected 692, robust z 5.8); main driver: platform = android (94% of the deviation). Window 2025-09-13 to 2025-09-20, 6 day(s) flagged, severity high (no known business event - investigate). _(source: `outputs/anomalies/anomaly_episodes.json`)_
- **[F50]** EXP-ONB-2026-01 (onboarding redesign, 2026-01-12 to 2026-02-22 (6 weeks)): 7-day KYC completion 61.78% treatment vs 58.51% control, difference +3.26 pp (95% CI +0.54 to +5.99 pp), relative uplift +5.6%, p-value 0.0191; P(treatment better) 99.0%. _(source: `outputs/experiments/experiment_results.json`)_
- **[F52]** EXP-ONB-2026-01 guardrails: approval rate +3.13 pp (pass), FPD30 -1.48 pp (pass), KYC support tickets +0.16 pp (inconclusive). Decision: SHIP with post-launch monitoring of kyc_support_ticket_rate. _(source: `outputs/experiments/experiment_results.json`)_
- **[F54]** EXP-RPY-2025-11 (Autopay nudge at disbursal): autopay 64.28% treatment vs 46.62% control, difference +17.65 pp (95% CI +12.76 to +22.54 pp), p-value 0.0000. Decision: SHIP. _(source: `outputs/experiments/experiment_results.json`)_
- **[F55]** EXP-PRC-2025-06 (Upfront fee transparency on the offer screen): accepted 90.98% treatment vs 88.78% control, difference +2.20 pp (95% CI -1.93 to +6.32 pp), p-value 0.2974. Decision: INCONCLUSIVE - underpowered: needed 1,530 users per arm for a 3.0 pp MDE, had 410. _(source: `outputs/experiments/experiment_results.json`)_
- **[F58]** LTV/CAC by channel (cohorts with 12+ months of history): referral 9.4x (CAC per borrower ₹869); partnerships 9.0x (CAC per borrower ₹520); paid_search 2.5x (CAC per borrower ₹2,460); affiliate 1.4x (CAC per borrower ₹4,330); paid_social 1.3x (CAC per borrower ₹3,427); organic n/a (CAC per borrower ₹0). _(source: `outputs/sql_results/05_customer_ltv__ltv_cac_by_channel.csv`)_
- **[F59]** First-loan FPD30 for loans disbursed in the Oct-Nov 2025 festive season vs Jun-Sep 2025: affiliate 4.49% vs 1.71%, paid social 5.42% vs 3.67%, partnerships 2.40% vs 3.25%. _(source: `outputs/sql_results/07_delinquency__festive_season_risk.csv`)_
- **[F60]** Borrowers with autopay pay 86.99% of instalments on time vs 79.89% without (correlation, not causation); 62.82% of borrowers have used autopay. _(source: `outputs/sql_results/10_product_adoption__feature_adoption_impact.csv`)_
- **[F61]** Campaign CMP-202509-AFFNB (Affiliate Network B, Sep 2025): spend ₹5.56 L, 1,258 signups, 4 funded customers, cost per funded customer ₹1.39 L; flagged 'inefficient_spend'. _(source: `outputs/sql_results/13_marketing_cac__campaign_scorecard.csv`)_
- **[F64]** Data quality: DQ score 92.0 on the raw extract and 99.1 on the curated layer; critical failures 22 -> 0; 9 warnings remain (documented open issues); 27 of 27 planted defect types detected. _(source: `outputs/data_quality/dq_summary.json`)_
- **[F65]** Open data-quality issue (warning): marketing_campaigns.budget_inr,spend_inr cross_field:spend_within_budget - 1 rows (spend_inr <= 1.5 * budget_inr). _(source: `outputs/data_quality/dq_results_clean.csv`)_
- **[F66]** Open data-quality issue (warning): customers.city not_null - 974 rows (nulls in a non-nullable column). _(source: `outputs/data_quality/dq_results_clean.csv`)_
- **[F67]** Open data-quality issue (warning): customers.age not_null - 65 rows (nulls in a non-nullable column). _(source: `outputs/data_quality/dq_results_clean.csv`)_
