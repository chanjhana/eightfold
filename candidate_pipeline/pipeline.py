"""Pipeline orchestration (PRD §3) — the only place stages are wired together.

inputs -> adapters -> SourceRecords -> IdentityResolver -> clusters ->
MergeEngine(+ConfidenceScorer) -> CanonicalProfiles -> Projector(+config) ->
validated dicts, with RunReport threaded throughout.
"""

from __future__ import annotations

from datetime import date

from candidate_pipeline.config.schema import ProjectionConfig
from candidate_pipeline.merge.engine import MergeEngine
from candidate_pipeline.models.canonical import CanonicalProfile
from candidate_pipeline.models.report import RunReport
from candidate_pipeline.project.projector import ProjectionError, project
from candidate_pipeline.project.validator import build_output_model, validate_output
from candidate_pipeline.resolve.identity import IdentityResolver
from candidate_pipeline.sources.registry import build_adapter


def resolve_and_merge(
    inputs: dict[str, str],
    report: RunReport,
    default_region: str | None = None,
    as_of: date | None = None,
    live: bool = False,
) -> list[CanonicalProfile]:
    records = []
    for key, path in inputs.items():
        adapter = build_adapter(key, report=report, default_region=default_region, live=live)
        records.extend(adapter.load(path))

    report.counts["records_in"] = len(records)
    report.counts["records_skipped"] = sum(1 for s in report.skips if s.stage.startswith("record:"))
    clusters = IdentityResolver().resolve(records)
    report.counts["clusters"] = len(clusters)

    engine = MergeEngine(report=report, as_of=as_of or date.today())
    profiles = [engine.merge(c) for c in clusters]
    profiles.sort(key=lambda p: p.candidate_id)  # deterministic ordering for goldens
    return profiles


def project_profiles(
    profiles: list[CanonicalProfile], config: ProjectionConfig, report: RunReport
) -> list[dict]:
    model = build_output_model(config)
    outputs: list[dict] = []
    for p in profiles:
        try:
            projected = project(p, config)
        except ProjectionError as exc:
            report.add_skip("projection", p.candidate_id, str(exc))
            continue
        try:
            validated = validate_output(projected, model)
        except Exception as exc:  # noqa: BLE001 - bad output skips the profile, batch continues
            report.add_skip("validation", p.candidate_id, str(exc))
            continue
        outputs.append(validated)

    report.counts["profiles_out"] = len(outputs)
    report.counts["sources_skipped"] = sum(1 for s in report.skips if s.stage.startswith("adapter:"))
    return outputs


def run_pipeline(
    inputs: dict[str, str],
    config: ProjectionConfig,
    default_region: str | None = None,
    as_of: date | None = None,
    live: bool = False,
) -> tuple[list[dict], list[CanonicalProfile], RunReport]:
    report = RunReport()
    profiles = resolve_and_merge(inputs, report, default_region=default_region, as_of=as_of, live=live)
    outputs = project_profiles(profiles, config, report)
    return outputs, profiles, report
