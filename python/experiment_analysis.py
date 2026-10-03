"""Experiment analysis: pre-registered design checks, inference and a decision readout.

For every registered experiment:
  * sample-ratio-mismatch (SRM) check - chi-square against the planned 50/50 split
  * two-proportion z-test, Wald CI on the absolute difference, delta-method CI on relative uplift
  * Bayesian Beta-Binomial: P(treatment > control) and expected loss
  * power: required n for the pre-registered MDE, achieved power, MDE at the realised n
  * guardrails evaluated as non-inferiority (pass / inconclusive / breach)
For the onboarding test additionally: novelty check (effect by week), heterogeneity by
platform / city tier with Holm correction, and business-impact sizing.

    python -m python.experiment_analysis
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from python.config import Settings, get_settings
from python.io_utils import fmt_inr, write_json

ALPHA = 0.05
POWER = 0.80


# ---------------------------------------------------------------- statistics
def two_proportion_test(xc: int, nc: int, xt: int, nt: int, alpha: float = ALPHA) -> Dict:
    if nc == 0 or nt == 0:
        nan = float("nan")
        return {"control_n": nc, "control_x": xc, "control_rate": nan, "treatment_n": nt, "treatment_x": xt,
                "treatment_rate": nan, "diff_abs": nan, "ci_low": nan, "ci_high": nan, "relative_uplift": nan,
                "rel_ci_low": nan, "rel_ci_high": nan, "z": nan, "p_value": nan, "significant": False}
    pc, pt = xc / nc, xt / nt
    diff = pt - pc
    zcrit = stats.norm.ppf(1 - alpha / 2)
    se = math.sqrt(pc * (1 - pc) / nc + pt * (1 - pt) / nt)
    p_pool = (xc + xt) / (nc + nt)
    se_pool = math.sqrt(p_pool * (1 - p_pool) * (1 / nc + 1 / nt))
    z = diff / se_pool if se_pool > 0 else 0.0
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))
    rel = diff / pc if pc > 0 else float("nan")
    if pc > 0 and pt > 0:
        se_log = math.sqrt((1 - pt) / (nt * pt) + (1 - pc) / (nc * pc))
        log_rr = math.log(pt / pc)
        rel_ci = (math.exp(log_rr - zcrit * se_log) - 1, math.exp(log_rr + zcrit * se_log) - 1)
    else:
        rel_ci = (float("nan"), float("nan"))
    return {"control_n": nc, "control_x": xc, "control_rate": pc, "treatment_n": nt, "treatment_x": xt,
            "treatment_rate": pt, "diff_abs": diff, "ci_low": diff - zcrit * se, "ci_high": diff + zcrit * se,
            "relative_uplift": rel, "rel_ci_low": rel_ci[0], "rel_ci_high": rel_ci[1], "z": z, "p_value": p_value,
            "significant": p_value < alpha}


def required_n_per_arm(p1: float, mde_abs: float, alpha: float = ALPHA, power: float = POWER) -> float:
    p2 = p1 + mde_abs
    if not 0 < p2 < 1:
        return float("inf")  # a lift this large is impossible from this baseline
    za, zb = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    pbar = (p1 + p2) / 2
    n = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / mde_abs ** 2
    return int(math.ceil(n))


def achieved_power(p1: float, p2: float, n_per_arm: float, alpha: float = ALPHA) -> float:
    se = math.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    return float(stats.norm.cdf(abs(p2 - p1) / se - stats.norm.ppf(1 - alpha / 2)))


def mde_at_n(p1: float, n_per_arm: float, alpha: float = ALPHA, power: float = POWER) -> float:
    lo, hi = 1e-5, min(0.5, 1 - p1 - 1e-6)  # the treatment rate must stay below 100%
    for _ in range(60):
        mid = (lo + hi) / 2
        if required_n_per_arm(p1, mid, alpha, power) > n_per_arm:
            lo = mid
        else:
            hi = mid
    return hi


def bayes_beta_binomial(xc: int, nc: int, xt: int, nt: int, draws: int = 200_000, seed: int = 11) -> Dict:
    rng = np.random.default_rng(seed)
    t = rng.beta(1 + xt, 1 + nt - xt, draws)
    c = rng.beta(1 + xc, 1 + nc - xc, draws)
    d = t - c
    return {"prob_treatment_better": float((d > 0).mean()),
            "expected_loss_if_ship": float(np.maximum(-d, 0).mean()),
            "credible_low": float(np.percentile(d, 2.5)), "credible_high": float(np.percentile(d, 97.5))}


def srm_check(n_control: int, n_treatment: int, expected_treatment_share: float = 0.5) -> Dict:
    total = n_control + n_treatment
    exp = [total * (1 - expected_treatment_share), total * expected_treatment_share]
    chi2, p = stats.chisquare([n_control, n_treatment], f_exp=exp)
    return {"control_n": n_control, "treatment_n": n_treatment, "treatment_share": n_treatment / total,
            "chi_square": float(chi2), "p_value": float(p), "srm_detected": bool(p < 0.001)}


def holm_adjust(pvals: List[float]) -> List[float]:
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvals[idx])
        adj[idx] = min(1.0, running)
    return adj.tolist()


def guardrail_status(res: Dict, margin: float, higher_is_worse: bool) -> str:
    """Non-inferiority on the deterioration d (positive = worse):
    pass if the whole CI of d is below the margin; breach if d is significantly > 0 and its point
    estimate exceeds the margin (or the whole CI exceeds it); otherwise inconclusive."""
    if higher_is_worse:
        d, lo, hi = res["diff_abs"], res["ci_low"], res["ci_high"]
    else:
        d, lo, hi = -res["diff_abs"], -res["ci_high"], -res["ci_low"]
    if any(math.isnan(v) for v in (d, lo, hi)):
        return "insufficient data"
    if hi <= margin:
        return "pass"
    if lo > margin or (lo > 0 and d > margin):
        return "breach"
    return "inconclusive"


def _metric(df: pd.DataFrame, col: str, mask: Optional[pd.Series] = None) -> Dict:
    d = df if mask is None else df[mask]
    g = d.groupby("variant")[col].agg(["sum", "count"]).reindex(["control", "treatment"]).fillna(0)
    return two_proportion_test(int(g.loc["control", "sum"]), int(g.loc["control", "count"]),
                               int(g.loc["treatment", "sum"]), int(g.loc["treatment", "count"]))


def _pp(x: float) -> str:
    return "%+.2f pp" % (100 * x)


def _pct(x: float) -> str:
    return "%.2f%%" % (100 * x)


# ---------------------------------------------------------------- data access
ONB_SQL = """
WITH u AS (
    SELECT a.customer_id, a.variant, a.platform, f.city_tier, f.signup_ts,
           CAST(date_trunc('week', a.assigned_ts) AS DATE) AS assignment_week,
           CAST(f.kyc_completed_7d AS INTEGER) AS kyc_7d,
           CAST(f.app_submitted_14d AS INTEGER) AS app_14d,
           CAST(f.disbursed_30d AS INTEGER) AS disb_30d
    FROM core.experiment_assignments a
    JOIN marts.fct_customer_funnel f ON f.customer_id = a.customer_id
    WHERE a.experiment_id = 'EXP-ONB-2026-01'
),
apps AS (
    SELECT u.customer_id,
           MAX(CASE WHEN ap.submitted_ts <= u.signup_ts + INTERVAL 30 DAY AND ap.decision IS NOT NULL THEN 1 ELSE 0 END) AS decided_30d,
           MAX(CASE WHEN ap.submitted_ts <= u.signup_ts + INTERVAL 30 DAY AND ap.decision = 'approved' THEN 1 ELSE 0 END) AS approved_30d
    FROM u JOIN core.applications ap ON ap.customer_id = u.customer_id
    GROUP BY u.customer_id
),
fl AS (
    SELECT customer_id, CAST(fpd30_mature AS INTEGER) AS fpd_mature, CAST(is_fpd30 AS INTEGER) AS fpd30
    FROM marts.fct_loan_performance WHERE loan_sequence_number = 1
),
tk AS (
    SELECT DISTINCT t.customer_id
    FROM core.support_tickets t JOIN u ON u.customer_id = t.customer_id
    WHERE t.category = 'kyc_issue' AND t.created_ts <= u.signup_ts + INTERVAL 7 DAY
)
SELECT u.*, COALESCE(apps.decided_30d, 0) AS decided_30d, COALESCE(apps.approved_30d, 0) AS approved_30d,
       COALESCE(fl.fpd_mature, 0) AS fpd_mature, COALESCE(fl.fpd30, 0) AS fpd30,
       CASE WHEN tk.customer_id IS NOT NULL THEN 1 ELSE 0 END AS kyc_ticket_7d
FROM u
LEFT JOIN apps ON apps.customer_id = u.customer_id
LEFT JOIN fl   ON fl.customer_id = u.customer_id
LEFT JOIN tk   ON tk.customer_id = u.customer_id
"""

PRE_PERIOD_SQL = """
SELECT COUNT(*) AS signups, AVG(CAST(kyc_completed_7d AS INTEGER)) AS kyc_7d_rate,
       COUNT(*) / (date_diff('day', DATE '2025-11-17', DATE '2026-01-11') / 7.0) AS weekly_signups
FROM marts.fct_customer_funnel
WHERE signup_platform <> 'web' AND signup_ts >= TIMESTAMP '2025-11-17' AND signup_ts < TIMESTAMP '2026-01-12'
"""

RPY_SQL = """
SELECT a.variant, CAST(l.autopay_enabled AS INTEGER) AS autopay,
       CAST(l.first_installment_dpd = 0 AS INTEGER) AS first_emi_on_time,
       CAST(l.first_due_date <= p.as_of_date - INTERVAL 30 DAY AS INTEGER) AS first_emi_mature
FROM core.experiment_assignments a
JOIN marts.fct_loan_performance l ON l.customer_id = a.customer_id AND l.disbursed_ts = a.assigned_ts
CROSS JOIN marts.run_params p
WHERE a.experiment_id = 'EXP-RPY-2025-11'
"""

PRC_SQL = """
SELECT a.variant, CAST(ap.application_status = 'disbursed' AS INTEGER) AS accepted
FROM core.experiment_assignments a
JOIN core.applications ap ON ap.customer_id = a.customer_id AND ap.decision_ts = a.assigned_ts
WHERE a.experiment_id = 'EXP-PRC-2025-06'
"""

IMPACT_SQL = """
WITH post AS (
    SELECT COUNT(*) * 365.0 / NULLIF(date_diff('day', DATE '2026-03-02', p.as_of_date) + 1, 0) AS annual_app_signups
    FROM marts.fct_customer_funnel f CROSS JOIN marts.run_params p
    WHERE f.signup_platform <> 'web' AND f.signup_ts >= TIMESTAMP '2026-03-02'
    GROUP BY p.as_of_date
),
conv AS (   -- of customers who complete KYC, share who get a loan within 30 days of signup (mature cohorts)
    SELECT AVG(CAST(disbursed_30d AS INTEGER)) AS kyc_to_loan_30d
    FROM marts.fct_customer_funnel WHERE kyc_completed_ts IS NOT NULL AND is_mature_30d
),
rev AS (    -- average lifetime-to-date net revenue of first loans disbursed >= 12 months ago
    SELECT AVG(total_revenue - credit_loss) AS net_revenue_per_first_loan
    FROM marts.fct_loan_performance lp CROSS JOIN marts.run_params p
    WHERE lp.loan_sequence_number = 1 AND lp.disbursed_ts < p.as_of_date - INTERVAL 12 MONTH
)
SELECT post.annual_app_signups, conv.kyc_to_loan_30d, rev.net_revenue_per_first_loan FROM post, conv, rev
"""


# ---------------------------------------------------------------- analyses
def analyse_onboarding(con) -> Dict:
    df = con.execute(ONB_SQL).df()
    pre = con.execute(PRE_PERIOD_SQL).df().iloc[0]
    n_c = int((df["variant"] == "control").sum())
    n_t = int((df["variant"] == "treatment").sum())
    srm = srm_check(n_c, n_t)

    baseline = float(pre["kyc_7d_rate"])
    planned_mde = 0.04  # smallest lift worth the build cost, sized to ~6 weeks of app traffic
    n_req = required_n_per_arm(baseline, planned_mde)
    weeks_needed = math.ceil(2 * n_req / float(pre["weekly_signups"]))

    primary = _metric(df, "kyc_7d")
    secondary = {"application_submitted_14d": _metric(df, "app_14d"), "loan_disbursed_30d": _metric(df, "disb_30d")}
    guard = {
        "approval_rate": {**_metric(df, "approved_30d", df["decided_30d"] == 1), "margin": 0.02, "higher_is_worse": False,
                          "population": "users with an underwriting decision within 30 days"},
        "fpd30_rate": {**_metric(df, "fpd30", df["fpd_mature"] == 1), "margin": 0.015, "higher_is_worse": True,
                       "population": "first loans with a matured first EMI"},
        "kyc_support_ticket_rate": {**_metric(df, "kyc_ticket_7d"), "margin": 0.01, "higher_is_worse": True,
                                    "population": "all randomised users"},
    }
    for g in guard.values():
        g["status"] = guardrail_status(g, g["margin"], g["higher_is_worse"])

    weekly = []
    for wk, grp in df.groupby("assignment_week"):
        r = _metric(grp, "kyc_7d")
        weekly.append({"assignment_week": str(wk), "users": int(len(grp)), "diff_abs": r["diff_abs"],
                       "ci_low": r["ci_low"], "ci_high": r["ci_high"]})
    seg_rows = []
    for dim in ("platform", "city_tier"):
        for val, grp in df.groupby(dim):
            r = _metric(grp, "kyc_7d")
            seg_rows.append({"dimension": dim, "segment": val, "users": int(len(grp)), **{k: r[k] for k in
                             ("control_rate", "treatment_rate", "diff_abs", "ci_low", "ci_high", "p_value")}})
    adj = holm_adjust([s["p_value"] for s in seg_rows])
    for s, a in zip(seg_rows, adj):
        s["p_value_holm"] = a
        s["significant_after_holm"] = a < ALPHA

    bayes = bayes_beta_binomial(primary["control_x"], primary["control_n"], primary["treatment_x"], primary["treatment_n"])
    imp = con.execute(IMPACT_SQL).df().iloc[0]
    inc_kyc = primary["diff_abs"] * float(imp["annual_app_signups"])
    inc_loans = inc_kyc * float(imp["kyc_to_loan_30d"])
    inc_rev = inc_loans * float(imp["net_revenue_per_first_loan"])
    impact = {"annual_app_signups_run_rate": float(imp["annual_app_signups"]), "incremental_kyc_per_year": inc_kyc,
              "kyc_to_first_loan_30d": float(imp["kyc_to_loan_30d"]), "incremental_first_loans_per_year": inc_loans,
              "net_revenue_per_first_loan": float(imp["net_revenue_per_first_loan"]),
              "incremental_net_revenue_per_year": inc_rev,
              "assumptions": "Uplift applied to the post-rollout app-signup run rate; downstream conversion and revenue "
                             "per first loan held at historical averages (no repeat-loan value counted - conservative)."}

    breach = any(g["status"] == "breach" for g in guard.values())
    inconclusive = [k for k, g in guard.items() if g["status"] == "inconclusive"]
    if primary["significant"] and primary["diff_abs"] > 0 and not breach:
        decision = "SHIP" + (" with post-launch monitoring of %s" % ", ".join(inconclusive) if inconclusive else "")
    elif breach:
        decision = "DO NOT SHIP - guardrail breach"
    else:
        decision = "ITERATE - no significant improvement"

    return {
        "experiment_id": "EXP-ONB-2026-01",
        "name": "Onboarding redesign: trust signals + progress indicator",
        "design": {"unit": "new app signup (android/ios)", "allocation": "50/50 random at first app open",
                   "window": "2026-01-12 to 2026-02-22 (6 weeks)", "primary_metric": "KYC completed within 7 days of signup",
                   "alpha": ALPHA, "power": POWER, "pre_period_baseline": baseline, "planned_mde_abs": planned_mde,
                   "required_n_per_arm": n_req, "pre_period_weekly_app_signups": float(pre["weekly_signups"]),
                   "weeks_needed": weeks_needed},
        "srm": srm,
        "primary": primary,
        "achieved_power_at_observed_effect": achieved_power(primary["control_rate"], primary["treatment_rate"],
                                                            min(primary["control_n"], primary["treatment_n"])),
        "mde_at_realised_n": mde_at_n(primary["control_rate"], min(primary["control_n"], primary["treatment_n"])),
        "secondary": secondary,
        "guardrails": guard,
        "bayesian": bayes,
        "weekly_effect": weekly,
        "segments": seg_rows,
        "impact": impact,
        "decision": decision,
    }


def analyse_simple(con, sql: str, metric: str, experiment_id: str, name: str, planned_mde: float,
                   extra: Optional[Dict[str, str]] = None) -> Dict:
    df = con.execute(sql).df()
    srm = srm_check(int((df["variant"] == "control").sum()), int((df["variant"] == "treatment").sum()))
    primary = _metric(df, metric)
    n = min(primary["control_n"], primary["treatment_n"])
    out = {"experiment_id": experiment_id, "name": name, "srm": srm, "primary_metric": metric, "primary": primary,
           "planned_mde_abs": planned_mde, "required_n_per_arm": required_n_per_arm(primary["control_rate"], planned_mde),
           "mde_at_realised_n": mde_at_n(primary["control_rate"], n),
           "bayesian": bayes_beta_binomial(primary["control_x"], primary["control_n"], primary["treatment_x"], primary["treatment_n"])}
    for label, (col, mask_col) in (extra or {}).items():
        out.setdefault("secondary", {})[label] = _metric(df, col, df[mask_col] == 1 if mask_col else None)
    if primary["significant"]:
        out["decision"] = "SHIP" if primary["diff_abs"] > 0 else "DO NOT SHIP"
    elif out["required_n_per_arm"] > n:
        out["decision"] = ("INCONCLUSIVE - underpowered: needed %s users per arm for a %.1f pp MDE, had %s"
                           % (format(out["required_n_per_arm"], ","), 100 * planned_mde, format(n, ",")))
    else:
        out["decision"] = "NO EFFECT - keep control"
    return out


# ---------------------------------------------------------------- readout
def readout_markdown(r: Dict) -> str:
    d, p = r["design"], r["primary"]
    lines = [
        "# Experiment readout - %s" % r["experiment_id"], "",
        "_%s. Synthetic data; generated by `python/experiment_analysis.py`._" % r["name"], "",
        "**Decision: %s**" % r["decision"], "",
        "## Design (pre-registered)", "",
        "| Item | Value |", "|---|---|",
        "| Unit / allocation | %s, %s |" % (d["unit"], d["allocation"]),
        "| Window | %s |" % d["window"],
        "| Primary metric | %s |" % d["primary_metric"],
        "| Baseline (pre-period) | %s |" % _pct(d["pre_period_baseline"]),
        "| MDE / alpha / power | %.1f pp / %.2f / %.0f%% |" % (100 * d["planned_mde_abs"], d["alpha"], 100 * d["power"]),
        "| Required sample | %s per arm (~%d weeks at %s app signups/week) |" % (
            format(d["required_n_per_arm"], ","), d["weeks_needed"], format(int(d["pre_period_weekly_app_signups"]), ",")),
        "", "## Validity checks", "",
        "- Sample ratio: control %s vs treatment %s (treatment share %s), chi-square p = %.3f -> %s." % (
            format(r["srm"]["control_n"], ","), format(r["srm"]["treatment_n"], ","), _pct(r["srm"]["treatment_share"]),
            r["srm"]["p_value"], "SRM detected, results invalid" if r["srm"]["srm_detected"] else "no sample-ratio mismatch"),
        "- Novelty check: weekly effects range from %s to %s; no decay pattern is required for a ship decision but is monitored." % (
            _pp(min(w["diff_abs"] for w in r["weekly_effect"])), _pp(max(w["diff_abs"] for w in r["weekly_effect"]))),
        "", "## Results", "",
        "| Metric | Control | Treatment | Difference (95% CI) | Relative uplift | p-value |", "|---|---:|---:|---|---:|---:|",
    ]

    def row(label, m):
        return "| %s | %s | %s | %s (%s to %s) | %+.1f%% | %.4f |" % (
            label, _pct(m["control_rate"]), _pct(m["treatment_rate"]), _pp(m["diff_abs"]), _pp(m["ci_low"]),
            _pp(m["ci_high"]), 100 * m["relative_uplift"], m["p_value"])

    lines.append(row("**KYC completed in 7 days (primary)**", p))
    for k, m in r["secondary"].items():
        lines.append(row(k.replace("_", " "), m))
    lines += ["", "Bayesian view: P(treatment better) = %.1f%%, expected loss if shipped = %.3f pp." % (
        100 * r["bayesian"]["prob_treatment_better"], 100 * r["bayesian"]["expected_loss_if_ship"]),
        "Achieved power at the observed effect = %.0f%%; MDE at the realised sample = %.2f pp." % (
        100 * r["achieved_power_at_observed_effect"], 100 * r["mde_at_realised_n"]),
        "", "## Guardrails (non-inferiority)", "",
        "| Guardrail | Control | Treatment | Difference (95% CI) | Margin | Status |", "|---|---:|---:|---|---:|---|"]
    for k, g in r["guardrails"].items():
        lines.append("| %s | %s | %s | %s (%s to %s) | %.1f pp | %s |" % (
            k.replace("_", " "), _pct(g["control_rate"]), _pct(g["treatment_rate"]), _pp(g["diff_abs"]), _pp(g["ci_low"]),
            _pp(g["ci_high"]), 100 * g["margin"], g["status"]))
    lines += ["", "## Heterogeneity (exploratory, Holm-adjusted)", "",
              "| Segment | Users | Difference | 95% CI | Holm p |", "|---|---:|---:|---|---:|"]
    for s in r["segments"]:
        lines.append("| %s = %s | %s | %s | %s to %s | %.4f |" % (s["dimension"], s["segment"], format(s["users"], ","),
                                                                  _pp(s["diff_abs"]), _pp(s["ci_low"]), _pp(s["ci_high"]),
                                                                  s["p_value_holm"]))
    imp = r["impact"]
    lines += ["", "## Business impact (estimate)", "",
              "- ~%s additional verified customers per year at the post-launch app-signup run rate." % format(int(round(imp["incremental_kyc_per_year"])), ","),
              "- ~%s additional first loans per year (KYC -> first loan within 30 days: %s)." % (
                  format(int(round(imp["incremental_first_loans_per_year"])), ","), _pct(imp["kyc_to_first_loan_30d"])),
              "- ~%s additional net revenue per year from first loans alone (%s per first loan)." % (
                  fmt_inr(imp["incremental_net_revenue_per_year"]), fmt_inr(imp["net_revenue_per_first_loan"])),
              "- Assumptions: %s" % imp["assumptions"],
              "", "## Assumptions", "",
              "- Randomisation at the customer level is independent of outcome drivers (checked with the SRM test and "
              "balanced platform mix).",
              "- No interference between units (one customer's onboarding does not change another's) and a single, stable "
              "treatment version during the test (SUTVA).",
              "- Fixed horizon: the readout is computed once at the planned end date - no peeking-based early stopping, so "
              "the nominal 5% false-positive rate holds.",
              "- Normal approximation to the binomial is valid (thousands of users per arm, rates far from 0 and 1).",
              "- Guardrails are judged by non-inferiority margins agreed before launch, not by significance alone.",
              "", "## Limitations", "",
              "- Downstream metrics (loans, FPD30) are diluted by the many steps after KYC, so the test is not powered for them; "
              "FPD30 is monitored post-launch rather than decided on.",
              "- Web signups were not eligible; the web flow needs its own test.",
              "- Segment results are exploratory (multiple comparisons) and should not drive targeting without a follow-up test.",
              "- Customers were assigned at first app open; users who reinstalled could in principle see both variants "
              "(assignment is keyed on customer_id, so exposure is stable after signup).",
              "- Effects can shrink after launch (novelty, seasonality); the KYC weekly trend is tracked against the pre-period."]
    return "\n".join(lines) + "\n"


def run(settings: Optional[Settings] = None) -> Dict:
    settings = settings or get_settings()
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        onb = analyse_onboarding(con)
        rpy = analyse_simple(con, RPY_SQL, "autopay", "EXP-RPY-2025-11", "Autopay nudge at disbursal", 0.08,
                             {"first_emi_on_time": ("first_emi_on_time", "first_emi_mature")})
        prc = analyse_simple(con, PRC_SQL, "accepted", "EXP-PRC-2025-06", "Upfront fee transparency on the offer screen", 0.03)
    finally:
        con.close()
    out_dir = settings.outputs_dir / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"EXP-ONB-2026-01": onb, "EXP-RPY-2025-11": rpy, "EXP-PRC-2025-06": prc}
    write_json(results, out_dir / "experiment_results.json")
    (out_dir / "EXP-ONB-2026-01_readout.md").write_text(readout_markdown(onb), encoding="utf-8")
    pd.DataFrame(onb["weekly_effect"]).to_csv(out_dir / "onboarding_weekly_effect.csv", index=False)
    pd.DataFrame(onb["segments"]).to_csv(out_dir / "onboarding_segment_effects.csv", index=False)
    return results


if __name__ == "__main__":
    res = run()
    for k, r in res.items():
        p = r["primary"]
        print("%s  control %.2f%%  treatment %.2f%%  diff %+.2f pp  p=%.4f  -> %s" % (
            k, 100 * p["control_rate"], 100 * p["treatment_rate"], 100 * p["diff_abs"], p["p_value"], r["decision"]))
