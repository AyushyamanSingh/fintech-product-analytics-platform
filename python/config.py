"""Central configuration: paths, simulation window and business calendar.

All paths hang off ``Settings.base_dir`` so the whole pipeline can be pointed at a
temporary directory (the test-suite does this) without touching the real data folder.
Code assets (SQL files, data contracts) always come from the repository itself.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]

COMPANY_NAME = "Vittora Credit"  # fictional digital lender used throughout the project
CURRENCY = "INR"

TABLES: List[str] = [
    "products",
    "marketing_campaigns",
    "customers",
    "applications",
    "loans",
    "repayments",
    "transactions",
    "product_events",
    "support_tickets",
    "experiments",
    "experiment_assignments",
]

# Load order respects foreign keys (parents before children).
LOAD_ORDER: List[str] = TABLES

# Business calendar: known events used to annotate (not suppress) anomalies.
BUSINESS_CALENDAR: List[Dict[str, str]] = [
    {"start": "2024-10-10", "end": "2024-11-10", "event": "Festive campaign 2024 (Diwali)", "type": "marketing"},
    {"start": "2025-04-01", "end": "2025-04-30", "event": "Flexi Credit Line (P07) launch", "type": "product_launch"},
    {"start": "2025-05-12", "end": "2025-05-16", "event": "App release 5.2.0 (hotfix 5.2.1 on 16 May)", "type": "release"},
    {"start": "2025-06-02", "end": "2025-06-29", "event": "EXP-PRC-2025-06 fee transparency test", "type": "experiment"},
    {"start": "2025-10-01", "end": "2025-11-15", "event": "Festive campaign 2025 (Diwali)", "type": "marketing"},
    {"start": "2025-11-03", "end": "2025-12-14", "event": "EXP-RPY-2025-11 autopay nudge test", "type": "experiment"},
    {"start": "2026-01-12", "end": "2026-02-22", "event": "EXP-ONB-2026-01 onboarding redesign test", "type": "experiment"},
    {"start": "2026-03-02", "end": "2026-03-08", "event": "Onboarding redesign rolled out to 100% (app 6.0.0)", "type": "release"},
]


@dataclass
class Settings:
    """Runtime settings. Override any field via keyword args or FPA_* env vars."""

    base_dir: Path = PROJECT_ROOT
    seed: int = 42
    n_customers: int = 80_000
    start_date: str = "2024-07-01"
    end_date: str = "2026-06-30"  # inclusive; also the "as-of" date of the extract
    inject_dq_issues: bool = True
    offline_ai: bool = False  # force the deterministic summariser even if an API key exists
    extra: Dict[str, str] = field(default_factory=dict)

    # ---- data layers -------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    @property
    def warehouse_path(self) -> Path:
        return self.data_dir / "warehouse" / "fintech.duckdb"

    # ---- outputs -----------------------------------------------------
    @property
    def outputs_dir(self) -> Path:
        return self.base_dir / "outputs"

    @property
    def images_dir(self) -> Path:
        return self.base_dir / "docs" / "images"

    @property
    def powerbi_data_dir(self) -> Path:
        return self.base_dir / "powerbi" / "data"

    # ---- code assets (always from the repo) --------------------------
    @property
    def sql_dir(self) -> Path:
        return PROJECT_ROOT / "sql"

    @property
    def contracts_path(self) -> Path:
        return PROJECT_ROOT / "data_quality" / "contracts.yaml"

    def out(self, *parts: str) -> Path:
        """Path inside outputs/, creating the parent folder."""
        path = self.outputs_dir.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_dirs(self) -> None:
        for d in (
            self.raw_dir,
            self.staging_dir,
            self.processed_dir,
            self.quarantine_dir,
            self.warehouse_path.parent,
            self.outputs_dir,
            self.images_dir,
            self.powerbi_data_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_settings(**overrides) -> Settings:
    """Build settings from env vars (FPA_BASE_DIR, FPA_N_CUSTOMERS, FPA_SEED, FPA_OFFLINE_AI) + overrides."""
    env: Dict[str, object] = {}
    if os.getenv("FPA_BASE_DIR"):
        env["base_dir"] = Path(os.environ["FPA_BASE_DIR"])
    if os.getenv("FPA_N_CUSTOMERS"):
        env["n_customers"] = int(os.environ["FPA_N_CUSTOMERS"])
    if os.getenv("FPA_SEED"):
        env["seed"] = int(os.environ["FPA_SEED"])
    if os.getenv("FPA_OFFLINE_AI"):
        env["offline_ai"] = os.environ["FPA_OFFLINE_AI"].lower() in ("1", "true", "yes")
    env.update(overrides)
    if "base_dir" in env:
        env["base_dir"] = Path(env["base_dir"])  # type: ignore[arg-type]
    return Settings(**env)  # type: ignore[arg-type]
