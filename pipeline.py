"""End-to-end orchestrator for the FinTech Product Analytics & Decision Intelligence Platform.

    extract -> validate (raw) -> transform -> validate (curated, gate) -> load warehouse + marts
    -> SQL analytics -> KPIs -> anomalies -> experiments -> segmentation -> charts
    -> Power BI extracts -> AI executive summary -> HTML dashboard -> data dictionary

Usage:
    python pipeline.py                         # run on existing raw files
    python pipeline.py --generate              # regenerate synthetic sources first
    python pipeline.py --generate --n-customers 5000 --offline-ai
    python pipeline.py --steps kpis,anomalies,ai_summary

Every run writes outputs/run_logs/run_<id>.json (step status, timings, row counts) and exits
non-zero if a step fails or the curated-layer data-quality gate finds a critical issue.
ALL DATA IS SYNTHETIC.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from python.config import Settings, get_settings  # noqa: E402
from python.io_utils import read_json, write_json  # noqa: E402

STEPS = ["generate", "extract", "validate_raw", "transform", "validate_clean", "load", "sql_analytics", "kpis",
         "anomalies", "experiments", "segmentation", "charts", "powerbi_export", "ai_summary", "dashboard",
         "data_dictionary"]
DEFAULT_STEPS = [s for s in STEPS if s != "generate"]

log = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, settings: Settings, run_id: str):
        self.s = settings
        self.run_id = run_id
        self.state: Dict = {}
        self.manifest: Dict = {"run_id": run_id, "started_at": datetime.now().isoformat(timespec="seconds"),
                               "settings": {"base_dir": str(settings.base_dir), "n_customers": settings.n_customers,
                                            "seed": settings.seed, "window": [settings.start_date, settings.end_date]},
                               "steps": []}

    # ------------------------------------------------------------ steps
    def step_generate(self):
        from python.generate_data import generate
        counts = generate(self.s)
        return {"rows": int(sum(counts.values())), "tables": counts}

    def step_extract(self):
        from etl.extract import extract
        raw, lineage = extract(self.s)
        self.state["raw"] = raw
        out = self.s.outputs_dir / "data_quality"
        out.mkdir(parents=True, exist_ok=True)
        lineage.to_csv(out / "extract_lineage.csv", index=False)
        return {"rows": int(lineage["rows"].sum()), "tables": int(len(lineage))}

    def _contracts(self):
        if "contracts" not in self.state:
            from data_quality.runner import load_contracts
            self.state["contracts"] = load_contracts(self.s.contracts_path)
        return self.state["contracts"]

    def _fingerprint_path(self, stage: str) -> Path:
        return self.s.outputs_dir / "data_quality" / ("schema_fingerprint_%s.json" % stage)

    def _validate(self, stage: str, tables: Dict[str, pd.DataFrame]):
        from data_quality.runner import run_checks, schema_fingerprint, summarize
        fp_path = self._fingerprint_path(stage)
        previous = read_json(fp_path) if fp_path.exists() else None
        res = run_checks(tables, self._contracts(), stage, pd.Timestamp(self.s.end_date), previous)
        out = self.s.outputs_dir / "data_quality"
        res.to_csv(out / ("dq_results_%s.csv" % stage), index=False)
        write_json(schema_fingerprint(tables), fp_path)
        summary = summarize(res)
        self.state["dq_" + stage] = (res, summary)
        return summary

    def step_validate_raw(self):
        summary = self._validate("raw", self.state["raw"])
        return {k: summary[k] for k in ("checks_run", "critical_failures", "warnings", "dq_score")}

    def step_transform(self):
        from etl.transform import Transformer
        from etl.load import write_processed, write_quarantine
        t = Transformer(self._contracts(), pd.Timestamp(self.s.end_date))
        clean, cleaning_log, quarantine = t.transform(self.state["raw"])
        self.state.update(clean=clean, cleaning_log=cleaning_log)
        write_processed(clean, self._contracts(), self.s)
        write_quarantine(quarantine, self.s)
        cleaning_log.to_csv(self.s.outputs_dir / "data_quality" / "cleaning_log.csv", index=False)
        return {"rows_out": int(sum(len(d) for d in clean.values())),
                "rows_quarantined": int(sum(len(d) for d in quarantine.values())),
                "rules_fired": int((cleaning_log["rows_affected"] > 0).sum())}

    def step_validate_clean(self):
        from data_quality.report import render_html, render_markdown
        from data_quality.runner import gate, injected_issue_recall
        summary = self._validate("clean", self.state["clean"])
        if "dq_raw" not in self.state:
            self._validate("raw", self.state["raw"])
        raw_res, raw_summary = self.state["dq_raw"]
        clean_res, _ = self.state["dq_clean"]
        manifest_path = self.s.raw_dir / "_injected_issues.json"
        recall = injected_issue_recall(raw_res, read_json(manifest_path)) if manifest_path.exists() else None
        out = self.s.outputs_dir / "data_quality"
        if recall is not None:
            recall.to_csv(out / "injected_issue_recall.csv", index=False)
        render_html(raw_res, clean_res, raw_summary, summary, self.state["cleaning_log"], recall,
                    out / "data_quality_report.html", self.run_id)
        render_markdown(raw_summary, summary, clean_res, self.state["cleaning_log"], recall, out / "data_quality_summary.md")
        write_json({"raw": raw_summary, "clean": summary,
                    "recall": None if recall is None else {"detected": int(recall["detected"].sum()), "total": int(len(recall))}},
                   out / "dq_summary.json")
        ok, blocking = gate(clean_res)
        if not ok:
            raise RuntimeError("Data-quality gate failed: %d critical check(s) on the curated layer:\n%s" % (
                len(blocking), blocking[["table", "check", "column", "failed_rows", "details"]].to_string(index=False)))
        return {k: summary[k] for k in ("checks_run", "critical_failures", "warnings", "dq_score")}

    def step_load(self):
        from etl.load import build_warehouse
        stats = build_warehouse(self.s, self._contracts())
        stats.to_csv(self.s.outputs_dir / "data_quality" / "load_stats.csv", index=False)
        return {"objects": int(len(stats)), "core_rows": int(stats.loc[stats["layer"] == "core", "rows"].sum())}

    def step_sql_analytics(self):
        from python.run_sql_analytics import run_all
        m = run_all(self.s)
        return {"queries": int(len(m)), "total_ms": float(m["runtime_ms"].sum())}

    def step_kpis(self):
        from python.kpis import compute_kpis
        snap = compute_kpis(self.s)
        return {"monthly_kpis": len(snap["monthly"]), "reporting_month": snap["reporting_month"]}

    def step_anomalies(self):
        from python.anomaly_detection import run
        res = run(self.s)
        return {"flagged_days": res["flagged_days"], "episodes": len(res["episodes"])}

    def step_experiments(self):
        from python.experiment_analysis import run
        res = run(self.s)
        return {k: v["decision"] for k, v in res.items()}

    def step_segmentation(self):
        from python.segmentation import run
        res = run(self.s)
        return {"k": res["kmeans"]["k"], "silhouette": res["kmeans"]["silhouette"]}

    def step_charts(self):
        from python.visualize import build_all
        files = build_all(self.s)
        return {"charts": len(files)}

    def step_powerbi_export(self):
        from python.powerbi_export import export
        files = export(self.s)
        return {"files": len(files)}

    def step_ai_summary(self):
        from ai_analyst.summarizer import generate_summary
        res = generate_summary(self.s, offline=self.s.offline_ai)
        return {"mode": res["mode"], "grounded": res["validation"]["grounded"], "facts": res["facts_used"]}

    def step_dashboard(self):
        from python.build_dashboard import build
        return {"path": str(build(self.s))}

    def step_data_dictionary(self):
        from python.build_data_dictionary import build
        path = build(self.s)
        return {"path": str(path)}

    # ------------------------------------------------------------ driver
    def run(self, steps: List[str]) -> bool:
        ok = True
        for name in steps:
            fn: Callable = getattr(self, "step_" + name)
            t0 = time.time()
            log.info("> %s", name)
            try:
                info = fn() or {}
                status = "success"
            except Exception as exc:  # keep going only for non-critical analytics steps
                info = {"error": str(exc).splitlines()[0][:300]}
                status = "failed"
                log.error("step %s failed: %s", name, exc)
                log.debug(traceback.format_exc())
                ok = False
            secs = round(time.time() - t0, 2)
            self.manifest["steps"].append({"step": name, "status": status, "seconds": secs, **{"info": info}})
            log.info("  %s in %.1fs %s", status, secs, info)
            if status == "failed" and name in ("generate", "extract", "transform", "validate_clean", "load"):
                log.error("Stopping: '%s' is a blocking step.", name)
                break
        self.manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.manifest["status"] = "success" if ok else "failed"
        write_json(self.manifest, self.s.outputs_dir / "run_logs" / ("run_%s.json" % self.run_id))
        write_json(self.manifest, self.s.outputs_dir / "run_logs" / "latest_run.json")
        return ok


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Run the analytics pipeline (synthetic data).")
    p.add_argument("--generate", action="store_true", help="regenerate the synthetic raw files first")
    p.add_argument("--n-customers", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--base-dir", help="write data/outputs under this directory (default: repo root)")
    p.add_argument("--offline-ai", action="store_true", help="use the deterministic summariser (no API call)")
    p.add_argument("--skip-ai", action="store_true", help="skip the AI summary step")
    p.add_argument("--steps", help="comma-separated subset of: " + ",".join(STEPS))
    args = p.parse_args(argv)

    overrides = {}
    if args.n_customers:
        overrides["n_customers"] = args.n_customers
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.base_dir:
        overrides["base_dir"] = Path(args.base_dir)
    if args.offline_ai:
        overrides["offline_ai"] = True
    settings = get_settings(**overrides)
    settings.ensure_dirs()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = settings.outputs_dir / "run_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(log_dir / ("run_%s.log" % run_id), encoding="utf-8")])

    steps = args.steps.split(",") if args.steps else list(DEFAULT_STEPS)
    if args.generate and "generate" not in steps:
        steps = ["generate"] + steps
    if args.skip_ai:
        steps = [s for s in steps if s != "ai_summary"]
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        p.error("unknown steps: %s" % unknown)
    # steps that need in-memory frames from earlier steps
    if "validate_raw" in steps or "transform" in steps:
        if "extract" not in steps:
            steps.insert(steps.index("validate_raw") if "validate_raw" in steps else steps.index("transform"), "extract")
    if "validate_clean" in steps and "transform" not in steps:
        p.error("validate_clean needs transform in the same run")

    log.info("Run %s | steps: %s | base: %s", run_id, ", ".join(steps), settings.base_dir)
    ok = Pipeline(settings, run_id).run(steps)
    log.info("Run %s finished: %s", run_id, "SUCCESS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
