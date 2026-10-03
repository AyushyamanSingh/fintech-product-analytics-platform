"""Load: write the curated parquet layer, build the DuckDB warehouse and its marts.

Strategy: full refresh. The warehouse file is rebuilt from the curated parquet on every
run (cheap at this volume and guarantees idempotency). The incremental design for
production - partitioned event tables + MERGE on primary keys - is described in
docs/technical_documentation.md.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

import duckdb
import pandas as pd

from etl.transform import sql_types
from python.config import LOAD_ORDER, Settings
from python.io_utils import write_parquet


def write_processed(tables: Dict[str, pd.DataFrame], contracts: Dict, settings: Settings) -> None:
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        write_parquet(df, settings.processed_dir / (name + ".parquet"), sql_types(contracts, name))


def write_quarantine(quarantine: Dict[str, pd.DataFrame], settings: Settings) -> None:
    settings.quarantine_dir.mkdir(parents=True, exist_ok=True)
    for old in settings.quarantine_dir.glob("*.csv"):
        old.unlink()
    for name, df in quarantine.items():
        df.to_csv(settings.quarantine_dir / (name + "_quarantine.csv"), index=False)


def _run_sql_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text(encoding="utf-8"))


def build_warehouse(settings: Settings, contracts: Dict) -> pd.DataFrame:
    """(Re)create the warehouse: core tables with constraints, then marts. Returns load stats."""
    db = settings.warehouse_path
    db.parent.mkdir(parents=True, exist_ok=True)
    for f in (db, Path(str(db) + ".wal")):
        if f.exists():
            f.unlink()
    con = duckdb.connect(str(db))
    stats: List[Dict] = []
    try:
        _run_sql_file(con, settings.sql_dir / "ddl" / "01_core_schema.sql")
        for table in LOAD_ORDER:
            t0 = time.time()
            cols = ", ".join('"%s"' % c for c in contracts["tables"][table]["columns"])
            parquet = (settings.processed_dir / (table + ".parquet")).as_posix()
            con.execute("INSERT INTO core.%s (%s) SELECT %s FROM read_parquet('%s')" % (table, cols, cols, parquet))
            n = con.execute("SELECT COUNT(*) FROM core.%s" % table).fetchone()[0]
            stats.append({"layer": "core", "object": table, "rows": int(n), "seconds": round(time.time() - t0, 2)})

        con.execute("CREATE SCHEMA IF NOT EXISTS marts")
        con.execute("CREATE OR REPLACE TABLE marts.run_params AS SELECT DATE '%s' AS as_of_date, DATE '%s' AS start_date"
                    % (settings.end_date, settings.start_date))
        for path in sorted((settings.sql_dir / "marts").glob("*.sql")):
            t0 = time.time()
            _run_sql_file(con, path)
            name = path.stem.split("_", 1)[1]
            n = con.execute("SELECT COUNT(*) FROM marts.%s" % name).fetchone()[0]
            stats.append({"layer": "marts", "object": name, "rows": int(n), "seconds": round(time.time() - t0, 2)})
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return pd.DataFrame(stats)
