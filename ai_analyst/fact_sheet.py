"""Build the fact sheet: every number the AI analyst is allowed to use, with an id and a source.

Facts are plain sentences with pre-formatted numbers (so the model can copy them verbatim) plus
the structured values behind them. Sources: KPI snapshot, anomaly episodes, experiment results,
segmentation, data-quality summary and selected SQL analytics outputs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from python.config import Settings, get_settings
from python.io_utils import fmt_inr, write_json


def _month(period: str) -> str:
    return pd.Timestamp(period + "-01").strftime("%b %Y")


def _read_json(path: Path) -> Optional[Dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _sql(settings: Settings, name: str) -> Optional[pd.DataFrame]:
    p = settings.outputs_dir / "sql_results" / (name + ".csv")
    return pd.read_csv(p) if p.exists() else None


class FactSheet:
    def __init__(self):
        self.facts: List[Dict] = []

    def add(self, topic: str, statement: str, source: str, **data) -> str:
        fid = "F%02d" % (len(self.facts) + 1)
        self.facts.append({"id": fid, "topic": topic, "statement": statement, "source": source, "data": data})
        return fid


def build_fact_sheet(settings: Optional[Settings] = None) -> Dict:
    settings = settings or get_settings()
    fs = FactSheet()
    out = settings.outputs_dir

    snap = _read_json(out / "kpis" / "kpi_snapshot.json")
    if snap:
        for k in snap["monthly"]:
            s = "%s (%s): %s" % (k["name"], _month(k["period"]), k["value_fmt"])
            if k["previous_value"] is not None:
                s += "; prior month %s (%s)" % (k["previous_fmt"], k["delta_fmt"])
            if k["yoy_value"] is not None:
                s += "; same month last year %s (%s)" % (k["yoy_fmt"], k["yoy_delta_fmt"])
            if k["target_status"]:
                s += "; target %s %s -> %s" % (k["target_op"], k["target_fmt"], k["target_status"].replace("_", " "))
            s += "; assessment: %s%s." % (k["assessment"], ", notable" if k["notable"] else "")
            if k.get("lag_note") and not k["is_reporting_month"]:
                s += " (Latest available period: %s.)" % k["lag_note"]
            fs.add("kpi_monthly", s, "outputs/kpis/kpi_snapshot.json", kpi=k["id"], period=k["period"],
                   value=k["value"], assessment=k["assessment"], notable=k["notable"], target_status=k["target_status"],
                   direction=k["direction"], delta_fmt=k["delta_fmt"], value_fmt=k["value_fmt"], name=k["name"])
        for w in snap["weekly"]:
            fs.add("kpi_weekly", "%s (week of %s): %s; prior week %s (%s); 4-week average %s (%s)." % (
                w["name"], pd.Timestamp(w["week_start"]).strftime("%d %b %Y"), w["value_fmt"], w["prior_week_fmt"],
                w["wow_delta_fmt"], w["avg_4w_fmt"], w["vs_4w_delta_fmt"]), "outputs/kpis/kpi_snapshot.json",
                kpi=w["id"], assessment=w["assessment"], notable=w["notable"], name=w["name"], value_fmt=w["value_fmt"],
                delta_fmt=w["wow_delta_fmt"])

    an = _read_json(out / "anomalies" / "anomaly_episodes.json")
    if an:
        eps = an["episodes"]
        recent_cut = (pd.Timestamp(settings.end_date) - pd.Timedelta(days=56)).strftime("%Y-%m-%d")
        recent = [e for e in eps if e["end"] >= recent_cut]
        fs.add("anomaly_summary", "Anomaly monitor: %d episodes flagged across the 24-month history; %d in the last 8 weeks "
               "(since %s)." % (len(eps), len(recent), pd.Timestamp(recent_cut).strftime("%d %b %Y")),
               "outputs/anomalies/anomaly_episodes.json", total=len(eps), recent=len(recent))
        for e in eps:
            label = "known event: %s" % e["known_context"] if e["known_context"] else "no known business event - investigate"
            fs.add("anomaly", "%s. Window %s to %s, %d day(s) flagged, severity %s (%s)." % (
                e["headline"], e["start"], e["end"], e["days_flagged"], e["severity"], label),
                "outputs/anomalies/anomaly_episodes.json", metric=e["metric"], start=e["start"], end=e["end"],
                severity=e["severity"], classification=e["classification"], recent=e["end"] >= recent_cut)

    ex = _read_json(out / "experiments" / "experiment_results.json")
    if ex:
        o = ex["EXP-ONB-2026-01"]
        p = o["primary"]
        fs.add("experiment", "EXP-ONB-2026-01 (onboarding redesign, %s): 7-day KYC completion %.2f%% treatment vs %.2f%% "
               "control, difference %+.2f pp (95%% CI %+.2f to %+.2f pp), relative uplift %+.1f%%, p-value %.4f; "
               "P(treatment better) %.1f%%." % (o["design"]["window"], 100 * p["treatment_rate"], 100 * p["control_rate"],
                                               100 * p["diff_abs"], 100 * p["ci_low"], 100 * p["ci_high"],
                                               100 * p["relative_uplift"], p["p_value"],
                                               100 * o["bayesian"]["prob_treatment_better"]),
               "outputs/experiments/experiment_results.json", experiment="EXP-ONB-2026-01")
        fs.add("experiment", "EXP-ONB-2026-01 design: %s users per arm required for a %.1f pp MDE; realised %s control / %s "
               "treatment; sample-ratio check p-value %.3f (no SRM)." % (
                   format(o["design"]["required_n_per_arm"], ","), 100 * o["design"]["planned_mde_abs"],
                   format(o["srm"]["control_n"], ","), format(o["srm"]["treatment_n"], ","), o["srm"]["p_value"]),
               "outputs/experiments/experiment_results.json", experiment="EXP-ONB-2026-01")
        g = o["guardrails"]
        fs.add("experiment", "EXP-ONB-2026-01 guardrails: approval rate %+.2f pp (%s), FPD30 %+.2f pp (%s), KYC support "
               "tickets %+.2f pp (%s). Decision: %s." % (
                   100 * g["approval_rate"]["diff_abs"], g["approval_rate"]["status"], 100 * g["fpd30_rate"]["diff_abs"],
                   g["fpd30_rate"]["status"], 100 * g["kyc_support_ticket_rate"]["diff_abs"],
                   g["kyc_support_ticket_rate"]["status"], o["decision"]),
               "outputs/experiments/experiment_results.json", experiment="EXP-ONB-2026-01")
        imp = o["impact"]
        fs.add("experiment", "EXP-ONB-2026-01 estimated impact at the post-launch run rate: about %s additional verified "
               "customers and %s additional first loans per year, worth about %s net revenue from first loans." % (
                   format(int(round(imp["incremental_kyc_per_year"])), ","),
                   format(int(round(imp["incremental_first_loans_per_year"])), ","),
                   fmt_inr(imp["incremental_net_revenue_per_year"])),
               "outputs/experiments/experiment_results.json", experiment="EXP-ONB-2026-01")
        for key in ("EXP-RPY-2025-11", "EXP-PRC-2025-06"):
            r = ex[key]
            p = r["primary"]
            fs.add("experiment", "%s (%s): %s %.2f%% treatment vs %.2f%% control, difference %+.2f pp (95%% CI %+.2f to "
                   "%+.2f pp), p-value %.4f. Decision: %s." % (
                       key, r["name"], r["primary_metric"].replace("_", " "), 100 * p["treatment_rate"],
                       100 * p["control_rate"], 100 * p["diff_abs"], 100 * p["ci_low"], 100 * p["ci_high"], p["p_value"],
                       r["decision"]), "outputs/experiments/experiment_results.json", experiment=key)

    funnel = _sql(settings, "01_funnel_conversion__funnel_overall")
    if funnel is not None:
        f = funnel.set_index("stage")
        fs.add("funnel", "Onboarding funnel (cohorts at least 30 days old): %s signups, %.2f%% completed KYC, %.2f%% submitted "
               "an application, %.2f%% received a loan; the largest single loss is signup to KYC completion (%s customers)." % (
                   format(int(f.loc["Signed up", "customers"]), ","), f.loc["KYC completed", "pct_of_signups"],
                   f.loc["Application submitted", "pct_of_signups"], f.loc["Disbursed", "pct_of_signups"],
                   format(int(f.loc["Signed up", "customers"] - f.loc["KYC completed", "customers"]), ",")),
               "outputs/sql_results/01_funnel_conversion__funnel_overall.csv")
    seg = _sql(settings, "02_funnel_dropoff__kyc_dropoff_by_segment")
    if seg is not None:
        plat = seg[seg["dimension"] == "platform"].set_index("segment")
        if {"web", "ios"}.issubset(plat.index):
            fs.add("funnel", "7-day KYC completion by platform: web %.2f%%, Android %.2f%%, iOS %.2f%%; web trails iOS by "
                   "%.2f pp." % (plat.loc["web", "kyc_7d_pct"], plat.loc["android", "kyc_7d_pct"], plat.loc["ios", "kyc_7d_pct"],
                                 plat.loc["web", "gap_to_best_pp"]),
                   "outputs/sql_results/02_funnel_dropoff__kyc_dropoff_by_segment.csv")
    ltv = _sql(settings, "05_customer_ltv__ltv_cac_by_channel")
    if ltv is not None:
        parts = []
        for _, r in ltv.iterrows():
            ratio = "n/a" if pd.isna(r["ltv_to_cac"]) else "%.1fx" % r["ltv_to_cac"]
            parts.append("%s %s (CAC per borrower %s)" % (r["acquisition_channel"], ratio, fmt_inr(r["cac_per_borrower"])))
        fs.add("unit_economics", "LTV/CAC by channel (cohorts with 12+ months of history): " + "; ".join(parts) + ".",
               "outputs/sql_results/05_customer_ltv__ltv_cac_by_channel.csv")
    fest = _sql(settings, "07_delinquency__festive_season_risk")
    if fest is not None:
        piv = fest.pivot(index="acquisition_channel", columns="period", values="fpd30_pct")
        if {"affiliate", "paid_social"}.issubset(piv.index):
            fs.add("risk", "First-loan FPD30 for loans disbursed in the Oct-Nov 2025 festive season vs Jun-Sep 2025: affiliate "
                   "%.2f%% vs %.2f%%, paid social %.2f%% vs %.2f%%, partnerships %.2f%% vs %.2f%%." % (
                       piv.loc["affiliate", "festive_oct_nov_2025"], piv.loc["affiliate", "baseline_jun_sep_2025"],
                       piv.loc["paid_social", "festive_oct_nov_2025"], piv.loc["paid_social", "baseline_jun_sep_2025"],
                       piv.loc["partnerships", "festive_oct_nov_2025"], piv.loc["partnerships", "baseline_jun_sep_2025"]),
                   "outputs/sql_results/07_delinquency__festive_season_risk.csv")
    feat = _sql(settings, "10_product_adoption__feature_adoption_impact")
    if feat is not None and "autopay" in set(feat["feature"]):
        a = feat.set_index("feature").loc["autopay"]
        fs.add("repayments", "Borrowers with autopay pay %.2f%% of instalments on time vs %.2f%% without (correlation, not "
               "causation); %.2f%% of borrowers have used autopay." % (a["on_time_pct_adopters"], a["on_time_pct_non_adopters"],
                                                                        a["adoption_pct"]),
               "outputs/sql_results/10_product_adoption__feature_adoption_impact.csv")
    camp = _sql(settings, "13_marketing_cac__campaign_scorecard")
    if camp is not None:
        nb = camp[camp["campaign_id"] == "CMP-202509-AFFNB"]
        if len(nb):
            r = nb.iloc[0]
            fs.add("marketing", "Campaign CMP-202509-AFFNB (Affiliate Network B, Sep 2025): spend %s, %s signups, %s funded "
                   "customers, cost per funded customer %s; flagged '%s'." % (
                       fmt_inr(r["spend"]), format(int(r["signups"]), ","), format(int(r["funded"]), ","),
                       fmt_inr(r["cost_per_funded"]), r["review_flag"]),
                   "outputs/sql_results/13_marketing_cac__campaign_scorecard.csv")

    sg = _read_json(out / "segments" / "segmentation_summary.json")
    if sg:
        bs = sorted(sg["business_segments"], key=lambda r: -(r.get("share_of_net_revenue_pct") or 0))
        fs.add("segments", "Business segments by share of net revenue: " + "; ".join(
            "%s %.1f%% of customers / %.1f%% of net revenue" % (r["business_segment"], r["share_of_customers_pct"],
                                                               r["share_of_net_revenue_pct"]) for r in bs) + ".",
               "outputs/segments/segmentation_summary.json")
        cl = sorted(sg["kmeans"]["clusters"], key=lambda r: -r["share_of_net_revenue_pct"])
        fs.add("segments", "K-Means (k=%d, silhouette %.3f) borrower clusters: " % (sg["kmeans"]["k"], sg["kmeans"]["silhouette"])
               + "; ".join("%s %.1f%% of borrowers / %.1f%% of net revenue" % (r["cluster_name"], r["share_of_borrowers_pct"],
                                                                               r["share_of_net_revenue_pct"]) for r in cl) + ".",
               "outputs/segments/segmentation_summary.json")

    dq = _read_json(out / "data_quality" / "dq_summary.json")
    if dq:
        s = "Data quality: DQ score %.1f on the raw extract and %.1f on the curated layer; critical failures %d -> %d; %d " \
            "warnings remain (documented open issues)" % (dq["raw"]["dq_score"], dq["clean"]["dq_score"],
                                                          dq["raw"]["critical_failures"], dq["clean"]["critical_failures"],
                                                          dq["clean"]["warnings"])
        if dq.get("recall"):
            s += "; %d of %d planted defect types detected" % (dq["recall"]["detected"], dq["recall"]["total"])
        fs.add("data_quality", s + ".", "outputs/data_quality/dq_summary.json")
        clean = pd.read_csv(out / "data_quality" / "dq_results_clean.csv")
        for _, r in clean[clean["status"] == "fail"].iterrows():
            fs.add("data_quality", "Open data-quality issue (%s): %s.%s %s - %s rows (%s)." % (
                r["severity"], r["table"], r["column"], r["check"], format(int(r["failed_rows"]), ","), r["details"]),
                "outputs/data_quality/dq_results_clean.csv", severity=r["severity"])

    sheet = {"as_of_date": settings.end_date, "synthetic_data": True,
             "reporting_month": snap["reporting_month"] if snap else None,
             "reporting_week": snap.get("reporting_week") if snap else None,
             "facts": fs.facts}
    return sheet


def save_fact_sheet(sheet: Dict, settings: Settings) -> Path:
    path = settings.outputs_dir / "ai" / "fact_sheet.json"
    write_json(sheet, path)
    return path


def facts_for_prompt(sheet: Dict) -> str:
    """Compact rendering for the model: id, topic and statement only (structured data stays local)."""
    return "\n".join("[%s] (%s) %s" % (f["id"], f["topic"], f["statement"]) for f in sheet["facts"])
