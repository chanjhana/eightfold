"""email normalizer (PRD §6). Lowercase + basic shape; invalid -> dropped (None)."""

import pytest

from candidate_pipeline.normalize.email import normalize_email


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Foo@Bar.com", "foo@bar.com"),
        ("  a@b.co  ", "a@b.co"),
        ("First.Last@Example.IO", "first.last@example.io"),
    ],
)
def test_lowercases_and_trims_valid(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["not-an-email", "no@domain", "@no-local.com", "", None, "a b@c.com"])
def test_invalid_dropped(raw):
    assert normalize_email(raw) is None
