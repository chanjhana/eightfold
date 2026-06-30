"""Edge-case coverage for the normalizers (PRD §6).

These assert *invariants* — "garbage resolves to None, never an invented value",
"a known cleanup happens for a whole class of input" — not memorized outputs.
Where an outcome is a genuine, irreducible ambiguity (e.g. "Georgia" the country
vs the US state) it is pinned with a comment so it documents behavior rather than
locking in an accident.
"""

import pytest

from candidate_pipeline.normalize.country import normalize_country
from candidate_pipeline.normalize.dates import normalize_date
from candidate_pipeline.normalize.email import normalize_email
from candidate_pipeline.normalize.phone import normalize_phone
from candidate_pipeline.normalize.skills import canonicalize_skill, split_skills


# ---- email -----------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("mailto:foo@bar.com", "foo@bar.com"),       # copy-paste prefix stripped
        ("MAILTO: Foo@Bar.com", "foo@bar.com"),
        ("foo@bar.com.", "foo@bar.com"),             # prose trailing punctuation
        ("foo@bar.com,", "foo@bar.com"),
        ("foo@bar.com)", "foo@bar.com"),
    ],
)
def test_email_cleanup_classes(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["foo@bar@baz.com", "foo@@bar.com", "foo@bar", "@bar.com", "foo@"])
def test_email_still_rejects_clearly_invalid(raw):
    assert normalize_email(raw) is None


def test_email_ip_domain_is_accepted():
    # An IP-literal domain is a syntactically valid address; we do not reject it.
    # Pinned to document the deliberate non-rejection.
    assert normalize_email("ops@192.168.1.1") == "ops@192.168.1.1"


# ---- phone -----------------------------------------------------------------

def test_phone_empty_and_garbage_are_none():
    for raw in ["", "   ", "not-a-phone", "+1@#$"]:
        assert normalize_phone(raw).value is None  # never invented


def test_phone_explicit_country_code_normalizes_to_e164():
    res = normalize_phone("+1 (415) 555-2671")
    assert res.value == "+14155552671"
    assert res.flag is None


def test_phone_default_region_flags_the_assumption():
    res = normalize_phone("98765 43210", default_region="IN")
    assert res.value and res.value.startswith("+91")
    assert res.flag is not None and res.flag.kind == "assumed_region"


def test_phone_no_region_keeps_nothing_rather_than_guess():
    # No country code and no default region: we refuse to guess a region.
    assert normalize_phone("98765 43210").value is None


def test_phone_vanity_letters_are_converted_by_phonenumbers():
    # Pinned: the phonenumbers library converts vanity letters to digits. This is
    # library behavior, not our fabrication; documented so the behavior is explicit.
    assert normalize_phone("+1-800-FLOWERS").value == "+18003569377"


# ---- dates -----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [("2018", "2018"), ("2020-3", "2020-03"), ("2020-03", "2020-03")])
def test_date_explicit_formats(raw, expected):
    assert normalize_date(raw) == expected


def test_date_year_only_never_fabricates_a_month():
    assert normalize_date("2019") == "2019"  # not "2019-01"


@pytest.mark.parametrize("raw", ["Present", "present", "", "   ", None, "current", "now", "n/a", "tbd"])
def test_date_ongoing_or_unparseable_is_none(raw):
    assert normalize_date(raw) is None


def test_date_out_of_range_month_rejected_not_padded():
    # "2020-13" must not become a fake month — it is not a real date.
    assert normalize_date("2020-13") is None


def test_date_full_date_drops_to_month_granularity():
    assert normalize_date("2019-11-15") == "2019-11"


# ---- country ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [("United States", "US"), ("USA", "US"), ("IN", "IN"), ("India", "IN")])
def test_country_resolves_common_forms(raw, expected):
    assert normalize_country(raw) == expected


def test_country_free_text_takes_the_country_token():
    assert normalize_country("Bengaluru, India") == "IN"


@pytest.mark.parametrize("raw", ["Remote", "Unknown", "Worldwide", "Wakanda", "", None])
def test_country_unresolvable_is_none(raw):
    assert normalize_country(raw) is None


def test_country_georgia_is_a_known_ambiguity():
    # "Georgia" the country (GE) wins over the US state — an irreducible ambiguity
    # in a bare token. Pinned + documented as a known limitation, not a target.
    assert normalize_country("Georgia") == "GE"


# ---- skills ----------------------------------------------------------------

@pytest.mark.parametrize(
    "sep_string,expected_count",
    [("Python|Go|Rust", 3), ("Python\nGo\nRust", 3), ("Python\tGo", 2), ("Python; Go, Rust", 3)],
)
def test_split_handles_many_separators(sep_string, expected_count):
    assert len(split_skills(sep_string)) == expected_count


def test_split_does_not_break_slashed_skills():
    # "/" is intentionally NOT a separator (CI/CD, TCP/IP are single skills).
    assert split_skills("CI/CD, TCP/IP") == ["CI/CD", "TCP/IP"]


def test_split_drops_empty_tokens():
    assert split_skills("Python,,;|  ;Go") == ["Python", "Go"]


@pytest.mark.parametrize("raw,expected", [("vue", "Vue.js"), ("rust", "Rust"), ("graphql", "GraphQL"), ("k8s", "Kubernetes")])
def test_expanded_alias_table(raw, expected):
    r = canonicalize_skill(raw)
    assert r.value == expected and r.is_canonical


def test_unknown_skill_is_kept_verbatim_and_flagged_not_dropped():
    r = canonicalize_skill("Quantum Wizardry 9000")
    assert r.value == "Quantum Wizardry 9000"  # verbatim, never invented/dropped
    assert r.is_canonical is False and r.flag is not None


def test_cpp_family_never_collapses():
    assert canonicalize_skill("C++").value == "C++"
    assert canonicalize_skill("C#").value == "C#"
    assert canonicalize_skill(".NET").value == ".NET"
