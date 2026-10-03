# Technical documentation

_Vittora Credit is fictional; every record in this repository is synthetic._

Contents: [1 Repository map](#1-repository-map) - [2 Running it](#2-running-it) - [3 Synthetic data design](#3-synthetic-data-design) -
[4 Data quality framework](#4-data-quality-framework) - [5 ETL rules](#5-etl-rules) - [6 Warehouse & SQL conventions](#6-warehouse--sql-conventions) -
[7 KPI layer](#7-kpi-layer) - [8 Anomaly detection](#8-anomaly-detection) - [9 Experimentation](#9-experimentation) -
[10 Segmentation](#10-segmentation) - [11 AI analyst](#11-ai-analyst) - [12 Automation & operations](#12-automation--operations) -
[13 Known limitations](#13-known-limitations)

## 1. Repository map

| Folder | Purpose | Key entry points |
|---|---|---|
| `data/` | raw / processed / quarantine / warehouse layers (generated, git-ignored) + committed `sample/` | `data/raw/_injected_issues.json` (DQ answer key) |
| `python/` | generator, KPI layer, analytics modules, charts, exports | `generate_data.py`, `kpis.py`, `experiment_analysis.py`, `segmentation.py`, `anomaly_detection.py`, `visualize.py` |
| `etl/` | extract (lineage), transform (repair/quarantine/log), load (warehouse + marts) | `extract.py`, `transform.py`, `load.py` |
| `data_quality/` | contracts, checks, reconciliations, gate, HTML/Markdown report | `contracts.yaml`, `runner.py`, `report.py` |
| `sql/` | DDL, marts, 15 analytics files (50 named queries), KPI SQL | `ddl/`, `marts/`, `analytics/`, `kpis/` |
| `ai_analyst/` | fact sheet, Claude client, grounding checker, summariser, Q&A, SQL guard | `cli.py` |
| `powerbi/` | DAX, Power Query, theme, data model, page spec | `dashboard_spec.md` |
| `notebooks/` | generated, executed analysis notebooks | `build_notebooks.py` |
| `tests/` | unit + end-to-end tests | `pytest -q` |
| `docs/` | requirements, architecture, dictionary, case study | this file |
| `outputs/` | sample outputs of the latest run (committed) | `ai/executive_summary.md`, `data_quality/data_quality_report.html` |

## 2. Running it

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt          # Windows (use .venv/bin/pip on macOS/Linux)
.venv\Scripts\python pipeline.py --generate --offline-ai
```

| Command | What it does |
|---|---|
| `python pipeline.py --generate` | full run; uses Claude for the summary if credentials resolve, otherwise the deterministic summariser |
| `python pipeline.py --steps kpis,anomalies,ai_summary` | re-run part of the pipeline against the existing warehouse |
| `python pipeline.py --generate --n-customers 5000 --base-dir C:\tmp\fpa` | small run in a scratch folder |
| `python -m ai_analyst.cli ask "Which channel has the best LTV:CAC?"` | grounded Q&A (needs `ANTHROPIC_API_KEY` or `ant auth login`; `--offline` answers KPI questions without an LLM) |
| `python -m pytest -q` | unit tests + small end-to-end pipeline |
| `python notebooks/build_notebooks.py` | regenerate and execute the notebooks (needs `requirements-notebooks.txt`) |

Environment variables: `FPA_N_CUSTOMERS`, `FPA_SEED`, `FPA_BASE_DIR`, `FPA_OFFLINE_AI`, `AI_ANALYST_MODEL`
(default `claude-opus-5-5`), `ANTHROPIC_API_KEY`.

Runtime on a laptop (Python 3.8, 1.25M rows): generate ~25 s, extract + validate ~10 s, transform ~11 s,
load + marts ~20 s, 50 SQL queries ~2 s, everything else < 30 s.

## 3. Synthetic data design

The generator (`python/generate_data.py`) simulates each customer's lifecycle with vectorised NumPy/pandas:
daily signups (growth trend x weekday seasonality x festive multipliers) -> channel / platform / demographics ->
KYC (probabilities by channel, platform, tier, employment, NTC) -> applications (product choice by employment,
amounts tied to income, tenure menus) -> underwriting (log-odds risk score; per-product cut-offs) -> disbursal
-> amortised EMI schedules -> payment behaviour (on-time / late / partial / default / foreclosure) -> repeat
loans in successive "generations" after good closures -> ledger entries, support tickets, Mixpanel-style events.

**Planted ground truths** (what the analytics should rediscover - and does):

| Truth | Mechanism in the generator | Where it is rediscovered |
|---|---|---|
| KYC is the biggest leak; worse on web, tier-3, gig workers, NTC | multiplicative KYC probabilities | `02_funnel_dropoff__kyc_dropoff_by_segment` |
| Paid social / affiliate: cheap signups, weak conversion, higher risk | channel log-odds and intent multipliers | `01__funnel_by_channel`, `05__ltv_cac_by_channel`, `07__risk_by_segment` |
| Referral / partnerships: best unit economics | lower risk, higher KYC and intent | `05__ltv_cac_by_channel` |
| Onboarding redesign lifts 7-day KYC (true effect ~+5.6 pp, observed +3.3 pp) | +1.8 pp KYC start, +5 pp completion for treated users; rolled out 2 Mar 2026 | `experiment_analysis.py`, `02__kyc_weekly_trend` |
| Autopay nudge raises autopay take-up (+13 pp) | treatment shifts mandate probability | EXP-RPY readout |
| Fee transparency has no effect | no effect planted | EXP-PRC readout (underpowered, inconclusive) |
| Festive 2025 cohorts default more | 1.8x PD for paid social / affiliate loans disbursed Oct-Nov 2025 | `07__festive_season_risk`, vintage curves, credit losses in May-Jun 2026 |
| 14-15 Aug 2025 payment-gateway outage | auto-debits due those days fail (gateway_timeout) and are paid 2-5 days late; tickets triple | anomaly episodes |
| 12-15 May 2025 Android 5.2.0 tracking bug | `kyc_completed` not emitted by that build; 30% of users lag one version for 2 weeks | anomaly episode + `15__kyc_tracking_by_app_version` + DQ reconciliation |
| 8-21 Sep 2025 affiliate fraud ring | 1,200 synthetic identities (night-time signups, Android, NTC-heavy) via "Affiliate Network B"; rejected as kyc_data_mismatch / fraud_suspected | signups anomaly, approval-rate dip, rejection mix, campaign scorecard |
| Autopay users repay better and borrow again | on-time probability and repeat probability conditional on autopay | `10__feature_adoption_impact`, `09__repeat_drivers` |
| P07 credit line launched Apr 2025 | product unavailable before launch | `10__credit_line_launch` |

**Defects injected into the raw layer** (27 types, recorded in `data/raw/_injected_issues.json`): CRM duplicate
rows, channel casing/spacing variants, missing city and income, impossible ages and bureau scores, income keyed
x100, KYC timestamps written in UTC (precede KYC start), duplicate applications, negative amounts, decision
before submission, APR in basis points, orphan loans and transactions, future payment dates, payment amounts
x100, duplicate webhook deliveries, sign errors, SDK retry duplicates, QA test accounts, platform casing, future
device clocks, a new upstream column (`agent_id`), a numeric column exported as text with `N/A`, swapped
campaign dates and a campaign billed at 3.4x budget.

## 4. Data quality framework

**Contracts as code.** `data_quality/contracts.yaml` declares, per table: columns, types, nullability,
accepted values, ranges, regex patterns, foreign keys, outlier columns, date-order pairs, cross-field rules,
conditional rules, freshness column and severity. The same file drives the checks, the ETL type casting, the
data dictionary and a test asserting the DDL matches.

| Dimension | Checks |
|---|---|
| Schema | missing columns (critical), unexpected columns (warning), dtype drift incl. numeric-as-text, drift vs previous run's fingerprint |
| Completeness | not-null (severity per column) |
| Uniqueness | primary keys, composite keys (`loan_id + installment_number`, `experiment_id + customer_id`); exact-duplicate counts reported |
| Validity | accepted values, numeric ranges, regex patterns |
| Timeliness | date ordering, timestamps after the extract date, freshness vs extract date |
| Integrity | foreign keys across all 11 tables |
| Plausibility | robust z-score outliers on log scale, cross-field rules (net = principal - fee, current DPD <= max DPD, paid <= due, ...) |
| Reconciliation | ledger vs repayment schedule, disbursement ledger vs loans, loans vs disbursed applications, tracked vs backend KYC, channel vs campaign tag |
| Volume | minimum rows; > 50% change vs previous run |

**Severity and the gate.** Every check is `critical` or `warning`. The raw layer is profiled (never blocks);
the curated layer is a gate: any critical failure stops the pipeline before anything is published. Warnings are
published and carried into report caveats (e.g. missing city on 1.2% of customers).

**Measuring the framework itself.** The generator's defect manifest is an answer key; `injected_issue_recall.csv`
shows which check caught each planted defect type. Current recall: 27 of 27.

**DQ score** = weighted share of passing checks (critical weight 3, warning 1).

## 5. ETL rules

Principles: never silently drop data (quarantine with a reason), never invent data (repair only when the root
cause is known and reversible), keep financial facts even when lineage is broken, log every rule.

| Table | Rule | Action |
|---|---|---|
| all | columns not in contract | dropped + logged as schema drift (contract change request) |
| all | exact duplicates, then duplicate primary keys | drop (keep first) |
| all | contract typing; text tokens `N/A`, `NULL` in numeric columns | cast; tokens -> null (logged) |
| all | orphan foreign keys | quarantine, or null the reference and keep the row (`loans.application_id`, `transactions.repayment_id`, `support_tickets.loan_id`) |
| customers | channel casing/spacing | standardise; then derive channel from the campaign tag when they disagree (campaign = attribution source of truth) |
| customers | bureau score outside 300-900 | null, **after** deriving `is_ntc` so bad data is not mistaken for new-to-credit |
| customers | age outside 18-75 | null |
| customers | income > 15L/month and /100 plausible | divide by 100 |
| customers | `kyc_completed_ts` earlier than `kyc_started_ts` by <= 5h30m | +05:30 (UTC written into an IST column) |
| applications | negative requested amount | absolute value |
| applications | decision before submission | decision timestamp nulled (decision kept) |
| loans | APR > 100 | divide by 100 (basis points) |
| repayments | paid date exactly a year in the future | -365 days; otherwise null |
| repayments | amount paid 100x the instalment | divide by 100 |
| transactions | negative amount | absolute value |
| product_events | `TEST-*` users, future timestamps | quarantine |
| product_events | platform casing | standardise; flatten JSON properties into `prop_*` columns |
| support_tickets | resolved before created | `resolved_ts` nulled |
| marketing_campaigns | start after end | swap; spend > 150% of budget flagged to Finance (not changed) |

## 6. Warehouse & SQL conventions

* **DuckDB** with a `core` schema (PK/FK/UNIQUE/CHECK constraints enforced at load) and a `marts` schema rebuilt
  each run. Full refresh keeps the run idempotent; the production design would partition `product_events` by
  month and MERGE on primary keys (see `sql/ddl/02_postgres_indexes.sql` for the PostgreSQL index plan).
* **One definition, one place.** Business logic lives in eight marts (funnel, loan performance, user activity,
  daily metrics, portfolio snapshots, customer 360, revenue ledger, calendar); analytics queries read marts.
* **Fair comparisons.** Time-bounded conversion (7-day KYC, 14-day application, 30-day disbursal) plus
  maturity flags remove right-censoring bias; vintage curves only count loans old enough to be observed.
* **Point-in-time correctness.** Month-end PAR/NPA are rebuilt from instalment history - a payment made after the
  month end does not cure that month's DPD.
* **Style.** CTEs named for what they hold; aggregate before joining (no fan-out); window functions instead of
  self-joins (LAG/LEAD, running SUM, NTILE, RANK, FIRST_VALUE, rolling AVG/STDDEV); GROUPING SETS for multi-cut
  segment tables; `CASE` inside aggregates instead of dialect-specific `FILTER`; `percentile_cont ... WITHIN GROUP`.
* **Portability.** PostgreSQL-flavoured; DuckDB-specific pieces are `date_diff`, `strftime`, `range()` and
  `MEDIAN` (one-line replacements on Postgres / Snowflake / BigQuery).
* **Proof of execution.** `python/run_sql_analytics.py` executes every `-- @query:` block on each run and writes
  results plus runtime to `outputs/sql_results/`.

## 7. KPI layer

28 KPIs are registered in `python/kpi_definitions.py` (id, definition, formula, unit, direction, target, lag
note). `sql/kpis/kpi_monthly.sql` computes them; `python/kpis.py` adds prior-month and year-ago deltas, a
z-score against the trailing six months, target status and an assessment (improved / worsened / stable, with a
"notable" flag at >= 2 pp or >= 10% or |z| >= 2). Cohort KPIs that need a maturity window (30-day conversion,
FPD30) automatically report the latest mature month and say so.

## 8. Anomaly detection

Daily metrics: signups, applications, approval rate, disbursals, payment-failure rate, tickets, tracked/backend
KYC ratio, DAU. Expected value = median of the same weekday over the previous 8 weeks (current day excluded,
campaign days excluded from baselines); noise = max(1.4826 x MAD, 5% of expected, Poisson or binomial standard
error, metric floor). A day is flagged when |robust z| >= 4 and the deviation >= 25%; rates are scored only with
>= 30 trials. Consecutive flags merge into episodes; single-day blips are kept in `daily_anomalies.csv` but only
escalated if |z| >= 6. Each episode gets driver attribution (share of the excess explained by each channel,
platform, rejection reason, failure reason or ticket category) and a business-calendar label (known campaign,
release, launch) - so a Diwali spike is "expected" while a payment outage is "investigate".

## 9. Experimentation

`python/experiment_analysis.py` runs for each registered experiment: SRM chi-square (alarm at p < 0.001),
two-proportion z-test (pooled SE for the test, unpooled for the Wald CI), relative uplift with a delta-method CI
on the log ratio, Beta-Binomial posterior (P(treatment > control), expected loss), required sample size for the
pre-registered MDE, achieved power and MDE at the realised n. Guardrails are evaluated as non-inferiority with
explicit margins (pass / inconclusive / breach). The onboarding test also gets a weekly novelty check,
Holm-corrected heterogeneity by platform and city tier, and an impact estimate in incremental verified
customers, first loans and net revenue. Decision rule: ship if the primary metric improves significantly and no
guardrail is breached; inconclusive guardrails become post-launch monitoring items.

## 10. Segmentation

Two lenses on `marts.customer_360`:
1. **Rule-based business segments** for all customers (High-risk, New, High-value repeat, High-engagement,
   Onboarding drop-off, Inactive, Verified-never-borrowed, Core borrowers) - mutually exclusive, priority-ordered,
   each with a CRM action.
2. **K-Means** on borrowers: 11 behavioural/financial features (log-transformed counts and money, signed log for
   net revenue, on-time rate, worst DPD, logins, tenure, products, autopay, tickets), standardised; k chosen from
   3-8 by silhouette with an interpretability constraint (4-6 clusters unless that costs > 20% of the best
   silhouette); clusters named from centroid profiles.

## 11. AI analyst

* **Fact sheet** (`ai_analyst/fact_sheet.py`): 73 numbered facts with pre-formatted numbers and sources (KPI
  snapshot, anomaly episodes, experiment results, segments, DQ, selected SQL outputs).
* **Summary** (`summarizer.py`): Claude (`claude-opus-5-5`, adaptive thinking, effort `high`, structured JSON output,
  server-side refusal fallback) writes headline / highlights / KPI movements / anomalies / experiments / risks /
  recommendations with owners / data caveats, citing fact ids per item.
* **Grounding checker** (`grounding.py`): extracts every number (INR, lakh/crore, %, pp, x) after stripping
  dates, ids and versions, and requires it to appear - exactly or rounded - in a fact the item cites. Failures
  trigger up to two targeted retries; anything still unverified is removed and the removal is noted in the report.
* **Q&A** (`qa.py`): tool use with `run_sql` + `get_metric_definitions`; SQL passes the guard (`sql_guard.py`:
  SELECT-only, single statement, allow-listed tables, no file functions, row cap) and runs on a read-only DuckDB
  connection with external access disabled; numbers in the final answer must match the returned rows.
* **No API key?** The deterministic summariser produces the same structure from the same facts and passes the
  same checker, so CI and offline runs always ship a summary.
* **Privacy.** The model receives aggregates only - never customer-level rows.

## 12. Automation & operations

| Concern | Implementation |
|---|---|
| Orchestration | `pipeline.py` - 16 named steps, `--steps` for partial runs, blocking vs non-blocking steps |
| Scheduling | GitHub Actions (`.github/workflows/weekly_pipeline.yml`, Mondays 07:00 IST + manual) or Windows Task Scheduler (`scripts/run_weekly.ps1`) |
| Observability | `outputs/run_logs/latest_run.json` (status, duration, info per step) + log file; GitHub job summary shows the executive summary and DQ summary |
| Failure handling | DQ gate failure or blocking-step failure -> exit 1, nothing published downstream |
| Artifacts | outputs, charts, Power BI extract uploaded per run (30-day retention) |
| Runbook: gate failed | open `outputs/data_quality/data_quality_report.html` -> "Open issues on the curated layer" -> fix the source or add an ETL rule -> re-run |
| Runbook: anomaly flagged | check `known_context`; if "investigate", use the driver attribution and the dashboard's drill-through; confirm whether it is a data incident (reconciliations) before escalating as a business incident |

## 13. Known limitations

* Synthetic data encodes the patterns it was designed with; real data would be noisier and confounded.
* Revenue is cash-basis; no provisioning (ECL), cost of funds or opex - "net revenue" is not profit.
* Correlations (autopay vs on-time payment) are observational; only the A/B tests support causal claims.
* LTV is realised value to date for cohorts >= 12 months old - not a lifetime projection.
* Full-refresh loads are fine at this size; production needs incremental loads and partitioning.
