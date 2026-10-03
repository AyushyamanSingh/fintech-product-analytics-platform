# data/

> **Everything here is synthetic**, produced by `python -m python.generate_data` for the fictional lender
> Vittora Credit. No real people, companies or transactions.

| Folder | Layer | Committed? | Produced by |
|---|---|---|---|
| `raw/` | Source-system extracts as delivered (CSV; events as CSV.gz), **with injected defects**, plus `_injected_issues.json` (the DQ answer key) and `_generation_summary.json` | no (regenerate) | `python/generate_data.py` |
| `sample/` | First 200 raw rows of each table, for browsing on GitHub | yes | `python/generate_data.py` |
| `processed/` | Curated Parquet (typed, de-duplicated, repaired) | no | `etl/transform.py` + `etl/load.py` |
| `quarantine/` | Rows that could not be repaired, with `_quarantine_reason` | no | `etl/transform.py` |
| `warehouse/` | DuckDB file: `core` (constrained tables) + `marts` | no | `etl/load.py` |

Regenerate everything: `python pipeline.py --generate`. Default size: 80,000 customers (+ a 1,200-identity fraud
ring) -> ~1.25M rows across 11 tables; change with `--n-customers`.

Table-level documentation: [docs/data_dictionary.md](../docs/data_dictionary.md).
