"""Shared fixtures.

``e2e`` runs the real pipeline once per test session on a small synthetic dataset in a temporary
directory (the repository's data/ and outputs/ folders are never touched).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import Pipeline  # noqa: E402
from python.config import get_settings  # noqa: E402

E2E_STEPS = ["generate", "extract", "validate_raw", "transform", "validate_clean", "load", "sql_analytics", "kpis",
             "anomalies", "experiments", "segmentation", "powerbi_export", "ai_summary", "dashboard"]


@pytest.fixture(scope="session")
def e2e(tmp_path_factory):
    base = tmp_path_factory.mktemp("fpa_e2e")
    settings = get_settings(base_dir=base, n_customers=6000, seed=7, offline_ai=True)
    settings.ensure_dirs()
    pipe = Pipeline(settings, "pytest")
    ok = pipe.run(E2E_STEPS)
    return {"settings": settings, "ok": ok, "manifest": pipe.manifest, "state": pipe.state}


@pytest.fixture(scope="session")
def contracts():
    from data_quality.runner import load_contracts
    return load_contracts(get_settings().contracts_path)
