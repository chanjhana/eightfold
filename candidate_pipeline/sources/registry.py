"""Maps CLI --inputs keys to adapter classes (PRD §5)."""

from __future__ import annotations

from candidate_pipeline.models.report import RunReport
from candidate_pipeline.sources.ats_json import AtsJsonAdapter
from candidate_pipeline.sources.base import SourceAdapter
from candidate_pipeline.sources.github_api import GithubApiAdapter
from candidate_pipeline.sources.recruiter_csv import RecruiterCsvAdapter
from candidate_pipeline.sources.resume_pdf import ResumePdfAdapter

REGISTRY: dict[str, type[SourceAdapter]] = {
    "csv": RecruiterCsvAdapter,
    "ats": AtsJsonAdapter,
    "github": GithubApiAdapter,
    "resume": ResumePdfAdapter,
}


def build_adapter(
    key: str,
    report: RunReport | None = None,
    default_region: str | None = None,
    live: bool = False,
) -> SourceAdapter:
    # A key may carry an optional ":label" so several files of the same type can
    # be ingested in one run (e.g. "csv:primary", "csv:backfill"). The label only
    # disambiguates the input map; the base before ":" selects the adapter.
    base = key.split(":", 1)[0]
    try:
        cls = REGISTRY[base]
    except KeyError:
        raise ValueError(f"unknown source key '{key}'; known: {sorted(REGISTRY)}") from None
    if cls is GithubApiAdapter:
        return cls(report=report, default_region=default_region, live=live)
    return cls(report=report, default_region=default_region)
