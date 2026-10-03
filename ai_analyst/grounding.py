"""Numeric grounding checks: no number reaches a stakeholder unless it exists in a cited source.

* Summaries: every number in an item must appear (exactly, or rounded to fewer decimals) in one of
  the facts that item cites; items with numbers must cite at least one known fact.
* Q&A: every number in the answer must match a value returned by the SQL the model executed
  (percent / lakh / crore scalings are understood).
Identifiers, dates, app versions and fact ids are stripped before checking.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December"
STRIP_PATTERNS = [
    r"\[F\d+\]",                                  # fact citations
    r"\bF\d{2,3}\b",                              # bare fact ids
    r"\b[A-Z]{2,5}(?:-[A-Z0-9]{2,6})+\b",         # ids like EXP-ONB-2026-01, CMP-202509-AFFNB
    r"\b[A-Z]{1,3}\d{2,}\b",                      # product / entity ids like P07, C000123
    r"\b\d+\.\d+\.\d+\b",                         # app versions 5.2.0
    r"\b\d{4}-\d{2}(?:-\d{2})?\b",                # ISO dates / months
    r"\b\d{1,2}\s+(?:%s)\.?\s+\d{4}\b" % MONTHS,  # 14 Aug 2025
    r"\b\d{1,2}\s+(?:%s)\b" % MONTHS,             # 14 Aug
    r"\b(?:%s)\.?\s+\d{4}\b" % MONTHS,            # Aug 2025
    r"\b(?:%s)\s+\d{1,2}\b" % MONTHS,             # Aug 14
    r"\bQ[1-4]\s*\d{4}\b", r"\bFY\s?\d{2,4}\b",   # quarters, fiscal years
    r"\b(?:19|20)\d{2}\b",                        # bare years
    r"\b\d+-(?:day|week|month|year)s?\b",         # 7-day, 30-day windows (definitions, not results)
    r"\b\d+\+",                                   # thresholds: 30+ DPD, 12+ months
    r"\b(?:within|last|next|over|past|first|after|for)\s+\d+\s+(?:days?|weeks?|months?|years?|hours?)\b",
    r"\b(?:k|K)\s*=\s*\d+\b",                     # k=5
]
NUMBER = re.compile(r"(?P<sign>[+\-−])?\s?(?P<cur>₹)?\s?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                    r"\s?(?P<unit>%|pp|x\b|Cr\b|L\b|lakh\b|crore\b|k\b)?")
UNIT_SCALE = {"Cr": 1e7, "crore": 1e7, "L": 1e5, "lakh": 1e5, "k": 1e3}


def strip_non_metrics(text: str) -> str:
    for p in STRIP_PATTERNS:
        text = re.sub(p, " ", text)
    return text


def extract_numbers(text: str) -> List[Dict]:
    out = []
    for m in NUMBER.finditer(strip_non_metrics(text)):
        raw = m.group("num")
        core = raw.replace(",", "")
        decimals = len(core.split(".")[1]) if "." in core else 0
        out.append({"text": m.group(0).strip(), "value": float(core), "decimals": decimals, "unit": m.group("unit")})
    return out


def _matches(n: Dict, candidates: Iterable[float]) -> bool:
    """Exact value, or the narrative value is the candidate rounded to fewer decimals."""
    for c in candidates:
        if abs(c - n["value"]) < 1e-9:
            return True
        if abs(round(c, n["decimals"]) - n["value"]) < 1e-9:
            return True
    return False


def fact_numbers(statement: str) -> Set[float]:
    return {n["value"] for n in extract_numbers(statement)}


def validate_items(items: List[Dict], facts: List[Dict]) -> Dict:
    """items: [{"section", "text", "fact_ids"}]; facts: fact-sheet facts."""
    by_id = {f["id"]: f for f in facts}
    nums_by_id = {fid: fact_numbers(f["statement"]) for fid, f in by_id.items()}
    problems, checked = [], 0
    for it in items:
        nums = extract_numbers(it["text"])
        checked += len(nums)
        cited = [fid for fid in it.get("fact_ids", [])]
        unknown = [fid for fid in cited if fid not in by_id]
        if unknown:
            problems.append({"section": it["section"], "text": it["text"], "issue": "unknown fact ids", "detail": unknown})
        if nums and not [fid for fid in cited if fid in by_id]:
            problems.append({"section": it["section"], "text": it["text"], "issue": "numbers without citation",
                             "detail": [n["text"] for n in nums]})
            continue
        pool = set().union(*[nums_by_id[fid] for fid in cited if fid in by_id]) if cited else set()
        bad = [n["text"] for n in nums if not _matches(n, pool)]
        if bad:
            problems.append({"section": it["section"], "text": it["text"], "issue": "numbers not found in cited facts",
                             "detail": bad, "cited": cited})
    return {"grounded": not problems, "items_checked": len(items), "numbers_checked": checked, "problems": problems}


def summary_items(summary: Dict) -> List[Dict]:
    items = [{"section": "headline", "text": summary["headline"]["text"], "fact_ids": summary["headline"]["fact_ids"]}]
    for section in ("highlights", "kpi_movements", "anomalies", "experiments", "risks", "recommendations", "data_caveats"):
        for it in summary.get(section, []):
            items.append({"section": section, "text": it["text"], "fact_ids": it.get("fact_ids", [])})
    return items


def validate_summary(summary: Dict, facts: List[Dict]) -> Dict:
    return validate_items(summary_items(summary), facts)


def drop_ungrounded(summary: Dict, validation: Dict) -> Tuple[Dict, List[str]]:
    """Remove items that still fail validation after retries (never ship an unverified number)."""
    bad_texts = {p["text"] for p in validation["problems"]}
    removed: List[str] = []
    cleaned = dict(summary)
    for section in ("highlights", "kpi_movements", "anomalies", "experiments", "risks", "recommendations", "data_caveats"):
        kept = []
        for it in summary.get(section, []):
            if it["text"] in bad_texts:
                removed.append(it["text"])
            else:
                kept.append(it)
        cleaned[section] = kept
    if summary["headline"]["text"] in bad_texts:
        removed.append(summary["headline"]["text"])
        cleaned["headline"] = {"text": "Weekly business summary (headline withheld: failed numeric verification)", "fact_ids": []}
    return cleaned, removed


# ---------------------------------------------------------------- Q&A grounding
def result_values(rows: List[Dict]) -> List[float]:
    vals = []
    for r in rows:
        for v in r.values():
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, (int, float)):
                vals.append(float(v))
    return vals


def validate_answer(answer_text: str, results: Dict[str, Dict]) -> Dict:
    values = []
    for res in results.values():
        values += result_values(res.get("rows", []))
    candidates = set(values)
    candidates |= {v * 100 for v in values}                         # ratios shown as %
    for scale in (1e7, 1e5, 1e3):
        candidates |= {v / scale for v in values}                   # Cr / L / k
    problems = []
    nums = extract_numbers(answer_text)
    for n in nums:
        if not _matches(n, candidates):
            problems.append(n["text"])
    return {"grounded": not problems, "numbers_checked": len(nums), "ungrounded_numbers": problems}
