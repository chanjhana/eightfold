"""SourceRecord: the normalized, per-source intermediate (PRD §5/§6).

Every field carries the raw value alongside the normalized one so the merge
engine can record both in provenance. One SourceRecord == one raw record from
one source, after normalization.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from candidate_pipeline.models.canonical import Flag


class SourceValue(BaseModel):
    """A single normalized field value carrying its raw form and provenance method."""

    value: Any | None = None  # post-normalization
    raw: Any | None = None  # pre-normalization
    method: str | None = None  # provenance method, e.g. "csv:column", "normalize:e164"


class SourceExperience(BaseModel):
    company: SourceValue | None = None
    title: SourceValue | None = None
    start: SourceValue | None = None  # "YYYY" | "YYYY-MM" | None (ongoing)
    end: SourceValue | None = None  # None == ongoing
    summary: SourceValue | None = None


class SourceEducation(BaseModel):
    institution: SourceValue | None = None
    degree: SourceValue | None = None
    field: SourceValue | None = None
    end_year: SourceValue | None = None


class SourceRecord(BaseModel):
    source_name: str  # "ats_json" | "recruiter_csv" | "github_api"
    record_id: str  # stable-ish identifier for skip/audit logging

    # identity
    full_name: SourceValue | None = None
    emails: list[SourceValue] = Field(default_factory=list)
    phones: list[SourceValue] = Field(default_factory=list)
    github_login: SourceValue | None = None

    # flat current employment (reconciled into current experience entry on merge)
    current_company: SourceValue | None = None
    current_title: SourceValue | None = None

    # rich fields
    location: SourceValue | None = None  # value is {city, region, country, raw}
    headline: SourceValue | None = None  # from prose (e.g. github bio)
    skills: list[SourceValue] = Field(default_factory=list)
    experience: list[SourceExperience] = Field(default_factory=list)
    education: list[SourceEducation] = Field(default_factory=list)

    # link hints (raw): {"github_login": ..., "blog": ..., "linkedin": ...}
    link_hints: dict = Field(default_factory=dict)

    last_updated: str | None = None  # ISO timestamp; drives recency decay (§9)

    # flags raised during this record's normalization (assumed_region,
    # uncanonicalized_skill); the merge engine lifts these onto the profile.
    flags: list[Flag] = Field(default_factory=list)

    def primary_email(self) -> str | None:
        for e in self.emails:
            if e.value:
                return str(e.value)
        return None
