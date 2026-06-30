from pathlib import Path

import pytest

import candidate_pipeline

_FIXTURES = Path(candidate_pipeline.__file__).parent / "data" / "fixtures"
_CONFIGS = Path(candidate_pipeline.__file__).parent / "data" / "configs"


@pytest.fixture
def fixtures_dir() -> Path:
    return _FIXTURES


@pytest.fixture
def configs_dir() -> Path:
    return _CONFIGS


@pytest.fixture
def csv_path(fixtures_dir) -> str:
    return str(fixtures_dir / "recruiter.csv")


@pytest.fixture
def ats_path(fixtures_dir) -> str:
    return str(fixtures_dir / "ats.json")


@pytest.fixture
def github_path(fixtures_dir) -> str:
    return str(fixtures_dir / "github.json")


@pytest.fixture
def built_profiles(csv_path, ats_path, github_path):
    """Run adapters -> resolve -> merge over the fixtures; return {name: profile}.

    Pinned as_of so confidence/years are deterministic.
    """
    from datetime import date

    from candidate_pipeline.merge.engine import MergeEngine
    from candidate_pipeline.models.report import RunReport
    from candidate_pipeline.resolve.identity import IdentityResolver
    from candidate_pipeline.sources.registry import build_adapter

    report = RunReport()
    records = []
    records += build_adapter("csv", report=report, default_region="IN").load(csv_path)
    records += build_adapter("ats", report=report).load(ats_path)
    records += build_adapter("github", report=report).load(github_path)

    clusters = IdentityResolver().resolve(records)
    engine = MergeEngine(report=report, as_of=date(2026, 6, 30))
    profiles = [engine.merge(c) for c in clusters]
    by_name = {p.full_name.value: p for p in profiles if p.full_name}
    return by_name, report


def current_entry(profile):
    return next(
        (e for e in profile.experience if e.end is None or (e.end and e.end.value is None)),
        None,
    )
