# Event taxonomy & tracking plan (Mixpanel-style)

_Vittora Credit (fictional) - synthetic data._ This is the tracking plan the product-event stream
(`core.product_events`) follows. It is written the way a product-analytics team publishes it for engineers:
one row per event, when it fires, who emits it, and the properties it must carry.

## Conventions

| Rule | Detail |
|---|---|
| Naming | `object_action` in snake_case, past tense for completed actions (`kyc_completed`, `payment_made`) |
| Identity | `user_id` = `customer_id` from signup onward (Mixpanel `distinct_id`); pre-signup anonymous events are out of scope |
| Dedup key | `event_id` (Mixpanel `$insert_id`) - SDK retries reuse it, the ETL de-duplicates on it |
| Time | `event_ts` in IST, device time for client events, server time for server events |
| Source of truth | Money and decisions are tracked **server-side** (`platform = server`) so ad-blockers and app bugs cannot lose them; UX events are client-side |
| Sessions | `session_id` from the SDK (30-minute inactivity); re-derived in SQL for validation (`10_product_adoption__sessionization_last_month`) |
| Properties | JSON in `properties`; the ETL flattens the governed keys into `prop_*` columns |
| Versioning | `app_version` on every mobile event - essential for diagnosing instrumentation regressions |

## Events

| # | Event | Fires when | Emitted by | Required properties | Funnel / metric use |
|---|---|---|---|---|---|
| 1 | `signup` | Account created (OTP verified) | client | `channel`, `campaign_id`, `city_tier` | Acquisition, cohorts |
| 2 | `login` | App/web session starts for a returning user | client | `method` (otp / biometric) | MAU, DAU, stickiness, retention |
| 3 | `kyc_started` | First KYC screen submitted | client | `variant` (experiment arm or `none`) | Onboarding funnel step 2 |
| 4 | `kyc_completed` | KYC vendor confirms verification | client (UI confirmation) | `kyc_method`, `variant` | Onboarding funnel step 3, EXP-ONB primary metric (cross-checked with backend) |
| 5 | `loan_application_started` | Product selected and form opened | client | `product_id`, `is_repeat` | Lending funnel |
| 6 | `loan_application_submitted` | Application sent to underwriting | client | `product_id`, `amount`, `tenure_months` | Lending funnel, demand |
| 7 | `loan_approved` | Underwriting approves (incl. counter-offers) | server | `product_id`, `amount`, `risk_band` | Approval rate |
| 8 | `loan_rejected` | Underwriting rejects | server | `product_id`, `reason` | Rejection-reason mix, fraud monitoring |
| 9 | `loan_disbursed` | Money credited to the borrower | server | `product_id`, `amount`, `loan_sequence` | Disbursal rate, volume |
| 10 | `payment_made` | EMI payment succeeds | server | `amount`, `method`, `on_time` | Repayment behaviour |
| 11 | `repeat_loan` | Disbursal of a borrower's 2nd+ loan | server | `product_id`, `loan_sequence` | Repeat borrowing |
| 12 | `support_contact` | Ticket created | client (in-app chat) or server | `category`, `channel` | Support load, friction signals |
| 13 | `credit_score_viewed` | Credit-score widget opened | client | `source` | Feature adoption |
| 14 | `emi_calculator_used` | EMI calculator run before applying | client | `product_id` | Feature adoption, intent |
| 15 | `autopay_enabled` | NACH / UPI-Autopay mandate registered | client | `mandate_type` | Autopay adoption (EXP-RPY primary metric) |
| 16 | `referral_shared` | Referral link shared | client | `share_channel` | Referral programme |

## Funnels built on this taxonomy

| Funnel | Steps | Conversion window |
|---|---|---|
| Onboarding | `signup` -> `kyc_started` -> `kyc_completed` -> `loan_application_started` -> `loan_application_submitted` -> `loan_approved` -> `loan_disbursed` | 7 days to KYC, 14 days to application, 30 days to cash |
| Repayment | `loan_disbursed` -> `autopay_enabled` -> `payment_made` (on_time = true) | first EMI |
| Repeat | `loan_disbursed` (seq n) -> loan closure -> `repeat_loan` (seq n+1) | 90 days after closure |

## Instrumentation health checks (automated)

| Check | Where | What it caught |
|---|---|---|
| Tracked `kyc_completed` vs backend KYC completions per day | `data_quality/reconciliations.py`, `sql/analytics/15_data_reconciliation.sql` | Android 5.2.0 (12-16 May 2025) shipped without the `kyc_completed` call: only 52.5% of KYC completions by users on that build were tracked while backend KYC was normal |
| Duplicate `event_id` | contract `primary_key` | SDK retry duplicates |
| Unknown `user_id` | contract FK to customers | QA test accounts leaking into production analytics |
| Platform value set | contract `accepted_values` | Old SDK sending `Android` / `iOS` casing |
| Future timestamps | contract `future_date` | Device clocks set ahead |

**Lesson encoded in the plan:** any metric that drives a decision (KYC completion in EXP-ONB) is computed
from the backend table and only *cross-checked* against client events - so the May 2025 tracking bug
changed a dashboard line, not a business decision.
