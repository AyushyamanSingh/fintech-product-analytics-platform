"""Anomaly detection on daily operating metrics.

Method (robust and seasonality-aware):
  expected  = median of the same weekday over the previous 8 weeks (>= 4 observations)
  scale     = max(1.4826 * MAD, 5% of expected, metric floor)
  robust z  = (value - expected) / scale
  flag      = |z| >= 4  AND  relative deviation >= 25%

Flagged days are merged into *episodes* (same metric and direction, gaps <= 2 days), each
episode gets a driver attribution (which channel / platform / reason / category explains the
excess) and is annotated with the business calendar so known campaigns are labelled as such
instead of being reported as incidents.

    python -m python.anomaly_detection
"""
from __future__ import annotations

from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd

from python.config import BUSINESS_CALENDAR, Settings, get_settings
from python.io_utils import write_json

METRICS = {
    # metric: (kind, floor for the robust scale, label)
    "signups": ("count", 5, "Signups"),
    "applications_submitted": ("count", 3, "Applications submitted"),
    "approval_rate": ("rate", 0.03, "Approval rate"),
    "loans_disbursed": ("count", 3, "Loans disbursed"),
    "payment_failure_rate": ("rate", 0.01, "EMI payment failure rate"),
    "support_tickets": ("count", 3, "Support tickets"),
    "kyc_tracking_ratio": ("rate", 0.03, "Tracked / backend KYC completions"),
    "dau": ("count", 20, "Daily active users"),
}
# Rate metrics are only scored on days with enough trials, and their noise floor includes the
# binomial standard error of the expected rate (small days are naturally noisier).
RATE_DENOMINATOR = {"approval_rate": "approval_n", "payment_failure_rate": "payment_n",
                    "kyc_tracking_ratio": "kyc_completions_backend"}
MIN_DENOMINATOR = 30
# Count metrics are over-dispersed Poisson: noise floor = 1.5 * sqrt(expected)
POISSON_OVERDISPERSION = 1.5
# An episode is reported if it persists for 2+ days or a single day is extreme
MIN_EPISODE_DAYS, SINGLE_DAY_Z = 2, 6.0
# Which calendar event types can explain which metrics
CALENDAR_RELEVANCE = {
    "marketing": {"signups", "applications_submitted", "loans_disbursed", "dau", "support_tickets"},
    "product_launch": {"applications_submitted", "loans_disbursed", "approval_rate"},
    "release": {"kyc_tracking_ratio", "dau", "support_tickets"},
    "experiment": set(),
}

# Driver queries: daily numerator broken down by one dimension
DRIVER_SQL = {
    "signups": "SELECT CAST(signup_ts AS DATE) AS d, acquisition_channel AS dim, COUNT(*) AS n FROM core.customers GROUP BY 1, 2",
    "applications_submitted": """SELECT CAST(a.submitted_ts AS DATE) AS d, c.acquisition_channel AS dim, COUNT(*) AS n
                                 FROM core.applications a JOIN core.customers c ON c.customer_id = a.customer_id
                                 WHERE a.submitted_ts IS NOT NULL GROUP BY 1, 2""",
    "approval_rate": """SELECT CAST(decision_ts AS DATE) AS d, rejection_reason AS dim, COUNT(*) AS n
                        FROM core.applications WHERE decision = 'rejected' AND decision_ts IS NOT NULL GROUP BY 1, 2""",
    "loans_disbursed": "SELECT CAST(disbursed_ts AS DATE) AS d, product_id AS dim, COUNT(*) AS n FROM core.loans GROUP BY 1, 2",
    "payment_failure_rate": """SELECT CAST(txn_ts AS DATE) AS d, failure_reason AS dim, COUNT(*) AS n FROM core.transactions
                               WHERE txn_type = 'emi_payment' AND txn_status = 'failed' GROUP BY 1, 2""",
    "support_tickets": "SELECT CAST(created_ts AS DATE) AS d, category AS dim, COUNT(*) AS n FROM core.support_tickets GROUP BY 1, 2",
    "kyc_tracking_ratio": """WITH b AS (SELECT CAST(kyc_completed_ts AS DATE) AS d, signup_platform AS dim, COUNT(*) AS n_b
                                        FROM core.customers WHERE kyc_completed_ts IS NOT NULL GROUP BY 1, 2),
                                  t AS (SELECT CAST(e.event_ts AS DATE) AS d, c.signup_platform AS dim, COUNT(DISTINCT e.user_id) AS n_t
                                        FROM core.product_events e JOIN core.customers c ON c.customer_id = e.user_id
                                        WHERE e.event_name = 'kyc_completed' GROUP BY 1, 2)
                             SELECT b.d, b.dim, b.n_b - COALESCE(t.n_t, 0) AS n
                             FROM b LEFT JOIN t ON t.d = b.d AND t.dim = b.dim""",
    "dau": """SELECT CAST(event_ts AS DATE) AS d, platform AS dim, COUNT(DISTINCT user_id) AS n FROM core.product_events
              WHERE platform <> 'server' GROUP BY 1, 2""",
}
DRIVER_LABEL = {"signups": "acquisition channel", "applications_submitted": "acquisition channel",
                "approval_rate": "rejection reason (excess rejections)", "loans_disbursed": "product",
                "payment_failure_rate": "failure reason (excess failed debits)", "support_tickets": "ticket category",
                "kyc_tracking_ratio": "platform (untracked completions)", "dau": "platform"}


def _marketing_days(dates: pd.Series) -> pd.Series:
    mask = pd.Series(False, index=dates.index)
    for e in BUSINESS_CALENDAR:
        if e["type"] == "marketing":
            mask |= (dates >= e["start"]) & (dates <= e["end"])
    return mask


def _baseline(values: pd.Series, iso_dow: pd.Series, floor: float, weeks: int = 8,
              exclude: Optional[pd.Series] = None) -> pd.DataFrame:
    """Same-weekday rolling median/MAD of the previous `weeks` observations (current day excluded).
    Days in `exclude` (known campaign days) are scored but never used as baseline for later days."""
    base_values = values if exclude is None else values.where(~exclude)
    out = pd.DataFrame({"value": base_values, "dow": iso_dow})
    exp = pd.Series(np.nan, index=values.index)
    scale = pd.Series(np.nan, index=values.index)
    for dow, grp in out.groupby("dow"):
        v = grp["value"]
        med = v.shift(1).rolling(weeks, min_periods=4).median()
        mad = (v.shift(1).rolling(weeks, min_periods=4)
               .apply(lambda x: np.nanmedian(np.abs(x - np.nanmedian(x))), raw=True))
        exp.loc[grp.index] = med
        scale.loc[grp.index] = np.maximum.reduce([1.4826 * mad.values, 0.05 * np.abs(med.values),
                                                  np.full(len(med), floor)])
    return pd.DataFrame({"expected": exp, "scale": scale})


def detect(daily: pd.DataFrame, z_threshold: float = 4.0, min_rel_dev: float = 0.25) -> pd.DataFrame:
    daily = daily.sort_values("date_day").reset_index(drop=True)
    daily["kyc_tracking_ratio"] = daily["kyc_completions_tracked"] / daily["kyc_completions_backend"].replace(0, np.nan)
    daily["approval_n"] = daily["approvals"] + daily["rejections"]
    daily["payment_n"] = daily["payments_success"] + daily["payments_failed"]
    special = _marketing_days(daily["date_day"])
    rows = []
    for metric, (kind, floor, label) in METRICS.items():
        v = daily[metric].astype(float)
        if kind == "rate":
            n = daily[RATE_DENOMINATOR[metric]].astype(float)
            v = v.where(n >= MIN_DENOMINATOR)
        b = _baseline(v, daily["iso_dow"], floor, exclude=special)
        if kind == "rate":
            p = b["expected"].clip(0.001, 0.999)
            b["scale"] = np.maximum(b["scale"], np.sqrt(p * (1 - p) / n.clip(lower=1)))
        else:
            b["scale"] = np.maximum(b["scale"], POISSON_OVERDISPERSION * np.sqrt(b["expected"].clip(lower=1)))
        z = (v - b["expected"]) / b["scale"]
        rel = (v - b["expected"]) / b["expected"].replace(0, np.nan)
        flag = (z.abs() >= z_threshold) & (rel.abs() >= min_rel_dev) & v.notna()
        for i in np.where(flag.fillna(False))[0]:
            rows.append({"date_day": daily.loc[i, "date_day"], "metric": metric, "metric_label": label, "kind": kind,
                         "value": v[i], "expected": b["expected"][i], "robust_z": z[i], "deviation_pct": 100 * rel[i],
                         "direction": "spike" if v[i] > b["expected"][i] else "drop"})
    columns = ["date_day", "metric", "metric_label", "kind", "value", "expected", "robust_z", "deviation_pct", "direction"]
    return pd.DataFrame(rows, columns=columns)


def _calendar_context(metric: str, start: pd.Timestamp, end: pd.Timestamp) -> Optional[str]:
    hits = [e["event"] for e in BUSINESS_CALENDAR
            if metric in CALENDAR_RELEVANCE.get(e["type"], set())
            and pd.Timestamp(e["start"]) <= end and pd.Timestamp(e["end"]) >= start]
    return "; ".join(hits) if hits else None


_DRIVER_CACHE: Dict[str, pd.DataFrame] = {}


def _drivers(con, metric: str, day: pd.Timestamp, direction: str) -> List[Dict]:
    q = DRIVER_SQL.get(metric)
    if not q:
        return []
    if metric not in _DRIVER_CACHE:
        frame = con.execute(q).df()
        frame["d"] = pd.to_datetime(frame["d"])
        _DRIVER_CACHE[metric] = frame.dropna(subset=["dim"])
    df = _DRIVER_CACHE[metric]
    window = df[(df["d"] <= day) & (df["d"] >= day - pd.Timedelta(days=56))]
    same_dow = window[window["d"].dt.dayofweek == day.dayofweek]
    cur = same_dow[same_dow["d"] == day].set_index("dim")["n"]
    hist = same_dow[same_dow["d"] < day].pivot_table(index="d", columns="dim", values="n", aggfunc="sum").fillna(0)
    expected = hist.median() if len(hist) else pd.Series(dtype=float)
    dims = cur.index.union(expected.index)
    dev = cur.reindex(dims, fill_value=0) - expected.reindex(dims, fill_value=0)
    want_positive = direction == "spike" or metric in ("approval_rate", "kyc_tracking_ratio")
    # share of the movement in the anomaly's direction (dimensions moving the other way are ignored)
    total = dev[dev > 0].sum() if want_positive else dev[dev < 0].sum()
    if total == 0:
        return []
    dev = dev.sort_values(ascending=not want_positive)
    out = []
    for dim, d in dev.head(2).items():
        if (d > 0) != want_positive:
            continue
        out.append({"dimension_value": str(dim), "actual": float(cur.get(dim, 0)), "expected": float(expected.get(dim, 0)),
                    "share_of_deviation_pct": round(100 * d / total, 1) if total else None})
    return out


def episodes(flags: pd.DataFrame, con, max_gap_days: int = 2) -> List[Dict]:
    if flags.empty:
        return []
    out = []
    flags = flags.sort_values(["metric", "direction", "date_day"])
    for (metric, direction), grp in flags.groupby(["metric", "direction"]):
        grp = grp.reset_index(drop=True)
        ep_id = (grp["date_day"].diff().dt.days.fillna(0) > max_gap_days).cumsum()
        for _, ep in grp.groupby(ep_id):
            peak = ep.loc[ep["robust_z"].abs().idxmax()]
            if len(ep) < MIN_EPISODE_DAYS and abs(peak["robust_z"]) < SINGLE_DAY_Z:
                continue  # isolated moderate blip: kept in daily_anomalies.csv, not escalated
            start, end = ep["date_day"].min(), ep["date_day"].max()
            kind = peak["kind"]
            context = _calendar_context(metric, start, end)
            drivers = _drivers(con, metric, pd.Timestamp(peak["date_day"]), direction)
            fmt = (lambda x: "%.1f%%" % (100 * x)) if kind == "rate" else (lambda x: format(int(round(x)), ","))
            headline = "%s %s to %s on %s (expected %s, robust z %.1f)" % (
                peak["metric_label"], "spiked" if direction == "spike" else "dropped", fmt(peak["value"]),
                pd.Timestamp(peak["date_day"]).strftime("%d %b %Y"), fmt(peak["expected"]), peak["robust_z"])
            if drivers:
                headline += "; main driver: %s = %s (%.0f%% of the deviation)" % (
                    DRIVER_LABEL[metric], drivers[0]["dimension_value"], drivers[0]["share_of_deviation_pct"] or 0)
            out.append({
                "metric": metric, "metric_label": peak["metric_label"], "direction": direction,
                "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "days_flagged": int(len(ep)),
                "peak_date": pd.Timestamp(peak["date_day"]).strftime("%Y-%m-%d"),
                "peak_value": float(peak["value"]), "peak_value_fmt": fmt(peak["value"]),
                "expected_value": float(peak["expected"]), "expected_fmt": fmt(peak["expected"]),
                "peak_robust_z": round(float(peak["robust_z"]), 1),
                "peak_deviation_pct": round(float(peak["deviation_pct"]), 1),
                "severity": "high" if abs(peak["robust_z"]) >= 8 or len(ep) >= 3 else "medium",
                "known_context": context, "classification": "expected (known event)" if context else "investigate",
                "drivers": drivers, "headline": headline,
            })
    return sorted(out, key=lambda e: (e["peak_date"], e["metric"]))


def run(settings: Optional[Settings] = None) -> Dict:
    settings = settings or get_settings()
    _DRIVER_CACHE.clear()
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        daily = con.execute("SELECT * FROM marts.fct_daily_metrics ORDER BY date_day").df()
        daily["date_day"] = pd.to_datetime(daily["date_day"])
        flags = detect(daily)
        eps = episodes(flags, con)
    finally:
        con.close()
    out_dir = settings.outputs_dir / "anomalies"
    out_dir.mkdir(parents=True, exist_ok=True)
    flags.to_csv(out_dir / "daily_anomalies.csv", index=False)
    episode_cols = ["metric", "metric_label", "direction", "start", "end", "days_flagged", "peak_date", "peak_value",
                    "peak_value_fmt", "expected_value", "expected_fmt", "peak_robust_z", "peak_deviation_pct", "severity",
                    "known_context", "classification", "headline"]
    pd.DataFrame([{k: v for k, v in e.items() if k != "drivers"} for e in eps], columns=episode_cols) \
        .to_csv(out_dir / "anomaly_episodes.csv", index=False)  # header even when there are no episodes
    result = {"method": "same-weekday rolling median / MAD, |robust z| >= 4 and |deviation| >= 25%",
              "flagged_days": int(len(flags)), "episodes": eps}
    write_json(result, out_dir / "anomaly_episodes.json")
    return result


if __name__ == "__main__":
    res = run()
    for e in res["episodes"]:
        print("[%s] %s %s | %s" % (e["severity"], e["start"], e["classification"], e["headline"]))
