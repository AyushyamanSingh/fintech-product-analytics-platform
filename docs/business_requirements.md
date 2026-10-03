# Business requirements

_Vittora Credit is a fictional company; all data is synthetic._

## 1. Context

Vittora Credit is a digital lender (RBI-registered NBFC in the scenario) serving salaried employees, gig workers,
small-business owners and students across tier-1 to tier-3 Indian cities through Android, iOS and web apps.
It runs a 7-product portfolio:

| ID | Product | Ticket (INR) | Tenure | Revenue model |
|---|---|---|---|---|
| P01 | Instant Personal Loan | 10k - 2L | 3-24 m | interest + fees |
| P02 | Salary Advance | 5k - 50k | 1-3 m | interest + fees |
| P03 | Pay Later (BNPL) | 1k - 20k | 1-6 m | interest + fees |
| P04 | Consumer Durable Loan | 15k - 1.5L | 6-18 m | interest + fees |
| P05 | Business Micro Loan | 50k - 5L | 12-36 m | interest + fees |
| P06 | P2P Marketplace Loan | 25k - 3L | 6-24 m | platform fee only (lenders earn the interest) |
| P07 | Flexi Credit Line (launched Apr 2025) | 10k - 1L | 3-12 m | interest + fees |

Growth has been funded by paid acquisition and festive-season campaigns. Leadership believes growth is healthy
but has no single, trusted view of the funnel, credit quality, unit economics and experiment results: each team
reports from its own spreadsheet with its own definitions.

## 2. Problem statement

> We acquire ~4,000 customers a month, but fewer than one in five ever takes a loan, we do not know which
> channels pay back, credit quality shifts after every campaign, and decisions wait on manually assembled
> reports whose numbers do not agree.

## 3. Stakeholders and their questions

| Stakeholder | Decisions they make | Questions this platform must answer |
|---|---|---|
| CEO / leadership | Where to invest, what to fix first | Is the business healthy this week? What changed and why? |
| CFO / Finance | Budgets, provisioning, pricing | Revenue by product and component, credit losses, LTV:CAC, AUM |
| Head of Product / PMs | Roadmap, experiments | Where does the funnel leak, for whom? Did the experiment win? Which features matter? |
| Head of Growth / Marketing | Channel budgets, campaigns | CAC and cost per funded customer by channel and campaign; cohort quality |
| Head of Risk / Collections | Cut-offs, collections strategy | PAR30, NPA, FPD30, vintages, risky segments, fraud spikes |
| Customer Support | Staffing, process fixes | Ticket drivers, CSAT, incident spikes |
| Analytics Engineering | Data trust | Is the data complete, consistent and fresh? What was repaired? |

## 4. Objectives and success criteria

| # | Objective | Success criterion |
|---|---|---|
| O1 | One governed set of KPI definitions | 28 KPIs defined once (`python/kpi_definitions.py`) and reused by SQL, Power BI and the AI layer |
| O2 | Trustworthy data | Automated contract checks on every run; publishing blocked on any critical failure; 100% of planted defect types detected |
| O3 | Funnel and cohort visibility | Stage-level conversion and drop-off by channel, platform, city tier, employment and cohort |
| O4 | Unit economics by channel | LTV:CAC and cost per funded customer per channel on mature cohorts |
| O5 | Portfolio risk monitoring | Month-end PAR30 / NPA, FPD30, vintage curves, write-offs |
| O6 | Experimentation discipline | Pre-registered design, SRM check, CIs, guardrails, written readout for every test |
| O7 | Early warning | Daily anomaly detection with drivers and business-calendar context |
| O8 | Faster reporting | Weekly executive summary generated automatically with every number traceable to a source |
| O9 | Reproducibility | One command rebuilds data, warehouse, analyses, charts and summary; CI runs tests and a scheduled pipeline |

## 5. Functional requirements

| ID | Requirement | Delivered by |
|---|---|---|
| FR1 | Ingest 11 source tables (CRM, LOS, LMS, ledger, events, helpdesk, experimentation, marketing) | `etl/extract.py` |
| FR2 | Validate schema, completeness, uniqueness, validity, timeliness, integrity, plausibility | `data_quality/` |
| FR3 | Repair known defect classes, quarantine the rest, log every rule | `etl/transform.py` |
| FR4 | Load a warehouse with enforced keys and analytics marts | `etl/load.py`, `sql/ddl`, `sql/marts` |
| FR5 | Answer the analytics questions in section 3 with reusable SQL | `sql/analytics` (15 files, 50 queries) |
| FR6 | Compute KPIs with targets, deltas and z-scores | `python/kpis.py` |
| FR7 | Detect anomalies and attribute drivers | `python/anomaly_detection.py` |
| FR8 | Analyse experiments with design, inference and guardrails | `python/experiment_analysis.py` |
| FR9 | Segment customers (rules + clustering) with actions | `python/segmentation.py` |
| FR10 | Power BI model, measures and 8-page report spec | `powerbi/` |
| FR11 | AI analyst: weekly summary + natural-language Q&A, no invented numbers | `ai_analyst/` |
| FR12 | Orchestrate end to end, schedule weekly, alert on failure | `pipeline.py`, `.github/workflows`, `scripts/run_weekly.ps1` |

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | Full pipeline on ~1.25M rows in under 5 minutes on a laptop; every analytics query under 1 s |
| Reliability | Idempotent full refresh; non-zero exit on failure; run manifest per execution |
| Security & privacy | No real personal data; synthetic identifiers; the AI layer gets aggregates only, and model SQL runs read-only with external access disabled |
| Auditability | Lineage (file hash, row counts), cleaning log, quarantine files, cited facts in AI output |
| Maintainability | Contracts as code, tests in CI, documentation generated from code where possible |
| Fairness | Gender and other protected attributes are not collected or used; employment type and NTC status are monitored for disparate approval/conversion |

## 7. KPI targets (FY2026-27 plan)

| KPI | Target | Rationale |
|---|---|---|
| KYC completion (7-day) | >= 62% | Industry-typical for app-first lenders after a trust-focused onboarding |
| Activation (first loan within 30 days of signup) | >= 15% | Needed for the paid-acquisition model to pay back |
| Approval rate | >= 50% | Below this, acquisition spend is wasted on ineligible traffic |
| Offer acceptance | >= 85% | Pricing / offer UX health |
| Autopay adoption | >= 60% | Strongest lever on collections |
| PAR30 | <= 6% | Risk appetite for unsecured lending |
| NPA (90+ DPD) | <= 3.5% | Board risk appetite |
| FPD30 | <= 3% | Early-warning on underwriting / fraud |
| Collection efficiency | >= 95% | Treasury planning |
| Payment failure rate | <= 8% | Payments operations |
| CSAT | >= 4.0 | Support quality |
| Cost per new borrower | <= INR 2,500 | Unit economics guard-rail |

## 8. Scope and assumptions

* In scope: analytics, data quality, experimentation, reporting automation. Out of scope: underwriting model
  development, collections operations, real-time streaming.
* Data covers 1 Jul 2024 - 30 Jun 2026 (24 months); extract date 30 Jun 2026.
* Revenue is recognised on a cash basis (interest when collected, fees when charged); credit losses at write-off
  (180 DPD). NPA follows the RBI 90-DPD definition.
* All monetary values in INR; L = lakh (1e5), Cr = crore (1e7).
