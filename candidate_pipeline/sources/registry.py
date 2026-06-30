"""Maps CLI --inputs keys to adapter classes (PRD §5)."""

from __future__ import annotations

from candidate_pipeline.models.report import RunReport
from candidate_pipeline.sources.ats_json import AtsJsonAdapter
from candidate_pipeline.sources.base import SourceAdapter
from candidate_pipeline.sources.github_api import GithubApiAdapter
from candidate_pipeline.sources.recruiter_csv import RecruiterCsvAdapter

REGISTRY: dict[str, type[SourceAdapter]] = {
    "csv": RecruiterCsvAdapter,
    "ats": AtsJsonAdapter,
    "github": GithubApiAdapter,
}


def build_adapter(
    key: str,
    report: RunReport | None = None,
    default_region: str | None = None,
    live: bool = False,
) -> SourceAdapter:
    try:
        cls = REGISTRY[key]
    except KeyError:
        raise ValueError(f"unknown source key '{key}'; known: {sorted(REGISTRY)}") from None
    if cls is GithubApiAdapter:
        return cls(report=report, default_region=default_region, live=live)
    return cls(report=report, default_region=default_region)
