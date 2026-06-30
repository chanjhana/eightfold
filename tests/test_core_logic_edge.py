"""Edge cases across resolve / merge / confidence / projection.

Invariant-style: clusters/counts, "no crash", "missing -> null, never invented",
clamps hold. Genuine limitations (shared email merges two people) are pinned with
a comment so the test documents behavior rather than asserting it is correct.
"""

from datetime import date

import pytest

from candidate_pipeline.confidence.scorer import clamp01, recency_factor
from candidate_pipeline.config.schema import FieldSpec, ProjectionConfig
from candidate_pipeline.merge.engine import MergeEngine, _to_month_index
from candidate_pipeline.models.source_record import (
    SourceExperience,
    SourceRecord,
    SourceValue,
)
from candidate_pipeline.project.projector import project
from candidate_pipeline.resolve.identity import IdentityResolver, name_block_key


def _rec(source, name=None, email=None, login=None, phone=None):
    return SourceRecord(
        source_name=source,
        record_id=email or login or name or "rec",
        full_name=SourceValue(value=name, raw=name, method="x") if name else None,
        emails=[SourceValue(value=email, raw=email, method="x")] if email else [],
        github_login=SourceValue(value=login, raw=login, method="x") if login else None,
        phones=[SourceValue(value=phone, raw=phone, method="x")] if phone else [],
    )


# ---- identity --------------------------------------------------------------

def test_login_case_difference_still_links():
    recs = [
        _rec("github_api", "Sri Krishna", login="Sri-Krishna"),
        _rec("ats_json", "Sri Krishna", login="sri-krishna"),
    ]
    assert len(IdentityResolver().resolve(recs)) == 1


def test_unicode_name_block_key_is_accent_folded():
    # accents are folded so the same name in two encodings blocks together
    assert name_block_key("José Núñez") == name_block_key("Jose Nunez")


def test_record_with_no_name_links_by_email_only():
    recs = [
        _rec("recruiter_csv", name=None, email="x@e.com"),
        _rec("ats_json", name="Has Name", email="x@e.com"),
    ]
    assert len(IdentityResolver().resolve(recs)) == 1


def test_transitive_linking_unions_through_a_bridge():
    # A~B share email, B~C share login, A and C share nothing directly.
    recs = [
        _rec("recruiter_csv", "A Person", email="bridge@e.com"),
        _rec("ats_json", "B Person", email="bridge@e.com", login="bridgelogin"),
        _rec("github_api", "C Person", login="bridgelogin"),
    ]
    clusters = IdentityResolver().resolve(recs)
    assert len(clusters) == 1 and len(clusters[0]) == 3


def test_shared_email_merges_two_people_known_limitation():
    # KNOWN LIMITATION: a shared inbox links two different people into one cluster.
    # Pinned to document current behavior; disambiguation is deliberately descoped.
    recs = [
        _rec("github_api", "Alice Different", email="shared@e.com"),
        _rec("github_api", "Bob Unrelated", email="shared@e.com"),
    ]
    assert len(IdentityResolver().resolve(recs)) == 1


# ---- confidence ------------------------------------------------------------

@pytest.mark.parametrize("x,expected", [(-0.5, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (1.5, 1.0)])
def test_clamp01_bounds(x, expected):
    assert clamp01(x) == expected


def test_recency_with_none_as_of_does_not_crash():
    assert recency_factor("2020-01-01T00:00:00Z", None, True) == 1.0


def test_recency_future_timestamp_does_not_increase_confidence():
    # last_updated AFTER as_of -> no negative staleness -> factor stays 1.0
    assert recency_factor("2030-01-01T00:00:00Z", date(2026, 6, 30), True) == 1.0


# ---- merge -----------------------------------------------------------------

def _merge_one(rec):
    return MergeEngine(as_of=date(2026, 6, 30)).merge([rec])


def test_single_record_cluster_has_base_confidence_no_conflict():
    p = _merge_one(_rec("ats_json", "Solo Person", email="solo@e.com"))
    assert p.full_name.value == "Solo Person"
    assert p.full_name.confidence == pytest.approx(0.90)  # ATS base, no conflict
    assert not any(f.kind == "conflict_resolved" for f in p.flags)


def test_all_empty_cluster_produces_profile_without_crashing():
    p = _merge_one(_rec("github_api", name=None))
    assert p.candidate_id.startswith("cand_")
    assert p.full_name is None
    assert p.overall_confidence == 0.0  # nothing to score, never invented


def test_to_month_index_is_safe_on_garbage():
    assert _to_month_index("2020-03", date(2026, 6, 30)) == 2020 * 12 + 3
    assert _to_month_index("garbage", date(2026, 6, 30)) is None
    assert _to_month_index("", date(2026, 6, 30)) is None


def test_years_experience_skips_unparseable_interval_without_crashing():
    rec = SourceRecord(
        source_name="ats_json",
        record_id="r",
        full_name=SourceValue(value="Dates", method="x"),
        experience=[
            SourceExperience(
                company=SourceValue(value="Acme", method="x"),
                start=SourceValue(value="not-a-date", method="x"),
                end=SourceValue(value="2021", method="x"),
            )
        ],
    )
    p = _merge_one(rec)
    assert p.years_experience is None  # unparseable interval skipped, not invented


# ---- projection ------------------------------------------------------------

@pytest.mark.parametrize("bad_path", ["emails[abc]", "full_name..value", "full_name.", "emails[-1]", "emails[99]"])
def test_malformed_or_oob_path_is_missing_not_crash(built_profiles, bad_path):
    profiles, _ = built_profiles
    cfg = ProjectionConfig(
        on_missing="null", fields=[FieldSpec(path="x", from_=bad_path, type="string")]
    )
    out = project(profiles["Aisha Khan"], cfg)
    assert out["x"] is None  # gracefully missing, never raised


def test_unknown_normalize_assertion_is_lenient(built_profiles):
    # An unrecognized normalize name passes leniently (forward-compatible).
    profiles, _ = built_profiles
    cfg = ProjectionConfig(
        fields=[FieldSpec(path="full_name", type="string", normalize="not-a-real-format")]
    )
    out = project(profiles["Aisha Khan"], cfg)
    assert out["full_name"] == "Aisha Khan"
