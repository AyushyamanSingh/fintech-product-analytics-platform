"""Create (and execute) the analysis notebooks from version-controlled Python source.

Notebooks are generated rather than hand-edited so they stay reviewable in git and always run
against the current warehouse. Requires requirements-notebooks.txt. Run after the pipeline:

    python notebooks/build_notebooks.py            # build + execute
    python notebooks/build_notebooks.py --no-exec  # build only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat as nbf

if sys.platform.startswith("win"):  # pyzmq needs a selector event loop on Windows
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

HERE = Path(__file__).resolve().parent

SETUP = """import sys, json
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
sys.path.insert(0, str(ROOT))
import duckdb, numpy as np, pandas as pd
import matplotlib.pyplot as plt
from python import visualize as viz   # shared chart style (palette, fonts, grid)
%matplotlib inline
from python.config import get_settings
S = get_settings(base_dir=ROOT)
con = duckdb.connect(str(S.warehouse_path), read_only=True)
q = lambda sql: con.execute(sql).df()
pd.set_option("display.max_columns", 30); pd.set_option("display.width", 160)
print("Warehouse:", S.warehouse_path.name, "| as of", S.end_date, "| SYNTHETIC DATA")"""

NOTEBOOKS = {
    "01_data_exploration.ipynb": [
        ("md", "# 01 - Data exploration & quality\n_Vittora Credit (fictional) - synthetic data._\n\n"
               "Goal: understand the shape of the 11 source tables, how they relate, and what the data-quality "
               "framework found before trusting any metric."),
        ("code", SETUP),
        ("md", "## Row counts across the curated layer"),
        ("code", "tables = [r[0] for r in con.execute(\"SELECT table_name FROM information_schema.tables WHERE table_schema='core' ORDER BY 1\").fetchall()]\n"
                 "counts = pd.DataFrame({'table': tables, 'rows': [con.execute(f'SELECT COUNT(*) FROM core.{t}').fetchone()[0] for t in tables]})\n"
                 "print('total rows:', format(counts.rows.sum(), ','))\ncounts.sort_values('rows', ascending=False)"),
        ("md", "## Who are the customers?"),
        ("code", "q(\"\"\"SELECT acquisition_channel, signup_platform, COUNT(*) AS customers,\n"
                 "       ROUND(AVG(monthly_income)) AS avg_income, ROUND(100*AVG(CASE WHEN is_ntc THEN 1 ELSE 0 END),1) AS ntc_pct\n"
                 "FROM core.customers GROUP BY 1,2 ORDER BY customers DESC LIMIT 12\"\"\")"),
        ("code", "c = q('SELECT monthly_income, credit_score, employment_type FROM core.customers')\n"
                 "fig, axes = plt.subplots(1, 2, figsize=(11, 3.6))\n"
                 "axes[0].hist(np.log10(c.monthly_income.dropna()), bins=60, color=viz.SERIES[0]); axes[0].set_title('Monthly income (log10 INR)')\n"
                 "axes[1].hist(c.credit_score.dropna(), bins=60, color=viz.SERIES[0]); axes[1].set_title('Bureau score (NTC excluded)')\n"
                 "plt.tight_layout(); plt.show()"),
        ("md", "## Data-quality results (raw extract vs curated layer)\nEvery defect the generator planted is listed in "
               "`data/raw/_injected_issues.json`; the framework's job is to catch all of them."),
        ("code", "dq = json.loads((S.outputs_dir/'data_quality'/'dq_summary.json').read_text())\n"
                 "pd.DataFrame({k: {m: dq[k][m] for m in ['checks_run','dq_score','critical_failures','warnings']} for k in ['raw','clean']})"),
        ("code", "pd.read_csv(S.outputs_dir/'data_quality'/'injected_issue_recall.csv')[['table','column','issue','rows_affected','detected']]"),
        ("code", "pd.read_csv(S.outputs_dir/'data_quality'/'cleaning_log.csv').query('rows_affected > 0')"),
        ("md", "**Takeaway:** the curated layer has no critical issues; the remaining warnings (missing city/income, "
               "a flagged campaign over budget, the KYC tracking gap) are documented and carried into report caveats."),
    ],
    "02_funnel_and_cohorts.ipynb": [
        ("md", "# 02 - Funnel, drop-off and cohort analysis\n_Synthetic data._\n\nQuestions: where do customers leak "
               "between signup and first loan, who leaks most, and do cohorts retain?"),
        ("code", SETUP),
        ("code", "pd.read_csv(S.outputs_dir/'sql_results'/'01_funnel_conversion__funnel_overall.csv')"),
        ("md", "The biggest absolute loss is between signup and KYC completion. Which segments drive it?"),
        ("code", "seg = pd.read_csv(S.outputs_dir/'sql_results'/'02_funnel_dropoff__kyc_dropoff_by_segment.csv')\n"
                 "seg.sort_values('recoverable_customers', ascending=False).head(10)"),
        ("code", "pd.read_csv(S.outputs_dir/'sql_results'/'01_funnel_conversion__funnel_by_channel.csv')"),
        ("md", "## Weekly KYC completion - before, during and after the onboarding test"),
        ("code", "from IPython.display import Image\nImage(filename=str(S.images_dir/'kyc_weekly_trend.png'))"),
        ("md", "## Cohort retention (monthly active)"),
        ("code", "Image(filename=str(S.images_dir/'cohort_retention.png'))"),
        ("code", "pd.read_csv(S.outputs_dir/'sql_results'/'03_cohort_retention__retention_curve_by_borrower_status.csv').pivot(index='month_number', columns='borrower_status', values='retention_pct').head(13)"),
        ("md", "## Growth accounting: is MAU growth acquisition or retention?"),
        ("code", "pd.read_csv(S.outputs_dir/'sql_results'/'04_active_users__mau_growth_accounting.csv').tail(8)"),
        ("md", "**Takeaways:** (1) KYC is the main leak and is concentrated in web, tier-3, gig-worker and paid-social "
               "signups; (2) borrowing is what keeps users active - non-borrowers churn within two months; "
               "(3) the redesigned onboarding lifted the weekly KYC trend after launch."),
    ],
    "03_ab_test_onboarding.ipynb": [
        ("md", "# 03 - A/B test: onboarding redesign (EXP-ONB-2026-01)\n_Synthetic data._\n\nControl = existing "
               "onboarding; treatment = trust signals + DigiLocker one-tap + progress indicator. Primary metric: KYC "
               "completed within 7 days of signup."),
        ("code", SETUP),
        ("code", "from python.experiment_analysis import ONB_SQL, two_proportion_test, required_n_per_arm, achieved_power, srm_check, bayes_beta_binomial\n"
                 "units = q(ONB_SQL)\nunits.groupby('variant').agg(users=('customer_id','size'), kyc_7d=('kyc_7d','mean'), app_14d=('app_14d','mean'), disb_30d=('disb_30d','mean'))"),
        ("md", "## 1. Validity first: sample-ratio mismatch"),
        ("code", "n = units.variant.value_counts(); srm_check(int(n['control']), int(n['treatment']))"),
        ("md", "## 2. Primary metric: two-proportion z-test, by hand and via the library"),
        ("code", "g = units.groupby('variant').kyc_7d.agg(['sum','count'])\n"
                 "xc, nc, xt, nt = g.loc['control','sum'], g.loc['control','count'], g.loc['treatment','sum'], g.loc['treatment','count']\n"
                 "pc, pt = xc/nc, xt/nt; p = (xc+xt)/(nc+nt)\n"
                 "z = (pt-pc)/np.sqrt(p*(1-p)*(1/nc+1/nt))\n"
                 "print(f'control {pc:.4f}  treatment {pt:.4f}  diff {100*(pt-pc):+.2f} pp  z={z:.2f}')\n"
                 "two_proportion_test(int(xc), int(nc), int(xt), int(nt))"),
        ("md", "## 3. Power: was the test big enough?"),
        ("code", "res = json.loads((S.outputs_dir/'experiments'/'experiment_results.json').read_text())['EXP-ONB-2026-01']\n"
                 "d = res['design']; print('baseline', round(d['pre_period_baseline'],4), '| MDE', d['planned_mde_abs'], '| required n/arm', d['required_n_per_arm'], '| weeks needed', d['weeks_needed'])\n"
                 "mdes = np.linspace(0.01, 0.08, 15)\nplt.figure(figsize=(7,3.2)); plt.plot(100*mdes, [required_n_per_arm(d['pre_period_baseline'], m) for m in mdes], color=viz.SERIES[0])\n"
                 "plt.axhline(nc, color=viz.MUTED, lw=1); plt.title('Users per arm needed vs detectable lift (80% power)'); plt.xlabel('MDE (pp)'); plt.show()"),
        ("md", "## 4. Guardrails, Bayesian view and heterogeneity"),
        ("code", "pd.DataFrame(res['guardrails']).T[['control_rate','treatment_rate','diff_abs','ci_low','ci_high','margin','status']]"),
        ("code", "res['bayesian']"),
        ("code", "pd.DataFrame(res['segments'])[['dimension','segment','users','diff_abs','ci_low','ci_high','p_value_holm']]"),
        ("code", "from IPython.display import Markdown\nMarkdown((S.outputs_dir/'experiments'/'EXP-ONB-2026-01_readout.md').read_text())"),
    ],
    "04_customer_segmentation.ipynb": [
        ("md", "# 04 - Customer segmentation\n_Synthetic data._\n\nTwo lenses: rule-based CRM segments for every customer "
               "(actionable today) and K-Means clusters on borrower behaviour and value (discovery)."),
        ("code", SETUP),
        ("code", "pd.read_csv(S.outputs_dir/'segments'/'business_segments.csv')[['business_segment','rule','customers','share_of_customers_pct','share_of_net_revenue_pct','recommended_action']]"),
        ("md", "## Choosing k: silhouette with an interpretability constraint (4-6 clusters)"),
        ("code", "ks = pd.read_csv(S.outputs_dir/'segments'/'k_selection.csv'); ks"),
        ("code", "pd.read_csv(S.outputs_dir/'segments'/'cluster_profiles.csv').round(2)"),
        ("code", "from IPython.display import Image\nImage(filename=str(S.images_dir/'segments.png'))"),
        ("md", "**Business reading:** a small loyal high-value group carries a disproportionate share of net revenue - protect it "
               "with pre-approved top-ups; the credit-stressed cluster is negative-value and belongs in collections, "
               "not in marketing audiences; lapsed one-time borrowers are the cheapest re-activation pool."),
    ],
    "05_ai_analyst_demo.ipynb": [
        ("md", "# 05 - AI analyst: grounded summaries and Q&A\n_Synthetic data._\n\nThe model never invents numbers: it "
               "writes from a fact sheet and every number is machine-checked against the facts it cites. This notebook "
               "runs offline (no API key needed)."),
        ("code", SETUP),
        ("code", "from ai_analyst.fact_sheet import build_fact_sheet, facts_for_prompt\nsheet = build_fact_sheet(S)\nprint(facts_for_prompt(sheet)[:2500])"),
        ("md", "## The grounding checker catches an invented number"),
        ("code", "from ai_analyst.grounding import validate_items\n"
                 "f = next(x for x in sheet['facts'] if x['data'].get('kpi') == 'approval_rate')\n"
                 "good = {'section':'demo','text': 'Approval rate: ' + f['data']['value_fmt'], 'fact_ids':[f['id']]}\n"
                 "bad  = {'section':'demo','text': 'Approval rate jumped to 71.3%', 'fact_ids':[f['id']]}\n"
                 "validate_items([good, bad], sheet['facts'])"),
        ("md", "## The SQL guard blocks unsafe model-written SQL"),
        ("code", "from ai_analyst.sql_guard import validate_sql, SQLGuardError\nfor s in ['SELECT COUNT(*) FROM marts.fct_loan_performance', 'DROP TABLE core.loans', \"SELECT * FROM read_csv('secrets.csv')\"]:\n"
                 "    try: print('OK     ', validate_sql(s, ['marts.fct_loan_performance']).splitlines()[1])\n"
                 "    except SQLGuardError as e: print('BLOCKED', s, '->', e)"),
        ("md", "## Weekly executive summary (deterministic mode; set ANTHROPIC_API_KEY to let Claude write it)"),
        ("code", "from ai_analyst.summarizer import generate_summary\nr = generate_summary(S, offline=True)\nprint(r['mode'], r['validation']['grounded'], r['validation']['numbers_checked'], 'numbers checked')\n"
                 "from IPython.display import Markdown\nMarkdown(Path(r['path']).read_text().split('## Sources')[0])"),
        ("code", "from ai_analyst.qa import ask\nask('What was the PAR30 and NPA last month?', S, offline=True)['answer']"),
    ],
}


def build(execute: bool = True) -> None:
    for name, cells in NOTEBOOKS.items():
        nb = nbf.v4.new_notebook()
        nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        nb.cells = [nbf.v4.new_markdown_cell(src) if kind == "md" else nbf.v4.new_code_cell(src) for kind, src in cells]
        path = HERE / name
        if execute:
            from nbclient import NotebookClient
            NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(HERE)}}).execute()
        nbf.write(nb, str(path))
        print("wrote", path.name, "(executed)" if execute else "")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-exec", action="store_true")
    build(execute=not ap.parse_args().no_exec)
