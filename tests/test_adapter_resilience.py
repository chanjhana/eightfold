"""Adapter robustness (PRD: "a missing or garbage source must not crash the run").

The contract these pin is per-RECORD resilience and shape tolerance: one poison
record is skipped and logged, the rest survive; an odd top-level shape (a single
object, an explicit null nested value, a non-object array element) degrades
gracefully instead of dropping the whole source. Assertions are invariants
(counts, "no exception", "skip logged"), not memorized field values.
"""

from candidate_pipeline.models.report import RunReport
from candidate_pipeline.sources.ats_json import AtsJsonAdapter
from candidate_pipeline.sources.github_api import GithubApiAdapter
from candidate_pipeline.sources.recruiter_csv import RecruiterCsvAdapter


# ---- ATS JSON --------------------------------------------------------------

def test_ats_single_object_is_tolerated(edge_dir):
    # A top-level object (not an array) must still yield one record, not crash.
    report = RunReport()
    recs = AtsJsonAdapter(report=report).load(str(edge_dir / "ats_single.json"))
    assert len(recs) == 1
    assert recs[0].full_name.value == "Single Object"
    assert not [s for s in report.skips if s.stage.startswith("adapter:")]


def test_ats_messy_skips_bad_records_keeps_good(edge_dir):
    report = RunReport()
    recs = AtsJsonAdapter(report=report).load(str(edge_dir / "ats_messy.json"))
    # The top-level string entry is skipped per-record; the three objects survive.
    record_skips = [s for s in report.skips if s.stage == "record:ats_json"]
    assert len(record_skips) == 1
    assert len(recs) == 3
    # whole source NOT skipped — file-level adapter skip must be absent
    assert not [s for s in report.skips if s.stage.startswith("adapter:")]


def test_ats_null_nested_values_do_not_crash(edge_dir):
    # null candidate/employment/location and an experience-as-object are handled.
    report = RunReport()
    recs = AtsJsonAdapter(report=report).load(str(edge_dir / "ats_messy.json"))
    names = {r.full_name.value for r in recs if r.full_name}
    assert "Null Nested" in names  # the null-nested record was built, not dropped


def test_ats_out_of_range_month_is_not_fabricated(edge_dir):
    report = RunReport()
    recs = AtsJsonAdapter(report=report).load(str(edge_dir / "ats_messy.json"))
    bad = next(r for r in recs if r.full_name and r.full_name.value == "Bad Dates")
    # "2020-13" must not survive as a fake month anywhere in the record.
    starts = [e.start.value for e in bad.experience if e.start]
    assert "2020-13" not in starts


# ---- GitHub ----------------------------------------------------------------

def test_github_non_string_scalars_do_not_crash(edge_dir):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(str(edge_dir / "github_messy.json"))
    assert len(recs) == 4  # every object handled, none dropped
    # a numeric login is coerced to text; a list/dict name is treated as absent
    rec0 = recs[0]
    assert rec0.github_login.value == "12345"
    assert rec0.full_name is None  # ["Array","Name"] is not a usable name


def test_github_malformed_repos_do_not_crash(edge_dir):
    report = RunReport()
    recs = GithubApiAdapter(report=report).load(str(edge_dir / "github_messy.json"))
    assert len(recs) == 4  # malformed repos never drop the record
    rec0 = recs[0]
    skills = {s.value for s in rec0.skills}
    # "not-an-object" and the junk language(42) are skipped; only Rust survives
    assert skills == {"Rust"}
    # the junk-fork repo (fork "yes") is excluded; the one valid non-fork repo links
    assert rec0.link_hints.get("notable_repos") == ["https://github.com/x/real-one"]


def test_github_login_case_is_normalized_for_linking(edge_dir):
    from candidate_pipeline.resolve.identity import _login

    report = RunReport()
    recs = GithubApiAdapter(report=report).load(str(edge_dir / "github_messy.json"))
    mixed = next(r for r in recs if r.github_login and "Mixed" in str(r.github_login.value))
    assert _login(mixed) == "mixed-case-login"  # lower-cased so it links


# ---- CSV -------------------------------------------------------------------

def test_csv_bom_and_messy_headers_are_tolerated(edge_dir):
    # BOM + " Full_Name " / "PHONE" / mixed case must still map to canonical cols.
    report = RunReport()
    recs = RecruiterCsvAdapter(report=report, default_region="IN").load(
        str(edge_dir / "recruiter_messy.csv")
    )
    names = [r.full_name.value for r in recs if r.full_name and r.full_name.value]
    assert any(n and "Núñez" in n for n in names)  # unicode name parsed via BOM header
    assert not [s for s in report.skips if s.stage.startswith("adapter:")]


def test_csv_poison_row_does_not_drop_the_file(edge_dir):
    # A NUL-byte row must not abort the whole file — the good rows still load.
    report = RunReport()
    recs = RecruiterCsvAdapter(report=report, default_region="IN").load(
        str(edge_dir / "recruiter_poison.csv")
    )
    emails = {r.primary_email() for r in recs}
    assert "good.one@example.com" in emails
    assert "good.two@example.com" in emails
    # the whole source must not be skipped
    assert not [s for s in report.skips if s.stage.startswith("adapter:")]


def test_csv_messy_email_and_skill_cleanup(edge_dir):
    report = RunReport()
    recs = RecruiterCsvAdapter(report=report, default_region="IN").load(
        str(edge_dir / "recruiter_messy.csv")
    )
    # mailto: prefix stripped on one row, pipe/tab-separated skills split out
    all_emails = {e for r in recs for e in [r.primary_email()] if e}
    assert "jose@example.com" in all_emails  # was "mailto:jose@example.com"
    all_skills = {s.value for r in recs for s in r.skills}
    assert {"Vue.js", "Angular", "Rust"} <= all_skills  # "Vue|Angular; rust"
