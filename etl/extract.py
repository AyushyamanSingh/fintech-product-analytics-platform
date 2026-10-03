"""Extract: read the raw source-system files and record lineage (file hash, size, row count)."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

from python.config import TABLES, Settings


def _md5(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def raw_path(settings: Settings, table: str) -> Path:
    gz = settings.raw_dir / (table + ".csv.gz")
    return gz if gz.exists() else settings.raw_dir / (table + ".csv")


def extract(settings: Settings) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """Read every raw table as delivered (no type coercion beyond pandas' defaults)."""
    tables: Dict[str, pd.DataFrame] = {}
    lineage = []
    for t in TABLES:
        path = raw_path(settings, t)
        if not path.exists():
            raise FileNotFoundError("Raw file missing for table '%s': %s (run python -m python.generate_data)" % (t, path))
        # Only empty fields are null: tokens like "N/A" or "NULL" are kept as delivered so that type
        # drift is visible to the data-quality checks instead of being silently coerced by pandas.
        df = pd.read_csv(path, low_memory=False, keep_default_na=False, na_values=[""])
        tables[t] = df
        lineage.append({
            "table": t, "source_file": path.name, "bytes": path.stat().st_size, "md5": _md5(path),
            "rows": len(df), "columns": len(df.columns), "extracted_at": datetime.now().isoformat(timespec="seconds"),
        })
    return tables, pd.DataFrame(lineage)
