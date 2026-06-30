"""Source adapters load their fixtures into SourceRecords (PRD §5, milestone M4).

Robustness: a bad source never crashes — it logs a SkipEntry and returns [].
"""

from candidate_pipeline.models.report import RunReport
from candidate_pipeline.sources.recruiter_csv import RecruiterCsvAdapter
from candidate_pipeline.sources.ats_json import AtsJsonAdapter
from candidate_pipeline.sources.github_api import GithubApiAdapter
from candidate_pipeline.sources.registry import build_adapter


def test_csv_adapter_loads_records(csv_path):
    report = RunReport()
    recs = RecruiterCsvAdapter(report=report, default_region="IN").load(csv_path)
    assert len(recs) == 2
    assert all(r.source_name == "recruiter_csv" for r in recs)
    a = recs[0]
    assert a.full_name.value == "Aisha Khan"
    assert a.primary_email() == "aisha.khan@example.com"
    assert a.phones[0].value == "+14155552671"  # explicit country code
    skills = {s.value for s in a.skills}
    assert "React" in skills and "Node.js" in skills and "C++" in skills


def test_csv_adapter_applies_default_region_and_flags(csv_path):
    report = RunReport()
    recs = RecruiterCsvAdapter(report=report, default_region="IN").load(csv_path)
    b = recs[1]
    assert b.phones[0].value == "+919876543210"  # no CC -> default region applied
    assert b.phones[0].method == "assume:default_region"
    assert any(f.kind == "assumed_region" for f in b.flags)
    # COBOL is unknown -> kept verbatim, flagged
    assert any(s.value == "COBOL" for s in b.skills)
    assert any(f.kind == "uncanonicalized_skill" for f in b.flags)


def test_ats_adapter_maps_nested_fields(ats_path):
    report = RunReport()
    recs = AtsJsonAdapter(report=report).load(ats_path)
    assert len(recs) == 1
    a = recs[0]
    assert a.source_name == "ats_json"
    assert a.full_name.value == "Aisha Khan"
    assert a.current_company.value == "Stripe"
    assert len(a.experience) == 2
    current = [e for e in a.experience if e.end is None or e.end.value is None]
    assert current and current[0].company.value == "Stripe"
    # date normalization + granularity
    assert recs[0].experience[0].start.value == "2021-03"
    assert recs[0].experience[0].end is None or recs[0].experience[0].end.value is None
    assert recs[0].experience[1].start.value == "2018"  # year-only preserved
    assert len(a.education) == 1
    assert a.last_updated == "2025-01-15T00:00:00Z"


def test_github_adapter_loads_and_marks_orphan(github_path):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(github_path)
    assert len(recs) == 4
    by_login = {r.github_login.value: r for r in recs}
    assert by_login["aishakhan"].primary_email() == "aisha.khan@example.com"
    # orphan: no email
    assert by_login["ghost-coder"].primary_email() is None
    assert by_login["aishakhan"].headline.value  # bio -> headline


def test_github_live_flag_is_noop(github_path):
    report = RunReport()
    recs = GithubApiAdapter(report=report, live=True).load(github_path)
    assert len(recs) == 4  # --live defaults to the fixture, never hits network


def test_github_repo_languages_become_canonical_skills(github_path):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(github_path)
    by_login = {r.github_login.value: r for r in recs}
    aisha_skills = {s.value for s in by_login["aishakhan"].skills}
    # non-fork repo languages canonicalize through the shared alias map
    assert {"Go", "Python"} <= aisha_skills
    # the Shell repo is a fork -> excluded from languages
    assert "Shell" not in aisha_skills


def test_github_forks_excluded_from_skills_and_links(github_path):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(github_path)
    by_login = {r.github_login.value: r for r in recs}
    # ghost-coder's only repo is a fork -> no languages, no notable repos
    ghost = by_login["ghost-coder"]
    assert ghost.skills == []
    assert "notable_repos" not in ghost.link_hints


def test_github_notable_repos_are_top_two_by_stars(github_path):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(github_path)
    by_login = {r.github_login.value: r for r in recs}
    # sri-krishna: 3 non-fork repos, top 2 by stars are the Go ones (230, 95)
    notable = by_login["sri-krishna"].link_hints["notable_repos"]
    assert notable == [
        "https://github.com/sri-krishna/distributed-scheduler",
        "https://github.com/sri-krishna/k8s-operators",
    ]


def test_github_raw_repos_populated_star_sorted_no_forks(github_path):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(github_path)
    by_login = {r.github_login.value: r for r in recs}
    aisha = by_login["aishakhan"]
    assert [(r.name, r.stars) for r in aisha.repos] == [
        ("payments-api", 142),
        ("checkout-service", 58),
    ]  # star-sorted, the fork (dotfiles) excluded
    # ghost-coder's only repo is a fork -> no repo entries
    assert by_login["ghost-coder"].repos == []


def test_github_live_success_overlays_api_data(monkeypatch, github_path):
    """--live replaces fixture data with the API response (parsed identically)."""
    def fake_api_get(endpoint):
        if endpoint.startswith("/users/") and "/repos" not in endpoint:
            return {"login": "aishakhan", "name": "Aisha (live)", "email": "live@example.com"}
        return [{"name": "live-repo", "language": "Rust", "fork": False,
                 "stargazers_count": 7, "html_url": "https://github.com/aishakhan/live-repo"}]

    monkeypatch.setattr(GithubApiAdapter, "_api_get", staticmethod(fake_api_get))
    report = RunReport()
    recs = GithubApiAdapter(report=report, live=True).load(github_path)
    by_login = {r.github_login.value: r for r in recs}
    aisha = by_login["aishakhan"]
    assert aisha.full_name.value == "Aisha (live)"  # live profile overlaid
    assert [r.name for r in aisha.repos] == ["live-repo"]  # live repos parsed
    assert any(s.value == "Rust" for s in aisha.skills)


def test_github_live_failure_falls_back_to_fixture(monkeypatch, github_path):
    """A live fetch error must not crash; the fixture record is used and logged."""
    def boom(endpoint):
        raise OSError("network down")

    monkeypatch.setattr(GithubApiAdapter, "_api_get", staticmethod(boom))
    report = RunReport()
    recs = GithubApiAdapter(report=report, live=True).load(github_path)
    assert len(recs) == 4  # never flakes
    by_login = {r.github_login.value: r for r in recs}
    assert by_login["aishakhan"].full_name.value == "Aisha Khan"  # fixture value
    assert any(s.stage == "github:live" for s in report.skips)  # honest about fallback


def test_bad_source_skips_not_crashes(tmp_path):
    report = RunReport()
    bad = tmp_path / "broken.json"
    bad.write_text("{ this is not valid json ", encoding="utf-8")
    recs = AtsJsonAdapter(report=report).load(str(bad))
    assert recs == []
    assert len(report.skips) == 1
    assert report.skips[0].stage == "adapter:ats_json"


def test_missing_file_skips_not_crashes():
    report = RunReport()
    recs = RecruiterCsvAdapter(report=report).load("does/not/exist.csv")
    assert recs == []
    assert len(report.skips) == 1


def test_registry_builds_adapters():
    report = RunReport()
    assert build_adapter("csv", report=report, default_region="IN").source_name == "recruiter_csv"
    assert build_adapter("ats", report=report).source_name == "ats_json"
    assert build_adapter("github", report=report).source_name == "github_api"
