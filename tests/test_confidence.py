"""Confidence scoring (PRD §9). Scorer unit formulas + the three overall anchors."""

from datetime import date

import pytest

from candidate_pipeline.confidence.scorer import (
    multi_valued_confidence,
    recency_factor,
    single_valued_confidence,
)

TOL = 1e-9


# ---- §9.1 single-valued formula -------------------------------------------

def test_single_valued_base_only():
    assert single_valued_confidence("ats_json", ["ats_json"], False, False, 1.0) == pytest.approx(0.90)


def test_single_valued_corroboration_with_github_full_weight():
    # ATS + GitHub agree, independence 1.0 -> +0.05
    assert single_valued_confidence(
        "ats_json", ["ats_json", "github_api"], False, False, 1.0
    ) == pytest.approx(0.95)


def test_single_valued_corroboration_ats_csv_half_weight():
    # ATS + CSV agree, independence 0.5 -> +0.025
    assert single_valued_confidence(
        "ats_json", ["ats_json", "recruiter_csv"], False, False, 1.0
    ) == pytest.approx(0.925)


def test_single_valued_corroboration_capped():
    # three additional github-like sources would exceed cap -> +0.10 max
    val = single_valued_confidence(
        "ats_json", ["ats_json", "github_api", "x", "y"], False, False, 1.0
    )
    assert val == pytest.approx(0.90 + 0.10)


def test_single_valued_prose_penalty():
    assert single_valued_confidence("github_api", ["github_api"], True, False, 1.0) == pytest.approx(0.60)


def test_single_valued_conflict_penalty():
    assert single_valued_confidence("ats_json", ["ats_json"], False, True, 1.0) == pytest.approx(0.85)


def test_single_valued_recency_multiplies_last():
    assert single_valued_confidence("ats_json", ["ats_json"], False, False, 0.8) == pytest.approx(0.72)


# ---- §9.2 multi-valued formula --------------------------------------------

def test_multi_valued_python_example():
    # "Python" from GitHub(0.70)+ATS(0.90), independence 1.0 -> 0.95
    assert multi_valued_confidence("ats_json", ["ats_json", "github_api"], False, 1.0) == pytest.approx(0.95)


def test_multi_valued_github_only():
    assert multi_valued_confidence("github_api", ["github_api"], False, 1.0) == pytest.approx(0.70)


def test_multi_valued_unknown_verbatim():
    # unknown kept verbatim -> 0.70 - 0.10 = 0.60
    assert multi_valued_confidence("github_api", ["github_api"], True, 1.0) == pytest.approx(0.60)


# ---- §9.3 recency scope ----------------------------------------------------

def test_recency_not_time_varying_is_one():
    assert recency_factor("2000-01-01T00:00:00Z", date(2026, 6, 30), False) == 1.0


def test_recency_none_last_updated_is_one():
    assert recency_factor(None, date(2026, 6, 30), True) == 1.0


def test_recency_decays_linearly():
    # 10 months stale -> 1 - 0.10
    assert recency_factor("2025-08-30T00:00:00Z", date(2026, 6, 30), True) == pytest.approx(0.90, abs=0.02)


def test_recency_decay_capped_at_20pct():
    # very stale -> capped at 0.20 decay
    assert recency_factor("2020-01-01T00:00:00Z", date(2026, 6, 30), True) == pytest.approx(0.80)


# ---- §9.4 / §4.4 the three overall-confidence anchors ----------------------

def test_anchor_clean_three_source_high(built_profiles):
    profiles, _ = built_profiles
    assert profiles["Aisha Khan"].overall_confidence == pytest.approx(0.88, abs=0.03)


def test_anchor_two_source_one_conflict_mid(built_profiles):
    profiles, _ = built_profiles
    assert profiles["Sri Krishna V"].overall_confidence == pytest.approx(0.78, abs=0.03)


def test_anchor_sparse_stale_low(built_profiles):
    profiles, _ = built_profiles
    assert profiles["Jordan Lee"].overall_confidence == pytest.approx(0.42, abs=0.05)


def test_anchors_are_ordered(built_profiles):
    profiles, _ = built_profiles
    assert (
        profiles["Aisha Khan"].overall_confidence
        > profiles["Sri Krishna V"].overall_confidence
        > profiles["Jordan Lee"].overall_confidence
    )

