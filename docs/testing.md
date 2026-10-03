# Testing

_Synthetic data._ Run everything with:

```bash
python -m pytest -q            # ~25 s on a laptop, includes a full pipeline run on 6,000 customers
```

## Strategy

| Layer | What is tested | How |
|---|---|---|
| Data generation | the simulator is internally consistent before any defect is injected | PK uniqueness, referential integrity, lifecycle ordering (signup ≤ KYC ≤ application ≤ decision), amortisation repays principal, ledger = schedule, determinism by seed, defect answer key |
| Data-quality checks | each check fires on exactly the bad rows | tiny hand-built frames per check: not-null, duplicates, accepted values, ranges, patterns, date order, future dates, foreign keys, schema/type drift, cross-field, conditional, robust outliers, gate behaviour |
| ETL rules | each repair fixes only its target defect and is logged | inject defects into clean data, round-trip through CSV-style strings, assert outcomes (dedupe, channel attribution, UTC→IST, basis points, type/schema drift, quarantine, NTC derivation) |
| Statistics | experiment maths matches textbook values | z-test and CI vs manual formulas, sample size for p=0.5 / +5 pp ≈ 1,565 per arm, MDE/power round-trip, SRM detection, Holm adjustment, guardrail logic, Bayesian sanity |
| Anomaly detection | finds planted spikes, stays quiet on noise, ignores tiny denominators | simulated daily series with Poisson/binomial noise |
| AI safety | no unverified number or unsafe SQL gets through | number extraction (₹, lakh/crore, %, pp, x; dates/ids/versions ignored), grounding pass/fail cases, rounding rule, missing/unknown citations, Q&A scaling, SQL guard blocks DDL/DML, multi-statements, file functions, unknown tables |
| Contracts | DDL, contracts and KPI registry cannot drift apart | warehouse column names/types == contract; every FK targets a PK; every registered KPI exists in the KPI SQL |
| End to end | the real pipeline works and the outputs make business sense | `generate → … → ai_summary → dashboard` on 6,000 customers in a temp dir: success, zero critical DQ issues, 100% planted-defect recall, warehouse = processed layer, all SQL ran, monotonic funnel, month-0 retention >= 99% and never exceeded later, revenue reconciles across marts, PAR ≤ outstanding, KPI ranges, experiment CIs contain estimates, AI summary grounded, Power BI extract written, dashboard embeds the run's data |

## Results (latest run)

78 tests, all passing (Python 3.8, Windows 11; `pytest -q` in about 40 s):

| File | Tests | Focus |
|---|---:|---|
| `test_ai_grounding.py` | 18 | number extraction, grounding pass/fail, Q&A scaling, SQL guard (7 attack patterns) |
| `test_generator.py` | 15 | keys, integrity, lifecycle order, amortisation, ledger = schedule, determinism, defect key |
| `test_pipeline_e2e.py` | 13 | full pipeline on 6,000 customers + business invariants |
| `test_data_quality.py` | 9 | every check type and the publish gate |
| `test_transform.py` | 8 | ETL repair rules, quarantine, NTC derivation |
| `test_experiment_stats.py` | 7 | z-test, CI, sample size, SRM, Holm, guardrails, Bayesian |
| `test_contracts.py` | 4 | DDL vs contract, FK targets, KPI registry vs KPI SQL |
| `test_anomaly.py` | 3 | planted spike found, quiet on noise, small denominators ignored |

Bugs the suite caught during development (all fixed): an empty anomaly file crashing the Power BI export at small scale; an over-strict retention assumption (a quarantined event can legitimately remove a customer's only signup-month activity); a recommendation template containing numbers that no fact supported (rejected by the grounding checker); and a math-domain error in the MDE search for high baseline rates.

## Conventions

* Tests never touch the repository's `data/` or `outputs/` - the end-to-end fixture runs in a temporary directory.
* The end-to-end fixture runs the AI step in offline (deterministic) mode, so CI needs no API key and costs nothing.
* A failing data-quality gate is a failing test: `test_curated_layer_has_no_critical_issues`.
* CI (`.github/workflows/weekly_pipeline.yml`) runs the suite on every push and pull request, and before every
  scheduled pipeline run.
