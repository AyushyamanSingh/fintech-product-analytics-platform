"""Transform: contract-driven typing, de-duplication, standardisation and repair rules.

Principles (documented in docs/technical_documentation.md):
1. Never silently drop data - bad rows go to data/quarantine/ with a reason.
2. Never invent data - repairs are only applied when the root cause is known and reversible
   (e.g. a UTC timestamp written into an IST column, an APR stored in basis points).
3. Financial facts are kept even when lineage is broken (orphan loan -> application link nulled
   and flagged, the loan itself is kept).
4. Every rule writes to the cleaning log, which feeds the data-quality report.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from python.config import LOAD_ORDER

# FK orphan policy: quarantine the row, or null the reference and keep the row.
FK_POLICY = {
    ("loans", "application_id"): "nullify",       # keep the money, flag the lineage gap
    ("transactions", "loan_id"): "quarantine",    # a ledger entry that cannot be attributed to a loan
    ("transactions", "repayment_id"): "nullify",
    ("support_tickets", "loan_id"): "nullify",
}

PROPERTY_FIELDS = {
    "prop_product_id": (r'"product_id":"([^"]*)"', "string"),
    "prop_amount": (r'"amount":(-?[0-9.]+)', "float"),
    "prop_variant": (r'"variant":"([^"]*)"', "string"),
    "prop_reason": (r'"reason":"([^"]*)"', "string"),
    "prop_category": (r'"category":"([^"]*)"', "string"),
    "prop_method": (r'"method":"([^"]*)"', "string"),
    "prop_on_time": (r'"on_time":(true|false)', "boolean"),
}


class Transformer:
    def __init__(self, contracts: Dict, as_of: pd.Timestamp):
        self.contracts = contracts
        self.as_of = as_of
        self.log: List[Dict] = []
        self.quarantine: Dict[str, List[pd.DataFrame]] = {}
        self._done: Dict[str, pd.DataFrame] = {}  # tables already transformed (parents), for cross-table rules

    # ------------------------------------------------------------ bookkeeping
    def _log(self, table: str, rule: str, action: str, rows: int, detail: str = "") -> None:
        self.log.append({"table": table, "rule": rule, "action": action, "rows_affected": int(rows), "detail": detail})

    def _quarantine(self, table: str, df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
        mask = mask.fillna(False).astype(bool)
        if mask.any():
            q = df[mask].copy()
            q["_quarantine_reason"] = reason
            self.quarantine.setdefault(table, []).append(q)
        self._log(table, reason, "quarantine", int(mask.sum()))
        return df[~mask].copy()

    # ------------------------------------------------------------ generic steps
    def _drop_unexpected(self, table: str, df: pd.DataFrame) -> pd.DataFrame:
        spec = self.contracts["tables"][table]["columns"]
        extra = [c for c in df.columns if c not in spec]
        if extra:
            self._log(table, "schema_drift: drop columns not in contract (%s)" % ", ".join(extra), "drop_column", len(df),
                      "raise a contract change request to adopt them")
            df = df.drop(columns=extra)
        return df

    def _cast(self, table: str, df: pd.DataFrame) -> pd.DataFrame:
        spec = self.contracts["tables"][table]["columns"]
        for col, cs in spec.items():
            if col not in df.columns:
                continue
            s, typ = df[col], cs["type"]
            before_null = s.isna().sum()
            if typ in ("integer", "float", "money"):
                if s.dtype == object:
                    tokens = s.astype(str).str.strip().str.upper().isin(["N/A", "NA", "NULL", "NONE", ""])
                    if tokens.any():
                        self._log(table, "type_drift: '%s' text tokens (N/A, NULL) -> null" % col, "coerce", int(tokens.sum()))
                v = pd.to_numeric(s, errors="coerce")
                if typ == "money":
                    df[col] = v.round(2)
                elif typ == "integer":
                    df[col] = v.round().astype("Int64")
                else:
                    df[col] = v
            elif typ == "timestamp":
                df[col] = pd.to_datetime(s, errors="coerce")
            elif typ == "date":
                df[col] = pd.to_datetime(s, errors="coerce").dt.normalize()
            elif typ == "boolean":
                if not pd.api.types.is_bool_dtype(s):
                    df[col] = s.map(lambda x: None if pd.isna(x) else str(x).strip().lower() in ("true", "1", "1.0", "yes"))
            else:
                df[col] = s.where(s.notna(), None)
            new_null = int(df[col].isna().sum() - before_null)
            if new_null > 0 and typ not in ("integer", "float", "money"):
                self._log(table, "unparseable %s values in %s -> null" % (typ, col), "coerce", new_null)
        return df

    def _dedupe(self, table: str, df: pd.DataFrame) -> pd.DataFrame:
        n0 = len(df)
        df = df.drop_duplicates()
        self._log(table, "exact duplicate rows", "drop_duplicate", n0 - len(df))
        pk = self.contracts["tables"][table]["primary_key"]
        n1 = len(df)
        df = df.drop_duplicates(subset=pk, keep="first")
        self._log(table, "duplicate primary key (%s), keep first" % "+".join(pk), "drop_duplicate", n1 - len(df))
        return df

    def _foreign_keys(self, table: str, df: pd.DataFrame, done: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        spec = self.contracts["tables"][table]["columns"]
        for col, cs in spec.items():
            if "fk" not in cs or col not in df.columns:
                continue
            ptable, pcol = cs["fk"].split(".")
            if ptable not in done:
                continue
            keys = set(done[ptable][pcol].dropna().astype(str))
            orphan = df[col].notna() & ~df[col].astype(str).isin(keys)
            policy = FK_POLICY.get((table, col), "nullify" if cs.get("nullable", True) else "quarantine")
            if policy == "nullify":
                df.loc[orphan, col] = None
                self._log(table, "orphan %s (no %s) -> reference nulled, row kept" % (col, cs["fk"]), "nullify",
                          int(orphan.sum()))
            else:
                df = self._quarantine(table, df, orphan, "orphan %s (no matching %s)" % (col, cs["fk"]))
        return df

    # ------------------------------------------------------------ table rules
    def _rules_marketing_campaigns(self, df: pd.DataFrame) -> pd.DataFrame:
        swap = df["start_date"] > df["end_date"]
        df.loc[swap, ["start_date", "end_date"]] = df.loc[swap, ["end_date", "start_date"]].values
        self._log("marketing_campaigns", "start_date after end_date -> swapped", "repair", int(swap.sum()))
        over = df["spend_inr"] > 1.5 * df["budget_inr"]
        self._log("marketing_campaigns", "spend > 150% of budget -> flagged for Finance (not changed)", "flag", int(over.sum()),
                  ", ".join(df.loc[over, "campaign_id"].astype(str)))
        return df

    def _rules_customers(self, df: pd.DataFrame) -> pd.DataFrame:
        raw = df["acquisition_channel"].astype(str)
        std = raw.str.strip().str.lower().str.replace(r"[\s\-]+", "_", regex=True)
        self._log("customers", "acquisition_channel casing/spacing standardised", "standardise", int((raw != std).sum()))
        df["acquisition_channel"] = std
        # Attribution source of truth = the campaign tag (paid channels always carry one); free-text labels are not
        camps = self._done.get("marketing_campaigns")
        if camps is not None:
            derived = df["campaign_id"].map(camps.set_index("campaign_id")["channel"])
            derived = derived.where(df["campaign_id"].notna(), "organic")
            mismatch = derived.notna() & (derived != df["acquisition_channel"])
            df.loc[mismatch, "acquisition_channel"] = derived[mismatch]
            self._log("customers", "acquisition_channel contradicts campaign tag -> derived from campaign", "repair",
                      int(mismatch.sum()))
        # is_ntc must be derived BEFORE invalid scores are nulled, otherwise bad data becomes "new to credit"
        df["is_ntc"] = df["credit_score"].isna()
        bad_score = df["credit_score"].notna() & ~df["credit_score"].between(300, 900)
        df.loc[bad_score, "credit_score"] = pd.NA
        self._log("customers", "credit_score outside 300-900 -> null (is_ntc stays false)", "nullify", int(bad_score.sum()))
        bad_age = df["age"].notna() & ~df["age"].between(18, 75)
        df.loc[bad_age, "age"] = pd.NA
        self._log("customers", "age outside 18-75 -> null", "nullify", int(bad_age.sum()))
        inc = df["monthly_income"]
        typo = inc > 1_500_000
        fixable = typo & (inc / 100).between(3000, 1_500_000)
        df.loc[fixable, "monthly_income"] = (inc[fixable] / 100).round(2)
        df.loc[typo & ~fixable, "monthly_income"] = np.nan
        self._log("customers", "monthly_income > 15L/month keyed with extra zeros -> divided by 100", "repair", int(fixable.sum()))
        gap = df["kyc_started_ts"] - df["kyc_completed_ts"]
        tz = gap.notna() & (gap > pd.Timedelta(0)) & (gap <= pd.Timedelta(hours=5, minutes=31))
        df.loc[tz, "kyc_completed_ts"] = df.loc[tz, "kyc_completed_ts"] + pd.Timedelta(hours=5, minutes=30)
        self._log("customers", "kyc_completed_ts written in UTC (precedes kyc_started by <= 5h30m) -> +05:30", "repair", int(tz.sum()))
        still = (df["kyc_completed_ts"] < df["kyc_started_ts"]).fillna(False)
        df.loc[still, "kyc_completed_ts"] = pd.NaT
        self._log("customers", "kyc_completed_ts still before kyc_started_ts -> null", "nullify", int(still.sum()))
        return df

    def _rules_applications(self, df: pd.DataFrame) -> pd.DataFrame:
        neg = df["requested_amount"] < 0
        df.loc[neg, "requested_amount"] = df.loc[neg, "requested_amount"].abs()
        self._log("applications", "negative requested_amount (sign error) -> absolute value", "repair", int(neg.sum()))
        bad = (df["decision_ts"] < df["submitted_ts"]).fillna(False)
        df.loc[bad, "decision_ts"] = pd.NaT
        self._log("applications", "decision_ts before submitted_ts -> null (decision kept)", "nullify", int(bad.sum()))
        return df

    def _rules_loans(self, df: pd.DataFrame) -> pd.DataFrame:
        bps = df["interest_rate_apr"] > 100
        df.loc[bps, "interest_rate_apr"] = df.loc[bps, "interest_rate_apr"] / 100
        self._log("loans", "interest_rate_apr stored in basis points -> divided by 100", "repair", int(bps.sum()))
        return df

    def _rules_repayments(self, df: pd.DataFrame) -> pd.DataFrame:
        fut = df["paid_date"] > self.as_of
        back = df["paid_date"] - pd.Timedelta(days=365)
        fixable = fut & (back <= self.as_of) & (back >= df["due_date"] - pd.Timedelta(days=31))
        df.loc[fixable, "paid_date"] = back[fixable]
        df.loc[fut & ~fixable, "paid_date"] = pd.NaT
        self._log("repayments", "paid_date in the future by exactly one year (year typo) -> -365 days", "repair",
                  int(fixable.sum()))
        big = df["amount_paid"] > df["total_due"] * 1.01
        fix = big & ((df["amount_paid"] / 100) <= df["total_due"] * 1.01)
        df.loc[fix, "amount_paid"] = (df.loc[fix, "amount_paid"] / 100).round(2)
        self._log("repayments", "amount_paid 100x the instalment (missing decimal) -> divided by 100", "repair", int(fix.sum()))
        return df

    def _rules_transactions(self, df: pd.DataFrame) -> pd.DataFrame:
        neg = df["amount"] < 0
        df.loc[neg, "amount"] = df.loc[neg, "amount"].abs()
        self._log("transactions", "negative amount (sign convention) -> absolute value", "repair", int(neg.sum()))
        return df

    def _rules_product_events(self, df: pd.DataFrame) -> pd.DataFrame:
        raw = df["platform"].astype(str)
        df["platform"] = raw.str.strip().str.lower()
        self._log("product_events", "platform casing standardised", "standardise", int((raw != df["platform"]).sum()))
        test = df["user_id"].astype(str).str.startswith("TEST-")
        df = self._quarantine("product_events", df, test, "QA test account events")
        fut = df["event_ts"] >= self.as_of + pd.Timedelta(days=1)
        df = self._quarantine("product_events", df, fut, "event_ts in the future (device clock)")
        props = df["properties"].astype(str)
        for col, (pattern, typ) in PROPERTY_FIELDS.items():
            val = props.str.extract(pattern, expand=False)
            if typ == "float":
                val = pd.to_numeric(val, errors="coerce")
            elif typ == "boolean":
                val = val.map({"true": True, "false": False})
            df[col] = val
        self._log("product_events", "flatten JSON properties into prop_* columns", "derive", len(df))
        return df

    def _rules_support_tickets(self, df: pd.DataFrame) -> pd.DataFrame:
        bad = (df["resolved_ts"] < df["created_ts"]).fillna(False)
        df.loc[bad, "resolved_ts"] = pd.NaT
        self._log("support_tickets", "resolved_ts before created_ts -> null", "nullify", int(bad.sum()))
        return df

    # ------------------------------------------------------------ driver
    def transform(self, raw: Dict[str, pd.DataFrame]) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, Dict[str, pd.DataFrame]]:
        done: Dict[str, pd.DataFrame] = self._done
        for table in LOAD_ORDER:
            df = raw[table].copy()
            df = self._drop_unexpected(table, df)
            df = self._cast(table, df)
            df = self._dedupe(table, df)
            rule = getattr(self, "_rules_" + table, None)
            if rule is not None:
                df = rule(df)
            df = self._foreign_keys(table, df, done)
            ordered = [c for c in self.contracts["tables"][table]["columns"] if c in df.columns]
            done[table] = df[ordered].reset_index(drop=True)
        quarantine = {t: pd.concat(parts, ignore_index=True) for t, parts in self.quarantine.items()}
        return done, pd.DataFrame(self.log), quarantine


def sql_types(contracts: Dict, table: str) -> Dict[str, str]:
    types = contracts["types"]
    return {c: types[s["type"]] for c, s in contracts["tables"][table]["columns"].items()}
