# outputs/ - results of the latest pipeline run (synthetic data)

Regenerated on every `python pipeline.py` run; committed here as sample output so the results can be reviewed
without running anything.

| Folder | Contents | Start with |
|---|---|---|
| `ai/` | Fact sheet given to the model, weekly executive summary (Markdown + JSON with the validation result) | [`executive_summary.md`](ai/executive_summary.md) |
| `data_quality/` | Raw and curated check results, cleaning log, planted-defect recall, extract lineage, load stats, HTML report | [`data_quality_report.html`](data_quality/data_quality_report.html), [`data_quality_summary.md`](data_quality/data_quality_summary.md) |
| `sql_results/` | One CSV per analytics query (`<file>__<query>.csv`) + `_manifest.csv` with row counts and runtimes | `01_funnel_conversion__funnel_overall.csv` |
| `kpis/` | Monthly KPIs (wide and long), weekly KPIs, snapshot with deltas / z-scores / target status | [`kpi_snapshot.json`](kpis/kpi_snapshot.json) |
| `experiments/` | Results for all three experiments, the onboarding readout, weekly effects, segment effects | [`EXP-ONB-2026-01_readout.md`](experiments/EXP-ONB-2026-01_readout.md) |
| `segments/` | Business segments, K-Means cluster profiles and centroids, k-selection scores | `cluster_profiles.csv` |
| `anomalies/` | Flagged days and merged episodes with drivers and calendar context | `anomaly_episodes.json` |
| `run_logs/` | `latest_run.json` - step status, timings and row counts of the last run | `latest_run.json` |
