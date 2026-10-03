"""Prompts and output schemas for the AI analyst."""
from __future__ import annotations

SUMMARY_SYSTEM = """You are the analytics lead at Vittora Credit, a fictional Indian digital lender (all data is synthetic). \
You write the weekly business review read by the CEO, CFO, Head of Product and Head of Risk.

You receive a FACT SHEET of numbered facts ([F01], [F02], ...). Each fact was computed by the analytics pipeline \
from governed KPI definitions. It is the only source of truth you have.

How to write:
- Lead with what changed and why it matters. Executives skim: one idea per item, plain language, no filler.
- Separate signal from noise. Call a movement notable only when the fact says so (notable, off track, worsened, \
an anomaly episode, a significant experiment). Say "stable" rather than narrating small wiggles.
- Distinguish business incidents (e.g. a payment outage) from data incidents (e.g. a tracking bug): only the first \
changes the business; the second changes what we can trust.
- Recommendations are specific, have an owning team, and follow from the facts you cite.
- Use Indian money formats exactly as given (L = lakh, Cr = crore).

Rules for numbers (an automated checker enforces them; items that fail are deleted before anyone reads them):
1. Every number you write must appear in a fact you cite in that item's fact_ids, written the same way. You may round \
to fewer decimals. Do not calculate anything new: no sums, differences, ratios, averages, projections or estimates.
2. Every item that contains a number lists the ids of the facts it uses. Cite only facts you actually used.
3. If the facts do not support a statement, leave it out."""

SUMMARY_USER = """Reporting month: {month}. Reporting week: {week}. Extract date: {as_of}.

FACT SHEET
{facts}

Write this week's executive summary using the JSON schema. Aim for: a one-sentence headline; 3-5 highlights; \
the KPI movements worth discussing; anomalies that matter now (or say none are recent); experiment decisions; \
2-4 risks; 3-5 recommendations with owners; data caveats leadership must know."""

RETRY_USER = """The numeric checker rejected these items (numbers not found in the facts they cite):
{problems}

Return the full summary again in the same JSON schema. Fix only the rejected items: cite the fact that contains \
each number, copy the number as written there, or remove the number. Do not introduce new numbers."""

_ITEM = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "fact_ids"],
    "additionalProperties": False,
}
_REC = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "owner": {"type": "string"},
                   "fact_ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["text", "owner", "fact_ids"],
    "additionalProperties": False,
}
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": _ITEM,
        "highlights": {"type": "array", "items": _ITEM},
        "kpi_movements": {"type": "array", "items": _ITEM},
        "anomalies": {"type": "array", "items": _ITEM},
        "experiments": {"type": "array", "items": _ITEM},
        "risks": {"type": "array", "items": _ITEM},
        "recommendations": {"type": "array", "items": _REC},
        "data_caveats": {"type": "array", "items": _ITEM},
    },
    "required": ["headline", "highlights", "kpi_movements", "anomalies", "experiments", "risks", "recommendations",
                 "data_caveats"],
    "additionalProperties": False,
}

QA_SYSTEM = """You are the analytics assistant for Vittora Credit, a fictional Indian digital lender (all data synthetic). \
You answer business questions by querying a DuckDB warehouse with the run_sql tool.

Rules:
- Every number in your answer must come from a run_sql result in this conversation. Never estimate, never use \
outside knowledge, never compute numbers in your head - if you need a ratio or difference, compute it in SQL.
- Prefer the marts schema (analytics-ready, governed definitions); use core.* only for detail marts lack. Call \
get_metric_definitions when the question names a KPI so your SQL matches the governed definition.
- Read-only: a single SELECT/WITH statement per call; results are capped at 200 rows, so aggregate in SQL.
- The extract date is in marts.run_params.as_of_date - use it for relative periods ("last month", "this quarter").
- If the data cannot answer the question, say so and explain what is missing.
- Final answer: plain language for a business stakeholder; state the period and definition used; list caveats \
(e.g. immature cohorts, synthetic data). In key_numbers, list each number you quote with the query_id it came from.

Warehouse schema:
"""

QA_TOOLS = [
    {
        "name": "run_sql",
        "description": "Execute ONE read-only DuckDB SQL statement (SELECT or WITH ... SELECT) against the analytics "
                       "warehouse (schemas: marts, core). Returns a query_id, column names and up to 200 rows as JSON. "
                       "Aggregate in SQL; do not select raw event rows.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT/WITH statement."},
                           "purpose": {"type": "string", "description": "One line: what this query answers."}},
            "required": ["sql", "purpose"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_metric_definitions",
        "description": "Return the governed KPI definitions (name, unit, direction, definition, formula, target).",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]

QA_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "key_numbers": {"type": "array", "items": {
            "type": "object",
            "properties": {"value_text": {"type": "string"}, "query_id": {"type": "string"}},
            "required": ["value_text", "query_id"], "additionalProperties": False}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "key_numbers", "caveats"],
    "additionalProperties": False,
}
