"""phone normalizer (PRD §6, edge case §15 #4)."""

from candidate_pipeline.normalize.phone import normalize_phone


def test_explicit_country_code_normalizes_to_e164_no_flag():
    r = normalize_phone("+1 415 555 2671", default_region=None)
    assert r.value == "+14155552671"
    assert r.method == "normalize:e164"
    assert r.flag is None


def test_no_country_code_with_default_region_assumes_and_flags():
    r = normalize_phone("98765 43210", default_region="IN")
    assert r.value == "+919876543210"
    assert r.method == "assume:default_region"
    assert r.flag is not None
    assert r.flag.kind == "assumed_region"


def test_no_country_code_no_region_keeps_raw_no_e164_no_flag():
    r = normalize_phone("98765 43210", default_region=None)
    assert r.value is None
    assert r.raw == "98765 43210"
    assert r.method is None
    assert r.flag is None


def test_garbage_phone_returns_no_value():
    r = normalize_phone("not-a-phone", default_region="IN")
    assert r.value is None
