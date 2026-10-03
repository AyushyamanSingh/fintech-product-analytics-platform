# Power BI layer

_Synthetic data - fictional lender Vittora Credit._

| Path | What it is |
|---|---|
| [`dashboard_spec.md`](dashboard_spec.md) | Page-by-page build spec for the 8-page executive report |
| [`dax/measures.dax`](dax/measures.dax) | Measure library (70+ measures, grouped by display folder) |
| [`model/data_model.md`](model/data_model.md) | Star schema, relationships, modelling decisions, RLS, refresh |
| [`power_query/load_tables.pq`](power_query/load_tables.pq) | Parameterised CSV loader (`fnLoadCsv`) with type inference |
| [`theme/vittora_theme.json`](theme/vittora_theme.json) | Report theme (accessible palette, status colours, typography) |
| `data/` | Star-schema extract written by the pipeline (git-ignored, regenerate with `python pipeline.py`) |

## Build the report (about 45 minutes)

1. Run the pipeline so `powerbi/data/` exists: `python pipeline.py --generate --offline-ai`.
2. Power BI Desktop -> **Transform data** -> New parameter `DataFolder` (text) = full path to `powerbi\data\`.
3. New blank query `fnLoadCsv`, paste the function from `power_query/load_tables.pq`; create one query per CSV
   (`= fnLoadCsv("fct_loans")` ...), plus the `'Funnel Stage'` disconnected table.
4. **Model view**: create the relationships in `model/data_model.md` (inactive ones dashed), mark `dim_date`
   as the date table.
5. Create a `_Measures` table and paste the measures from `dax/measures.dax` (display folders as in the file headers).
6. **View -> Themes -> Browse** -> `theme/vittora_theme.json`.
7. Build the pages following `dashboard_spec.md`; export page images to `docs/images/powerbi/`.
