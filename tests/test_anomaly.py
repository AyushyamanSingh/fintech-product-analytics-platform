"""Anomaly detector: finds planted spikes, stays quiet on noise, respects small denominators."""
import numpy as np
import pandas as pd

from python.anomaly_detection import detect


def daily_frame(days=140, seed=0):
    rng = np.random.default_rng(seed)
    d = pd.date_range("2024-01-01", periods=days, freq="D")
    n = len(d)
    approvals = rng.poisson(60, n)
    rejections = rng.poisson(40, n)
    success = rng.poisson(800, n)
    failed = rng.binomial(success + 80, 0.08)
    df = pd.DataFrame({
        "date_day": d, "iso_dow": d.dayofweek + 1, "signups": rng.poisson(300, n),
        "applications_submitted": rng.poisson(100, n), "approvals": approvals, "rejections": rejections,
        "approval_rate": approvals / (approvals + rejections), "loans_disbursed": rng.poisson(50, n),
        "payments_success": success, "payments_failed": failed, "payment_failure_rate": failed / (success + failed),
        "support_tickets": rng.poisson(30, n), "kyc_completions_backend": rng.poisson(150, n), "dau": rng.poisson(2000, n),
    })
    df["kyc_completions_tracked"] = df["kyc_completions_backend"]
    return df


def test_quiet_series_has_few_flags():
    flags = detect(daily_frame())
    assert len(flags) <= 2  # false-positive budget on pure noise


def test_planted_spike_is_found():
    df = daily_frame()
    i = 120
    df.loc[i, "payments_failed"] = 600
    df.loc[i, "payment_failure_rate"] = 600 / (df.loc[i, "payments_success"] + 600)
    df.loc[i + 3, "kyc_completions_tracked"] = int(df.loc[i + 3, "kyc_completions_backend"] * 0.4)
    flags = detect(df)
    hit = flags[(flags["metric"] == "payment_failure_rate") & (flags["date_day"] == df.loc[i, "date_day"])]
    assert len(hit) == 1 and hit.iloc[0]["direction"] == "spike"
    assert ((flags["metric"] == "kyc_tracking_ratio") & (flags["date_day"] == df.loc[i + 3, "date_day"])).any()


def test_small_denominator_rates_not_scored():
    df = daily_frame()
    i = 125
    df.loc[i, ["approvals", "rejections"]] = [0, 5]  # 0% approval, but only 5 decisions
    df.loc[i, "approval_rate"] = 0.0
    flags = detect(df)
    assert not ((flags["metric"] == "approval_rate") & (flags["date_day"] == df.loc[i, "date_day"])).any()
