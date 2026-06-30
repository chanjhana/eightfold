"""A malformed source must not crash the batch (PRD §15 #3, §16).

The adapter try/except logs a SkipEntry; other sources still produce output.
"""

from datetime import date
from pathlib import Path

import candidate_pipeline
from candidate_pipeline.config.loader import DEFAULT_CONFIG
from candidate_pipeline.pipeline import run_pipeline


def _fix():
    return Path(candidate_pipeline.__file__).parent / "data" / "fixtures"


def test_malformed_source_skips_and_batch_continues(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{ this is not valid json :: ", encoding="utf-8")

    inputs = {
        "csv": str(_fix() / "recruiter.csv"),
        "ats": str(bad),  # malformed
        "github": str(_fix() / "github.json"),
    }
    outputs, _profiles, report = run_pipeline(
        inputs, DEFAULT_CONFIG, default_region="IN", as_of=date(2026, 6, 30)
    )

    # the bad source is skipped, not fatal
    assert any(s.stage == "adapter:ats_json" for s in report.skips)
    assert report.counts["sources_skipped"] >= 1
    # other sources still resolve into profiles
    assert outputs
    names = {o["full_name"] for o in outputs}
    assert "Aisha Khan" in names  # still resolved from CSV + GitHub


def test_completely_missing_file_does_not_crash(tmp_path):
    inputs = {
        "csv": str(_fix() / "recruiter.csv"),
        "ats": "no/such/file.json",
        "github": str(_fix() / "github.json"),
    }
    outputs, _profiles, report = run_pipeline(
        inputs, DEFAULT_CONFIG, default_region="IN", as_of=date(2026, 6, 30)
    )
    assert any(s.stage == "adapter:ats_json" for s in report.skips)
    assert outputs
