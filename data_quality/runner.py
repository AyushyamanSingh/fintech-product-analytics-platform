"""Run the contract against a set of tables and turn the results into a gate decision.

    python -m data_quality.runner --stage clean     # re-validate the processed layer
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

from data_quality import checks as C
from data_quality.reconciliations import run_reconciliations

SEVERITY_WEIGHT = {"critical": 3, "warning": 1}


def load_contracts(path: Path) -> Dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def schema_fingerprint(tables: Dict[str, pd.DataFrame]) -> Dict:
    return {name: {"rows": int(len(df)), "columns": {c: str(t) for c, t in df.dtypes.items()}}
            for name, df in tables.items()}


def _schema_drift_vs_previous(stage: str, tables: Dict[str, pd.DataFrame], previous: Optional[Dict]) -> List[C.CheckResult]:
    if not previous:
        return []
    out = []
    for name, df in tables.items():
        prev = previous.get(name)
        if not prev:
            continue
        cur = {c: str(t) for c, t in df.dtypes.items()}
        added = [c for c in cur if c not in prev["columns"]]
        removed = [c for c in prev["columns"] if c not in cur]
        changed = [c for c in cur if c in prev["columns"] and prev["columns"][c] != cur[c]]
        n = len(added) + len(removed) + len(changed)
        out.append(C._result(stage, name, "schema_drift_vs_previous_run", "*", "warning", n, max(len(cur), 1),
                             "added=%s removed=%s dtype_changed=%s" % (added, removed, changed),
                             added + removed + changed))
    return out


def run_checks(tables: Dict[str, pd.DataFrame], contracts: Dict, stage: str, as_of: pd.Timestamp,
               previous_fingerprint: Optional[Dict] = None) -> pd.DataFrame:
    results: List[C.CheckResult] = []
    tol = int(contracts.get("as_of_tolerance_days", 2))
    prev_counts = {k: v["rows"] for k, v in (previous_fingerprint or {}).items()}
    for name, spec in contracts["tables"].items():
        if name not in tables:
            results.append(C._result(stage, name, "table_present", "*", "critical", 1, 1, "table missing from extract"))
            continue
        df = tables[name]
        key = spec["primary_key"][0]
        results += C.check_schema_columns(stage, name, df, spec)
        results += C.check_schema_dtypes(stage, name, df, spec, key)
        results += C.check_not_null(stage, name, df, spec, key)
        results += C.check_unique(stage, name, df, spec, key)
        results += C.check_accepted_values(stage, name, df, spec, key)
        results += C.check_ranges(stage, name, df, spec, key)
        results += C.check_patterns(stage, name, df, spec, key)
        results += C.check_date_order(stage, name, df, spec, key)
        results += C.check_future_dates(stage, name, df, spec, as_of, key)
        results += C.check_foreign_keys(stage, name, df, spec, tables, contracts, key)
        results += C.check_outliers(stage, name, df, spec, key)
        results += C.check_cross_field(stage, name, df, spec, key)
        results += C.check_conditional(stage, name, df, spec, key)
        results += C.check_freshness(stage, name, df, spec, as_of, tol)
        results += C.check_row_count(stage, name, df, spec, prev_counts.get(name))
    results += run_reconciliations(stage, tables)
    results += _schema_drift_vs_previous(stage, tables, previous_fingerprint)
    return pd.DataFrame([r.to_dict() for r in results])


def summarize(results: pd.DataFrame) -> Dict:
    fails = results[results["status"] == "fail"]
    w = results["severity"].map(SEVERITY_WEIGHT).fillna(1)
    passed_w = w[results["status"] == "pass"].sum()
    by_table = (results.assign(fail=results["status"].eq("fail"),
                               crit=results["status"].eq("fail") & results["severity"].eq("critical"))
                .groupby("table").agg(checks=("check", "size"), failed=("fail", "sum"), critical_failed=("crit", "sum"))
                .reset_index().to_dict("records"))
    return {
        "checks_run": int(len(results)),
        "checks_passed": int((results["status"] == "pass").sum()),
        "critical_failures": int((fails["severity"] == "critical").sum()),
        "warnings": int((fails["severity"] == "warning").sum()),
        "dq_score": round(100.0 * passed_w / w.sum(), 1) if len(results) else 100.0,
        "failed_rows_total": int(fails["failed_rows"].sum()),
        "by_table": by_table,
    }


def gate(results: pd.DataFrame) -> Tuple[bool, pd.DataFrame]:
    blocking = results[(results["status"] == "fail") & (results["severity"] == "critical")]
    return blocking.empty, blocking


def injected_issue_recall(results_raw: pd.DataFrame, manifest: List[Dict]) -> pd.DataFrame:
    """Did the raw-layer checks catch every defect we deliberately planted?"""
    rows = []
    failed = results_raw[results_raw["status"] == "fail"]
    for issue in manifest:
        check_family = issue["expected_check"]
        cand = failed[failed["table"] == issue["table"]]
        hit = cand[cand["check"].str.contains(check_family.split(":")[0], regex=False)
                   & (cand["column"].str.contains(issue["column"], regex=False) | cand["column"].eq("*"))]
        if check_family == "foreign_key" and hit.empty:  # orphans also surface through reconciliations
            hit = failed[failed["check"].str.startswith("reconciliation") &
                         failed["table"].isin([issue["table"], "transactions", "loans"])]
        rows.append({**issue, "detected": not hit.empty,
                     "detected_by": "; ".join(sorted(set(hit["check"])))[:120]})
    return pd.DataFrame(rows)


def main() -> None:  # pragma: no cover - thin CLI
    from python.config import get_settings
    from python.io_utils import read_parquet

    p = argparse.ArgumentParser(description="Validate the processed layer against the data contracts.")
    p.add_argument("--stage", default="clean", choices=["clean"])
    args = p.parse_args()
    s = get_settings()
    contracts = load_contracts(s.contracts_path)
    tables = {t: read_parquet(s.processed_dir / (t + ".parquet")) for t in contracts["tables"]}
    res = run_checks(tables, contracts, args.stage, pd.Timestamp(s.end_date))
    print(json.dumps(summarize(res), indent=2))
    ok, blocking = gate(res)
    if not ok:
        print(blocking[["table", "check", "column", "failed_rows", "details"]].to_string(index=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
