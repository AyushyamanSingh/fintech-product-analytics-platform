"""Synthetic data generator for *Vittora Credit*, a FICTIONAL Indian digital lender.

ALL DATA PRODUCED HERE IS SYNTHETIC. No real customers, companies or transactions.

The simulator walks every customer through the lending lifecycle

    acquisition -> signup -> KYC -> application -> decision -> disbursal
    -> monthly repayments -> closure / delinquency -> repeat borrowing

and emits eleven source-system tables (CRM, loan management system, payment ledger,
Mixpanel-style event stream, helpdesk, experimentation platform, marketing).

Behavioural "ground truths" are planted on purpose so that the analytics layer has
something real to discover (see docs/technical_documentation.md, section 3):

* KYC is the largest funnel leak - worse on web, in tier-3 cities and for gig workers.
* paid_social / affiliate bring cheap signups but weak conversion and higher risk;
  referral and employer partnerships bring the best unit economics.
* EXP-ONB-2026-01 (onboarding redesign) lifts 7-day KYC completion by ~4pp; shipped 2 Mar 2026.
* Festive-season 2025 cohorts acquired via paid social / affiliate default more often.
* 14-15 Aug 2025 payment-gateway outage: failed auto-debits, late payments, ticket spike.
* 12-15 May 2025 Android app 5.2.0 stopped firing ``kyc_completed`` (backend data intact).
* 8-21 Sep 2025 affiliate fraud ring: application surge and approval-rate dip.
* Autopay users pay on time more often and come back for repeat loans more often.

Usage::

    python -m python.generate_data                 # full 80k-customer dataset
    python -m python.generate_data --n-customers 5000 --no-dq-issues
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from python.config import COMPANY_NAME, Settings, get_settings

# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------
CHANNELS = np.array(["organic", "paid_search", "paid_social", "affiliate", "referral", "partnerships"])
PLATFORMS = np.array(["android", "ios", "web"])
EMPLOYMENT = np.array(["salaried", "self_employed", "gig_worker", "student"])
TIERS = np.array(["tier_1", "tier_2", "tier_3"])

CITIES = {
    "tier_1": [("Mumbai", "Maharashtra"), ("Delhi", "Delhi"), ("Bengaluru", "Karnataka"),
               ("Hyderabad", "Telangana"), ("Chennai", "Tamil Nadu"), ("Pune", "Maharashtra"),
               ("Kolkata", "West Bengal"), ("Ahmedabad", "Gujarat")],
    "tier_2": [("Jaipur", "Rajasthan"), ("Lucknow", "Uttar Pradesh"), ("Chandigarh", "Chandigarh"),
               ("Indore", "Madhya Pradesh"), ("Kochi", "Kerala"), ("Nagpur", "Maharashtra"),
               ("Coimbatore", "Tamil Nadu"), ("Mohali", "Punjab"), ("Bhopal", "Madhya Pradesh"),
               ("Vadodara", "Gujarat"), ("Ludhiana", "Punjab"), ("Surat", "Gujarat"),
               ("Patna", "Bihar"), ("Visakhapatnam", "Andhra Pradesh")],
    "tier_3": [("Hisar", "Haryana"), ("Bathinda", "Punjab"), ("Kota", "Rajasthan"),
               ("Siliguri", "West Bengal"), ("Udaipur", "Rajasthan"), ("Dehradun", "Uttarakhand"),
               ("Jammu", "Jammu and Kashmir"), ("Ranchi", "Jharkhand"), ("Guntur", "Andhra Pradesh"),
               ("Warangal", "Telangana"), ("Gorakhpur", "Uttar Pradesh"), ("Belagavi", "Karnataka")],
}

PRODUCTS = [
    # id, name, category, min, max, min_tenure, max_tenure, apr %, fee %, revenue model, launch
    ("P01", "Instant Personal Loan", "personal_loan", 10000, 200000, 3, 24, 24.0, 2.50, "interest_and_fees", "2021-04-01"),
    ("P02", "Salary Advance", "salary_advance", 5000, 50000, 1, 3, 30.0, 2.00, "interest_and_fees", "2021-09-01"),
    ("P03", "Pay Later", "bnpl", 1000, 20000, 1, 6, 16.0, 1.00, "interest_and_fees", "2022-06-01"),
    ("P04", "Consumer Durable Loan", "consumer_durable", 15000, 150000, 6, 18, 20.0, 2.00, "interest_and_fees", "2022-11-01"),
    ("P05", "Business Micro Loan", "business_loan", 50000, 500000, 12, 36, 26.0, 3.00, "interest_and_fees", "2023-03-01"),
    ("P06", "P2P Marketplace Loan", "p2p_loan", 25000, 300000, 6, 24, 22.0, 3.50, "platform_fee", "2023-08-01"),
    ("P07", "Flexi Credit Line", "credit_line", 10000, 100000, 3, 12, 28.0, 1.50, "interest_and_fees", "2025-04-01"),
]
PRODUCT_IDS = [p[0] for p in PRODUCTS]
PROD = {p[0]: dict(zip(["id", "name", "category", "min", "max", "tmin", "tmax", "apr", "fee", "rev", "launch"], p))
        for p in PRODUCTS}
P07_LAUNCH = pd.Timestamp("2025-04-01")

PRODUCT_MIX = {  # weights over P01..P07 (P07 only offered after its launch)
    "salaried": [0.34, 0.24, 0.14, 0.12, 0.02, 0.06, 0.08],
    "self_employed": [0.24, 0.00, 0.07, 0.10, 0.33, 0.18, 0.08],
    "gig_worker": [0.27, 0.00, 0.34, 0.15, 0.08, 0.08, 0.08],
    "student": [0.00, 0.00, 0.80, 0.20, 0.00, 0.00, 0.00],
}
AMOUNT_MODEL = {  # (kind, median, sigma)
    "P01": ("income_multiple", 2.0, 0.45),
    "P02": ("income_multiple", 0.45, 0.25),
    "P03": ("absolute", 5500, 0.60),
    "P04": ("absolute", 38000, 0.45),
    "P05": ("absolute", 160000, 0.55),
    "P06": ("absolute", 85000, 0.50),
    "P07": ("income_multiple", 0.90, 0.35),
}
TENURES = {
    "P01": ([3, 6, 9, 12, 18, 24], [0.08, 0.22, 0.15, 0.30, 0.13, 0.12]),
    "P02": ([1, 2, 3], [0.55, 0.25, 0.20]),
    "P03": ([1, 3, 6], [0.45, 0.35, 0.20]),
    "P04": ([6, 9, 12, 18], [0.30, 0.25, 0.30, 0.15]),
    "P05": ([12, 18, 24, 36], [0.30, 0.25, 0.30, 0.15]),
    "P06": ([6, 12, 18, 24], [0.20, 0.40, 0.25, 0.15]),
    "P07": ([3, 6, 12], [0.35, 0.40, 0.25]),
}
PURPOSES = {
    "P01": (["medical", "travel", "education", "wedding", "debt_consolidation", "home_renovation", "other"],
            [0.18, 0.12, 0.12, 0.10, 0.22, 0.14, 0.12]),
    "P02": (["salary_advance"], [1.0]),
    "P03": (["online_shopping"], [1.0]),
    "P04": (["electronics", "home_appliances", "mobile_phone"], [0.35, 0.30, 0.35]),
    "P05": (["working_capital", "inventory", "equipment"], [0.50, 0.30, 0.20]),
    "P06": (["personal", "business", "education"], [0.50, 0.35, 0.15]),
    "P07": (["flexible_credit"], [1.0]),
}

# Risk / behaviour parameters (log-odds contributions)
EMP_RISK = {"salaried": -0.20, "self_employed": 0.10, "gig_worker": 0.35, "student": 0.45}
CHANNEL_RISK = {"organic": 0.0, "paid_search": -0.05, "paid_social": 0.25, "affiliate": 0.35,
                "referral": -0.30, "partnerships": -0.35}
PRODUCT_RISK = {"P01": 0.0, "P02": -0.25, "P03": -0.10, "P04": -0.05, "P05": 0.30, "P06": 0.10, "P07": 0.15}
TARGET_APPROVAL = {"P01": 0.45, "P02": 0.63, "P03": 0.67, "P04": 0.57, "P05": 0.35, "P06": 0.41, "P07": 0.47}
BAND_APR_ADJ = {"A": -3.0, "B": -1.5, "C": 0.0, "D": 2.0, "E": 4.0}
REPEAT_PROB = {"P01": 0.45, "P02": 0.66, "P03": 0.55, "P04": 0.28, "P05": 0.42, "P06": 0.35, "P07": 0.52}
FORECLOSURE_FEE_PCT = {"P01": 0.02, "P04": 0.02, "P05": 0.02}

# Funnel multipliers
KYC_START_CH = {"organic": 1.00, "paid_search": 1.01, "paid_social": 0.93, "affiliate": 0.97,
                "referral": 1.04, "partnerships": 1.05}
KYC_DONE_CH = {"organic": 1.00, "paid_search": 1.02, "paid_social": 0.88, "affiliate": 0.92,
               "referral": 1.09, "partnerships": 1.10}
KYC_DONE_PLATFORM = {"android": 1.00, "ios": 1.04, "web": 0.84}
KYC_DONE_TIER = {"tier_1": 1.02, "tier_2": 1.00, "tier_3": 0.92}
KYC_DONE_EMP = {"salaried": 1.02, "self_employed": 0.98, "gig_worker": 0.93, "student": 0.92}
APPLY_INTENT_CH = {"organic": 0.98, "paid_search": 1.06, "paid_social": 0.82, "affiliate": 0.95,
                   "referral": 1.05, "partnerships": 1.08}

# Time-varying acquisition mix
CHANNEL_MIX_START = np.array([0.22, 0.23, 0.22, 0.14, 0.09, 0.10])
CHANNEL_MIX_END = np.array([0.24, 0.19, 0.21, 0.11, 0.15, 0.10])
PLATFORM_MIX = {"paid_search": [0.66, 0.16, 0.18], "partnerships": [0.70, 0.25, 0.05]}
PLATFORM_MIX_DEFAULT = [0.79, 0.17, 0.04]
EMPLOYMENT_MIX = {"partnerships": [0.92, 0.04, 0.04, 0.00]}
EMPLOYMENT_MIX_DEFAULT = [0.56, 0.22, 0.15, 0.07]
DOW_WEIGHT = np.array([1.05, 1.04, 1.00, 1.00, 0.96, 0.88, 0.84])
HOUR_WEIGHTS = np.array([1.0, 0.6, 0.4, 0.3, 0.3, 0.5, 1.2, 2.2, 3.2, 3.8, 4.2, 4.6,
                         5.0, 4.8, 4.4, 4.2, 4.2, 4.5, 5.0, 5.6, 6.0, 5.6, 4.2, 2.4])
HOUR_WEIGHTS = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()

# Planted events
FESTIVE_WINDOWS = [("2024-10-10", "2024-11-10", 1.25), ("2025-10-01", "2025-11-15", 1.45)]
FESTIVE_2025_DISBURSAL = (pd.Timestamp("2025-10-01"), pd.Timestamp("2025-11-30"))
FRAUD_START, FRAUD_END, FRAUD_RING_SIZE = "2025-09-08", "2025-09-21", 1200
OUTAGE_DAYS = pd.to_datetime(["2025-08-14", "2025-08-15"])
ONB_EXP = ("EXP-ONB-2026-01", pd.Timestamp("2026-01-12"), pd.Timestamp("2026-02-22 23:59:59"))
ONB_ROLLOUT = pd.Timestamp("2026-03-02")
RPY_EXP = ("EXP-RPY-2025-11", pd.Timestamp("2025-11-03"), pd.Timestamp("2025-12-14 23:59:59"))
RPY_ROLLOUT = pd.Timestamp("2026-01-05")
PRC_EXP = ("EXP-PRC-2025-06", pd.Timestamp("2025-06-02"), pd.Timestamp("2025-06-29 23:59:59"))
KYC_TRACKING_BUG_VERSION = "5.2.0"
APP_RELEASES = [("2024-05-20", "4.8.0"), ("2024-08-26", "4.9.0"), ("2024-11-18", "5.0.0"),
                ("2025-02-24", "5.1.0"), ("2025-05-12", "5.2.0"), ("2025-05-16", "5.2.1"),
                ("2025-08-04", "5.3.0"), ("2025-11-10", "5.4.0"), ("2026-03-02", "6.0.0"),
                ("2026-05-18", "6.1.0")]

CAMPAIGN_CODES = {"paid_search": "PSR", "paid_social": "PSO", "affiliate": "AFF", "referral": "REF",
                  "partnerships": "PTN"}
CAMPAIGN_CPA = {"paid_search": 520, "paid_social": 300, "affiliate": 380, "referral": 250, "partnerships": 180}
CAMPAIGN_CTR = {"paid_search": 0.045, "paid_social": 0.012, "affiliate": 0.020, "referral": 0.25, "partnerships": 0.05}
CHANNEL_LABEL = {"paid_search": "Paid Search", "paid_social": "Paid Social", "affiliate": "Affiliate",
                 "referral": "Refer & Earn", "partnerships": "Employer Partnerships"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _choice_rows(rng: np.random.Generator, probs: np.ndarray) -> np.ndarray:
    """Row-wise categorical draw from an (n, k) matrix of (unnormalised) weights."""
    cum = np.cumsum(probs, axis=1)
    u = rng.random(probs.shape[0]) * cum[:, -1]
    return np.minimum((u[:, None] > cum).sum(axis=1), probs.shape[1] - 1)


def _td(values, unit: str) -> pd.TimedeltaIndex:
    return pd.to_timedelta(np.asarray(values, dtype="float64"), unit=unit)


def _add_months(dates: pd.Series, k: np.ndarray) -> pd.Series:
    """Add k calendar months; EMI day capped at the 28th so every month has it."""
    y, m = dates.dt.year.values, dates.dt.month.values
    d = np.minimum(dates.dt.day.values, 28)
    tot = y * 12 + (m - 1) + k
    return pd.to_datetime(pd.DataFrame({"year": tot // 12, "month": tot % 12 + 1, "day": d}))


def _map(values: np.ndarray, mapping: Dict) -> np.ndarray:
    return pd.Series(values).map(mapping).to_numpy(dtype=float)


def _json_props(cols: Dict[str, pd.Series], numeric: Tuple[str, ...] = ()) -> pd.Series:
    """Vectorised JSON-object builder for event properties (Mixpanel-style)."""
    parts = None
    for key, ser in cols.items():
        ser = ser.reset_index(drop=True)
        if key in numeric:
            val = ser.astype(str)
        else:
            val = '"' + ser.fillna("").astype(str) + '"'
        piece = '"' + key + '":' + val
        parts = piece if parts is None else parts + "," + piece
    return "{" + parts + "}"


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------
class LendingSimulator:
    def __init__(self, settings: Settings):
        self.s = settings
        self.rng = np.random.default_rng(settings.seed)
        self.start = pd.Timestamp(settings.start_date)
        self.asof = pd.Timestamp(settings.end_date)
        self.cutoff = self.asof + pd.Timedelta(days=1)  # exclusive upper bound for timestamps
        self.scale = settings.n_customers / 80_000
        self.thresholds: Optional[Dict[str, float]] = None
        self._app_key = 0

    # ------------------------------------------------------------------ products
    def build_products(self) -> pd.DataFrame:
        df = pd.DataFrame(PRODUCTS, columns=[
            "product_id", "product_name", "product_category", "min_amount", "max_amount",
            "min_tenure_months", "max_tenure_months", "base_apr_pct", "processing_fee_pct",
            "revenue_model", "launch_date"])
        df["launch_date"] = pd.to_datetime(df["launch_date"]).dt.date
        df["is_secured"] = False
        df["is_active"] = True
        return df

    # ------------------------------------------------------------------ customers
    def build_customers(self) -> pd.DataFrame:
        rng = self.rng
        n = self.s.n_customers
        days = pd.date_range(self.start, self.asof, freq="D")
        nd = len(days)
        t = np.arange(nd) / 365.0
        w = np.exp(0.33 * t) * DOW_WEIGHT[days.dayofweek.values]
        festive = np.zeros(nd, dtype=bool)
        for a, b, mult in FESTIVE_WINDOWS:
            mask = (days >= a) & (days <= b)
            w[mask] *= mult
            festive |= mask
        day_idx = np.repeat(np.arange(nd), rng.multinomial(n, w / w.sum()))

        mix = CHANNEL_MIX_START + (CHANNEL_MIX_END - CHANNEL_MIX_START) * (t / t.max())[:, None]
        mix[festive, 2] += 0.12
        ch_idx = _choice_rows(rng, mix[day_idx])

        # Affiliate fraud ring (8-21 Sep 2025): bursts of synthetic identities at odd hours
        n_fraud = max(1, int(round(FRAUD_RING_SIZE * self.scale)))
        f_first = (pd.Timestamp(FRAUD_START) - self.start).days
        f_len = (pd.Timestamp(FRAUD_END) - pd.Timestamp(FRAUD_START)).days + 1
        day_idx = np.concatenate([day_idx, f_first + rng.integers(0, f_len, n_fraud)])
        ch_idx = np.concatenate([ch_idx, np.full(n_fraud, 3)])
        fraud = np.concatenate([np.zeros(n, bool), np.ones(n_fraud, bool)])
        N = len(day_idx)

        hours = rng.choice(24, size=N, p=HOUR_WEIGHTS)
        hours[fraud] = rng.integers(0, 24, fraud.sum())
        signup = pd.Series(days.values[day_idx]) + _td(hours * 3600 + rng.integers(0, 3600, N), "s")
        channel = CHANNELS[ch_idx]

        plat_p = np.array([PLATFORM_MIX.get(c, PLATFORM_MIX_DEFAULT) for c in CHANNELS])[ch_idx]
        plat_p[fraud] = [0.97, 0.03, 0.0]
        platform = PLATFORMS[_choice_rows(rng, plat_p)]

        emp_p = np.array([EMPLOYMENT_MIX.get(c, EMPLOYMENT_MIX_DEFAULT) for c in CHANNELS])[ch_idx]
        emp_p[fraud] = [0.50, 0.20, 0.30, 0.0]
        emp = EMPLOYMENT[_choice_rows(rng, emp_p)]
        student = emp == "student"

        age = np.clip(np.round(rng.normal(32, 7, N)), 21, 60)
        age[student] = rng.integers(18, 25, student.sum())

        inc_med = _map(emp, {"salaried": 42000, "self_employed": 50000, "gig_worker": 21000, "student": 8000})
        inc_sig = _map(emp, {"salaried": 0.45, "self_employed": 0.70, "gig_worker": 0.35, "student": 0.50})
        income = np.round(np.exp(np.log(inc_med) + rng.normal(0, 1, N) * inc_sig) / 500) * 500
        income = np.maximum(income, 3000)

        tier_p = np.tile([0.46, 0.34, 0.20], (N, 1))
        tier_p[fraud] = [0.30, 0.30, 0.40]
        tier = TIERS[_choice_rows(rng, tier_p)]
        city = np.empty(N, dtype=object)
        state = np.empty(N, dtype=object)
        for tname, cities in CITIES.items():
            m = tier == tname
            pick = rng.integers(0, len(cities), m.sum())
            city[m] = [cities[i][0] for i in pick]
            state[m] = [cities[i][1] for i in pick]

        ntc_p = _map(emp, {"salaried": 0.15, "self_employed": 0.22, "gig_worker": 0.40, "student": 0.70})
        ntc_p = ntc_p + np.where(channel == "affiliate", 0.08, 0.0)
        ntc_p[fraud] = 0.60
        ntc = rng.random(N) < ntc_p
        cs_mean = _map(emp, {"salaried": 728, "self_employed": 705, "gig_worker": 672, "student": 690})
        cs_mean += _map(channel, {"organic": 0, "paid_search": 5, "paid_social": -15, "affiliate": -25,
                                  "referral": 15, "partnerships": 12})
        cs_mean[fraud] -= 60
        credit_score = np.clip(np.round(rng.normal(cs_mean, 55)), 300, 900)
        credit_score[ntc] = np.nan

        eng = np.exp(rng.normal(0, 0.45, N))
        eng *= _map(channel, {"organic": 1.0, "paid_search": 1.0, "paid_social": 0.9, "affiliate": 0.95,
                              "referral": 1.1, "partnerships": 1.1})
        eng[fraud] *= 0.3

        cust = pd.DataFrame({
            "signup_ts": signup.dt.floor("s"), "acquisition_channel": channel, "signup_platform": platform,
            "city": city, "state": state, "city_tier": tier, "age": age.astype(int),
            "employment_type": emp, "monthly_income": income, "credit_score": credit_score,
            "_fraud": fraud, "_eng": eng,
        })
        cust = cust.sort_values("signup_ts", kind="mergesort").reset_index(drop=True)
        cust.insert(0, "customer_id", ["C" + str(i).zfill(6) for i in range(1, len(cust) + 1)])
        cust["marketing_opt_in"] = rng.random(len(cust)) < 0.62
        self._assign_onboarding_experiment(cust)
        self._simulate_kyc(cust)
        return cust

    def _assign_onboarding_experiment(self, cust: pd.DataFrame) -> None:
        _, a, b = ONB_EXP
        app = cust["signup_platform"] != "web"
        in_exp = app & (cust["signup_ts"] >= a) & (cust["signup_ts"] <= b)
        variant = np.where(self.rng.random(len(cust)) < 0.5, "treatment", "control")
        cust["_onb_variant"] = np.where(in_exp, variant, None)
        cust["_onb_treated"] = (cust["_onb_variant"] == "treatment") | (app & (cust["signup_ts"] >= ONB_ROLLOUT))

    def _simulate_kyc(self, cust: pd.DataFrame) -> None:
        rng = self.rng
        N = len(cust)
        ch, plat = cust["acquisition_channel"].values, cust["signup_platform"].values
        treated = cust["_onb_treated"].values
        fraud = cust["_fraud"].values

        p_start = 0.87 * _map(ch, KYC_START_CH) * np.where(plat == "web", 0.92, 1.0) + 0.018 * treated
        p_start[fraud] = 0.97
        p_done = (0.70 * _map(ch, KYC_DONE_CH) * _map(plat, KYC_DONE_PLATFORM)
                  * _map(cust["city_tier"].values, KYC_DONE_TIER) * _map(cust["employment_type"].values, KYC_DONE_EMP)
                  * np.where(cust["credit_score"].isna(), 0.95, 1.0)) + 0.05 * treated
        p_done[fraud] = 0.55  # synthetic identities built on stolen documents often pass KYC
        started = rng.random(N) < np.clip(p_start, 0.02, 0.97)
        done = started & (rng.random(N) < np.clip(p_done, 0.02, 0.97))

        fast_start = rng.random(N) < 0.78
        start_delay_min = np.where(fast_start, 0.5 + rng.exponential(6, N), rng.exponential(2 * 1440, N))
        fast_done = rng.random(N) < np.where(treated, 0.75, 0.72)
        done_delay_min = np.where(fast_done, np.exp(np.log(11) + 0.8 * rng.normal(0, 1, N)),
                                  30 + rng.exponential(2.5 * 1440, N))
        start_ts = (cust["signup_ts"] + _td(start_delay_min, "m")).dt.floor("s")
        done_ts = (start_ts + _td(done_delay_min, "m")).dt.floor("s")
        started &= (start_ts < self.cutoff).values
        done &= started & (done_ts < self.cutoff).values

        kyc_fail = started & ~done & (rng.random(N) < np.where(fraud, 0.60, 0.15))
        status = np.where(done, "verified", np.where(kyc_fail, "failed", np.where(started, "pending", "not_started")))
        method_ctrl = ["aadhaar_okyc", "digilocker", "ckyc", "video_kyc"]
        m_idx = _choice_rows(rng, np.where(treated[:, None], [[0.25, 0.60, 0.10, 0.05]], [[0.40, 0.35, 0.15, 0.10]]))
        cust["kyc_status"] = status
        cust["kyc_started_ts"] = start_ts.where(started)
        cust["kyc_completed_ts"] = done_ts.where(done)
        cust["kyc_method"] = np.where(done, np.array(method_ctrl)[m_idx], None)

    # ------------------------------------------------------------------ campaigns
    def build_campaigns(self, cust: pd.DataFrame) -> pd.DataFrame:
        rng = self.rng
        ch = cust["acquisition_channel"].values
        month = cust["signup_ts"].dt.strftime("%Y%m").values
        camp = np.array([None] * len(cust), dtype=object)
        paid = ch != "organic"
        codes = pd.Series(ch).map(CAMPAIGN_CODES).fillna("").values
        camp[paid] = "CMP-" + month[paid] + "-" + codes[paid]

        ts = cust["signup_ts"]
        for tag, (a, b, _) in zip(["FEST24", "FEST25"], FESTIVE_WINDOWS):
            m = (ch == "paid_social") & (ts >= a) & (ts <= pd.Timestamp(b) + pd.Timedelta(days=1))
            camp[m.values] = "CMP-" + tag + "-PSO"
        fraud = cust["_fraud"].values
        window = (ts >= FRAUD_START) & (ts <= pd.Timestamp(FRAUD_END) + pd.Timedelta(days=1))
        network_b = fraud | ((ch == "affiliate") & window.values & (rng.random(len(cust)) < 0.30))
        camp[network_b] = "CMP-202509-AFFNB"
        cust["campaign_id"] = camp

        g = (cust[paid].groupby("campaign_id")
             .agg(channel=("acquisition_channel", "first"), signups=("customer_id", "size"),
                  first_ts=("signup_ts", "min")).reset_index())
        rows = []
        for r in g.itertuples(index=False):
            cid, channel = r.campaign_id, r.channel
            if cid.startswith("CMP-FEST"):
                year = 2024 if "24" in cid else 2025
                a, b, _ = FESTIVE_WINDOWS[0 if year == 2024 else 1]
                start, end = pd.Timestamp(a), pd.Timestamp(b)
                name = "Festive Season Mega Campaign %d | Consumer Durables | Paid Social" % year
                target, cpa, objective = "P04", 340, "seasonal_acquisition"
            elif cid == "CMP-202509-AFFNB":
                start, end = pd.Timestamp(FRAUD_START), pd.Timestamp(FRAUD_END)
                name = "Affiliate Network B | Personal Loan Push | Sep 2025"
                target, cpa, objective = "P01", 380, "acquisition"
            else:
                ym = cid.split("-")[1]
                start = pd.Timestamp(ym[:4] + "-" + ym[4:] + "-01")
                end = start + pd.offsets.MonthEnd(0)
                label = CHANNEL_LABEL[channel]
                target = {"paid_search": "P01", "affiliate": "P01", "partnerships": "P02",
                          "referral": None}.get(channel, "P03" if int(ym[4:]) % 2 else "P01")
                name = "%s | %s | %s" % (label, "Always-on" if channel != "referral" else "Referral bonus",
                                          start.strftime("%b %Y"))
                cpa, objective = CAMPAIGN_CPA[channel], "acquisition" if channel != "referral" else "referral"
            start = max(start, self.start)
            end = min(end, self.asof)
            spend = round(r.signups * cpa * float(np.exp(rng.normal(0, 0.12))), 2)
            budget = float(np.ceil(spend * rng.uniform(1.0, 1.2) / 10000) * 10000)
            clicks = int(r.signups / rng.uniform(0.08, 0.16))
            impressions = int(clicks / CAMPAIGN_CTR[channel] * rng.uniform(0.85, 1.15))
            rows.append((cid, name, channel, objective, target, start.date(), end.date(), budget, spend,
                         impressions, clicks))
        camps = pd.DataFrame(rows, columns=["campaign_id", "campaign_name", "channel", "objective",
                                            "target_product_id", "start_date", "end_date", "budget_inr",
                                            "spend_inr", "impressions", "clicks"])
        return camps.sort_values(["start_date", "campaign_id"]).reset_index(drop=True)

    # ------------------------------------------------------------------ lending
    def simulate_lending(self, cust: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        rng = self.rng
        # Generation 0: first application after KYC
        kyc = cust.index[cust["kyc_completed_ts"].notna()].values
        c = cust.loc[kyc]
        p_apply = (0.80 * _map(c["acquisition_channel"].values, APPLY_INTENT_CH)
                   * np.where(c["employment_type"].values == "student", 0.85, 1.0)
                   + 0.01 * c["_onb_treated"].values)
        p_apply[c["_fraud"].values] = 0.95
        applies = rng.random(len(c)) < np.clip(p_apply, 0, 0.97)
        fast = rng.random(len(c)) < 0.65
        delay_days = np.where(fast, rng.exponential(0.4, len(c)), rng.exponential(25, len(c)))
        start_ts = c["kyc_completed_ts"] + _td(delay_days * 1440 + 1, "m")
        ok = applies & (start_ts < self.cutoff).values
        pending = pd.DataFrame({"_cidx": kyc[ok], "started_ts": start_ts.values[ok],
                                "is_repeat": False, "prior_good": 0, "prev_product": None})

        apps_all, loans_all, reps_all = [], [], []
        gen = 0
        while len(pending) and gen < 15:
            apps = self._draw_applications(cust, pending, gen)
            apps = self._decide(cust, apps, gen)
            loans, reps = self._book_loans(cust, apps)
            apps_all.append(apps)
            if len(loans):
                loans_all.append(loans)
                reps_all.append(reps)
            pending = self._next_applications(cust, apps, loans)
            gen += 1

        apps = pd.concat(apps_all, ignore_index=True)
        loans = pd.concat(loans_all, ignore_index=True)
        reps = pd.concat(reps_all, ignore_index=True)
        return self._assign_lending_ids(cust, apps, loans, reps)

    def _draw_applications(self, cust: pd.DataFrame, pending: pd.DataFrame, gen: int) -> pd.DataFrame:
        rng = self.rng
        a = pending.reset_index(drop=True).copy()
        n = len(a)
        a["_app_key"] = np.arange(self._app_key, self._app_key + n)
        self._app_key += n
        c = cust.loc[a["_cidx"].values]
        emp = c["employment_type"].values
        W = np.array([PRODUCT_MIX[e] for e in emp], dtype=float)
        W[(a["started_ts"] < P07_LAUNCH).values, 6] = 0.0
        partner = (c["acquisition_channel"].values == "partnerships") & (emp == "salaried")
        W[partner] = 0.3 * W[partner] / W[partner].sum(axis=1, keepdims=True)
        W[partner, 1] += 0.7
        fraud = c["_fraud"].values
        W[fraud] = [0.8, 0, 0, 0, 0, 0, 0.2]
        W[fraud & (a["started_ts"] < P07_LAUNCH).values, 6] = 0.0
        prod = np.array(PRODUCT_IDS)[_choice_rows(rng, W)]
        sticky = a["prev_product"].notna().values & (rng.random(n) < 0.65)
        prod[sticky] = a["prev_product"].values[sticky]
        a["product_id"] = prod

        income = c["monthly_income"].values
        amount = np.zeros(n)
        tenure = np.zeros(n, dtype=int)
        purpose = np.empty(n, dtype=object)
        for pid in PRODUCT_IDS:
            m = prod == pid
            k = int(m.sum())
            if not k:
                continue
            kind, med, sig = AMOUNT_MODEL[pid]
            base = income[m] * med if kind == "income_multiple" else med
            amt = np.exp(np.log(base) + rng.normal(0, sig, k))
            amount[m] = np.clip(amt, PROD[pid]["min"], PROD[pid]["max"])
            choices, probs = TENURES[pid]
            tenure[m] = rng.choice(choices, size=k, p=probs)
            pchoices, pprobs = PURPOSES[pid]
            purpose[m] = rng.choice(pchoices, size=k, p=pprobs)
        amount *= np.where(a["prior_good"].values > 0, 1.15, 1.0)
        amount = np.where(amount < 10000, np.round(amount / 100) * 100, np.round(amount / 1000) * 1000)
        lo = np.array([PROD[p]["min"] for p in prod])
        hi = np.array([PROD[p]["max"] for p in prod])
        a["requested_amount"] = np.clip(amount, lo, hi)
        a["requested_tenure_months"] = tenure
        a["loan_purpose"] = purpose

        plat = c["signup_platform"].values.copy()
        switch = rng.random(n) < 0.15
        plat[switch] = np.where(rng.random(switch.sum()) < 0.7, "android", "ios")
        a["application_platform"] = plat
        a["generation"] = gen

        p_sub = (0.82 * np.where(plat == "web", 0.88, 1.0)
                 * pd.Series(prod).map({"P05": 0.80, "P06": 0.90}).fillna(1.0).values
                 + 0.10 * a["is_repeat"].values)
        p_sub[fraud] = 0.90
        submitted = rng.random(n) < np.clip(p_sub, 0, 0.96)
        manual = np.isin(prod, ["P05", "P06"])
        sub_delay = np.exp(np.log(np.where(manual, 50, 7)) + 0.9 * rng.normal(0, 1, n))
        sub_ts = (a["started_ts"] + _td(sub_delay, "m")).dt.floor("s")
        submitted &= (sub_ts < self.cutoff).values
        a["started_ts"] = a["started_ts"].dt.floor("s")
        a["submitted_ts"] = sub_ts.where(submitted)
        return a

    def _decide(self, cust: pd.DataFrame, a: pd.DataFrame, gen: int) -> pd.DataFrame:
        rng = self.rng
        n = len(a)
        c = cust.loc[a["_cidx"].values]
        cs = c["credit_score"].values
        ntc = np.isnan(cs)
        prod = a["product_id"].values
        fraud = c["_fraud"].values
        income = c["monthly_income"].values
        amount = a["requested_amount"].values
        prior = a["prior_good"].values

        z = np.where(ntc, 0.55, -0.011 * (np.nan_to_num(cs, nan=700) - 700))
        z += _map(c["employment_type"].values, EMP_RISK) + _map(c["acquisition_channel"].values, CHANNEL_RISK)
        z += _map(prod, PRODUCT_RISK)
        z += 0.35 * np.log(amount / np.maximum(income, 3000))
        z -= 0.5 * (prior > 0) + 0.1 * np.minimum(prior, 4)
        z += 2.6 * fraud
        z += rng.normal(0, 0.45, n)
        decision_score = z + rng.normal(0, 0.30, n)

        sub = a["submitted_ts"].notna().values
        if self.thresholds is None:
            self.thresholds = {}
            for pid in PRODUCT_IDS:
                m = sub & (prod == pid) & ~fraud
                self.thresholds[pid] = float(np.quantile(decision_score[m], TARGET_APPROVAL[pid])) if m.sum() > 20 else 0.0
        thr = _map(prod, self.thresholds)
        student = c["employment_type"].values == "student"
        policy_reject = (student & (amount > 25000)) | (ntc & (prod == "P05"))
        approve = sub & (decision_score < thr) & ~policy_reject

        manual = np.isin(prod, ["P05", "P06"])
        dec_delay = np.where(manual, 120 + rng.exponential(1.2 * 1440, n), 0.5 + rng.exponential(3, n))
        dec_ts = (a["submitted_ts"] + _td(dec_delay, "m")).dt.floor("s")
        decided = sub & (dec_ts < self.cutoff).values
        approve &= decided

        reason = np.where(ntc, "thin_credit_file",
                          np.where(np.nan_to_num(cs, nan=900) < 650, "low_bureau_score",
                                   np.where(amount / income > 3, "insufficient_income",
                                            np.where(rng.random(n) < 0.35, "high_existing_obligations",
                                                     "risk_policy_cutoff"))))
        reason = np.where(policy_reject, "policy_ineligible", reason)
        reason = np.where(fraud, np.where(rng.random(n) < 0.6, "kyc_data_mismatch", "fraud_suspected"), reason)

        pd_model = _sigmoid(z - 2.7)
        band = np.select([pd_model < 0.03, pd_model < 0.06, pd_model < 0.10, pd_model < 0.16],
                         ["A", "B", "C", "D"], "E")
        borderline = approve & (decision_score > thr - 0.4) & (rng.random(n) < 0.5)
        sanctioned = np.where(borderline, np.round(amount * rng.uniform(0.6, 0.9, n) / 1000) * 1000, amount)
        lo = np.array([PROD[p]["min"] for p in prod])
        sanctioned = np.maximum(sanctioned, lo)

        a["_z"] = z
        a["internal_risk_score"] = np.round(pd_model * 100, 2)
        a["risk_band"] = np.where(sub, band, None)
        a["decision"] = np.where(decided, np.where(approve, "approved", "rejected"), None)
        a["decision_ts"] = dec_ts.where(decided)
        a["rejection_reason"] = np.where(decided & ~approve, reason, None)
        a["sanctioned_amount"] = np.where(approve, sanctioned, np.nan)
        a["_counter_offer"] = borderline

        # fee-transparency experiment: exposure at offer screen, no true effect planted
        _, pa, pb = PRC_EXP
        a["_prc_exposed"] = approve & (a["decision_ts"] >= pa).values & (a["decision_ts"] <= pb).values

        p_disb = (pd.Series(prod).map({"P06": 0.78, "P03": 0.95, "P05": 0.86, "P07": 0.92}).fillna(0.89).values
                  + 0.06 * a["is_repeat"].values - 0.12 * borderline)
        accept = approve & (rng.random(n) < np.clip(p_disb, 0, 0.97))
        disb_delay = np.where(prod == "P06", 1440 + rng.exponential(2.5 * 1440, n),
                              np.where(prod == "P05", rng.exponential(0.6 * 1440, n), 5 + rng.exponential(180, n)))
        disb_ts = (a["decision_ts"] + _td(disb_delay, "m")).dt.floor("s")
        disbursed = accept & (disb_ts < self.cutoff).values
        a["disbursed_ts"] = disb_ts.where(disbursed)

        recent = (self.cutoff - a["started_ts"]) < pd.Timedelta(days=3)
        status = np.select(
            [disbursed, accept & ~disbursed, approve & ~accept, decided & ~approve, sub & ~decided,
             ~sub & recent.values],
            ["disbursed", "approved_pending", "offer_expired", "rejected", "under_review", "in_progress"],
            "abandoned")
        a["application_status"] = status
        return a

    def _book_loans(self, cust: pd.DataFrame, a: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        rng = self.rng
        d = a[a["disbursed_ts"].notna()].reset_index(drop=True)
        L = len(d)
        if not L:
            return pd.DataFrame(), pd.DataFrame()
        c = cust.loc[d["_cidx"].values]
        prod = d["product_id"].values
        P = d["sanctioned_amount"].values.astype(float)
        n = d["requested_tenure_months"].values.astype(int)
        band = d["risk_band"].values
        apr = (_map(prod, {k: v["apr"] for k, v in PROD.items()}) + _map(band, BAND_APR_ADJ)
               - 1.0 * (d["prior_good"].values > 0) + rng.normal(0, 0.5, L))
        apr = np.clip(np.round(apr * 4) / 4, 12.0, 36.0)
        r = apr / 1200.0
        g = (1 + r) ** n
        emi = np.round(P * r * g / (g - 1), 2)
        fee = np.round(P * _map(prod, {k: v["fee"] for k, v in PROD.items()}) / 100.0, 0)

        disb = d["disbursed_ts"]
        fraud = c["_fraud"].values
        ch = c["acquisition_channel"].values
        eng = c["_eng"].values
        in_fest = ((disb >= FESTIVE_2025_DISBURSAL[0]) & (disb <= FESTIVE_2025_DISBURSAL[1] + pd.Timedelta(days=1))).values
        fest_mult = np.where(in_fest, np.where(np.isin(ch, ["paid_social", "affiliate"]), 1.8, 1.25), 1.0)
        z_true = d["_z"].values + rng.normal(0, 0.5, L)
        base_pd = _sigmoid(z_true - 2.75)
        p_def = np.clip(base_pd * fest_mult * (0.6 + 0.4 * np.minimum(n, 24) / 12), 0, 0.95)
        p_def[fraud] = 0.65
        is_default = rng.random(L) < p_def
        default_k = np.minimum(rng.geometric(0.32, L), n)
        chronic = ~is_default & (rng.random(L) < 0.06 + 0.8 * base_pd)

        # Autopay: engagement-driven; the autopay-nudge experiment (and its rollout) raises take-up
        _, ra, rb = RPY_EXP
        in_rpy = ((disb >= ra) & (disb <= rb)).values
        cid = d["_cidx"].values
        rpy_variant = np.where(rng.random(L) < 0.5, "treatment", "control")
        # one variant per customer: first exposure wins
        first = pd.Series(rpy_variant).groupby(cid).transform("first").values
        rpy_variant = np.where(in_rpy, first, None)
        nudged = (rpy_variant == "treatment") | (disb >= RPY_ROLLOUT).values
        p_auto = np.clip(0.48 * eng ** 0.35 + 0.13 * nudged, 0.05, 0.92)
        autopay = rng.random(L) < p_auto
        mandate = np.where(rng.random(L) < 0.6, "nach_autodebit", "upi_autopay")

        loans = pd.DataFrame({
            "_app_key": d["_app_key"].values, "_cidx": cid, "product_id": prod,
            "principal_amount": P, "interest_rate_apr": apr, "tenure_months": n, "emi_amount": emi,
            "processing_fee": fee, "net_disbursed_amount": P - fee, "disbursed_ts": disb.values,
            "risk_band": band, "autopay_enabled": autopay, "_mandate": np.where(autopay, mandate, None),
            "_default": is_default, "_chronic": chronic, "_rpy_variant": rpy_variant,
            "_prior_good": d["prior_good"].values, "_z": d["_z"].values,
        })
        reps = self._simulate_repayments(loans, default_k)
        loans = self._loan_outcomes(loans, reps)
        return loans, reps

    def _simulate_repayments(self, loans: pd.DataFrame, default_k: np.ndarray) -> pd.DataFrame:
        rng = self.rng
        n = loans["tenure_months"].values
        L = len(loans)
        row = np.repeat(np.arange(L), n)
        R = len(row)
        k = np.arange(R) - np.repeat(np.cumsum(n) - n, n) + 1
        disb_date = loans["disbursed_ts"].dt.normalize()
        due = _add_months(disb_date.iloc[row].reset_index(drop=True), k)

        P = loans["principal_amount"].values[row]
        r = loans["interest_rate_apr"].values[row] / 1200.0
        nn = n[row]
        emi = loans["emi_amount"].values[row]
        g = (1 + r) ** nn
        out_before = P * (g - (1 + r) ** (k - 1)) / (g - 1)
        interest = np.round(out_before * r, 2)
        principal = np.round(emi - interest, 2)
        last = k == nn
        principal[last] = np.round(out_before[last], 2)
        total = np.round(principal + interest, 2)

        autopay = loans["autopay_enabled"].values[row]
        chronic = loans["_chronic"].values[row]
        isdef = loans["_default"].values[row]
        dk = default_k[row]
        on_time_p = np.where(chronic, 0.45, np.where(autopay, 0.95, 0.87))
        late = rng.random(R) > on_time_p
        late_days = np.where(chronic, 2 + rng.exponential(14, R), rng.geometric(0.35, R)).astype(int)
        late_days = np.clip(late_days, 1, 90)
        missed = isdef & (k > dk)
        at_def = isdef & (k == dk)
        partial = at_def & (rng.random(R) < 0.3)
        missed |= at_def & ~partial
        outage = autopay & due.isin(OUTAGE_DAYS).values & ~late & ~missed & ~partial
        late_days[outage] = rng.integers(2, 6, outage.sum())
        late |= outage

        early = np.where(autopay, 0, rng.integers(0, 5, R))
        offset = np.where(late, late_days, -early)
        offset = np.where(partial, rng.integers(0, 11, R), offset)
        paid_date = due + _td(offset, "D")
        floor_date = (disb_date.iloc[row].reset_index(drop=True) + pd.Timedelta(days=1))
        paid_date = paid_date.where(paid_date >= floor_date, floor_date)
        amount_paid = np.where(partial, np.round(total * rng.uniform(0.2, 0.6, R), 2), total)
        paid_date = paid_date.where(~missed)
        amount_paid = np.where(missed, 0.0, amount_paid)

        reps = pd.DataFrame({
            "_loan_row": row, "installment_number": k, "due_date": due, "principal_due": principal,
            "interest_due": interest, "total_due": total, "_paid_date": paid_date, "_amount": amount_paid,
            "_outage": outage, "_late": late & ~missed & ~partial,
        })

        # Foreclosure (early closure) for a slice of healthy loans
        eligible = ~loans["_default"].values & ~loans["_chronic"].values & (n >= 6)
        fc = eligible & (rng.random(L) < 0.12)
        j = np.where(fc, rng.integers(np.ceil(n / 3).astype(int), np.maximum(n, 2)), 0)
        j = np.minimum(j, n - 1)
        key = pd.Series(np.arange(R), index=pd.MultiIndex.from_arrays([row, k]))
        fc_idx = np.where(fc)[0]
        rows_j = key.reindex(pd.MultiIndex.from_arrays([fc_idx, j[fc_idx]])).values
        pd_j = reps["_paid_date"].values[rows_j]
        fdate = pd.Series(pd_j) + _td(rng.integers(1, 21, len(fc_idx)), "D")
        valid = fdate.notna().values & (fdate < self.cutoff).values
        fc_final = np.zeros(L, bool)
        fc_final[fc_idx[valid]] = True
        loans["_foreclosed"] = fc_final
        loans["_foreclosure_date"] = pd.NaT
        loans.loc[fc_idx[valid], "_foreclosure_date"] = fdate.values[valid]
        jj = np.zeros(L, int)
        jj[fc_idx[valid]] = j[fc_idx[valid]]
        g_ = (1 + loans["interest_rate_apr"].values / 1200.0) ** n
        rr = loans["interest_rate_apr"].values / 1200.0
        loans["_foreclosure_principal"] = np.where(
            fc_final, np.round(loans["principal_amount"].values * (g_ - (1 + rr) ** jj) / (g_ - 1), 2), 0.0)
        drop = fc_final[row] & (k > jj[row])
        reps = reps[~drop].reset_index(drop=True)

        # Censoring at the extract date and status / DPD derivation
        due = reps["due_date"]
        not_due = (due > self.asof).values
        pdte = reps["_paid_date"]
        paid_known = pdte.notna().values & (pdte <= self.asof).values & ~not_due
        amount = np.where(paid_known, reps["_amount"].values, 0.0)
        full = paid_known & (amount >= reps["total_due"].values - 0.005)
        part = paid_known & ~full
        dpd_paid = np.maximum((pdte - due).dt.days.fillna(0).values, 0)
        dpd_open = (self.asof - due).dt.days.values
        status = np.select([not_due, full & (dpd_paid == 0), full, part],
                           ["scheduled", "paid_on_time", "paid_late", "partially_paid"], "overdue")
        dpd = np.where(not_due, 0, np.where(full, dpd_paid, dpd_open)).astype(int)
        late_fee = np.where(full & (dpd_paid > 3), np.clip(np.round(0.02 * reps["total_due"].values), 250, 1000), 0.0)
        interest_paid = np.minimum(amount, reps["interest_due"].values)
        reps["amount_paid"] = np.round(amount, 2)
        reps["interest_paid"] = np.round(interest_paid, 2)
        reps["principal_paid"] = np.round(amount - interest_paid, 2)
        reps["paid_date"] = pdte.where(paid_known)
        reps["payment_status"] = status
        reps["days_past_due"] = dpd
        reps["late_fee"] = late_fee
        return reps

    def _loan_outcomes(self, loans: pd.DataFrame, reps: pd.DataFrame) -> pd.DataFrame:
        L = len(loans)
        row = reps["_loan_row"].values
        st = reps["payment_status"].values
        unpaid = np.isin(st, ["overdue", "partially_paid"])
        sched = st == "scheduled"
        n_unpaid = np.bincount(row, weights=unpaid, minlength=L)
        n_sched = np.bincount(row, weights=sched, minlength=L)
        dpd = reps["days_past_due"].values
        max_dpd = pd.Series(dpd).groupby(row).max().reindex(range(L)).fillna(0).values
        cur = pd.Series(np.where(unpaid, dpd, 0)).groupby(row).max().reindex(range(L)).fillna(0).values
        last_paid = reps["paid_date"].groupby(row).max().reindex(range(L))
        prin_paid = np.bincount(row, weights=reps["principal_paid"].values, minlength=L)

        fc = loans["_foreclosed"].values
        closed = (n_unpaid == 0) & (n_sched == 0)
        closed_date = pd.Series(np.where(fc, loans["_foreclosure_date"].values, last_paid.values))
        closed_date = pd.to_datetime(closed_date).where(closed | fc)
        status = np.select([closed | fc, cur >= 180, cur >= 90, cur >= 1],
                           ["closed", "written_off", "npa", "delinquent"], "active")
        outstanding = np.where(closed | fc, 0.0,
                               np.round(loans["principal_amount"].values - prin_paid, 2))
        loans["loan_status"] = status
        loans["closed_date"] = closed_date.dt.normalize().values
        loans["closure_type"] = np.where(fc, "foreclosure", np.where(closed, "repaid", None))
        loans["current_dpd"] = cur.astype(int)
        loans["max_dpd"] = max_dpd.astype(int)
        loans["outstanding_principal"] = np.maximum(outstanding, 0)
        loans["maturity_date"] = _add_months(loans["disbursed_ts"].dt.normalize(), loans["tenure_months"].values).values
        return loans

    def _next_applications(self, cust: pd.DataFrame, apps: pd.DataFrame, loans: pd.DataFrame) -> pd.DataFrame:
        rng = self.rng
        parts = []
        if len(loans):
            good = (loans["loan_status"].values == "closed") & (loans["max_dpd"].values < 30)
            lg = loans[good]
            c = cust.loc[lg["_cidx"].values]
            p = (_map(lg["product_id"].values, REPEAT_PROB) * np.clip(c["_eng"].values ** 0.5, 0.6, 1.6)
                 * np.where(lg["autopay_enabled"].values, 1.15, 1.0)
                 * _map(c["acquisition_channel"].values, {"organic": 1.0, "paid_search": 1.0, "paid_social": 0.9,
                                                           "affiliate": 0.9, "referral": 1.1, "partnerships": 1.05}))
            go = rng.random(len(lg)) < np.clip(p, 0, 0.85)
            start = pd.to_datetime(lg["closed_date"]) + _td(1440 + rng.exponential(18 * 1440, len(lg)), "m")
            ok = go & (start < self.cutoff).values
            parts.append(pd.DataFrame({"_cidx": lg["_cidx"].values[ok], "started_ts": start.values[ok],
                                       "is_repeat": True, "prior_good": lg["_prior_good"].values[ok] + 1,
                                       "prev_product": lg["product_id"].values[ok]}))
        # re-applications after a rejection or an expired offer (not repeat borrowing)
        rej = apps[(apps["application_status"] == "rejected") & ~cust.loc[apps["_cidx"].values, "_fraud"].values]
        go = rng.random(len(rej)) < 0.10
        start = rej["decision_ts"] + _td(rng.uniform(60, 150, len(rej)) * 1440, "m")
        ok = go & (start < self.cutoff).values
        parts.append(pd.DataFrame({"_cidx": rej["_cidx"].values[ok], "started_ts": start.values[ok],
                                   "is_repeat": rej["is_repeat"].values[ok], "prior_good": rej["prior_good"].values[ok],
                                   "prev_product": rej["product_id"].values[ok]}))
        exp = apps[apps["application_status"] == "offer_expired"]
        go = rng.random(len(exp)) < 0.15
        start = exp["decision_ts"] + _td(rng.uniform(15, 60, len(exp)) * 1440, "m")
        ok = go & (start < self.cutoff).values
        parts.append(pd.DataFrame({"_cidx": exp["_cidx"].values[ok], "started_ts": start.values[ok],
                                   "is_repeat": exp["is_repeat"].values[ok], "prior_good": exp["prior_good"].values[ok],
                                   "prev_product": exp["product_id"].values[ok]}))
        out = pd.concat(parts, ignore_index=True)
        out["prior_good"] = out["prior_good"].astype(int)
        out["is_repeat"] = out["is_repeat"].astype(bool)
        return out

    def _assign_lending_ids(self, cust, apps, loans, reps):
        apps = apps.sort_values(["started_ts", "_app_key"], kind="mergesort").reset_index(drop=True)
        apps["application_id"] = ["APP" + str(i).zfill(7) for i in range(1, len(apps) + 1)]
        apps["customer_id"] = cust["customer_id"].values[apps["_cidx"].values]
        key_to_app = dict(zip(apps["_app_key"], apps["application_id"]))

        reps = reps.copy()
        loans = loans.reset_index(drop=True)
        # each generation's reps index its own loans; rebuild a global key per row
        reps["_app_key"] = np.concatenate(
            [lk for lk in self._rep_app_keys(loans, reps)]) if len(reps) else []
        loans = loans.sort_values(["disbursed_ts", "_app_key"], kind="mergesort").reset_index(drop=True)
        loans["loan_id"] = ["LN" + str(i).zfill(7) for i in range(1, len(loans) + 1)]
        loans["application_id"] = loans["_app_key"].map(key_to_app)
        loans["customer_id"] = cust["customer_id"].values[loans["_cidx"].values]
        loans["loan_sequence_number"] = loans.groupby("_cidx").cumcount() + 1
        loans["is_repeat_loan"] = loans["loan_sequence_number"] > 1
        key_to_loan = dict(zip(loans["_app_key"], loans["loan_id"]))
        reps["loan_id"] = reps["_app_key"].map(key_to_loan)
        reps = reps.sort_values(["loan_id", "installment_number"]).reset_index(drop=True)
        reps["repayment_id"] = ["RP" + str(i).zfill(8) for i in range(1, len(reps) + 1)]
        reps["customer_id"] = reps["loan_id"].map(dict(zip(loans["loan_id"], loans["customer_id"])))
        return apps, loans, reps

    @staticmethod
    def _rep_app_keys(loans: pd.DataFrame, reps: pd.DataFrame):
        # reps were concatenated generation by generation; _loan_row restarts at 0 each generation.
        # Walk the blocks in order and translate local row -> global _app_key.
        out = []
        loan_keys = loans["_app_key"].values
        offset = 0
        local = reps["_loan_row"].values
        start = 0
        # block boundaries: where local row index decreases (new generation) - robust because rows are
        # emitted in loan order within each generation
        breaks = np.where(np.diff(local) < 0)[0] + 1
        bounds = list(zip(np.concatenate([[0], breaks]), np.concatenate([breaks, [len(local)]])))
        for b0, b1 in bounds:
            block = local[b0:b1]
            out.append(loan_keys[offset + block])
            offset += int(block.max()) + 1
        return out

    # ------------------------------------------------------------------ transactions
    def build_transactions(self, cust, loans, reps) -> pd.DataFrame:
        rng = self.rng
        parts = []
        lo = loans
        sec = _td(rng.integers(1, 30, len(lo)), "s")
        parts.append(pd.DataFrame({"customer_id": lo["customer_id"], "loan_id": lo["loan_id"], "repayment_id": None,
                                   "txn_ts": lo["disbursed_ts"] + sec, "txn_type": "disbursement",
                                   "amount": lo["net_disbursed_amount"], "payment_method": "imps_bank_transfer",
                                   "txn_status": "success", "failure_reason": None}))
        parts.append(pd.DataFrame({"customer_id": lo["customer_id"], "loan_id": lo["loan_id"], "repayment_id": None,
                                   "txn_ts": lo["disbursed_ts"] + sec, "txn_type": "processing_fee",
                                   "amount": lo["processing_fee"], "payment_method": "deducted_at_source",
                                   "txn_status": "success", "failure_reason": None}))

        lmap = lo.set_index("loan_id")
        rp = reps[reps["amount_paid"] > 0]
        auto = lmap.loc[rp["loan_id"], "autopay_enabled"].values
        mandate = lmap.loc[rp["loan_id"], "_mandate"].values
        manual_m = np.array(["upi", "netbanking", "debit_card"])[_choice_rows(rng, np.tile([0.70, 0.18, 0.12], (len(rp), 1)))]
        method = np.where(auto & (rp["payment_status"].values != "paid_late"), mandate, manual_m)
        method = np.where(auto & rp["_outage"].values, mandate, method)
        hour = np.where(auto, rng.uniform(6, 10, len(rp)), rng.uniform(8, 23.5, len(rp)))
        ts = (rp["paid_date"] + _td(hour * 3600, "s")).dt.floor("s")
        parts.append(pd.DataFrame({"customer_id": rp["customer_id"].values, "loan_id": rp["loan_id"].values,
                                   "repayment_id": rp["repayment_id"].values, "txn_ts": ts.values,
                                   "txn_type": "emi_payment", "amount": rp["amount_paid"].values,
                                   "payment_method": method, "txn_status": "success", "failure_reason": None}))
        lf = rp["late_fee"].values > 0
        parts.append(pd.DataFrame({"customer_id": rp["customer_id"].values[lf], "loan_id": rp["loan_id"].values[lf],
                                   "repayment_id": rp["repayment_id"].values[lf],
                                   "txn_ts": ts.values[lf] + np.timedelta64(2, "s"), "txn_type": "late_fee",
                                   "amount": rp["late_fee"].values[lf], "payment_method": method[lf],
                                   "txn_status": "success", "failure_reason": None}))

        # Failed debit attempts: auto-debit bounces on the due date (late / unpaid instalments) and the outage
        due_past = reps["due_date"] <= self.asof
        late_or_unpaid = np.isin(reps["payment_status"].values, ["paid_late", "overdue", "partially_paid"])
        r_auto = lmap.loc[reps["loan_id"], "autopay_enabled"].values
        fail = due_past.values & r_auto & late_or_unpaid
        fr = reps[fail]
        reason = np.where(fr["_outage"].values, "gateway_timeout",
                          np.where(rng.random(len(fr)) < 0.85, "insufficient_funds", "mandate_inactive"))
        fts = (fr["due_date"] + _td(rng.uniform(7, 9, len(fr)) * 3600, "s")).dt.floor("s")
        parts.append(pd.DataFrame({"customer_id": fr["customer_id"].values, "loan_id": fr["loan_id"].values,
                                   "repayment_id": fr["repayment_id"].values, "txn_ts": fts.values,
                                   "txn_type": "emi_payment", "amount": fr["total_due"].values,
                                   "payment_method": lmap.loc[fr["loan_id"], "_mandate"].values,
                                   "txn_status": "failed", "failure_reason": reason}))
        # Manual UPI declines before a late payment, plus random technical failures
        man = reps[~r_auto & (reps["payment_status"].values == "paid_late")]
        pick = rng.random(len(man)) < 0.25
        man = man[pick]
        mts = (man["paid_date"] + _td(rng.uniform(8, 12, len(man)) * 3600, "s")).dt.floor("s")
        parts.append(pd.DataFrame({"customer_id": man["customer_id"].values, "loan_id": man["loan_id"].values,
                                   "repayment_id": man["repayment_id"].values, "txn_ts": mts.values,
                                   "txn_type": "emi_payment", "amount": man["total_due"].values,
                                   "payment_method": "upi", "txn_status": "failed",
                                   "failure_reason": "upi_txn_declined"}))
        tech = rp[rng.random(len(rp)) < 0.01]
        tts = (tech["paid_date"] + _td(rng.uniform(6, 8, len(tech)) * 3600, "s")).dt.floor("s")
        parts.append(pd.DataFrame({"customer_id": tech["customer_id"].values, "loan_id": tech["loan_id"].values,
                                   "repayment_id": tech["repayment_id"].values, "txn_ts": tts.values,
                                   "txn_type": "emi_payment", "amount": tech["amount_paid"].values,
                                   "payment_method": "netbanking", "txn_status": "failed",
                                   "failure_reason": "bank_server_down"}))
        # Foreclosures
        fc = lo[lo["_foreclosed"]]
        fts = (pd.to_datetime(fc["_foreclosure_date"]) + _td(rng.uniform(10, 18, len(fc)) * 3600, "s")).dt.floor("s")
        parts.append(pd.DataFrame({"customer_id": fc["customer_id"].values, "loan_id": fc["loan_id"].values,
                                   "repayment_id": None, "txn_ts": fts.values, "txn_type": "foreclosure_payment",
                                   "amount": fc["_foreclosure_principal"].values, "payment_method": "netbanking",
                                   "txn_status": "success", "failure_reason": None}))
        fee_pct = fc["product_id"].map(FORECLOSURE_FEE_PCT).fillna(0).values
        has_fee = fee_pct > 0
        parts.append(pd.DataFrame({"customer_id": fc["customer_id"].values[has_fee], "loan_id": fc["loan_id"].values[has_fee],
                                   "repayment_id": None, "txn_ts": fts.values[has_fee] + np.timedelta64(3, "s"),
                                   "txn_type": "foreclosure_fee",
                                   "amount": np.round(fc["_foreclosure_principal"].values[has_fee] * fee_pct[has_fee], 2),
                                   "payment_method": "netbanking", "txn_status": "success", "failure_reason": None}))
        tx = pd.concat(parts, ignore_index=True)
        tx = tx[pd.to_datetime(tx["txn_ts"]) < self.cutoff]
        tx = tx.sort_values(["txn_ts", "loan_id"], kind="mergesort").reset_index(drop=True)
        tx.insert(0, "transaction_id", ["TX" + str(i).zfill(9) for i in range(1, len(tx) + 1)])
        tx["amount"] = tx["amount"].astype(float).round(2)
        return tx

    # ------------------------------------------------------------------ support
    def build_support_tickets(self, cust, apps, loans, reps, txns) -> pd.DataFrame:
        rng = self.rng
        parts = []

        def add(cids, lids, ts, category, p):
            m = rng.random(len(cids)) < p
            if m.sum():
                parts.append(pd.DataFrame({"customer_id": np.asarray(cids)[m], "loan_id": np.asarray(lids, dtype=object)[m],
                                           "created_ts": pd.Series(np.asarray(ts)[m]), "category": category}))

        hrs = lambda k, scale: _td(rng.exponential(scale, k) * 3600, "s")
        stuck = cust[cust["kyc_status"].isin(["pending", "failed"])]
        add(stuck["customer_id"], [None] * len(stuck), stuck["kyc_started_ts"] + hrs(len(stuck), 8), "kyc_issue", 0.12)
        ok = cust[cust["kyc_status"] == "verified"]
        add(ok["customer_id"], [None] * len(ok), ok["kyc_completed_ts"] + hrs(len(ok), 24), "kyc_issue", 0.02)
        rej = apps[apps["application_status"] == "rejected"]
        add(rej["customer_id"], [None] * len(rej), rej["decision_ts"] + hrs(len(rej), 12), "application_status", 0.06)
        slow = (loans["disbursed_ts"] - pd.to_datetime(apps.set_index("_app_key").loc[loans["_app_key"], "decision_ts"].values)) > pd.Timedelta(days=2)
        sl = loans[slow.values]
        add(sl["customer_id"], sl["loan_id"], sl["disbursed_ts"] - hrs(len(sl), 20), "disbursement_delay", 0.25)
        fails = txns[(txns["txn_status"] == "failed")]
        p_fail = np.where(fails["failure_reason"].values == "gateway_timeout", 0.35, 0.05)
        add(fails["customer_id"], fails["loan_id"], fails["txn_ts"] + hrs(len(fails), 3), "payment_failure", p_fail)
        col = reps[reps["days_past_due"] >= 15]
        col = col.drop_duplicates("loan_id")
        add(col["customer_id"], col["loan_id"], col["due_date"] + _td(rng.uniform(15, 40, len(col)), "D"), "collections", 0.20)
        fcl = loans[loans["_foreclosed"]]
        add(fcl["customer_id"], fcl["loan_id"], pd.to_datetime(fcl["_foreclosure_date"]) - hrs(len(fcl), 72), "foreclosure_request", 0.30)
        bug = cust[(cust["signup_platform"] == "android") & (cust["kyc_started_ts"] >= "2025-05-12") & (cust["kyc_started_ts"] < "2025-05-16")]
        add(bug["customer_id"], [None] * len(bug), bug["kyc_started_ts"] + hrs(len(bug), 6), "app_bug", 0.10)
        add(cust["customer_id"], [None] * len(cust), cust["signup_ts"] + _td(rng.uniform(1, 300, len(cust)), "D"), "general_query", 0.015)

        t = pd.concat(parts, ignore_index=True)
        t["created_ts"] = pd.to_datetime(t["created_ts"]).dt.floor("s")
        signup = cust.set_index("customer_id")["signup_ts"]
        t = t[(t["created_ts"] < self.cutoff) & (t["created_ts"] >= signup.loc[t["customer_id"]].values)]
        k = len(t)
        channel = np.array(["in_app_chat", "email", "phone", "whatsapp"])[_choice_rows(rng, np.tile([0.5, 0.2, 0.2, 0.1], (k, 1)))]
        outage_day = t["created_ts"].dt.normalize().isin(OUTAGE_DAYS + pd.Timedelta(days=0)).values | \
            t["created_ts"].dt.normalize().isin(OUTAGE_DAYS + pd.Timedelta(days=1)).values
        frt_med = pd.Series(channel).map({"in_app_chat": 4, "email": 240, "phone": 2, "whatsapp": 15}).values
        frt = np.exp(np.log(frt_med) + 0.7 * rng.normal(0, 1, k)) * np.where(outage_day, 4, 1)
        res_med = t["category"].map({"kyc_issue": 18, "payment_failure": 10, "disbursement_delay": 20, "collections": 48,
                                     "foreclosure_request": 72, "app_bug": 30, "general_query": 6,
                                     "application_status": 8}).values
        res_h = np.exp(np.log(res_med * np.where(outage_day, 3, 1)) + 0.8 * rng.normal(0, 1, k))
        resolved_ts = (t["created_ts"] + _td(res_h * 3600, "s")).dt.floor("s")
        is_open = (resolved_ts >= self.cutoff).values
        escalated = rng.random(k) < 0.02
        priority = t["category"].map({"payment_failure": "high", "collections": "medium", "kyc_issue": "medium",
                                      "disbursement_delay": "high", "foreclosure_request": "low", "app_bug": "high",
                                      "general_query": "low", "application_status": "low"}).values
        csat = np.clip(np.round(4.6 - 0.9 * np.log10(1 + res_h) - np.where(t["category"].values == "collections", 0.6, 0)
                                + rng.normal(0, 0.6, k)), 1, 5)
        responded = (rng.random(k) < 0.42) & ~is_open
        t = t.assign(channel=channel, priority=priority, first_response_minutes=np.round(frt, 1),
                     resolved_ts=resolved_ts.where(~is_open),
                     ticket_status=np.where(is_open, "open", np.where(escalated, "escalated_resolved", "resolved")),
                     csat_score=np.where(responded, csat, np.nan))
        t = t.sort_values("created_ts", kind="mergesort").reset_index(drop=True)
        t.insert(0, "ticket_id", ["TK" + str(i).zfill(6) for i in range(1, len(t) + 1)])
        t["agent_id"] = ["AG" + str(x).zfill(3) for x in rng.integers(1, 61, len(t))]  # new upstream column
        return t[["ticket_id", "customer_id", "loan_id", "created_ts", "channel", "category", "priority",
                  "first_response_minutes", "resolved_ts", "ticket_status", "csat_score", "agent_id"]]

    # ------------------------------------------------------------------ events
    def build_events(self, cust, apps, loans, reps, txns, tickets) -> pd.DataFrame:
        rng = self.rng
        E: List[pd.DataFrame] = []
        plat_of = cust.set_index("customer_id")["signup_platform"]
        eng_of = cust.set_index("customer_id")["_eng"]

        def ev(uids, ts, name, props, platform=None, client=True):
            uids = pd.Series(np.asarray(uids)).reset_index(drop=True)
            df = pd.DataFrame({"user_id": uids, "event_ts": pd.to_datetime(pd.Series(np.asarray(ts))).reset_index(drop=True),
                               "event_name": name, "properties": pd.Series(props).reset_index(drop=True)})
            df["platform"] = plat_of.loc[uids].values if platform is None else platform
            df["_client"] = client
            E.append(df)

        none_s = lambda k: pd.Series(["none"] * k)
        c = cust
        variant = c["_onb_variant"].fillna("none")
        ev(c["customer_id"], c["signup_ts"], "signup",
           _json_props({"channel": c["acquisition_channel"], "campaign_id": c["campaign_id"].fillna("organic"),
                        "city_tier": c["city_tier"]}))
        ks = c[c["kyc_started_ts"].notna()]
        ev(ks["customer_id"], ks["kyc_started_ts"], "kyc_started",
           _json_props({"variant": variant[ks.index]}))
        kd = c[c["kyc_completed_ts"].notna()]
        ev(kd["customer_id"], kd["kyc_completed_ts"], "kyc_completed",
           _json_props({"kyc_method": kd["kyc_method"], "variant": variant[kd.index]}))

        a = apps
        ev(a["customer_id"], a["started_ts"], "loan_application_started",
           _json_props({"product_id": a["product_id"], "is_repeat": a["is_repeat"].astype(str).str.lower()}, ("is_repeat",)),
           platform=a["application_platform"].values)
        s = a[a["submitted_ts"].notna()]
        ev(s["customer_id"], s["submitted_ts"], "loan_application_submitted",
           _json_props({"product_id": s["product_id"], "amount": s["requested_amount"].astype(int),
                        "tenure_months": s["requested_tenure_months"]}, ("amount", "tenure_months")),
           platform=s["application_platform"].values)
        ap = a[a["decision"] == "approved"]
        ev(ap["customer_id"], ap["decision_ts"], "loan_approved",
           _json_props({"product_id": ap["product_id"], "amount": ap["sanctioned_amount"].astype(int),
                        "risk_band": ap["risk_band"]}, ("amount",)), platform="server", client=False)
        rj = a[a["decision"] == "rejected"]
        ev(rj["customer_id"], rj["decision_ts"], "loan_rejected",
           _json_props({"product_id": rj["product_id"], "reason": rj["rejection_reason"]}), platform="server", client=False)
        lo = loans
        ev(lo["customer_id"], lo["disbursed_ts"], "loan_disbursed",
           _json_props({"product_id": lo["product_id"], "amount": lo["principal_amount"].astype(int),
                        "loan_sequence": lo["loan_sequence_number"]}, ("amount", "loan_sequence")),
           platform="server", client=False)
        rl = lo[lo["is_repeat_loan"]]
        ev(rl["customer_id"], rl["disbursed_ts"] + pd.Timedelta(seconds=1), "repeat_loan",
           _json_props({"product_id": rl["product_id"], "loan_sequence": rl["loan_sequence_number"]}, ("loan_sequence",)),
           platform="server", client=False)
        pay = txns[(txns["txn_type"] == "emi_payment") & (txns["txn_status"] == "success")]
        rstat = reps.set_index("repayment_id").loc[pay["repayment_id"], "payment_status"].values
        ev(pay["customer_id"], pay["txn_ts"], "payment_made",
           _json_props({"amount": pay["amount"].round(0).astype(int), "method": pay["payment_method"],
                        "on_time": pd.Series(rstat == "paid_on_time").astype(str).str.lower()}, ("amount", "on_time")),
           platform="server", client=False)
        tk = tickets
        tk_plat = np.where(tk["channel"].values == "in_app_chat", plat_of.loc[tk["customer_id"]].values, "server")
        ev(tk["customer_id"], tk["created_ts"], "support_contact",
           _json_props({"category": tk["category"], "channel": tk["channel"]}), platform=tk_plat,
           client=False)
        tk_client = E[-1]["platform"] != "server"
        E[-1]["_client"] = tk_client.values

        # Feature events
        au = lo[lo["autopay_enabled"]]
        ev(au["customer_id"], au["disbursed_ts"] + _td(rng.uniform(2, 60, len(au)), "m"), "autopay_enabled",
           _json_props({"mandate_type": au["_mandate"]}))
        emi_m = rng.random(len(a)) < np.clip(0.4 * eng_of.loc[a["customer_id"]].values ** 0.5, 0, 0.9)
        ae = a[emi_m]
        ev(ae["customer_id"], ae["started_ts"] - _td(rng.uniform(1, 30, len(ae)), "m"), "emi_calculator_used",
           _json_props({"product_id": ae["product_id"]}), platform=ae["application_platform"].values)

        def windows_events(uids, w0, w1, lam, name, props_fn, nominal_days=None):
            """Poisson count of events spread uniformly over [w0, w1). When the window is cut short by the
            extract date, the expected count is scaled down so recent users are not over-active (right-censoring)."""
            lam = np.asarray(lam, dtype=float)
            if nominal_days is not None:
                span_days = (pd.to_datetime(np.asarray(w1)) - pd.to_datetime(np.asarray(w0))).total_seconds().values / 86400
                lam = lam * np.clip(span_days / nominal_days, 0, 1)
            cnt = rng.poisson(np.maximum(lam, 0))
            if cnt.sum() == 0:
                return
            idx = np.repeat(np.arange(len(uids)), cnt)
            span = (pd.to_datetime(np.asarray(w1)) - pd.to_datetime(np.asarray(w0))).total_seconds().values
            span = np.maximum(span, 60)
            ts = pd.to_datetime(np.asarray(w0))[idx] + _td(rng.random(len(idx)) * span[idx], "s")
            ev(np.asarray(uids)[idx], ts, name, props_fn(len(idx)))

        login_props = lambda k: _json_props({"method": pd.Series(np.where(rng.random(k) < 0.6, "otp", "biometric"))})
        eng_c = c["_eng"].values
        kyc_ok = c["kyc_completed_ts"].notna().values
        d30 = c["signup_ts"] + pd.Timedelta(days=30)
        windows_events(c["customer_id"].values, c["signup_ts"].values, np.minimum(d30.values, np.datetime64(self.cutoff)),
                       np.where(kyc_ok, 2.0, 1.0) * eng_c, "login", login_props, nominal_days=30)
        borrower = c["customer_id"].isin(lo["customer_id"]).values
        nb = c[kyc_ok & ~borrower]
        end = np.minimum((nb["signup_ts"] + pd.Timedelta(days=365)).values, np.datetime64(self.cutoff))
        windows_events(nb["customer_id"].values, nb["signup_ts"].values, end, 1.0 * nb["_eng"].values, "login", login_props,
                       nominal_days=365)
        lo_end = pd.to_datetime(lo["closed_date"]).fillna(self.cutoff)
        lo_end = lo_end.where(lo_end > lo["disbursed_ts"], lo["disbursed_ts"] + pd.Timedelta(days=1))
        months = (lo_end - lo["disbursed_ts"]).dt.days.values / 30.4
        leng = eng_of.loc[lo["customer_id"]].values
        lam = 1.6 * leng * months * np.where(lo["_default"].values, 0.5, 1.0)
        windows_events(lo["customer_id"].values, lo["disbursed_ts"].values, lo_end.values, lam, "login", login_props)
        closed = lo[lo["closed_date"].notna()]
        cend = np.minimum((pd.to_datetime(closed["closed_date"]) + pd.Timedelta(days=45)).values, np.datetime64(self.cutoff))
        windows_events(closed["customer_id"].values, pd.to_datetime(closed["closed_date"]).values, cend,
                       1.5 * eng_of.loc[closed["customer_id"]].values, "login", login_props, nominal_days=45)

        kc = c[kyc_ok]
        kend = np.minimum((kc["kyc_completed_ts"] + pd.Timedelta(days=365)).values, np.datetime64(self.cutoff))
        windows_events(kc["customer_id"].values, kc["kyc_completed_ts"].values, kend, 0.7 * kc["_eng"].values,
                       "credit_score_viewed", lambda k: _json_props({"source": pd.Series(["dashboard"] * k)}),
                       nominal_days=365)
        first_loan = lo.groupby("customer_id")["disbursed_ts"].min()
        fl_end = np.full(len(first_loan), np.datetime64(self.cutoff))
        windows_events(first_loan.index.values, first_loan.values, fl_end, 0.25 * eng_of.loc[first_loan.index].values,
                       "referral_shared",
                       lambda k: _json_props({"share_channel": pd.Series(np.where(rng.random(k) < 0.7, "whatsapp", "sms"))}),
                       nominal_days=365)

        ev_df = pd.concat(E, ignore_index=True)
        ev_df = ev_df[(ev_df["event_ts"] < self.cutoff) & ev_df["event_ts"].notna()]
        ev_df["event_ts"] = ev_df["event_ts"].dt.floor("s")

        # App versions: latest release, with 30% of users lagging one version for 14 days after a release
        rel_dates = pd.to_datetime([r[0] for r in APP_RELEASES]).values
        rel_names = np.array([r[1] for r in APP_RELEASES])
        idx = np.searchsorted(rel_dates, ev_df["event_ts"].values, side="right") - 1
        since = (ev_df["event_ts"].values - rel_dates[np.maximum(idx, 0)]) / np.timedelta64(1, "D")
        lag = (since < 14) & (rng.random(len(ev_df)) < 0.30) & (idx > 0)
        idx = np.where(lag, idx - 1, idx)
        version = rel_names[np.maximum(idx, 0)]
        plat = ev_df["platform"].values
        ev_df["app_version"] = np.where(np.isin(plat, ["android", "ios"]), version,
                                        np.where(plat == "web", "web", None))
        # Planted instrumentation bug: Android 5.2.0 never fired kyc_completed
        bug = (ev_df["event_name"].values == "kyc_completed") & (plat == "android") & (ev_df["app_version"].values == KYC_TRACKING_BUG_VERSION)
        ev_df = ev_df[~bug]

        ev_df = ev_df.sort_values(["event_ts", "user_id"], kind="mergesort").reset_index(drop=True)
        bucket = (ev_df["event_ts"].values.astype("datetime64[s]").astype(np.int64) // 1800).astype(str)
        ev_df["session_id"] = np.where(ev_df["_client"].values, "S-" + ev_df["user_id"].str[1:] + "-" + bucket, None)
        ev_df.insert(0, "event_id", ["EV" + str(i).zfill(9) for i in range(1, len(ev_df) + 1)])
        return ev_df[["event_id", "user_id", "event_name", "event_ts", "session_id", "platform", "app_version", "properties"]]

    # ------------------------------------------------------------------ experiments
    def build_experiments(self, cust, apps, loans) -> Tuple[pd.DataFrame, pd.DataFrame]:
        rng = self.rng
        exps = pd.DataFrame([
            {"experiment_id": "EXP-PRC-2025-06", "experiment_name": "Upfront fee transparency on the offer screen",
             "feature_area": "loan_offer", "hypothesis": "Showing an itemised fee breakdown before acceptance raises offer acceptance (approved -> disbursed) by >= 3pp.",
             "unit": "customer", "allocation_pct": 50, "start_date": "2025-06-02", "end_date": "2025-06-29",
             "primary_metric": "offer_acceptance_rate", "secondary_metrics": "disbursal_within_3d",
             "guardrail_metrics": "support_contact_rate_7d", "status": "concluded_no_effect", "owner_team": "Lending Product"},
            {"experiment_id": "EXP-RPY-2025-11", "experiment_name": "Autopay nudge at disbursal",
             "feature_area": "repayments", "hypothesis": "A one-tap autopay prompt on the disbursal screen raises autopay enablement by >= 8pp and improves on-time first EMI.",
             "unit": "customer", "allocation_pct": 50, "start_date": "2025-11-03", "end_date": "2025-12-14",
             "primary_metric": "autopay_enabled_rate", "secondary_metrics": "first_emi_on_time_rate",
             "guardrail_metrics": "support_contact_rate_7d", "status": "concluded_shipped", "owner_team": "Collections & Repayments"},
            {"experiment_id": "EXP-ONB-2026-01", "experiment_name": "Onboarding redesign: trust signals + progress indicator",
             "feature_area": "onboarding", "hypothesis": "Adding security/trust signals (regulated-lender badge, encryption note, DigiLocker one-tap) and a 3-step progress bar raises 7-day KYC completion among new app signups by >= 4pp (MDE sized to 6 weeks of app traffic).",
             "unit": "customer", "allocation_pct": 50, "start_date": "2026-01-12", "end_date": "2026-02-22",
             "primary_metric": "kyc_completion_7d", "secondary_metrics": "application_submitted_14d,loan_disbursed_30d",
             "guardrail_metrics": "approval_rate,fpd30_rate,kyc_support_ticket_rate", "status": "concluded_shipped",
             "owner_team": "Growth & Onboarding"},
        ])
        for col in ("start_date", "end_date"):
            exps[col] = pd.to_datetime(exps[col]).dt.date

        parts = []
        onb = cust[cust["_onb_variant"].notna()]
        parts.append(pd.DataFrame({"experiment_id": "EXP-ONB-2026-01", "customer_id": onb["customer_id"].values,
                                   "variant": onb["_onb_variant"].values, "assigned_ts": onb["signup_ts"].values,
                                   "platform": onb["signup_platform"].values}))
        rp = loans[loans["_rpy_variant"].notna()].sort_values("disbursed_ts").drop_duplicates("customer_id")
        parts.append(pd.DataFrame({"experiment_id": "EXP-RPY-2025-11", "customer_id": rp["customer_id"].values,
                                   "variant": rp["_rpy_variant"].values, "assigned_ts": rp["disbursed_ts"].values,
                                   "platform": cust.set_index("customer_id").loc[rp["customer_id"], "signup_platform"].values}))
        pr = apps[apps["_prc_exposed"]].sort_values("decision_ts").drop_duplicates("customer_id")
        parts.append(pd.DataFrame({"experiment_id": "EXP-PRC-2025-06", "customer_id": pr["customer_id"].values,
                                   "variant": np.where(rng.random(len(pr)) < 0.5, "treatment", "control"),
                                   "assigned_ts": pr["decision_ts"].values,
                                   "platform": pr["application_platform"].values}))
        asg = pd.concat(parts, ignore_index=True).sort_values("assigned_ts", kind="mergesort").reset_index(drop=True)
        asg.insert(0, "assignment_id", ["AS" + str(i).zfill(7) for i in range(1, len(asg) + 1)])
        return exps, asg

    # ------------------------------------------------------------------ orchestration
    def run(self) -> Dict[str, pd.DataFrame]:
        products = self.build_products()
        cust = self.build_customers()
        campaigns = self.build_campaigns(cust)
        apps, loans, reps = self.simulate_lending(cust)
        txns = self.build_transactions(cust, loans, reps)
        tickets = self.build_support_tickets(cust, apps, loans, reps, txns)
        events = self.build_events(cust, apps, loans, reps, txns, tickets)
        exps, asg = self.build_experiments(cust, apps, loans)

        customers = cust[["customer_id", "signup_ts", "acquisition_channel", "campaign_id", "signup_platform", "city",
                          "state", "city_tier", "age", "employment_type", "monthly_income", "credit_score",
                          "kyc_status", "kyc_started_ts", "kyc_completed_ts", "kyc_method", "marketing_opt_in"]].copy()
        customers["credit_score"] = customers["credit_score"].astype("Int64")
        applications = apps[["application_id", "customer_id", "product_id", "started_ts", "submitted_ts",
                             "requested_amount", "requested_tenure_months", "loan_purpose", "application_platform",
                             "is_repeat", "internal_risk_score", "risk_band", "decision", "decision_ts",
                             "rejection_reason", "sanctioned_amount", "application_status"]].copy()
        applications = applications.rename(columns={"is_repeat": "is_repeat_customer"})
        applications.loc[applications["submitted_ts"].isna(), ["internal_risk_score"]] = np.nan
        loans_out = loans[["loan_id", "application_id", "customer_id", "product_id", "disbursed_ts", "principal_amount",
                           "processing_fee", "net_disbursed_amount", "interest_rate_apr", "tenure_months", "emi_amount",
                           "risk_band", "autopay_enabled", "loan_sequence_number", "is_repeat_loan", "maturity_date",
                           "loan_status", "current_dpd", "max_dpd", "outstanding_principal", "closed_date",
                           "closure_type"]].copy()
        loans_out["maturity_date"] = pd.to_datetime(loans_out["maturity_date"]).dt.date
        loans_out["closed_date"] = pd.to_datetime(loans_out["closed_date"]).dt.date
        repayments = reps[["repayment_id", "loan_id", "customer_id", "installment_number", "due_date", "principal_due",
                           "interest_due", "total_due", "amount_paid", "principal_paid", "interest_paid", "paid_date",
                           "payment_status", "days_past_due", "late_fee"]].copy()
        repayments["due_date"] = pd.to_datetime(repayments["due_date"]).dt.date
        repayments["paid_date"] = pd.to_datetime(repayments["paid_date"]).dt.date
        return {
            "products": products, "marketing_campaigns": campaigns, "customers": customers,
            "applications": applications, "loans": loans_out, "repayments": repayments, "transactions": txns,
            "product_events": events, "support_tickets": tickets, "experiments": exps,
            "experiment_assignments": asg,
        }


# ---------------------------------------------------------------------------
# Data-quality issue injection (simulates what real source systems deliver)
# ---------------------------------------------------------------------------
def inject_dq_issues(tables: Dict[str, pd.DataFrame], seed: int = 7) -> Tuple[Dict[str, pd.DataFrame], List[Dict]]:
    """Corrupt a copy of the clean tables the way real upstream systems do.

    Returns the corrupted tables plus a manifest of what was injected - the "answer key"
    used to measure the recall of the data-quality framework.
    """
    rng = np.random.default_rng(seed)
    t = {k: v.copy() for k, v in tables.items()}
    manifest: List[Dict] = []

    def log(table, column, issue, rows, check):
        manifest.append({"table": table, "column": column, "issue": issue, "rows_affected": int(rows),
                         "expected_check": check})

    def sample(df, frac, mask=None):
        pool = df.index if mask is None else df.index[mask]
        k = max(1, int(round(len(pool) * frac))) if len(pool) else 0
        return rng.choice(pool, size=min(k, len(pool)), replace=False)

    # customers ---------------------------------------------------------
    c = t["customers"]
    idx = sample(c, 0.006)
    variants = np.array(["Paid_Social", "paid social", " PAID_SOCIAL", "Organic ", "Paid-Search", "REFERRAL"])
    c.loc[idx, "acquisition_channel"] = rng.choice(variants, len(idx))
    log("customers", "acquisition_channel", "inconsistent category casing/spacing", len(idx), "accepted_values")
    idx = sample(c, 0.012)
    c.loc[idx, "city"] = None
    log("customers", "city", "missing city", len(idx), "not_null")
    idx = sample(c, 0.020)
    c.loc[idx, "monthly_income"] = np.nan
    log("customers", "monthly_income", "missing income", len(idx), "not_null")
    idx = sample(c, 0.0008)
    c.loc[idx, "age"] = rng.choice([0, 7, 15, 117, 150, -1], len(idx))
    log("customers", "age", "impossible age", len(idx), "range")
    idx = sample(c, 0.0005, c["credit_score"].notna().values)
    c["credit_score"] = c["credit_score"].astype("float")
    c.loc[idx, "credit_score"] = rng.choice([0, 999, 1200, 150], len(idx))
    log("customers", "credit_score", "bureau score outside 300-900", len(idx), "range")
    idx = sample(c, 0.0015, c["monthly_income"].notna().values)
    c.loc[idx, "monthly_income"] = c.loc[idx, "monthly_income"] * 100
    log("customers", "monthly_income", "income keyed with two extra zeros", len(idx), "outlier")
    gap = (c["kyc_completed_ts"] - c["signup_ts"]).dt.total_seconds()
    idx = sample(c, 0.02, (gap < 5.5 * 3600).fillna(False).values)
    c.loc[idx, "kyc_completed_ts"] = c.loc[idx, "kyc_completed_ts"] - pd.Timedelta(hours=5, minutes=30)
    bad = (c.loc[idx, "kyc_completed_ts"] < c.loc[idx, "kyc_started_ts"]).sum()
    log("customers", "kyc_completed_ts", "UTC timestamp written into IST column (KYC vendor callback)", bad, "date_order")
    dup = c.loc[sample(c, 0.004)]
    t["customers"] = pd.concat([c, dup], ignore_index=True)
    log("customers", "customer_id", "duplicate rows re-sent by CRM sync", len(dup), "unique")

    # applications ------------------------------------------------------
    a = t["applications"]
    idx = sample(a, 0.0005)
    a.loc[idx, "requested_amount"] = -a.loc[idx, "requested_amount"]
    log("applications", "requested_amount", "negative requested amount", len(idx), "range")
    idx = sample(a, 0.0008, a["decision_ts"].notna().values)
    a.loc[idx, "decision_ts"] = a.loc[idx, "submitted_ts"] - _td(rng.uniform(1, 120, len(idx)), "m")
    log("applications", "decision_ts", "decision before submission", len(idx), "date_order")
    dup = a.loc[sample(a, 0.0025)]
    t["applications"] = pd.concat([a, dup], ignore_index=True)
    log("applications", "application_id", "duplicate rows", len(dup), "unique")

    # loans -------------------------------------------------------------
    lo = t["loans"]
    idx = sample(lo, 0.001)
    lo.loc[idx, "interest_rate_apr"] = lo.loc[idx, "interest_rate_apr"] * 100
    log("loans", "interest_rate_apr", "APR stored in basis points", len(idx), "range")
    idx = sample(lo, 0.0003)
    lo.loc[idx, "application_id"] = ["APP9" + str(x).zfill(6) for x in rng.integers(0, 999999, len(idx))]
    log("loans", "application_id", "orphan loan (application missing in LOS extract)", len(idx), "foreign_key")

    # repayments --------------------------------------------------------
    r = t["repayments"]
    paid = r["paid_date"].notna().values
    idx = sample(r, 0.0002, paid)
    r.loc[idx, "paid_date"] = (pd.to_datetime(r.loc[idx, "paid_date"]) + pd.Timedelta(days=365)).dt.date
    log("repayments", "paid_date", "year typo puts payment in the future", len(idx), "future_date")
    idx = sample(r, 0.0001, paid)
    r.loc[idx, "amount_paid"] = r.loc[idx, "amount_paid"] * 100
    log("repayments", "amount_paid", "payment amount x100", len(idx), "outlier")

    # transactions ------------------------------------------------------
    x = t["transactions"]
    idx = sample(x, 0.0002, x["loan_id"].notna().values)
    x.loc[idx, "loan_id"] = ["LN9" + str(v).zfill(6) for v in rng.integers(0, 999999, len(idx))]
    log("transactions", "loan_id", "orphan transaction", len(idx), "foreign_key")
    idx = sample(x, 0.0002)
    x.loc[idx, "amount"] = -x.loc[idx, "amount"]
    log("transactions", "amount", "sign convention error (negative amount)", len(idx), "range")
    dup = x.loc[sample(x, 0.002)]
    t["transactions"] = pd.concat([x, dup], ignore_index=True)
    log("transactions", "transaction_id", "duplicate webhook delivery", len(dup), "unique")

    # product_events ----------------------------------------------------
    e = t["product_events"]
    idx = sample(e, 0.005, e["platform"].isin(["android", "ios"]).values)
    e.loc[idx, "platform"] = e.loc[idx, "platform"].map({"android": "Android", "ios": "iOS"})
    log("product_events", "platform", "platform casing from old SDK", len(idx), "accepted_values")
    idx = sample(e, 0.00005)
    e.loc[idx, "event_ts"] = e.loc[idx, "event_ts"] + pd.Timedelta(days=400)
    log("product_events", "event_ts", "device clock in the future", len(idx), "future_date")
    n_test = max(5, int(len(e) * 0.0003))
    test = e.sample(n_test, random_state=seed).copy()
    test["user_id"] = ["TEST-QA-" + str(v).zfill(3) for v in rng.integers(1, 21, n_test)]
    test["event_id"] = ["EVT" + str(v).zfill(9) for v in range(n_test)]
    dup = e.loc[sample(e, 0.004)]
    t["product_events"] = pd.concat([e, test, dup], ignore_index=True).sort_values("event_ts", kind="mergesort")
    log("product_events", "user_id", "QA test accounts not in CRM", n_test, "foreign_key")
    log("product_events", "event_id", "SDK retry duplicates", len(dup), "unique")

    # support_tickets (schema drift + type drift) ------------------------
    s = t["support_tickets"]
    idx = sample(s, 0.001, s["resolved_ts"].notna().values)
    s.loc[idx, "resolved_ts"] = s.loc[idx, "created_ts"] - _td(rng.uniform(1, 48, len(idx)), "h")
    log("support_tickets", "resolved_ts", "resolved before created", len(idx), "date_order")
    s["csat_score"] = s["csat_score"].map(lambda v: "N/A" if pd.isna(v) else str(int(v)))
    log("support_tickets", "csat_score", "numeric column exported as text with 'N/A'", len(s), "schema_dtype")
    log("support_tickets", "agent_id", "new column added upstream without notice", len(s), "schema_unexpected_columns")

    # marketing_campaigns -------------------------------------------------
    m = t["marketing_campaigns"]
    i = int(rng.integers(0, len(m)))
    m.loc[i, ["start_date", "end_date"]] = [m.loc[i, "end_date"], m.loc[i, "start_date"]]
    log("marketing_campaigns", "end_date", "start/end dates swapped", 1, "date_order")
    j = int(rng.integers(0, len(m)))
    m.loc[j, "spend_inr"] = round(m.loc[j, "budget_inr"] * 3.4, 2)
    log("marketing_campaigns", "spend_inr", "spend 3.4x budget (agency double-billing)", 1, "cross_field")
    return t, manifest


def write_raw(tables: Dict[str, pd.DataFrame], settings: Settings, manifest: List[Dict]) -> Dict[str, int]:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, df in tables.items():
        out = df.copy()
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        path = settings.raw_dir / (name + (".csv.gz" if name == "product_events" else ".csv"))
        out.to_csv(path, index=False)
        counts[name] = len(df)
    (settings.raw_dir / "_injected_issues.json").write_text(json.dumps(manifest, indent=2))
    # small, committed samples so the raw shape can be inspected on GitHub without running anything
    sample_dir = settings.data_dir / "sample"
    sample_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        out = df.head(200).copy()
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        out.to_csv(sample_dir / (name + "_sample.csv"), index=False)
    meta = {"company": COMPANY_NAME + " (fictional)", "synthetic": True, "seed": settings.seed,
            "n_customers_param": settings.n_customers, "window": [settings.start_date, settings.end_date],
            "row_counts": counts, "total_rows": int(sum(counts.values()))}
    (settings.raw_dir / "_generation_summary.json").write_text(json.dumps(meta, indent=2))
    return counts


def generate(settings: Optional[Settings] = None) -> Dict[str, int]:
    settings = settings or get_settings()
    t0 = time.time()
    tables = LendingSimulator(settings).run()
    manifest: List[Dict] = []
    if settings.inject_dq_issues:
        tables, manifest = inject_dq_issues(tables, seed=settings.seed + 1)
    counts = write_raw(tables, settings, manifest)
    print("Generated %s synthetic rows across %d tables in %.1fs" % (format(sum(counts.values()), ","), len(counts),
                                                                      time.time() - t0))
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description="Generate the synthetic Vittora Credit dataset (SYNTHETIC DATA).")
    p.add_argument("--n-customers", type=int, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--no-dq-issues", action="store_true", help="write clean raw files (no injected defects)")
    args = p.parse_args()
    overrides = {}
    if args.n_customers:
        overrides["n_customers"] = args.n_customers
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.no_dq_issues:
        overrides["inject_dq_issues"] = False
    counts = generate(get_settings(**overrides))
    for k, v in counts.items():
        print("  %-24s %10s" % (k, format(v, ",")))


if __name__ == "__main__":
    main()
