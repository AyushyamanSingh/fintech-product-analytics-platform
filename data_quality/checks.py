"""Individual data-quality checks.

Every check returns ``CheckResult`` objects so results from different tables, stages and
check types land in one tidy table (``outputs/data_quality/dq_results_<stage>.csv``).
Checks are written to work on both layers:

* raw   - CSV extracts, timestamps still strings, dirty categories, schema drift
* clean - typed, de-duplicated, standardised data written by etl/transform.py
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

NUMERIC_TYPES = {"integer", "float", "money"}
TEMPORAL_TYPES = {"timestamp", "date"}


@dataclass
class CheckResult:
    stage: str
    table: str
    check: str
    column: str
    severity: str
    status: str
    failed_rows: int
    total_rows: int
    threshold: float
    details: str
    sample: str = ""

    @property
    def failure_rate(self) -> float:
        return self.failed_rows / self.total_rows if self.total_rows else 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["failure_rate"] = round(self.failure_rate, 6)
        return d


def _result(stage, table, check, column, severity, failed, total, details, sample=None, threshold=0.0) -> CheckResult:
    rate = failed / total if total else 0.0
    status = "pass" if rate <= threshold else "fail"
    if sample is not None and len(sample):
        sample_s = ", ".join(str(v) for v in list(sample)[:5])
    else:
        sample_s = ""
    return CheckResult(stage, table, check, column, severity, status, int(failed), int(total), threshold, details, sample_s)


def as_datetime(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    return pd.to_datetime(s, errors="coerce")


def as_numeric(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        return s.astype("float64")
    return pd.to_numeric(s, errors="coerce")


def _key_sample(df: pd.DataFrame, mask: pd.Series, key: Optional[str]) -> List:
    if key and key in df.columns:
        return df.loc[mask, key].head(5).tolist()
    return df.index[mask][:5].tolist()


# ---------------------------------------------------------------- schema checks
def check_schema_columns(stage, table, df, spec) -> List[CheckResult]:
    cols = spec["columns"]
    expected = [c for c, s in cols.items() if not (stage == "raw" and s.get("derived"))]
    missing = [c for c in expected if c not in df.columns]
    unexpected = [c for c in df.columns if c not in cols]
    return [
        _result(stage, table, "schema_missing_columns", "*", "critical", len(missing), len(expected),
                "Columns required by the contract but absent: %s" % (missing or "none"), missing),
        _result(stage, table, "schema_unexpected_columns", "*", "warning", len(unexpected), max(len(df.columns), 1),
                "Columns delivered but not in the contract (additive schema change): %s" % (unexpected or "none"),
                unexpected),
    ]


def check_schema_dtypes(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns:
            continue
        s = df[col]
        typ = cs["type"]
        nn = s.notna()
        if typ in NUMERIC_TYPES:
            if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
                bad = pd.Series(False, index=s.index)
            else:
                bad = nn & pd.to_numeric(s, errors="coerce").isna()
            detail = "expected %s, received pandas dtype '%s'" % (typ, s.dtype)
        elif typ in TEMPORAL_TYPES:
            if pd.api.types.is_datetime64_any_dtype(s):
                bad = pd.Series(False, index=s.index)
            else:
                bad = nn & pd.to_datetime(s, errors="coerce").isna()
            detail = "expected %s; unparseable values counted" % typ
        elif typ == "boolean":
            if pd.api.types.is_bool_dtype(s):
                bad = pd.Series(False, index=s.index)
            else:
                bad = nn & ~s.astype(str).str.lower().isin(["true", "false", "1", "0", "1.0", "0.0"])
            detail = "expected boolean"
        else:
            continue
        drift = (not pd.api.types.is_numeric_dtype(s)) and typ in NUMERIC_TYPES
        if drift:
            detail += " (type drift: numeric column arrived as text)"
        sev = "critical" if bad.sum() else "warning"
        r = _result(stage, table, "schema_dtype", col, sev, int(bad.sum()) + (0 if not drift else 0),
                    len(df), detail, s[bad].astype(str).unique()[:5])
        if drift and r.status == "pass":
            r.status, r.severity, r.failed_rows = "fail", "warning", int(nn.sum())
        out.append(r)
    return out


# ---------------------------------------------------------------- column checks
def check_not_null(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns or cs.get("nullable", True):
            continue
        mask = df[col].isna()
        out.append(_result(stage, table, "not_null", col, cs.get("severity", "critical"), mask.sum(), len(df),
                           "nulls in a non-nullable column", _key_sample(df, mask, key)))
    return out


def check_unique(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    keys = [spec["primary_key"]] + spec.get("unique_together", [])
    for cols in keys:
        if any(c not in df.columns for c in cols):
            continue
        sub = df[cols].dropna()
        dup_mask = sub.duplicated(keep="first")
        exact = int(df.duplicated(keep="first").sum())
        name = "primary_key_unique" if cols == spec["primary_key"] else "unique_together"
        out.append(_result(stage, table, name, "+".join(cols), "critical", dup_mask.sum(), len(df),
                           "duplicate keys (of which %d are exact duplicate rows)" % exact,
                           sub.loc[dup_mask, cols[0]].head(5).tolist()))
    return out


def check_accepted_values(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns or "accepted_values" not in cs:
            continue
        s = df[col]
        allowed = set(str(v) for v in cs["accepted_values"])
        mask = s.notna() & ~s.astype(str).isin(allowed)
        out.append(_result(stage, table, "accepted_values", col, cs.get("severity", "critical"), mask.sum(), len(df),
                           "values outside the allowed set", s[mask].astype(str).value_counts().index[:5].tolist()))
    return out


def check_ranges(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns or ("min" not in cs and "max" not in cs):
            continue
        v = as_numeric(df[col])
        mask = pd.Series(False, index=df.index)
        if "min" in cs:
            mask |= v < cs["min"]
        if "max" in cs:
            mask |= v > cs["max"]
        out.append(_result(stage, table, "range", col, cs.get("severity", "critical"), mask.sum(), len(df),
                           "outside [%s, %s]" % (cs.get("min", "-inf"), cs.get("max", "inf")),
                           v[mask].head(5).tolist()))
    return out


def check_patterns(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns or "pattern" not in cs:
            continue
        s = df[col].dropna().astype(str)
        mask = ~s.str.match(cs["pattern"])
        out.append(_result(stage, table, "pattern", col, "critical", mask.sum(), len(df),
                           "does not match %s" % cs["pattern"], s[mask].head(5).tolist()))
    return out


def check_date_order(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for a, b in spec.get("date_order", []):
        if a not in df.columns or b not in df.columns:
            continue
        da, db = as_datetime(df[a]), as_datetime(df[b])
        mask = da.notna() & db.notna() & (db < da)
        out.append(_result(stage, table, "date_order", "%s<=%s" % (a, b), "critical", mask.sum(), len(df),
                           "%s earlier than %s" % (b, a), _key_sample(df, mask, key)))
    return out


def check_future_dates(stage, table, df, spec, as_of: pd.Timestamp, key=None) -> List[CheckResult]:
    out = []
    cols = [c for c, s in spec["columns"].items() if s["type"] == "timestamp"] + spec.get("future_date_columns", [])
    limit = as_of + pd.Timedelta(days=1)
    for col in dict.fromkeys(cols):
        if col not in df.columns:
            continue
        d = as_datetime(df[col])
        mask = d >= limit
        out.append(_result(stage, table, "future_date", col, "critical", mask.sum(), len(df),
                           "later than the extract date %s" % as_of.date(), d[mask].astype(str).head(5).tolist()))
    return out


def check_foreign_keys(stage, table, df, spec, tables: Dict[str, pd.DataFrame], contracts: Dict,
                       key=None) -> List[CheckResult]:
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns or "fk" not in cs:
            continue
        ptable, pcol = cs["fk"].split(".")
        if ptable not in tables or pcol not in tables[ptable].columns:
            continue
        parent = set(tables[ptable][pcol].dropna().astype(str))
        s = df[col]
        mask = s.notna() & ~s.astype(str).isin(parent)
        out.append(_result(stage, table, "foreign_key", col, cs.get("fk_severity", "critical"), mask.sum(), len(df),
                           "orphans: no matching %s" % cs["fk"], s[mask].astype(str).head(5).tolist()))
    return out


def check_outliers(stage, table, df, spec, key=None, z_threshold: float = 5.0) -> List[CheckResult]:
    """Robust z-score on log1p(value): |x - median| / (1.4826 * MAD) > threshold."""
    out = []
    for col, cs in spec["columns"].items():
        if col not in df.columns or not cs.get("outlier"):
            continue
        v = as_numeric(df[col])
        pos = v[v > 0]
        if len(pos) < 50:
            continue
        lv = np.log1p(pos)
        med = lv.median()
        mad = (lv - med).abs().median() * 1.4826
        if mad == 0:
            continue
        z = (lv - med) / mad
        mask = pd.Series(False, index=df.index)
        mask.loc[z.index] = z.abs() > z_threshold
        out.append(_result(stage, table, "outlier_robust_z", col, "warning", mask.sum(), len(df),
                           "robust z > %.0f on log scale (median %.0f)" % (z_threshold, np.expm1(med)),
                           v[mask].head(5).tolist()))
    return out


def _referenced_columns(expr: str, columns: Iterable[str]) -> List[str]:
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
    return [c for c in columns if c in tokens]


def check_cross_field(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for rule in spec.get("cross_field", []):
        cols = _referenced_columns(rule["expr"], df.columns)
        if not cols:
            continue
        tmp = pd.DataFrame({c: as_numeric(df[c]) for c in cols})
        valid = tmp.notna().all(axis=1)
        ok = tmp[valid].eval(rule["expr"])
        mask = pd.Series(False, index=df.index)
        mask.loc[ok.index] = ~ok.astype(bool)
        out.append(_result(stage, table, "cross_field:" + rule["name"], ",".join(cols), rule.get("severity", "critical"),
                           mask.sum(), len(df), rule["expr"], _key_sample(df, mask, key)))
    return out


def check_conditional(stage, table, df, spec, key=None) -> List[CheckResult]:
    out = []
    for rule in spec.get("conditional", []):
        col = rule["require_not_null"]
        if col not in df.columns:
            continue
        try:
            when = df.eval(rule["when"], engine="python")
        except Exception as exc:  # pragma: no cover - surfaced in the report
            out.append(_result(stage, table, "conditional:" + rule["name"], col, "warning", 0, len(df),
                               "could not evaluate: %s" % exc))
            continue
        mask = when.astype(bool) & df[col].isna()
        out.append(_result(stage, table, "conditional:" + rule["name"], col, rule.get("severity", "critical"),
                           mask.sum(), len(df), "when %s then %s is required" % (rule["when"], col),
                           _key_sample(df, mask, key)))
    return out


# ---------------------------------------------------------------- table-level checks
def check_freshness(stage, table, df, spec, as_of: pd.Timestamp, tolerance_days: int) -> List[CheckResult]:
    col = spec.get("freshness_column")
    if not col or col not in df.columns:
        return []
    latest = as_datetime(df[col]).max()
    lag = (as_of - latest.normalize()).days if pd.notna(latest) else 9999
    return [_result(stage, table, "freshness", col, "critical", int(lag > tolerance_days), 1,
                    "latest %s = %s (%d days before extract date; tolerance %d)" % (col, latest, lag, tolerance_days))]


def check_row_count(stage, table, df, spec, previous: Optional[int] = None) -> List[CheckResult]:
    out = []
    minimum = spec.get("row_count_min", 1)
    out.append(_result(stage, table, "row_count_min", "*", "critical", int(len(df) < minimum), 1,
                       "%d rows (minimum %d)" % (len(df), minimum)))
    if previous:
        change = abs(len(df) - previous) / previous
        out.append(_result(stage, table, "row_count_change", "*", "warning", int(change > 0.5), 1,
                           "%d rows vs %d in the previous run (%+.1f%%)" % (len(df), previous,
                                                                           100 * (len(df) - previous) / previous)))
    return out
