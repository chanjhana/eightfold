"""Identity resolution: blocking + linking (PRD §7, edge case §15 #2)."""

from candidate_pipeline.models.source_record import SourceRecord, SourceValue
from candidate_pipeline.resolve.identity import IdentityResolver, name_block_key


def _rec(source, name, email=None, login=None, phone=None):
    return SourceRecord(
        source_name=source,
        record_id=email or login or name,
        full_name=SourceValue(value=name, raw=name, method="x"),
        emails=[SourceValue(value=email, raw=email, method="x")] if email else [],
        github_login=SourceValue(value=login, raw=login, method="x") if login else None,
        phones=[SourceValue(value=phone, raw=phone, method="x")] if phone else [],
    )


def test_name_block_key_collapses_variants():
    assert name_block_key("Sri Krishna V") == "ksv"
    assert name_block_key("Sri Krishna Vijayarajan") == "ksv"
    assert name_block_key("V, Sri K.") == "ksv"


def test_name_variants_collapse_to_one_cluster():
    # Same person, name variants, NO shared email (edge #2). Two share a phone.
    recs = [
        _rec("recruiter_csv", "Sri Krishna V", email="sri.k@personal.com", phone="+919876543210"),
        _rec("ats_json", "Sri Krishna Vijayarajan", email="s.krishna@work.com", phone="+919876543210"),
        _rec("github_api", "V, Sri K.", login="sri-krishna"),
    ]
    clusters = IdentityResolver().resolve(recs)
    assert len(clusters) == 1
    assert len(clusters[0]) == 3


def test_orphan_with_no_signal_stays_separate():
    recs = [
        _rec("recruiter_csv", "Sri Krishna V", email="sri.k@personal.com", phone="+919876543210"),
        _rec("github_api", "Pat Morgan", login="ghost-coder"),  # block "mp", no overlap
    ]
    clusters = IdentityResolver().resolve(recs)
    assert len(clusters) == 2


def test_same_block_but_different_person_not_merged():
    # "Kevin S Vaughn" also blocks to "ksv" but the name doesn't align and there
    # is no corroborating identifier -> must NOT merge into the Sri cluster.
    recs = [
        _rec("recruiter_csv", "Sri Krishna V", email="sri.k@personal.com"),
        _rec("recruiter_csv", "Kevin S Vaughn", email="kevin@other.com"),
    ]
    clusters = IdentityResolver().resolve(recs)
    assert len(clusters) == 2


def test_exact_email_links_outright_despite_name_difference():
    recs = [
        _rec("recruiter_csv", "Robert Smith", email="shared@example.com"),
        _rec("ats_json", "Bob Smith", email="shared@example.com"),
    ]
    clusters = IdentityResolver().resolve(recs)
    assert len(clusters) == 1


def test_exact_login_links_outright():
    recs = [
        _rec("github_api", "Some Name", login="octocat"),
        _rec("ats_json", "Totally Different", login="octocat"),
    ]
    clusters = IdentityResolver().resolve(recs)
    assert len(clusters) == 1
