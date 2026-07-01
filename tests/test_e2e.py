"""End-to-end run compared against golden JSON (PRD §16). Deterministic via
fixed --as-of and the stable candidate_id."""

import json
from datetime import date
from pathlib import Path

import candidate_pipeline
from candidate_pipeline.config.loader import DEFAULT_CONFIG
from candidate_pipeline.pipeline import run_pipeline

_GOLDEN = Path(__file__).parent / "golden"


def _roundtrip(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


def _inputs():
    fix = Path(candidate_pipeline.__file__).parent / "data" / "fixtures"
    return {
        "csv": str(fix / "recruiter.csv"),
        "ats": str(fix / "ats.json"),
        "github": str(fix / "github.json"),
        "resume": str(fix / "resume.pdf"),
    }


def test_e2e_output_matches_golden():
    outputs, _profiles, _report = run_pipeline(
        _inputs(), DEFAULT_CONFIG, default_region="IN", as_of=date(2026, 6, 30)
    )
    golden = json.loads((_GOLDEN / "profiles_default.json").read_text(encoding="utf-8"))
    assert _roundtrip(outputs) == golden


def test_e2e_canonical_matches_golden():
    _outputs, profiles, _report = run_pipeline(
        _inputs(), DEFAULT_CONFIG, default_region="IN", as_of=date(2026, 6, 30)
    )
    canonical = [p.model_dump(mode="json") for p in profiles]
    golden = json.loads((_GOLDEN / "canonical.json").read_text(encoding="utf-8"))
    assert _roundtrip(canonical) == golden


def test_e2e_resolves_one_profile_per_person():
    outputs, _profiles, report = run_pipeline(
        _inputs(), DEFAULT_CONFIG, default_region="IN", as_of=date(2026, 6, 30)
    )
    # 8 source records -> 4 resolved people (A=4 incl. résumé, B=2, C=1, orphan=1)
    assert report.counts["records_in"] == 8
    assert report.counts["profiles_out"] == 4
    names = {o["full_name"] for o in outputs}
    assert {"Aisha Khan", "Sri Krishna V", "Jordan Lee", "Pat Morgan"} == names
