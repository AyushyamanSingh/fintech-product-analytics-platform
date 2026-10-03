"""Small I/O helpers. Parquet goes through DuckDB, so the project does not need pyarrow."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb
import numpy as np
import pandas as pd


def _duckdb_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Make a frame DuckDB can scan without guessing: nullable ints -> float, all-null objects -> str."""
    out = df.copy()
    for col in out.columns:
        dtype = str(out[col].dtype)
        if dtype.startswith("Int") or dtype.startswith("UInt"):
            out[col] = out[col].astype("float64")
        elif dtype in ("boolean", "string"):
            out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out


def write_parquet(df: pd.DataFrame, path: Path, column_types: Optional[Dict[str, str]] = None) -> None:
    """Write a DataFrame to Parquet (ZSTD). ``column_types`` optionally casts columns to SQL types."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.register("frame", _duckdb_safe(df))
        if column_types:
            select = ", ".join(
                'CAST("%s" AS %s) AS "%s"' % (c, column_types[c], c) if c in column_types else '"%s"' % c
                for c in df.columns
            )
        else:
            select = "*"
        con.execute("COPY (SELECT %s FROM frame) TO '%s' (FORMAT PARQUET, COMPRESSION ZSTD)" % (select, path.as_posix()))
    finally:
        con.close()


def read_parquet(path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        return con.execute("SELECT * FROM read_parquet('%s')" % path.as_posix()).df()
    finally:
        con.close()


def query_df(db_path: Path, sql: str, read_only: bool = True) -> pd.DataFrame:
    con = duckdb.connect(str(db_path), read_only=read_only)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


class _Encoder(json.JSONEncoder):
    def default(self, o: Any):  # noqa: D401 - json hook
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if isinstance(o, Path):
            return o.as_posix()
        return super().default(o)


def write_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, cls=_Encoder, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt_inr(value: float, decimals: int = 2) -> str:
    """Indian-style short money format: 1.23 Cr / 4.56 L / 7,890."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    v = float(value)
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e7:
        return "%s₹%.*f Cr" % (sign, decimals, v / 1e7)
    if v >= 1e5:
        return "%s₹%.*f L" % (sign, decimals, v / 1e5)
    return "%s₹%s" % (sign, format(round(v), ","))
