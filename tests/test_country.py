"""country normalizer (PRD §6). ISO-3166 alpha-2, best-effort on free text."""

import pytest

from candidate_pipeline.normalize.country import normalize_country


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("United States", "US"),
        ("USA", "US"),
        ("India", "IN"),
        ("Germany", "DE"),
        ("IN", "IN"),
        ("Bengaluru, India", "IN"),  # free text, last token resolves
    ],
)
def test_resolves_to_alpha2(raw, expected):
    assert normalize_country(raw) == expected


@pytest.mark.parametrize("raw", ["Wakanda", "", None, "   "])
def test_unresolvable_is_none(raw):
    assert normalize_country(raw) is None
