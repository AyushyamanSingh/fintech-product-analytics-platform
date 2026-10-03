"""Customer segmentation: rule-based CRM segments (all customers) + K-Means clusters (borrowers).

Two complementary lenses:
1. Business segments - mutually exclusive, priority-ordered rules a CRM team can act on today
   (High-risk, New, High-value repeat, High-engagement, Onboarding drop-off, Inactive, ...).
2. Behavioural clusters - K-Means on standardised behavioural + financial features of borrowers,
   k chosen with silhouette scores under an interpretability constraint (4-6 clusters), clusters
   named from their centroid profiles.

    python -m python.segmentation
"""
from __future__ import annotations

import warnings
from typing import Dict, List, Optional

# joblib (used by scikit-learn) probes physical CPU cores with a Windows tool that is often absent; the fallback
# to logical cores is harmless, so silence that one warning rather than letting it look like an error.
warnings.filterwarnings("ignore", message="Could not find the number of physical cores")

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from python.config import Settings, get_settings
from python.io_utils import write_json

RULE_SEGMENTS = [
    # (name, rule description, recommended action)
    ("High-risk", "current DPD >= 30, any loan written off, or ever 90+ DPD",
     "Collections workflow; block new credit; hardship restructuring offers"),
    ("New customers", "signed up in the last 30 days",
     "Onboarding nudges: KYC reminders, first-loan offer within eligibility"),
    ("High-value repeat", "2+ loans, net revenue in the top quartile of borrowers, never 30+ DPD",
     "Retention: pre-approved top-ups, rate discounts, credit-line upgrades (P07)"),
    ("High-engagement", "top 20% of 90-day app activity, not in the segments above",
     "Cross-sell and referral asks; beta-test new features"),
    ("Onboarding drop-off", "KYC not verified and signed up 30+ days ago",
     "Win-back: DigiLocker one-tap KYC, assisted KYC call-back"),
    ("Inactive", "no app activity in the last 90 days",
     "Re-activation campaign only if previously profitable; suppress paid retargeting otherwise"),
    ("Verified, never borrowed", "KYC verified, no loan yet, active in the last 90 days",
     "Pre-qualified offer; explain eligibility; EMI calculator nudge"),
    ("Core borrowers", "everyone else (active, mid-value)",
     "Autopay adoption, on-time payment rewards, next-loan offers at closure"),
]

FEATURES = ["log_loans", "log_disbursed", "net_revenue_slog", "on_time_rate", "log_max_dpd", "log_logins_90d",
            "active_months", "n_products", "autopay", "log_days_since_last_loan", "log_tickets"]


def rule_segments(c: pd.DataFrame) -> pd.Series:
    borrowers = c[c["n_loans"] > 0]
    rev_q75 = borrowers["net_revenue"].quantile(0.75) if len(borrowers) else 0
    eng_p80 = c["client_events_90d"].quantile(0.80)
    conds = [
        (c["current_dpd"] >= 30) | c["has_written_off_loan"] | (c["max_dpd_ever"] >= 90),
        c["tenure_days"] <= 30,
        (c["n_loans"] >= 2) & (c["net_revenue"] >= rev_q75) & (c["max_dpd_ever"] < 30),
        (c["client_events_90d"] >= max(eng_p80, 1)),
        (c["kyc_status"] != "verified"),
        (c["days_since_last_active"].fillna(9999) > 90),
        (c["n_loans"] == 0),
    ]
    names = [s[0] for s in RULE_SEGMENTS]
    return pd.Series(np.select(conds, names[:-1], default=names[-1]), index=c.index)


def build_features(b: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=b.index)
    f["log_loans"] = np.log1p(b["n_loans"])
    f["log_disbursed"] = np.log1p(b["total_disbursed"])
    nr = b["net_revenue"].astype(float)
    f["net_revenue_slog"] = np.sign(nr) * np.log1p(nr.abs())
    f["on_time_rate"] = b["on_time_rate"].fillna(b["on_time_rate"].median())
    f["log_max_dpd"] = np.log1p(b["max_dpd_ever"])
    f["log_logins_90d"] = np.log1p(b["logins_90d"])
    f["active_months"] = b["active_months"]
    f["n_products"] = b["n_products"]
    f["autopay"] = b["autopay_ever"].astype(int)
    f["log_days_since_last_loan"] = np.log1p(b["days_since_last_loan"].clip(lower=0))
    f["log_tickets"] = np.log1p(b["support_tickets"])
    return f


def choose_k(X: np.ndarray, k_range=range(3, 9), sample: int = 5000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X), size=min(sample, len(X)), replace=False)
    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X)
        rows.append({"k": k, "inertia": float(km.inertia_),
                     "silhouette": float(silhouette_score(X[idx], km.labels_[idx]))})
    return pd.DataFrame(rows)


CLUSTER_ACTIONS = {
    "Credit-stressed": "Collections / hardship restructuring; suppress from all marketing audiences",
    "Chronic late payers": "Pre-due reminders, enforce autopay, hold limit increases until 3 on-time EMIs",
    "Loyal repeat borrowers": "Loyalty pricing, pre-approved repeat offers at closure, referral asks",
    "High-value borrowers": "Protect: dedicated top-up offers, credit-line (P07) upgrade, service priority",
    "Lapsed one-time borrowers": "Low-cost re-activation (WhatsApp/email) for pre-qualified customers only",
    "New & ramping": "Nurture to a second loan: autopay set-up, on-time rewards, cross-sell at closure",
}


def name_clusters(profile: pd.DataFrame) -> Dict[int, str]:
    """Assign business names from centroid profiles (greedy, each name used once, risk first)."""
    names: Dict[int, str] = {}
    remaining = list(profile.index)

    def take(name, col, largest=True, condition=None):
        cands = [c for c in remaining if condition is None or condition(profile.loc[c])]
        if not cands:
            return
        s = profile.loc[cands, col]
        cid = s.idxmax() if largest else s.idxmin()
        names[cid] = name
        remaining.remove(cid)

    take("Credit-stressed", "max_dpd_ever")
    take("Chronic late payers", "on_time_rate", largest=False, condition=lambda r: r["on_time_rate"] < 0.6)
    take("Loyal repeat borrowers", "n_loans", condition=lambda r: r["n_loans"] >= 2)
    take("High-value borrowers", "net_revenue")
    take("Lapsed one-time borrowers", "days_since_last_loan")
    take("New & ramping", "days_since_last_loan", largest=False)
    for i, cid in enumerate(remaining):
        names[cid] = "Steady borrowers %d" % (i + 1)
    return names


def run(settings: Optional[Settings] = None) -> Dict:
    settings = settings or get_settings()
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        c = con.execute("SELECT * FROM marts.customer_360").df()
    finally:
        con.close()
    for col in ("has_written_off_loan", "has_open_loan", "autopay_ever"):
        c[col] = c[col].fillna(False).astype(bool)

    # ---- 1. rule-based segments
    c["business_segment"] = rule_segments(c)
    seg = (c.groupby("business_segment")
           .agg(customers=("customer_id", "size"), borrowers=("n_loans", lambda s: int((s > 0).sum())),
                avg_net_revenue=("net_revenue", "mean"), total_net_revenue=("net_revenue", "sum"),
                outstanding=("outstanding_principal", "sum"), avg_logins_90d=("logins_90d", "mean"),
                avg_on_time_rate=("on_time_rate", "mean"))
           .reset_index())
    seg["share_of_customers_pct"] = 100 * seg["customers"] / seg["customers"].sum()
    seg["share_of_net_revenue_pct"] = 100 * seg["total_net_revenue"] / seg["total_net_revenue"].sum()
    meta = pd.DataFrame(RULE_SEGMENTS, columns=["business_segment", "rule", "recommended_action"])
    seg = meta.merge(seg, on="business_segment", how="left").fillna({"customers": 0})

    # ---- 2. K-Means on borrowers
    b = c[c["n_loans"] > 0].copy()
    feats = build_features(b)
    X = StandardScaler().fit_transform(feats.values)
    k_scores = choose_k(X)
    best = k_scores.loc[k_scores["silhouette"].idxmax()]
    preferred = k_scores[k_scores["k"].between(4, 6)].sort_values("silhouette", ascending=False).iloc[0]
    # Behavioural data rarely forms crisp clusters (silhouette is low for every k), so k is chosen for
    # actionability: 4-6 segments a CRM team can run, unless that costs > 25% of the best silhouette.
    chosen = preferred if preferred["silhouette"] >= 0.75 * best["silhouette"] else best
    k = int(chosen["k"])
    km = KMeans(n_clusters=k, n_init=20, random_state=42).fit(X)
    b["cluster"] = km.labels_
    # Stability: re-fit with other seeds; adjusted Rand index ~1 means the segmentation is reproducible
    stability = [adjusted_rand_score(km.labels_, KMeans(n_clusters=k, n_init=10, random_state=s).fit(X).labels_)
                 for s in (7, 99, 2024)]

    prof_cols = ["n_loans", "total_disbursed", "net_revenue", "on_time_rate", "max_dpd_ever", "logins_90d",
                 "active_months", "n_products", "autopay_ever", "days_since_last_loan", "support_tickets"]
    profile = b.groupby("cluster")[prof_cols].mean()
    profile["autopay_ever"] = b.groupby("cluster")["autopay_ever"].mean()
    names = name_clusters(profile)
    profile.insert(0, "cluster_name", [names[i] for i in profile.index])
    profile.insert(1, "borrowers", b.groupby("cluster").size())
    profile["share_of_borrowers_pct"] = 100 * profile["borrowers"] / profile["borrowers"].sum()
    profile["share_of_net_revenue_pct"] = 100 * b.groupby("cluster")["net_revenue"].sum() / b["net_revenue"].sum()
    profile["share_of_outstanding_pct"] = 100 * b.groupby("cluster")["outstanding_principal"].sum() / max(b["outstanding_principal"].sum(), 1)
    profile["recommended_action"] = profile["cluster_name"].map(CLUSTER_ACTIONS).fillna("Monitor; no targeted action")
    # z-scored centroids (feature space) for the profile heatmap
    centroid_z = pd.DataFrame(km.cluster_centers_, columns=FEATURES)
    centroid_z.insert(0, "cluster_name", [names[i] for i in range(k)])

    b["cluster_name"] = b["cluster"].map(names)
    assign = c[["customer_id", "business_segment"]].merge(b[["customer_id", "cluster", "cluster_name"]],
                                                          on="customer_id", how="left")
    out_dir = settings.outputs_dir / "segments"
    out_dir.mkdir(parents=True, exist_ok=True)
    assign.to_csv(out_dir / "customer_segments.csv", index=False)
    seg.to_csv(out_dir / "business_segments.csv", index=False)
    profile.reset_index().to_csv(out_dir / "cluster_profiles.csv", index=False)
    centroid_z.to_csv(out_dir / "cluster_centroids_z.csv", index=False)
    k_scores.to_csv(out_dir / "k_selection.csv", index=False)

    result = {
        "business_segments": seg.round(2).to_dict("records"),
        "kmeans": {"k": k, "silhouette": round(float(chosen["silhouette"]), 3),
                   "best_k_by_silhouette": int(best["k"]), "best_silhouette": round(float(best["silhouette"]), 3),
                   "stability_ari_mean": round(float(np.mean(stability)), 3),
                   "features": FEATURES, "n_borrowers": int(len(b)),
                   "clusters": profile.reset_index().round(2).to_dict("records")},
    }
    write_json(result, out_dir / "segmentation_summary.json")
    return result


if __name__ == "__main__":
    r = run()
    print(pd.DataFrame(r["business_segments"])[["business_segment", "customers", "share_of_customers_pct",
                                                 "share_of_net_revenue_pct"]].to_string(index=False))
    print("k =", r["kmeans"]["k"], "silhouette", r["kmeans"]["silhouette"])
    print(pd.DataFrame(r["kmeans"]["clusters"])[["cluster_name", "borrowers", "n_loans", "net_revenue", "max_dpd_ever",
                                                  "share_of_net_revenue_pct"]].to_string(index=False))
