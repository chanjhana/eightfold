"""Merge engine (PRD §8): conflicts resolve by trust, with expected confidence."""

import pytest


def current_entry(profile):
    return next(
        (e for e in profile.experience if e.end is None or (e.end and e.end.value is None)),
        None,
    )


def test_company_conflict_picks_trusted_winner_with_confidence(built_profiles):
    profiles, report = built_profiles
    # B: ATS absent; CSV (Infosys) vs GitHub (Google). CSV trust 0.80 > GitHub 0.70.
    b = profiles["Sri Krishna V"]
    cur = current_entry(b)
    assert cur.company.value == "Infosys"
    assert cur.company.confidence == pytest.approx(0.75, abs=1e-6)  # 0.80 - conflict 0.05
    assert "Google" in cur.company.competitors
    assert any(f.kind == "conflict_resolved" for f in b.flags)
    assert any(c.field == "current_company" and c.winner == "Infosys" for c in report.conflicts)


def test_ats_outranks_csv_company_conflict(built_profiles):
    profiles, _ = built_profiles
    # A: ATS (Stripe) beats CSV (Shopify); GitHub corroborates Stripe.
    a = profiles["Aisha Khan"]
    cur = current_entry(a)
    assert cur.company.value == "Stripe"
    assert "Shopify" in cur.company.competitors


def test_multi_valued_skills_union_and_canonicalized(built_profiles):
    profiles, _ = built_profiles
    a = profiles["Aisha Khan"]
    skills = {s.value: s.confidence for s in a.skills}
    # aliases applied, C++/C#/.NET preserved intact
    assert {"React", "Node.js", "Python", "C++", "C#", ".NET", "PostgreSQL", "Rust"} <= set(skills)
    # Python is now a 4-source skill: ATS + CSV + GitHub repo + résumé. Corroboration
    # from 3 additional agreeing sources exceeds the +0.10 cap -> 0.90 + 0.10 = 1.00.
    assert skills["Python"] == pytest.approx(1.00, abs=1e-6)
    # Rust comes only from the résumé (canonical alias, structured skill list) -> 0.75
    assert skills["Rust"] == pytest.approx(0.75, abs=1e-6)
    # Go comes only from Aisha's GitHub repos (canonical alias) -> 0.70
    assert skills["Go"] == pytest.approx(0.70, abs=1e-6)
    # C++ only in CSV (canonical, structured) -> 0.80
    assert skills["C++"] == pytest.approx(0.80, abs=1e-6)


def test_repos_surface_on_canonical_profile(built_profiles):
    profiles, _ = built_profiles
    a = profiles["Aisha Khan"]
    # candidate's own (non-fork) repos, star-sorted, on the canonical profile
    assert [(r.name, r.language, r.stars) for r in a.repos] == [
        ("payments-api", "Go", 142),
        ("checkout-service", "Python", 58),
    ]
    # and their URLs surfaced as profile links
    assert a.links.value["other"] == [
        "https://github.com/aishakhan/payments-api",
        "https://github.com/aishakhan/checkout-service",
    ]
    # Pat Morgan's only repo is a fork -> no repos, no repo links
    pat = profiles["Pat Morgan"]
    assert pat.repos == []


def test_resume_is_a_fourth_source_and_outranks_github_on_headline(built_profiles):
    profiles, _ = built_profiles
    a = profiles["Aisha Khan"]
    # the résumé joins Aisha's cluster as a 4th source
    assert "resume_pdf" in a.full_name.sources
    # headline: résumé (trust 0.75) beats the GitHub bio (0.70); bio becomes a competitor
    assert a.headline.value == "Senior Software Engineer"
    assert a.headline.sources == ["resume_pdf"]
    assert any("Payments" in str(c) for c in a.headline.competitors)


def test_emails_union_confidence_sorted(built_profiles):
    profiles, _ = built_profiles
    a = profiles["Aisha Khan"]
    confs = [e.confidence for e in a.emails]
    assert confs == sorted(confs, reverse=True)
    assert a.emails[0].value == "aisha.khan@example.com"


def test_years_experience_merged_interval(built_profiles):
    profiles, _ = built_profiles
    a = profiles["Aisha Khan"]
    # Shopify 2018-01..2021-02 + Stripe 2021-03..2026-06 (as_of) ~ 8.33y
    assert a.years_experience == pytest.approx(8.33, abs=0.1)


def test_candidate_id_is_deterministic(built_profiles, csv_path, ats_path, github_path):
    from datetime import date

    from candidate_pipeline.merge.engine import MergeEngine
    from candidate_pipeline.models.report import RunReport
    from candidate_pipeline.resolve.identity import IdentityResolver
    from candidate_pipeline.sources.registry import build_adapter

    profiles, _ = built_profiles
    report = RunReport()
    records = []
    records += build_adapter("csv", report=report, default_region="IN").load(csv_path)
    records += build_adapter("ats", report=report).load(ats_path)
    records += build_adapter("github", report=report).load(github_path)
    clusters = IdentityResolver().resolve(records)
    engine = MergeEngine(report=report, as_of=date(2026, 6, 30))
    rerun = {p.full_name.value: p.candidate_id for p in (engine.merge(c) for c in clusters) if p.full_name}
    assert rerun["Aisha Khan"] == profiles["Aisha Khan"].candidate_id


def test_assumed_region_flag_and_assumption(built_profiles):
    profiles, report = built_profiles
    b = profiles["Sri Krishna V"]
    assert b.phones[0].value == "+919876543210"
    assert any(f.kind == "assumed_region" for f in b.flags)
    assert any(a.field == "phone" for a in report.assumptions)
