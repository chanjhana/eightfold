"""date normalizer (PRD §6, edge case §15 #5). Output YYYY or YYYY-MM; never fabricate a month."""

import pytest

from candidate_pipeline.normalize.dates import normalize_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2020-03", "2020-03"),
        ("2020-3", "2020-03"),
        ("2020", "2020"),
        ("2019-11-15", "2019-11"),  # day dropped, granularity capped at month
        ("March 2020", "2020-03"),
        ("2021", "2021"),
    ],
)
def test_preserves_granularity(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize("raw", ["Present", "", None, "  "])
def test_ongoing_or_empty_is_none(raw):
    assert normalize_date(raw) is None


def test_year_only_does_not_invent_month():
    assert normalize_date("2018") == "2018"  # not "2018-01"
