"""Unit tests for individual data-quality checks on tiny hand-built frames."""
import pandas as pd
import pytest

from data_quality import checks as C
from data_quality.runner import gate, run_checks

SPEC = {
    "primary_key": ["id"],
    "columns": {
        "id": {"type": "string", "nullable": False, "pattern": r"^X\d+$"},
        "status": {"type": "string", "nullable": False, "accepted_values": ["a", "b"]},
        "amount": {"type": "money", "nullable": False, "min": 0, "max": 100, "outlier": True},
        "parent_id": {"type": "string", "nullable": True, "fk": "parents.pid"},
        "start_ts": {"type": "timestamp", "nullable": False},
        "end_ts": {"type": "timestamp", "nullable": True},
        "score": {"type": "float", "nullable": True},
    },
    "date_order": [["start_ts", "end_ts"]],
    "cross_field": [{"name": "small", "expr": "amount <= 50", "severity": "warning"}],
    "conditional": [{"name": "b_needs_end", "when": "status == 'b'", "require_not_null": "end_ts", "severity": "critical"}],
}


def frame(**overrides):
    df = pd.DataFrame({
        "id": ["X1", "X2", "X3", "X4"], "status": ["a", "b", "a", "b"], "amount": [10.0, 20.0, 30.0, 40.0],
        "parent_id": ["P1", "P1", None, "P2"],
        "start_ts": pd.to_datetime(["2025-01-01"] * 4), "end_ts": pd.to_datetime(["2025-01-02"] * 4),
        "score": [1.0, 2.0, None, 4.0],
    })
    for k, v in overrides.items():
        df[k] = v
    return df


def failed(results, check):
    return [r for r in results if r.check.startswith(check) and r.status == "fail"]


def test_clean_frame_passes_column_checks():
    df = frame()
    res = (C.check_not_null("t", "x", df, SPEC) + C.check_unique("t", "x", df, SPEC) + C.check_accepted_values("t", "x", df, SPEC)
           + C.check_ranges("t", "x", df, SPEC) + C.check_patterns("t", "x", df, SPEC) + C.check_date_order("t", "x", df, SPEC))
    assert all(r.status == "pass" for r in res)


def test_not_null_and_duplicates_detected():
    df = frame(status=["a", None, "a", "b"])
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    assert failed(C.check_not_null("t", "x", df, SPEC), "not_null")[0].failed_rows == 1
    assert failed(C.check_unique("t", "x", df, SPEC), "primary_key_unique")[0].failed_rows == 1


def test_validity_checks():
    df = frame(status=["a", "B", "a", "c"], amount=[10.0, -5.0, 30.0, 500.0], id=["X1", "X2", "Y3", "X4"])
    assert failed(C.check_accepted_values("t", "x", df, SPEC), "accepted_values")[0].failed_rows == 2
    assert failed(C.check_ranges("t", "x", df, SPEC), "range")[0].failed_rows == 2
    assert failed(C.check_patterns("t", "x", df, SPEC), "pattern")[0].failed_rows == 1


def test_date_order_and_future_dates():
    df = frame(end_ts=pd.to_datetime(["2024-12-31", "2025-01-02", "2025-01-02", "2025-01-02"]),
               start_ts=pd.to_datetime(["2025-01-01", "2025-01-01", "2030-01-01", "2025-01-01"]))
    assert failed(C.check_date_order("t", "x", df, SPEC), "date_order")[0].failed_rows == 2
    fut = failed(C.check_future_dates("t", "x", df, SPEC, pd.Timestamp("2026-06-30")), "future_date")
    assert fut and fut[0].failed_rows == 1


def test_foreign_keys():
    df = frame(parent_id=["P1", "P9", None, "P2"])
    parents = pd.DataFrame({"pid": ["P1", "P2"]})
    res = failed(C.check_foreign_keys("t", "x", df, SPEC, {"x": df, "parents": parents}, {}), "foreign_key")
    assert res[0].failed_rows == 1 and "P9" in res[0].sample


def test_schema_drift_detected():
    df = frame(score=["4", "N/A", "3", "N/A"])
    df["agent_id"] = ["A1"] * 4
    cols = {r.check: r for r in C.check_schema_columns("raw", "x", df, SPEC)}
    assert cols["schema_unexpected_columns"].status == "fail"
    drift = [r for r in C.check_schema_dtypes("raw", "x", df, SPEC) if r.column == "score"][0]
    assert drift.status == "fail" and drift.failed_rows == 2


def test_cross_field_and_conditional():
    df = frame(end_ts=pd.to_datetime(["2025-01-02", None, "2025-01-02", "2025-01-02"]))
    assert not failed(C.check_cross_field("t", "x", df, SPEC), "cross_field")
    assert failed(C.check_cross_field("t", "x", frame(amount=[10.0, 80.0, 90.0, 1.0]), SPEC), "cross_field")[0].failed_rows == 2
    assert failed(C.check_conditional("t", "x", df, SPEC), "conditional")[0].failed_rows == 1


def test_outlier_robust_z():
    vals = [100.0 + i % 7 for i in range(200)] + [100000.0]
    df = pd.DataFrame({"id": ["X%d" % i for i in range(201)], "amount": vals})
    spec = {"primary_key": ["id"], "columns": {"id": {"type": "string"}, "amount": {"type": "money", "outlier": True}}}
    res = C.check_outliers("t", "x", df, spec)
    assert res[0].status == "fail" and res[0].failed_rows == 1


def test_gate_blocks_only_critical():
    contracts = {"as_of_tolerance_days": 2, "tables": {"x": SPEC}}
    ok_df = frame()
    res = run_checks({"x": ok_df}, contracts, "clean", pd.Timestamp("2025-01-02"))
    passed, blocking = gate(res)
    assert passed, blocking
    bad = frame(status=["a", "b", "a", "zzz"])
    passed, blocking = gate(run_checks({"x": bad}, contracts, "clean", pd.Timestamp("2025-01-02")))
    assert not passed and "accepted_values" in set(blocking["check"])
