"""Execute every analytics query in sql/analytics/ against the warehouse.

Each file holds one or more queries separated by ``-- @query: <name>`` markers. Results are
written to outputs/sql_results/<file>__<query>.csv and timings to _manifest.csv, so every
query in the repo is proven to run on every pipeline execution.

    python -m python.run_sql_analytics
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd

from python.config import Settings, get_settings

MARKER = re.compile(r"^--\s*@query:\s*(\w+)\s*$", re.MULTILINE)


def parse_queries(path: Path) -> List[Tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    marks = list(MARKER.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sql = text[m.end():end].strip().rstrip(";").strip()
        out.append((m.group(1), sql))
    return out


def all_queries(settings: Settings) -> Dict[str, str]:
    queries = {}
    for path in sorted((settings.sql_dir / "analytics").glob("*.sql")):
        for name, sql in parse_queries(path):
            queries["%s__%s" % (path.stem, name)] = sql
    return queries


def run_all(settings: Optional[Settings] = None) -> pd.DataFrame:
    settings = settings or get_settings()
    out_dir = settings.outputs_dir / "sql_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    manifest = []
    try:
        for key, sql in all_queries(settings).items():
            t0 = time.time()
            df = con.execute(sql).df()
            ms = (time.time() - t0) * 1000
            df.to_csv(out_dir / (key + ".csv"), index=False)
            manifest.append({"query": key, "rows": len(df), "columns": len(df.columns), "runtime_ms": round(ms, 1)})
    finally:
        con.close()
    man = pd.DataFrame(manifest)
    man.to_csv(out_dir / "_manifest.csv", index=False)
    return man


if __name__ == "__main__":
    m = run_all()
    print(m.to_string(index=False))
    print("\n%d queries, %.0f ms total" % (len(m), m["runtime_ms"].sum()))
