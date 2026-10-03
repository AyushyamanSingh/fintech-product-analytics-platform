"""Statistical helpers checked against hand-computed / textbook values."""
import math

import pytest

from python.experiment_analysis import (achieved_power, bayes_beta_binomial, guardrail_status, holm_adjust,
                                        mde_at_n, required_n_per_arm, srm_check, two_proportion_test)


def test_two_proportion_test_matches_manual():
    r = two_proportion_test(500, 1000, 550, 1000)
    pooled = 1050 / 2000
    z = 0.05 / math.sqrt(pooled * (1 - pooled) * (2 / 1000))
    assert r["diff_abs"] == pytest.approx(0.05)
    assert r["z"] == pytest.approx(z, rel=1e-9)
    assert r["p_value"] == pytest.approx(2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))), rel=1e-6)
    se = math.sqrt(0.5 * 0.5 / 1000 + 0.55 * 0.45 / 1000)
    assert r["ci_low"] == pytest.approx(0.05 - 1.959964 * se, rel=1e-4)
    assert r["significant"]
    assert r["relative_uplift"] == pytest.approx(0.10)


def test_no_difference_not_significant():
    r = two_proportion_test(300, 1000, 302, 1000)
    assert not r["significant"] and r["ci_low"] < 0 < r["ci_high"]


def test_sample_size_textbook_value():
    # p1=0.50, +5pp, alpha 0.05 two-sided, 80% power -> ~1,565 per arm (standard formula)
    n = required_n_per_arm(0.50, 0.05)
    assert 1540 <= n <= 1580
    assert mde_at_n(0.50, n) == pytest.approx(0.05, abs=0.002)
    assert achieved_power(0.50, 0.55, n) == pytest.approx(0.80, abs=0.02)


def test_srm_detection():
    assert not srm_check(5010, 4990)["srm_detected"]
    assert srm_check(5500, 4500)["srm_detected"]


def test_holm_is_monotone_and_bounded():
    adj = holm_adjust([0.01, 0.04, 0.03, 0.20])
    assert adj[0] == pytest.approx(0.04)
    assert all(0 <= a <= 1 for a in adj)
    assert adj[3] == pytest.approx(0.20)


def test_guardrail_logic():
    worse = {"diff_abs": 0.03, "ci_low": 0.02, "ci_high": 0.04, "significant": True}
    fine = {"diff_abs": 0.001, "ci_low": -0.004, "ci_high": 0.006, "significant": False}
    wide = {"diff_abs": 0.0, "ci_low": -0.03, "ci_high": 0.03, "significant": False}
    assert guardrail_status(worse, 0.015, higher_is_worse=True) == "breach"
    assert guardrail_status(fine, 0.015, higher_is_worse=True) == "pass"
    assert guardrail_status(wide, 0.015, higher_is_worse=True) == "inconclusive"
    # lower-is-worse metric (e.g. approval rate): a significant drop beyond the margin is a breach
    drop = {"diff_abs": -0.04, "ci_low": -0.06, "ci_high": -0.02, "significant": True}
    assert guardrail_status(drop, 0.02, higher_is_worse=False) == "breach"


def test_bayesian_agrees_with_clear_win():
    b = bayes_beta_binomial(500, 1000, 600, 1000, draws=50_000)
    assert b["prob_treatment_better"] > 0.99
    assert b["credible_low"] > 0
