"""Automated KPI calculation: governed monthly/weekly KPI tables + a snapshot with deltas.

    python -m python.kpis
Outputs (outputs/kpis/): kpi_monthly.csv (wide), kpi_monthly_long.csv, kpi_weekly.csv, kpi_snapshot.json
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd

from python.config import Settings, get_settings
from python.io_utils import fmt_inr, write_json
from python.kpi_definitions import KPI_BY_ID, KPIS, WEEKLY_KPIS


def _isnan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def format_value(value, unit: str) -> str:
    if _isnan(value):
        return "n/a"
    if unit == "pct":
        return "%.1f%%" % (100 * value)
    if unit == "inr":
        return fmt_inr(value)
    if unit == "count":
        return format(int(round(value)), ",")
    return "%.2f" % value


def format_delta(cur, prev, unit: str) -> Dict:
    if _isnan(cur) or _isnan(prev):
        return {"delta_abs": None, "delta_pct": None, "delta_fmt": "n/a"}
    d_abs = cur - prev
    d_pct = (cur / prev - 1) if prev not in (0, None) else None
    if unit == "pct":
        fmt = "%+.1f pp" % (100 * d_abs)
    elif d_pct is not None:
        fmt = "%+.1f%%" % (100 * d_pct)
    else:
        fmt = "%+.2f" % d_abs
    return {"delta_abs": d_abs, "delta_pct": d_pct, "delta_fmt": fmt}


def _assess(kpi: Dict, cur, prev, z) -> (str, bool):
    if _isnan(cur) or _isnan(prev):
        return "n/a", False
    unit = kpi["unit"]
    if unit == "pct":
        material = abs(cur - prev) >= 0.01
        notable = abs(cur - prev) >= 0.02
    else:
        rel = abs(cur / prev - 1) if prev else 0
        material = rel >= 0.05
        notable = rel >= 0.10
    notable = notable or (z is not None and abs(z) >= 2)
    if not material:
        return "stable", notable
    up = cur > prev
    if kpi["direction"] == "neutral":
        return ("up" if up else "down"), notable
    good = up if kpi["direction"] == "up_good" else not up
    return ("improved" if good else "worsened"), notable


def _target_status(kpi: Dict, value) -> Optional[str]:
    target = kpi.get("target")
    if not target or _isnan(value):
        return None
    t, op = target
    ok = value >= t if op == ">=" else value <= t
    return "on_track" if ok else "off_track"


def load_kpi_tables(settings: Settings) -> (pd.DataFrame, pd.DataFrame):
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        monthly = con.execute((settings.sql_dir / "kpis" / "kpi_monthly.sql").read_text(encoding="utf-8")).df()
        weekly = con.execute((settings.sql_dir / "kpis" / "kpi_weekly.sql").read_text(encoding="utf-8")).df()
    finally:
        con.close()
    monthly["month_start"] = pd.to_datetime(monthly["month_start"])
    weekly["week_start"] = pd.to_datetime(weekly["week_start"])
    for df in (monthly, weekly):
        for c in df.columns[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    return monthly, weekly


def _monthly_snapshot(monthly: pd.DataFrame, as_of: pd.Timestamp) -> List[Dict]:
    month_end_complete = (as_of + pd.Timedelta(days=1)).day == 1
    report_month = as_of.normalize().replace(day=1)
    if not month_end_complete:
        report_month = (report_month - pd.Timedelta(days=1)).replace(day=1)
    m = monthly[monthly["month_start"] <= report_month].set_index("month_start").sort_index()
    out = []
    for kpi in KPIS:
        s = m[kpi["id"]].dropna() if kpi["id"] in m.columns else pd.Series(dtype=float)
        if s.empty:
            continue
        period = s.index[-1]
        cur = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) > 1 else None
        hist = s.iloc[-7:-1]
        z = float((cur - hist.mean()) / hist.std()) if len(hist) >= 4 and hist.std() > 0 else None
        yoy_period = period - pd.DateOffset(years=1)
        yoy = float(s.loc[yoy_period]) if yoy_period in s.index else None
        unit = kpi["unit"]
        delta = format_delta(cur, prev, unit)
        yoy_delta = format_delta(cur, yoy, unit)
        assessment, notable = _assess(kpi, cur, prev, z)
        out.append({
            "id": kpi["id"], "name": kpi["name"], "category": kpi["category"], "unit": unit,
            "direction": kpi["direction"], "period": period.strftime("%Y-%m"),
            "is_reporting_month": period == report_month,
            "value": cur, "value_fmt": format_value(cur, unit),
            "previous_value": prev, "previous_fmt": format_value(prev, unit),
            "delta_abs": delta["delta_abs"], "delta_pct": delta["delta_pct"], "delta_fmt": delta["delta_fmt"],
            "yoy_value": yoy, "yoy_fmt": format_value(yoy, unit), "yoy_delta_fmt": yoy_delta["delta_fmt"],
            "trailing_6m_mean": float(hist.mean()) if len(hist) else None,
            "trailing_6m_mean_fmt": format_value(float(hist.mean()), unit) if len(hist) else "n/a",
            "z_vs_trailing_6m": round(z, 2) if z is not None else None,
            "target": kpi.get("target", (None, None))[0], "target_op": kpi.get("target", (None, None))[1],
            "target_fmt": format_value(kpi["target"][0], unit) if kpi.get("target") else None,
            "target_status": _target_status(kpi, cur), "assessment": assessment, "notable": notable,
            "definition": kpi["definition"], "lag_note": kpi.get("lag_note"),
        })
    return out


def _weekly_snapshot(weekly: pd.DataFrame) -> List[Dict]:
    w = weekly.set_index("week_start").sort_index()
    out = []
    for kpi in WEEKLY_KPIS:
        s = w[kpi["id"]].dropna()
        if len(s) < 5:
            continue
        cur, prev = float(s.iloc[-1]), float(s.iloc[-2])
        avg4 = float(s.iloc[-5:-1].mean())
        unit = kpi["unit"]
        d1, d4 = format_delta(cur, prev, unit), format_delta(cur, avg4, unit)
        assessment, notable = _assess({**kpi}, cur, prev, None)
        out.append({"id": kpi["id"], "name": kpi["name"], "unit": unit, "direction": kpi["direction"],
                    "week_start": s.index[-1].strftime("%Y-%m-%d"),
                    "value": cur, "value_fmt": format_value(cur, unit),
                    "prior_week": prev, "prior_week_fmt": format_value(prev, unit), "wow_delta_fmt": d1["delta_fmt"],
                    "avg_4w": avg4, "avg_4w_fmt": format_value(avg4, unit), "vs_4w_delta_fmt": d4["delta_fmt"],
                    "assessment": assessment, "notable": notable})
    return out


def compute_kpis(settings: Optional[Settings] = None) -> Dict:
    settings = settings or get_settings()
    monthly, weekly = load_kpi_tables(settings)
    as_of = pd.Timestamp(settings.end_date)
    out_dir = settings.outputs_dir / "kpis"
    out_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(out_dir / "kpi_monthly.csv", index=False)
    weekly.to_csv(out_dir / "kpi_weekly.csv", index=False)
    long = monthly.melt(id_vars="month_start", var_name="kpi_id", value_name="value")
    meta = pd.DataFrame(KPIS)[["id", "name", "category", "unit", "direction"]].rename(columns={"id": "kpi_id", "name": "kpi_name"})
    long = long.merge(meta, on="kpi_id", how="left")
    long.to_csv(out_dir / "kpi_monthly_long.csv", index=False)

    snapshot = {
        "as_of_date": settings.end_date,
        "synthetic_data": True,
        "monthly": _monthly_snapshot(monthly, as_of),
        "weekly": _weekly_snapshot(weekly),
    }
    snapshot["reporting_month"] = max(k["period"] for k in snapshot["monthly"])
    if snapshot["weekly"]:
        ws = pd.Timestamp(snapshot["weekly"][0]["week_start"])
        snapshot["reporting_week"] = {"start": ws.strftime("%Y-%m-%d"), "end": (ws + pd.Timedelta(days=6)).strftime("%Y-%m-%d")}
    write_json(snapshot, out_dir / "kpi_snapshot.json")
    return snapshot


if __name__ == "__main__":
    snap = compute_kpis()
    for k in snap["monthly"]:
        print("%-34s %-8s %14s  %-10s %s" % (k["name"], k["period"], k["value_fmt"], k["delta_fmt"], k["assessment"]))
