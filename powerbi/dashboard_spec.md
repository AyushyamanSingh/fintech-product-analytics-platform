# Executive dashboard - build specification

_Vittora Credit (fictional) - synthetic data._ This spec is what a BI developer needs to build the
report in Power BI Desktop without further questions: page purpose, layout, every visual with its fields
and measures, interactions and formatting. Measures live in [`dax/measures.dax`](dax/measures.dax), the
model in [`model/data_model.md`](model/data_model.md), the theme in [`theme/vittora_theme.json`](theme/vittora_theme.json).

## Global standards

| Item | Standard |
|---|---|
| Canvas | 1280 x 720, 12-column grid, 16 px gutters; page background `#f9f9f7`, visual surface `#fcfcfb` |
| Header band (every page) | Page title (left), `[Data As Of]` text (right), "SYNTHETIC DATA" badge, page navigator buttons |
| Global slicers (synced) | Date range (`dim_date[date_day]`, relative "last N months"), Product (`dim_product[product_name]`), Channel (`dim_channel[channel_label]`) - one slicer row above the visuals it scopes |
| Colour | Theme palette in fixed order; status colours (green/amber/red) only for target status, always with an icon or label - never colour alone |
| Numbers | Rates 1 decimal (`0.0%`), money `₹#,0` or the L/Cr short format, counts `#,0`; deltas as "+1.2 pp" for rates and "+4.5%" for volumes |
| Charts | No dual axes (use small multiples), no pies for > 3 parts, line charts for trends, bars for comparison, matrix heatmaps for cohorts |
| Accessibility | Alt text on every visual, logical tab order, data labels where colour carries meaning, min font 9 pt |
| Performance | Every visual < 1.5 s in Performance Analyzer; no visual over 30 data points without aggregation |
| Tooltips | Report-page tooltip "KPI context" (value, prior period, YoY, target, definition) reused on all KPI cards |

---

## Page 1 - Executive Overview

**Audience / question:** CEO, CFO - "Is the business healthy this month and what needs attention?"

| Zone (cols x rows) | Visual | Fields / measures | Notes |
|---|---|---|---|
| Row 1 (6 cards) | KPI cards with sparkline | `[Loans Disbursed]`, `[Disbursed Amount]`, `[Gross Revenue]`, `[Net Revenue]`, `[PAR30 %]`, `[MAU]` | Reference label: MoM delta; status icon vs target where a target exists |
| Row 2 left (8x3) | Line chart | Axis `dim_date[month_start]`; values `[Gross Revenue]`, `[Net Revenue]` | Same unit, one axis; annotate festive campaign |
| Row 2 right (4x3) | Multi-row card "Targets" | `[KYC Completion 7d %]`, `[Approval Rate %]`, `[Collection Efficiency %]`, `[Payment Failure Rate %]`, `[CSAT]` | Conditional icons from target table |
| Row 3 left (6x3) | Clustered bar | `dim_product[product_name]` x `[Gross Revenue]`, `[Revenue Mix %]` in tooltip | Sorted descending |
| Row 3 right (6x3) | Text box / smart narrative | Contents of `outputs/ai/executive_summary.md` headline + top 3 highlights | Each line keeps its [F..] citation |

Drill-through: product bar -> Page 5 (Loan Portfolio) filtered to the product.

## Page 2 - Acquisition Funnel

**Audience / question:** Growth, Marketing - "Where do we lose new customers and which channels are worth paying for?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 cards | `[New Customers]`, `[KYC Completion 7d %]` (+ vs target pp), `[Signup to Loan 30d %]`, `[Cost per Funded Customer]` |
| Row 2 left (7x4) | Funnel (bar chart on disconnected `'Funnel Stage'`) | Axis `'Funnel Stage'[Stage]`, values `[Funnel Customers]`; labels `[Funnel % of Signups]`; tooltip `[Funnel Step Conversion %]` |
| Row 2 right (5x4) | Matrix | Rows `fct_funnel[signup_platform]`, `[city_tier]`, `[employment_type]` (field parameter); values `[KYC Completion 7d %]` with data bars | Highlights web / tier-3 / gig gaps |
| Row 3 left (6x3) | Clustered bar | `dim_channel[channel_label]` x `[Signup to Loan 30d %]` |
| Row 3 right (6x3) | Table | `fct_cac_monthly`: channel, `[Marketing Spend]`, `[Cost per Signup]`, `[Cost per Funded Customer]` | Conditional format: cost per funded > 2x median -> amber icon |

Slicer: cohort month range. Bookmark: "Experiment window" (highlights Jan-Feb 2026 on the weekly KYC line in a hidden panel).

## Page 3 - Product Analytics (Mixpanel-style)

**Audience / question:** Product managers - "How do users move through the app and which features matter?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 cards | `[MAU]`, `[Avg DAU]`, `[Stickiness DAU/MAU %]`, `[Feature Events per Active User]` |
| Row 2 left (8x3) | Line | `dim_date[date_day]` x `[Avg DAU]`; anomaly markers from `fct_anomaly_episodes` (scatter overlay on same axis) |
| Row 2 right (4x3) | Bar | `fct_events_daily[event_name]` x `[Events]` (taxonomy order, see docs/event_taxonomy.md) |
| Row 3 left (6x3) | Stacked column | `dim_date[month_start]` x `[Loans Disbursed]` by `dim_product[product_name]` | Shows P07 launch adoption |
| Row 3 right (6x3) | Table | Feature adoption from `fct_loans`/`dim_customer`: autopay vs non-autopay on-time rate, repeat rate | Footnote: correlation, not causation |

Drill-through target: "Event detail" (hidden) - `fct_events_daily` by `app_version` for the selected event (used to find the Android 5.2.0 tracking gap).

## Page 4 - Customer Cohorts

**Audience / question:** Product, Growth, Risk - "Do customers stick, and is cohort quality improving?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 (12x4) | Matrix heatmap | Rows `fct_cohort_retention[cohort_month]`, columns `[month_number]` (0-12), values `[Retention %]`; background colour scale single-hue blue (light->dark) |
| Row 2 left (6x3) | Line | Borrower vs non-borrower retention curve (from `03_cohort_retention__retention_curve_by_borrower_status`) |
| Row 2 right (6x3) | Column + table | Cohort quality: KYC 7d %, disbursed 30d %, first-loan FPD30 % by cohort month (festive cohorts flagged) |

## Page 5 - Loan Portfolio

**Audience / question:** CFO, Head of Risk - "How big and how healthy is the book?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 cards | `[Outstanding Principal]`, `[PAR30 %]`, `[NPA %]`, `[FPD30 %]`, `[Write-offs]`, `[Collection Efficiency %]` |
| Row 2 left (6x3) | Line (small multiples by product) | `dim_date[month_start]` x `[PAR30 %]` | One scale per small multiple |
| Row 2 right (6x3) | Stacked bar 100% | `dim_product[product_name]` x outstanding by `fct_loans[dpd_bucket]` (ordinal blue ramp) |
| Row 3 left (7x3) | Line | Vintage curves from `fct_vintage_curves` (MOB x cum. 30+ DPD), Q4 2025 vintage highlighted, others grey |
| Row 3 right (5x3) | Matrix | Risk band x product: `[Approval Rate %]`, `[FPD30 %]`, `[Ever 30+ DPD %]` |

Drill-through: loan list (hidden page) filtered by product / DPD bucket for collections follow-up.

## Page 6 - Revenue & Customer Value

**Audience / question:** CFO, Marketing - "Where does revenue come from and which customers create value?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 cards | `[Gross Revenue]`, `[Gross Revenue MoM %]`, `[Gross Revenue YoY %]`, `[Gross Revenue FYTD]`, `[Net Revenue per Borrower]` |
| Row 2 left (7x3) | Stacked column | `dim_date[month_start]` x `[Interest Income]`, `[Fee Income]` (components) |
| Row 2 right (5x3) | Bar | Channel x `[LTV to CAC]` with constant line at 3.0x |
| Row 3 left (6x3) | Bar | `dim_business_segment[business_segment]` x share of customers vs share of net revenue |
| Row 3 right (6x3) | Table | K-Means clusters (`dim_cluster`): borrowers, avg loans, net revenue, worst DPD, recommended action |

## Page 7 - Experiment Analysis

**Audience / question:** Product, Growth, leadership - "What did we test, what won, and was it safe to ship?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 | Slicer (tiles) | `fct_experiment_results[experiment_id]` |
| Row 1 cards | `[Control Rate]`, `[Treatment Rate]`, `[Uplift (pp)]`, `[Result Label]`, `[Experiment Decision]` (filtered to primary metric) |
| Row 2 left (7x4) | Error-bar chart | Metric (primary, secondary, guardrail) x `[Uplift (pp)]` with error bars `[CI Low (pp)]`-`[CI High (pp)]`; reference line at 0 |
| Row 2 right (5x4) | Table | Guardrails: metric, control, treatment, diff, margin, status icon |
| Row 3 (12x2) | Column | `fct_experiment_weekly_effect`: weekly uplift with CI (novelty check) |

Text box: pre-registered design (MDE, power, sample size) from `outputs/experiments/EXP-ONB-2026-01_readout.md`.

## Page 8 - Data Quality

**Audience / question:** Analytics engineering, data owners - "Can we trust this report today?"

| Zone | Visual | Fields / measures |
|---|---|---|
| Row 1 cards | `[DQ Score (Raw)]`, `[DQ Score (Curated)]`, `[Critical Failures (Curated)]`, `[Warnings (Curated)]`, `[Rows Repaired or Quarantined]` |
| Row 2 left (6x3) | Clustered bar | Table x failed checks, raw vs curated |
| Row 2 right (6x3) | Table | Open curated issues: severity icon, table, check, column, failed rows, details |
| Row 3 (12x3) | Table | Cleaning log (`fct_cleaning_log`): table, rule, action, rows |

Rule: if `[Critical Failures (Curated)] > 0` the header shows a red "DATA NOT CERTIFIED" banner on every page
(conditional visibility via a bookmark-free measure-driven card).

---

## Screenshots

Power BI Desktop is required to build the `.pbix`; it is not committed (binary, environment-specific).
After building, export each page (File -> Export -> PDF or PNG) to `docs/images/powerbi/` and the README
gallery picks them up. Until then the README shows the Python-rendered analysis charts from `docs/images/`.
