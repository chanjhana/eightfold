"""End-to-end torture run over ALL edge fixtures at once.

This does NOT compare against a frozen golden (the edge data is meant to evolve);
it asserts the durable invariants a robust batch must hold no matter what we throw
at it:
  1. the run never raises and never whole-source-skips a valid file;
  2. one poison record is skipped + audited, the rest survive;
  3. every emitted profile validates against the requested schema;
  4. nothing is fabricated (no out-of-range month leaks through);
  5. the run is deterministic (same inputs -> identical output).
"""

import json
from datetime import date
from pathlib import Path

import candidate_pipeline
from candidate_pipeline.config.loader import DEFAULT_CONFIG
from candidate_pipeline.pipeline import run_pipeline
from candidate_pipeline.project.validator import build_output_model, validate_output

_EDGE = Path(candidate_pipeline.__file__).parent / "data" / "fixtures" / "edge"


def _inputs():
    return {
        "csv:messy": str(_EDGE / "recruiter_messy.csv"),
        "csv:poison": str(_EDGE / "recruiter_poison.csv"),
        "ats:messy": str(_EDGE / "ats_messy.json"),
        "ats:single": str(_EDGE / "ats_single.json"),
        "github": str(_EDGE / "github_messy.json"),
    }


def _run():
    return run_pipeline(_inputs(), DEFAULT_CONFIG, default_region="IN", as_of=date(2026, 6, 30))


def test_torture_run_survives_and_skips_nothing_wholesale():
    outputs, _profiles, report = _run()
    assert outputs  # produced profiles
    # no VALID file was skipped wholesale (every input is a real, readable file)
    assert [s for s in report.skips if s.stage.startswith("adapter:")] == []
    # but at least one poison record WAS skipped + audited
    assert report.counts["records_skipped"] >= 1
    assert any(s.stage.startswith("record:") for s in report.skips)


def test_every_emitted_profile_validates_against_schema():
    outputs, _profiles, _report = _run()
    model = build_output_model(DEFAULT_CONFIG)
    for o in outputs:
        validate_output(o, model)  # raises if any profile violates the schema


def test_no_fabricated_month_leaks_through():
    # "2020-13" in the messy ATS fixture must never appear as a real month.
    outputs, _profiles, _report = _run()
    blob = json.dumps(outputs)
    assert "2020-13" not in blob


def test_torture_run_is_deterministic():
    out1, _p1, _r1 = _run()
    out2, _p2, _r2 = _run()
    assert json.dumps(out1, sort_keys=True) == json.dumps(out2, sort_keys=True)
