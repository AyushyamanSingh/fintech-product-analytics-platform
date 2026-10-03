"""Render the data-quality results as a self-contained HTML report + a Markdown summary."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

CSS = """
:root{--surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--good:#0ca30c;--warn:#b07800;--crit:#d03b3b;--accent:#2a78d6;--card:#ffffff}
@media (prefers-color-scheme:dark){:root{--surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--good:#0ca30c;--warn:#fab219;--crit:#e66767;--accent:#3987e5;--card:#1a1a19}}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}p.sub{color:var(--ink2);margin:0 0 20px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;border:1px solid var(--grid);color:var(--ink2)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--grid);border-radius:10px;padding:14px}
.card .k{color:var(--ink2);font-size:12px}.card .v{font-size:26px;font-weight:600;margin-top:2px}
.card .d{color:var(--muted);font-size:12px}
.tbl{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--grid);border-radius:10px;overflow:hidden}
.tbl th,.tbl td{padding:7px 10px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top;font-size:13px}
.tbl th{color:var(--ink2);font-weight:600;background:var(--surface)}.num{text-align:right;font-variant-numeric:tabular-nums}
.wrap{overflow-x:auto}.crit{color:var(--crit);font-weight:600}.warn{color:var(--warn);font-weight:600}.ok{color:var(--good);font-weight:600}
code{font-size:12px}small{color:var(--muted)}
"""


def _status_cell(status: str, severity: str) -> str:
    if status == "pass":
        return '<span class="ok">&#10003; pass</span>'
    if severity == "critical":
        return '<span class="crit">&#9888; critical</span>'
    return '<span class="warn">&#9679; warning</span>'


def _table(df: pd.DataFrame, num_cols=()) -> str:
    if df.empty:
        return "<p><small>None.</small></p>"
    head = "".join("<th class='num'>%s</th>" % html.escape(str(c)) if c in num_cols else "<th>%s</th>" % html.escape(str(c))
                   for c in df.columns)
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            raw_html = isinstance(v, str) and v.startswith("<span")
            text = v if raw_html else html.escape("" if pd.isna(v) else (format(v, ",") if isinstance(v, int) else str(v)))
            cells.append("<td class='num'>%s</td>" % text if c in num_cols else "<td>%s</td>" % text)
        rows.append("<tr>%s</tr>" % "".join(cells))
    return "<div class='wrap'><table class='tbl'><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>" % (head, "".join(rows))


def _issues(df: pd.DataFrame) -> pd.DataFrame:
    f = df[df["status"] == "fail"].copy()
    if f.empty:
        return f
    f["result"] = [_status_cell(s, v) for s, v in zip(f["status"], f["severity"])]
    f["failure_rate"] = (100 * f["failure_rate"]).map(lambda x: "%.3f%%" % x)
    f = f.sort_values(["severity", "failed_rows"], ascending=[True, False])
    return f[["result", "table", "check", "column", "failed_rows", "failure_rate", "details", "sample"]]


def render_html(raw: pd.DataFrame, clean: pd.DataFrame, raw_summary: Dict, clean_summary: Dict,
                cleaning_log: pd.DataFrame, recall: Optional[pd.DataFrame], out_path: Path, run_id: str) -> Path:
    q_rows = int(cleaning_log.loc[cleaning_log["action"] == "quarantine", "rows_affected"].sum()) if len(cleaning_log) else 0
    cards = [
        ("DQ score - raw", "%.1f" % raw_summary["dq_score"], "weighted pass rate, %d checks" % raw_summary["checks_run"]),
        ("DQ score - curated", "%.1f" % clean_summary["dq_score"], "after ETL rules"),
        ("Critical failures", "%d &rarr; %d" % (raw_summary["critical_failures"], clean_summary["critical_failures"]),
         "raw &rarr; curated (0 required to publish)"),
        ("Warnings", "%d &rarr; %d" % (raw_summary["warnings"], clean_summary["warnings"]), "raw &rarr; curated"),
        ("Rows quarantined", format(q_rows, ","), "kept for review, not deleted"),
        ("ETL rules fired", str(int((cleaning_log["rows_affected"] > 0).sum()) if len(cleaning_log) else 0),
         "see cleaning log"),
    ]
    cards_html = "".join("<div class='card'><div class='k'>%s</div><div class='v'>%s</div><div class='d'>%s</div></div>" % c
                         for c in cards)

    mat = pd.DataFrame(raw_summary["by_table"]).rename(columns={"failed": "raw_failed", "critical_failed": "raw_critical"})
    cm = pd.DataFrame(clean_summary["by_table"]).rename(columns={"failed": "curated_failed", "critical_failed": "curated_critical",
                                                                 "checks": "curated_checks"})
    matrix = mat.merge(cm, on="table", how="outer").fillna(0)
    for c in matrix.columns[1:]:
        matrix[c] = matrix[c].astype(int)

    recall_html = ""
    if recall is not None and len(recall):
        rc = recall.copy()
        rc["detected"] = rc["detected"].map(lambda d: '<span class="ok">&#10003; yes</span>' if d else '<span class="crit">&#10007; no</span>')
        rate = 100.0 * recall["detected"].mean()
        recall_html = ("<h2>Framework recall against planted defects</h2><p class='sub'>The generator records every defect it "
                       "injects (<code>data/raw/_injected_issues.json</code>). %d of %d defect types were caught by the raw-layer "
                       "checks (%.0f%% recall).</p>%s" % (recall["detected"].sum(), len(recall), rate,
                                                          _table(rc[["table", "column", "issue", "rows_affected", "detected", "detected_by"]],
                                                                 num_cols=("rows_affected",))))

    log = cleaning_log.copy()
    body = """
<main>
<h1>Data Quality Report</h1>
<p class="sub">Run <code>%(run)s</code> &middot; generated %(ts)s &middot; <span class="badge">synthetic data</span>
&middot; contract-driven checks on the raw extract and the curated layer</p>
<div class="cards">%(cards)s</div>
<h2>Checks by table</h2>%(matrix)s
<h2>Open issues on the curated layer</h2>
<p class="sub">What remains after ETL. Critical failures would have blocked publishing; warnings are published with a note.</p>%(clean)s
<h2>Issues found in the raw extract</h2>
<p class="sub">Detected on arrival, then fixed, standardised or quarantined by <code>etl/transform.py</code>.</p>%(raw)s
<h2>ETL cleaning log</h2>%(log)s
%(recall)s
<h2>Method</h2>
<p class="sub">Checks are declared in <code>data_quality/contracts.yaml</code>: schema (missing / unexpected columns, type drift,
drift versus the previous run), completeness (not-null), uniqueness (primary and composite keys), validity (accepted values,
ranges, patterns), timeliness (date ordering, future dates, freshness), referential integrity (foreign keys), plausibility
(robust z-score outliers, cross-field rules) and cross-table reconciliations (ledger vs schedule, events vs backend).
DQ score = weighted share of passing checks (critical = 3, warning = 1).</p>
</main>""" % {
        "run": html.escape(run_id), "ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "cards": cards_html,
        "matrix": _table(matrix, num_cols=tuple(matrix.columns[1:])),
        "clean": _table(_issues(clean), num_cols=("failed_rows",)),
        "raw": _table(_issues(raw), num_cols=("failed_rows",)),
        "log": _table(log, num_cols=("rows_affected",)), "recall": recall_html,
    }
    doc = "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" \
          "<title>Data Quality Report</title><style>%s</style></head><body>%s</body></html>" % (CSS, body)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def render_markdown(raw_summary: Dict, clean_summary: Dict, clean: pd.DataFrame, cleaning_log: pd.DataFrame,
                    recall: Optional[pd.DataFrame], out_path: Path) -> Path:
    lines = ["# Data Quality Summary", "", "_Synthetic data. Generated by `data_quality/report.py`._", "",
             "| Metric | Raw extract | Curated layer |", "|---|---:|---:|",
             "| Checks run | %d | %d |" % (raw_summary["checks_run"], clean_summary["checks_run"]),
             "| DQ score (weighted pass rate) | %.1f | %.1f |" % (raw_summary["dq_score"], clean_summary["dq_score"]),
             "| Critical failures | %d | %d |" % (raw_summary["critical_failures"], clean_summary["critical_failures"]),
             "| Warnings | %d | %d |" % (raw_summary["warnings"], clean_summary["warnings"]), ""]
    if recall is not None and len(recall):
        lines += ["Planted-defect recall: **%d / %d** defect types detected on the raw layer." %
                  (recall["detected"].sum(), len(recall)), ""]
    open_issues = clean[clean["status"] == "fail"]
    lines += ["## Open issues on the curated layer", ""]
    if open_issues.empty:
        lines.append("None.")
    else:
        lines += ["| Severity | Table | Check | Failed rows | Details |", "|---|---|---|---:|---|"]
        for _, r in open_issues.iterrows():
            lines.append("| %s | %s | `%s` | %s | %s |" % (r["severity"], r["table"], r["check"], format(int(r["failed_rows"]), ","),
                                                         str(r["details"]).replace("|", "/")))
    lines += ["", "## ETL rules applied", "", "| Table | Rule | Action | Rows |", "|---|---|---|---:|"]
    for _, r in cleaning_log.iterrows():
        lines.append("| %s | %s | %s | %s |" % (r["table"], r["rule"], r["action"], format(int(r["rows_affected"]), ",")))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path
