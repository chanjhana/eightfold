"""Résumé parser + adapter units (PRD §18 promoted to a real source).

The parser is deterministic and heuristic: it recovers what it can and leaves the
rest absent — it never fabricates. PDF text extraction is covered in test_adapters.
"""

from candidate_pipeline.models.report import RunReport
from candidate_pipeline.sources.resume_pdf import ResumePdfAdapter, parse_resume_text

_CLEAN = """\
Aisha Khan
Senior Software Engineer
San Francisco, USA
aisha.khan@example.com | +1 415 555 2671

Technical Skills
Python, React, C++, Rust

Experience
Stripe — Senior Software Engineer (2021 - Present)
"""


def test_parse_clean_resume_extracts_all_lean_fields():
    p = parse_resume_text(_CLEAN)
    assert p["name"] == "Aisha Khan"
    assert p["headline"] == "Senior Software Engineer"
    assert p["location"] == "San Francisco, USA"
    assert p["emails"] == ["aisha.khan@example.com"]
    assert p["phones"] == ["+1 415 555 2671"]
    # skills stop at the next known section header ("Experience")
    assert p["skills"] == ["Python", "React", "C++", "Rust"]


def test_parse_inline_skills_label():
    p = parse_resume_text("Jane Roe\nSkills: Go, Python, COBOL\n")
    assert p["skills"] == ["Go", "Python", "COBOL"]


def test_parse_messy_degrades_without_fabricating():
    text = "=== CONTACT ===\n   jordan.q.dev@example.com\nSkills: Go\nrandom 12345 ###\n"
    p = parse_resume_text(text)
    assert p["emails"] == ["jordan.q.dev@example.com"]
    assert p["skills"] == ["Go"]
    # nothing recoverable -> absent, not invented
    assert p["name"] is None
    assert p["headline"] is None
    assert p["location"] is None
    assert p["phones"] == []


def test_parse_empty_text():
    p = parse_resume_text("")
    assert p == {"name": None, "emails": [], "phones": [], "headline": None,
                 "location": None, "skills": []}


def test_adapter_record_canonicalizes_and_flags_unknown_skill(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("Sam Lee\nSkills: reactjs, COBOL\nsam@example.com\n", encoding="utf-8")
    recs = ResumePdfAdapter(report=RunReport()).load(str(f))
    r = recs[0]
    skills = {s.value for s in r.skills}
    assert "React" in skills  # alias canonicalized
    assert "COBOL" in skills  # unknown kept verbatim
    assert any(fl.kind == "uncanonicalized_skill" for fl in r.flags)


def test_adapter_phone_without_country_code_uses_default_region(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("Priya N\nphone 98765 43210\npriya@example.com\n", encoding="utf-8")
    recs = ResumePdfAdapter(report=RunReport(), default_region="IN").load(str(f))
    r = recs[0]
    assert r.phones[0].value == "+919876543210"
    assert r.phones[0].method == "assume:default_region"
    assert any(fl.kind == "assumed_region" for fl in r.flags)


def test_adapter_empty_text_skips(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("   \n\n", encoding="utf-8")
    report = RunReport()
    recs = ResumePdfAdapter(report=report).load(str(f))
    assert recs == []
    assert any(s.stage == "adapter:resume_pdf" for s in report.skips)
