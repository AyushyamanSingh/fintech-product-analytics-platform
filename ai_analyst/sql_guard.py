"""Guardrails for model-written SQL.

Defense in depth:
1. Static checks - one statement, SELECT/WITH only, no DDL/DML/admin keywords, no file or network
   table functions, every FROM/JOIN target is a CTE, an allow-listed warehouse table or a safe
   generator function.
2. Row cap - the statement is wrapped in ``SELECT * FROM (...) LIMIT n``.
3. Runtime - executed on a read-only DuckDB connection with external access disabled.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|pragma|call|set|"
    r"grant|revoke|truncate|vacuum|checkpoint|merge|upsert|use|begin|commit|rollback)\b", re.IGNORECASE)
FILE_FUNCTIONS = re.compile(
    r"\b(read_csv|read_csv_auto|read_parquet|parquet_scan|read_json|read_json_auto|read_ndjson|read_text|read_blob|"
    r"glob|sqlite_scan|postgres_scan|mysql_scan|iceberg_scan|delta_scan|httpfs|getenv)\s*\(", re.IGNORECASE)
SAFE_TABLE_FUNCTIONS = {"range", "generate_series", "unnest"}


class SQLGuardError(ValueError):
    pass


def _strip_comments_and_strings(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)  # string literals cannot hide keywords from the checks


def cte_names(sql: str) -> Set[str]:
    return {m.group(1).lower() for m in re.finditer(r"(?:\bwith\b|,)\s*(\w+)\s+as\s*\(", sql, flags=re.IGNORECASE)}


def validate_sql(sql: str, allowed_tables: Iterable[str], max_rows: int = 200) -> str:
    if not sql or not sql.strip():
        raise SQLGuardError("empty query")
    body = sql.strip().rstrip(";").strip()
    scan = _strip_comments_and_strings(body)
    if ";" in scan:
        raise SQLGuardError("only one statement is allowed")
    if not re.match(r"^\s*(select|with)\b", scan, flags=re.IGNORECASE):
        raise SQLGuardError("only SELECT / WITH queries are allowed")
    bad = FORBIDDEN.search(scan)
    if bad:
        raise SQLGuardError("keyword not allowed: %s" % bad.group(1).upper())
    f = FILE_FUNCTIONS.search(scan)
    if f:
        raise SQLGuardError("file / external functions are not allowed: %s" % f.group(1))
    allowed = {t.lower() for t in allowed_tables}
    ctes = cte_names(scan)
    # functions whose syntax contains FROM (EXTRACT(year FROM ts), TRIM(BOTH FROM s), ...) are not table references
    scan = re.sub(r"\b(extract|substring|trim|position|overlay)\s*\([^()]*\)", "fn()", scan, flags=re.IGNORECASE)
    for m in re.finditer(r"\b(?:from|join)\s+([\w\.\"]+)(\s*\()?", scan, flags=re.IGNORECASE):
        target, is_call = m.group(1).replace('"', "").lower(), bool(m.group(2))
        if target in ("(", "lateral"):
            continue
        if is_call:
            if target not in SAFE_TABLE_FUNCTIONS:
                raise SQLGuardError("table function not allowed: %s" % target)
            continue
        if target in ctes or target in allowed:
            continue
        raise SQLGuardError("unknown or non-allow-listed table: %s (use schema-qualified marts.* or core.* tables)" % target)
    return "SELECT * FROM (\n%s\n) AS guarded_query LIMIT %d" % (body, max_rows)


def allowed_tables_from(con) -> List[str]:
    rows = con.execute("SELECT table_schema || '.' || table_name FROM information_schema.tables "
                       "WHERE table_schema IN ('core', 'marts')").fetchall()
    return [r[0] for r in rows]
