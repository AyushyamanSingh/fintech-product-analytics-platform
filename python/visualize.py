"""Static charts for the README, docs and case study (matplotlib, PNG).

Design rules (consistent across every chart):
* one validated categorical palette, assigned in fixed order; status colours only for status
* single-series charts use one colour; "highlight one, grey the rest" instead of rainbows
* no dual axes - different units go into small multiples
* thin marks, hairline recessive grid, direct labels only where they carry the story

Reads only files under outputs/ (decoupled from the warehouse).
    python -m python.visualize
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from python.config import Settings, get_settings  # noqa: E402

SURFACE, INK, INK2, MUTED, GRID, BASE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQ = LinearSegmentedColormap.from_list("seq_blue", ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])
DIV = LinearSegmentedColormap.from_list("div_blue_red", ["#2a78d6", "#9ec5f4", "#f0efec", "#f2a3a2", "#e34948"])
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
DE_EMPH = "#c9c8c2"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "axes.edgecolor": BASE, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left", "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.6,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
    "legend.frameon": False, "legend.labelcolor": INK2, "lines.linewidth": 2.0, "axes.axisbelow": True,
})

FOOT = "Synthetic data - Vittora Credit (fictional). Source: FinTech Product Analytics & Decision Intelligence Platform."


def _finish(fig, path: Path, title: str, subtitle: Optional[str] = None) -> Path:
    fig.suptitle(title, x=0.012, y=0.995, ha="left", va="top", fontsize=14, fontweight="semibold", color=INK)
    if subtitle:
        fig.text(0.012, 0.935 if fig.get_figheight() < 5 else 0.955, subtitle, ha="left", va="top", fontsize=10, color=INK2)
    # footer sits below everything (bbox_inches="tight" grows the canvas), so it never collides with axis titles
    fig.text(0.012, -0.045, FOOT, ha="left", va="bottom", fontsize=7.5, color=MUTED)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def _sql(settings: Settings, name: str) -> pd.DataFrame:
    return pd.read_csv(settings.outputs_dir / "sql_results" / (name + ".csv"))


def _inr_lakh(x, _=None):
    return "₹%.0fL" % (x / 1e5)


# ------------------------------------------------------------------------------------------- charts
def funnel(settings: Settings) -> Path:
    df = _sql(settings, "01_funnel_conversion__funnel_overall")
    fig, ax = plt.subplots(figsize=(10, 4.6))
    y = np.arange(len(df))[::-1]
    ax.barh(y, df["pct_of_signups"], color=SERIES[0], height=0.62)
    ax.set_yticks(y, df["stage"])
    ax.set_xlim(0, 112)
    ax.xaxis.set_major_formatter(lambda v, _: "%d%%" % v)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    worst = df.iloc[1:]["lost_vs_previous_stage"].astype(float).idxmax()
    for yi, (_, r) in zip(y, df.iterrows()):
        ax.text(r["pct_of_signups"] + 1.2, yi, "%.1f%%  ·  %s" % (r["pct_of_signups"], format(int(r["customers"]), ",")),
                va="center", fontsize=9.5, color=INK)
    r = df.loc[worst]
    ax.annotate("Largest leak: %s customers lost\nbetween KYC start and completion\n(%.0f%% step conversion)" % (
                    format(int(r["lost_vs_previous_stage"]), ","), r["step_conversion_pct"]),
                xy=(r["pct_of_signups"], y[worst] - 0.32), xytext=(76, y[worst] - 1.05), fontsize=9, color=INK2,
                va="center", arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    return _finish(fig, settings.images_dir / "funnel.png", "Onboarding funnel: KYC is the biggest leak",
                   "Share of signups reaching each stage (customer-level, cohorts at least 30 days old)")


def kyc_weekly(settings: Settings) -> Path:
    df = _sql(settings, "02_funnel_dropoff__kyc_weekly_trend")
    df["signup_week"] = pd.to_datetime(df["signup_week"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(df["signup_week"], df["kyc_7d_pct"], color=DE_EMPH, lw=1.2, label="Weekly")
    ax.plot(df["signup_week"], df["kyc_7d_pct_4wk_avg"], color=SERIES[0], lw=2.2, label="4-week average")
    ax.axvspan(pd.Timestamp("2026-01-12"), pd.Timestamp("2026-02-22"), color="#f0efec", zorder=0)
    ax.axvline(pd.Timestamp("2026-03-02"), color=MUTED, lw=1)
    ax.text(pd.Timestamp("2026-01-14"), ax.get_ylim()[1] - 0.6, "A/B test", fontsize=8.5, color=INK2, va="top")
    ax.text(pd.Timestamp("2026-03-05"), ax.get_ylim()[0] + 0.6, "Redesign\nshipped", fontsize=8.5, color=INK2, va="bottom")
    ax.yaxis.set_major_formatter(lambda v, _: "%d%%" % v)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.legend(loc="upper left", ncol=2)
    return _finish(fig, settings.images_dir / "kyc_weekly_trend.png", "7-day KYC completion, app signups",
                   "Weekly signup cohorts; the redesign tested in Jan-Feb 2026 lifted completion after launch")


def cohort_heatmap(settings: Settings) -> Path:
    df = _sql(settings, "03_cohort_retention__activity_retention_matrix")
    df = df[(df["month_number"] >= 1) & (df["month_number"] <= 12)]
    mat = df.pivot(index="cohort_month", columns="month_number", values="retention_pct")
    fig, ax = plt.subplots(figsize=(10, 6.4))
    im = ax.imshow(mat.values, aspect="auto", cmap=SEQ, vmin=0, vmax=np.nanpercentile(mat.values, 98))
    ax.set_xticks(range(mat.shape[1]), ["M%d" % c for c in mat.columns])
    ax.set_yticks(range(mat.shape[0]), [pd.Timestamp(i).strftime("%b %Y") for i in mat.index], fontsize=8.5)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    for (i, j), v in np.ndenumerate(mat.values):
        if not np.isnan(v) and j in (0, 2, 5, 11):
            ax.text(j, i, "%.0f" % v, ha="center", va="center", fontsize=7.5,
                    color="white" if v > np.nanpercentile(mat.values, 60) else INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.ax.yaxis.set_major_formatter(lambda v, _: "%d%%" % v)
    ax.set_xlabel("Months since signup")
    return _finish(fig, settings.images_dir / "cohort_retention.png", "Monthly active retention by signup cohort",
                   "% of each cohort with at least one app/web event in month N (labels at M1, M3, M6, M12)")


def kpi_trends(settings: Settings) -> Path:
    k = pd.read_csv(settings.outputs_dir / "kpis" / "kpi_monthly.csv", parse_dates=["month_start"])
    panels = [("loans_disbursed", "Loans disbursed", "count"), ("gross_revenue", "Gross revenue", "inr"),
              ("approval_rate", "Approval rate", "pct"), ("kyc_completion_rate_7d", "KYC completion (7-day)", "pct"),
              ("par30_rate", "PAR30 (month-end)", "pct"), ("mau", "Monthly active users", "count")]
    fig, axes = plt.subplots(2, 3, figsize=(12, 6.4))
    for ax, (col, label, unit) in zip(axes.flat, panels):
        s = k[["month_start", col]].dropna()
        ax.plot(s["month_start"], s[col], color=SERIES[0], lw=1.8)
        ax.set_title(label, fontsize=10.5)
        if unit == "pct":
            ax.yaxis.set_major_formatter(lambda v, _: "%.0f%%" % (100 * v))
            last = "%.1f%%" % (100 * s[col].iloc[-1])
        elif unit == "inr":
            ax.yaxis.set_major_formatter(_inr_lakh)
            last = _inr_lakh(s[col].iloc[-1])
        else:
            ax.yaxis.set_major_formatter(lambda v, _: format(int(v), ","))
            last = format(int(s[col].iloc[-1]), ",")
        ax.plot(s["month_start"].iloc[-1], s[col].iloc[-1], "o", color=SERIES[0], ms=5)
        ax.annotate(last, (s["month_start"].iloc[-1], s[col].iloc[-1]), xytext=(-4, 8), textcoords="offset points",
                    ha="right", fontsize=9, color=INK)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
        ax.set_ylim(bottom=0)
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    return _finish(fig, settings.images_dir / "kpi_trends.png", "Business KPIs, Jul 2024 - Jun 2026",
                   "Monthly; each panel has its own scale (no dual axes)")


def experiment_forest(settings: Settings) -> Path:
    res = json.loads((settings.outputs_dir / "experiments" / "experiment_results.json").read_text(encoding="utf-8"))
    r = res["EXP-ONB-2026-01"]
    labels = {"application_submitted_14d": "Application in 14 days", "loan_disbursed_30d": "First loan in 30 days",
              "approval_rate": "Approval rate", "fpd30_rate": "FPD30 rate", "kyc_support_ticket_rate": "KYC support tickets"}
    rows = [("KYC completed in 7 days (primary)", r["primary"], None)]
    rows += [(labels.get(k, k) + " (secondary)", v, None) for k, v in r["secondary"].items()]
    rows += [(labels.get(k, k) + " (guardrail)", v, v["margin"]) for k, v in r["guardrails"].items()]
    fig, ax = plt.subplots(figsize=(10, 4.4))
    for i, (label, m, margin) in enumerate(rows[::-1]):
        color = SERIES[0] if m["significant"] else MUTED
        ax.plot([100 * m["ci_low"], 100 * m["ci_high"]], [i, i], color=color, lw=2.2, solid_capstyle="round")
        ax.plot(100 * m["diff_abs"], i, "o", color=color, ms=8, mec=SURFACE, mew=2)
        ax.text(9.6, i, "%+.2f pp  (p=%.3f)" % (100 * m["diff_abs"], m["p_value"]), va="center", fontsize=9, color=INK2)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(range(len(rows)), [r_[0] for r_ in rows[::-1]])
    ax.set_xlim(-6, 9.5)
    ax.xaxis.set_major_formatter(lambda v, _: "%+.0f pp" % v)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Treatment - control (percentage points), 95% CI. Blue = significant at 5%.")
    return _finish(fig, settings.images_dir / "experiment_onboarding.png",
                   "EXP-ONB-2026-01: onboarding redesign lifted 7-day KYC completion",
                   "Decision: %s" % r["decision"])


def channel_economics(settings: Settings) -> Path:
    df = _sql(settings, "05_customer_ltv__ltv_cac_by_channel").sort_values("ltv_to_cac", na_position="first")
    fig, ax = plt.subplots(figsize=(10, 4.6))
    y = np.arange(len(df))
    h = 0.36
    ax.barh(y + h / 2, df["net_value_per_borrower"], height=h, color=SERIES[0], label="Net value per borrower")
    ax.barh(y - h / 2, df["cac_per_borrower"], height=h, color=SERIES[1], label="Acquisition cost per borrower")
    ax.set_yticks(y, df["acquisition_channel"].str.replace("_", " "))
    ax.xaxis.set_major_formatter(lambda v, _: "₹%s" % format(int(v), ","))
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    xmax = max(df["net_value_per_borrower"].max(), df["cac_per_borrower"].max())
    for yi, (_, r) in zip(y, df.iterrows()):
        txt = "LTV/CAC n/a (no paid spend)" if pd.isna(r["ltv_to_cac"]) else "LTV/CAC %.1fx" % r["ltv_to_cac"]
        ax.text(xmax * 1.02, yi, txt, va="center", fontsize=9, color=INK)
    ax.set_xlim(0, xmax * 1.35)
    ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.09), ncol=2)
    return _finish(fig, settings.images_dir / "channel_unit_economics.png",
                   "Unit economics by acquisition channel",
                   "Cohorts with 12+ months of history; net value = revenue - losses (NPA treated as lost)")


def vintage_curves(settings: Settings) -> Path:
    df = _sql(settings, "07_delinquency__vintage_curves")
    df["vintage_quarter"] = pd.to_datetime(df["vintage_quarter"])
    fig, ax = plt.subplots(figsize=(10, 4.6))
    highlight = pd.Timestamp("2025-10-01")
    for vq, g in df.groupby("vintage_quarter"):
        label = "Q%d %d" % ((vq.month - 1) // 3 + 1, vq.year)
        if vq == highlight:
            continue
        ax.plot(g["mob"], g["cum_30dpd_pct"], color=DE_EMPH, lw=1.4)
        ax.text(g["mob"].iloc[-1] + 0.15, g["cum_30dpd_pct"].iloc[-1], label, fontsize=7.5, color=MUTED, va="center")
    g = df[df["vintage_quarter"] == highlight]
    if len(g):
        ax.plot(g["mob"], g["cum_30dpd_pct"], color=SERIES[1], lw=2.6)
        ax.text(g["mob"].iloc[-1] + 0.15, g["cum_30dpd_pct"].iloc[-1], "Q4 2025 (festive)", fontsize=9, color=INK,
                va="center", fontweight="semibold")
    ax.set_xlabel("Months on book")
    ax.set_xticks(range(1, 13))
    ax.set_xlim(0.8, 13.6)
    ax.yaxis.set_major_formatter(lambda v, _: "%.0f%%" % v)
    return _finish(fig, settings.images_dir / "vintage_curves.png",
                   "Festive-season vintage hits 30+ DPD faster",
                   "Cumulative % of loans that reached 30+ days past due, by disbursal quarter")


def segments(settings: Settings) -> Path:
    prof = pd.read_csv(settings.outputs_dir / "segments" / "cluster_profiles.csv")
    cz = pd.read_csv(settings.outputs_dir / "segments" / "cluster_centroids_z.csv")
    labels = {"log_loans": "Loans", "log_disbursed": "Disbursed", "net_revenue_slog": "Net revenue",
              "on_time_rate": "On-time rate", "log_max_dpd": "Worst DPD", "log_logins_90d": "Logins (90d)",
              "active_months": "Active months", "n_products": "Products", "autopay": "Autopay",
              "log_days_since_last_loan": "Days since loan", "log_tickets": "Tickets"}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8), gridspec_kw={"width_ratios": [1.6, 1]})
    mat = cz.drop(columns="cluster_name")
    im = a1.imshow(mat.values, cmap=DIV, vmin=-2, vmax=2, aspect="auto")
    a1.set_xticks(range(mat.shape[1]), [labels[c] for c in mat.columns], rotation=35, ha="right")
    a1.set_yticks(range(len(cz)), cz["cluster_name"])
    a1.grid(False)
    for s in a1.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=a1, fraction=0.03, pad=0.02)
    cb.outline.set_visible(False)
    cb.set_label("Centroid (std. units)", color=INK2)
    a1.set_title("Cluster profiles", fontsize=10.5)
    order = prof.sort_values("share_of_net_revenue_pct")
    y = np.arange(len(order))
    h = 0.36
    a2.barh(y + h / 2, order["share_of_net_revenue_pct"], height=h, color=SERIES[0], label="Share of net revenue")
    a2.barh(y - h / 2, order["share_of_borrowers_pct"], height=h, color=SERIES[1], label="Share of borrowers")
    a2.set_yticks(y, order["cluster_name"])
    a2.xaxis.set_major_formatter(lambda v, _: "%d%%" % v)
    a2.grid(axis="x")
    a2.grid(axis="y", visible=False)
    a2.axvline(0, color=BASE, lw=1)
    a2.legend(loc="lower right", fontsize=8.5)
    a2.set_title("Who drives value", fontsize=10.5)
    fig.tight_layout(rect=(0, 0.02, 1, 0.92))
    return _finish(fig, settings.images_dir / "segments.png", "Borrower segments (K-Means on behaviour and value)",
                   "Standardised centroids (blue = below average, red = above) and value concentration")


def dq_scorecard(settings: Settings) -> Path:
    raw = pd.read_csv(settings.outputs_dir / "data_quality" / "dq_results_raw.csv")
    clean = pd.read_csv(settings.outputs_dir / "data_quality" / "dq_results_clean.csv")
    summ = json.loads((settings.outputs_dir / "data_quality" / "dq_summary.json").read_text(encoding="utf-8"))
    f = lambda d: d[d["status"] == "fail"].groupby("table").size()
    tables = sorted(set(raw["table"]))
    a, b = f(raw).reindex(tables, fill_value=0), f(clean).reindex(tables, fill_value=0)
    order = (a + b).sort_values().index
    fig, ax = plt.subplots(figsize=(10, 4.6))
    y = np.arange(len(order))
    h = 0.36
    ax.barh(y + h / 2, a[order], height=h, color=DE_EMPH, label="Raw extract")
    ax.barh(y - h / 2, b[order], height=h, color=SERIES[0], label="Curated layer")
    ax.set_yticks(y, order)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Failed checks (critical + warning)")
    ax.legend(loc="lower right")
    return _finish(fig, settings.images_dir / "dq_scorecard.png",
                   "Data quality: DQ score %.1f -> %.1f, critical failures %d -> %d" % (
                       summ["raw"]["dq_score"], summ["clean"]["dq_score"], summ["raw"]["critical_failures"],
                       summ["clean"]["critical_failures"]),
                   "Contract-driven checks per table before and after ETL; curated warnings are documented open issues")


def anomalies(settings: Settings) -> Path:
    import duckdb
    flags = pd.read_csv(settings.outputs_dir / "anomalies" / "daily_anomalies.csv", parse_dates=["date_day"])
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        dm = con.execute("SELECT * FROM marts.fct_daily_metrics").df()
    finally:
        con.close()
    dm["date_day"] = pd.to_datetime(dm["date_day"])
    dm["kyc_ratio"] = dm["kyc_completions_tracked"] / dm["kyc_completions_backend"].replace(0, np.nan)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.5, 4.4))
    w1 = dm[(dm["date_day"] >= "2025-07-01") & (dm["date_day"] <= "2025-09-30")]
    a1.plot(w1["date_day"], 100 * w1["payment_failure_rate"], color=SERIES[0], lw=1.6)
    f1 = flags[(flags["metric"] == "payment_failure_rate") & flags["date_day"].between("2025-07-01", "2025-09-30")]
    a1.plot(f1["date_day"], 100 * f1["value"], "o", color=STATUS["critical"], ms=7, mec=SURFACE, mew=2)
    if len(f1):
        r = f1.loc[f1["value"].idxmax()]
        a1.annotate("Gateway outage, %s: %.0f%%\n(expected %.0f%%)" % (r["date_day"].strftime("%d %b"), 100 * r["value"],
                                                                      100 * r["expected"]),
                    (r["date_day"], 100 * r["value"]), xytext=(10, -6), textcoords="offset points", fontsize=8.5, color=INK2)
    a1.set_title("EMI auto-debit failure rate - gateway outage", fontsize=10.5)
    a1.yaxis.set_major_formatter(lambda v, _: "%d%%" % v)
    a1.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    w2 = dm[(dm["date_day"] >= "2025-04-20") & (dm["date_day"] <= "2025-06-15")]
    a2.plot(w2["date_day"], 100 * w2["kyc_ratio"], color=SERIES[0], lw=1.6)
    f2 = flags[(flags["metric"] == "kyc_tracking_ratio") & flags["date_day"].between("2025-04-20", "2025-06-15")]
    a2.plot(f2["date_day"], 100 * f2["value"], "o", color=STATUS["serious"], ms=6, mec=SURFACE, mew=1.5)
    a2.axvspan(pd.Timestamp("2025-05-12"), pd.Timestamp("2025-05-16"), color="#f0efec", zorder=0)
    a2.text(pd.Timestamp("2025-05-12"), 103, " app 5.2.0 -> hotfix", fontsize=8.5, color=INK2)
    a2.set_ylim(0, 110)
    a2.set_title("Tracked / backend KYC completions - instrumentation bug", fontsize=10.5)
    a2.yaxis.set_major_formatter(lambda v, _: "%d%%" % v)
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.tight_layout(rect=(0, 0.02, 1, 0.91))
    return _finish(fig, settings.images_dir / "anomalies.png", "Two anomalies, two different root causes",
                   "Left: a real business incident. Right: a data incident - backend KYC volumes were normal")


def revenue_mix(settings: Settings) -> Path:
    df = _sql(settings, "06_revenue_analysis__revenue_mix_by_product")
    df["month_start"] = pd.to_datetime(df["month_start"])
    piv = df.pivot_table(index="month_start", columns="product_id", values="gross_revenue", aggfunc="sum").fillna(0)
    names = df.drop_duplicates("product_id").set_index("product_id")["product_name"]
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    bottom = np.zeros(len(piv))
    for i, pid in enumerate(sorted(piv.columns)):
        ax.bar(piv.index, piv[pid], bottom=bottom, width=24, color=SERIES[i], label=names.get(pid, pid),
               edgecolor=SURFACE, linewidth=0.6)
        bottom += piv[pid].values
    ax.yaxis.set_major_formatter(_inr_lakh)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.legend(ncol=4, loc="upper left", fontsize=8.5)
    ax.set_ylim(0, bottom.max() * 1.25)
    return _finish(fig, settings.images_dir / "revenue_mix.png", "Gross revenue by product",
                   "Interest (balance-sheet products) + processing, late and foreclosure fees; P2P earns fees only")


CHARTS = [funnel, kyc_weekly, cohort_heatmap, kpi_trends, experiment_forest, channel_economics, vintage_curves,
          segments, dq_scorecard, anomalies, revenue_mix]


def build_all(settings: Optional[Settings] = None) -> List[Path]:
    settings = settings or get_settings()
    out = []
    for fn in CHARTS:
        out.append(fn(settings))
    return out


if __name__ == "__main__":
    for p in build_all():
        print(p)
