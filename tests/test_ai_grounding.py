"""The AI layer's safety net: number extraction, grounding validation and the SQL guard."""
import pytest

from ai_analyst.grounding import extract_numbers, validate_answer, validate_items
from ai_analyst.sql_guard import SQLGuardError, validate_sql

FACTS = [
    {"id": "F01", "topic": "kpi", "statement": "Gross revenue (Jun 2026): ₹60.58 L; prior month ₹58.71 L (+3.2%)."},
    {"id": "F02", "topic": "kpi", "statement": "Approval rate (Jun 2026): 61.9%; prior month 63.9% (-2.0 pp)."},
    {"id": "F03", "topic": "kpi", "statement": "Loans disbursed (Jun 2026): 1,316; prior month 1,374 (-4.2%)."},
]


def item(text, ids, section="highlights"):
    return {"section": section, "text": text, "fact_ids": ids}


def test_number_extraction_handles_indian_formats():
    nums = {n["value"] for n in extract_numbers("Revenue ₹60.58 L, AUM ₹29.69 Cr, 1,23,456 loans, +3.2%, -2.0 pp, 3.5x")}
    assert {60.58, 29.69, 123456.0, 3.2, 2.0, 3.5} <= nums


def test_dates_ids_and_versions_are_not_metrics():
    text = "On 14 Aug 2025 (Q3 2025, FY2026) EXP-ONB-2026-01 on app 5.2.0 for P07 [F03] in 2026-06 within 7 days, 30+ DPD"
    assert extract_numbers(text) == []


def test_grounded_text_passes():
    v = validate_items([item("Revenue rose to ₹60.58 L (+3.2%).", ["F01"]),
                        item("Approval rate eased to 61.9% (-2.0 pp).", ["F02"])], FACTS)
    assert v["grounded"], v["problems"]


def test_rounding_to_fewer_decimals_is_allowed():
    assert validate_items([item("Approval rate was about 62%.", ["F02"])], FACTS)["grounded"]


def test_invented_number_fails():
    v = validate_items([item("Revenue rose to ₹61.00 L.", ["F01"])], FACTS)
    assert not v["grounded"] and v["problems"][0]["issue"] == "numbers not found in cited facts"


def test_number_from_wrong_fact_fails():
    v = validate_items([item("Loans disbursed: 1,316.", ["F02"])], FACTS)
    assert not v["grounded"]


def test_numbers_without_citation_fail():
    v = validate_items([item("Approval rate 61.9%.", [])], FACTS)
    assert not v["grounded"] and v["problems"][0]["issue"] == "numbers without citation"


def test_unknown_fact_id_flagged():
    v = validate_items([item("Stable quarter.", ["F99"])], FACTS)
    assert not v["grounded"]


def test_qa_answer_validation_understands_scaling():
    results = {"Q1": {"rows": [{"approval_rate": 0.6192, "disbursed": 62200000.0, "loans": 1316}]}}
    assert validate_answer("Approval was 61.9% on 1,316 loans worth ₹6.22 Cr.", results)["grounded"]
    assert not validate_answer("Approval was 64.0%.", results)["grounded"]


ALLOWED = ["marts.fct_loan_performance", "core.loans", "marts.run_params"]


def test_sql_guard_allows_analytics_queries():
    sql = ("WITH x AS (SELECT product_id, EXTRACT(year FROM disbursed_ts) AS y FROM marts.fct_loan_performance) "
           "SELECT x.product_id, COUNT(*) FROM x CROSS JOIN marts.run_params p GROUP BY 1")
    wrapped = validate_sql(sql, ALLOWED)
    assert wrapped.startswith("SELECT * FROM (") and wrapped.rstrip().endswith("LIMIT 200")


@pytest.mark.parametrize("sql", [
    "DROP TABLE core.loans",
    "SELECT 1; DELETE FROM core.loans",
    "SELECT * FROM read_csv('C:/secrets.csv')",
    "SELECT * FROM loans",
    "SELECT * FROM core.customers",
    "COPY core.loans TO 'out.csv'",
    "WITH a AS (SELECT 1) INSERT INTO core.loans SELECT * FROM a",
])
def test_sql_guard_blocks_unsafe_queries(sql):
    with pytest.raises(SQLGuardError):
        validate_sql(sql, ALLOWED)


def test_keywords_inside_strings_do_not_trip_the_guard():
    validate_sql("SELECT * FROM core.loans WHERE loan_status = 'drop table'", ALLOWED)
