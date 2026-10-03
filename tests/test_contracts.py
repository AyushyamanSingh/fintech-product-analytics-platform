"""The warehouse DDL, the data contracts and the KPI registry must not drift apart."""
import duckdb
import pytest

from python.kpi_definitions import KPIS

TYPE_EQUIV = {"VARCHAR": "VARCHAR", "BIGINT": "BIGINT", "DOUBLE": "DOUBLE", "DECIMAL(18,2)": "DECIMAL(18,2)",
              "TIMESTAMP": "TIMESTAMP", "DATE": "DATE", "BOOLEAN": "BOOLEAN"}


def test_ddl_matches_contracts(e2e, contracts):
    con = duckdb.connect(str(e2e["settings"].warehouse_path), read_only=True)
    try:
        cols = con.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                           "WHERE table_schema = 'core' ORDER BY table_name, ordinal_position").df()
    finally:
        con.close()
    for table, spec in contracts["tables"].items():
        actual = cols[cols["table_name"] == table]
        assert list(actual["column_name"]) == list(spec["columns"]), table
        for _, r in actual.iterrows():
            expected = contracts["types"][spec["columns"][r["column_name"]]["type"]]
            assert r["data_type"] == TYPE_EQUIV[expected], (table, r["column_name"], r["data_type"])


def test_every_fk_targets_a_primary_key(contracts):
    for table, spec in contracts["tables"].items():
        for col, cs in spec["columns"].items():
            if "fk" in cs:
                parent, pcol = cs["fk"].split(".")
                assert contracts["tables"][parent]["primary_key"] == [pcol], (table, col)


def test_kpi_registry_is_complete():
    ids = [k["id"] for k in KPIS]
    assert len(ids) == len(set(ids))
    for k in KPIS:
        assert {"id", "name", "category", "unit", "direction", "definition", "formula"} <= set(k), k["id"]
        assert k["unit"] in {"count", "pct", "inr", "ratio", "score"}
        assert k["direction"] in {"up_good", "down_good", "neutral"}


def test_kpi_sql_exposes_every_registered_kpi(e2e):
    import pandas as pd
    monthly = pd.read_csv(e2e["settings"].outputs_dir / "kpis" / "kpi_monthly.csv")
    missing = [k["id"] for k in KPIS if k["id"] not in monthly.columns]
    assert not missing
