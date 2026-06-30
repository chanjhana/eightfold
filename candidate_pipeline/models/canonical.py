"""Canonical profile model with per-field provenance and confidence (PRD §10).

This is the canonical/projection boundary: nothing upstream of `CanonicalProfile`
knows the projection config exists.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ProvenanceEntry(BaseModel):
    """One source's contribution to a tracked value, raw + normalized."""

    source: str  # "ats_json" | "recruiter_csv" | "github_api"
    method: str  # see PRD §14 vocabulary, e.g. "csv:column", "normalize:e164"
    raw: Any | None = None  # pre-normalization value
    value: Any = None  # post-normalization value


class TrackedValue(BaseModel, Generic[T]):
    """A value plus its confidence, contributing sources, and provenance trail."""

    value: T | None = None
    confidence: float | None = None
    sources: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    competitors: list[Any] = Field(default_factory=list)  # values that lost a conflict


class Flag(BaseModel):
    """A per-profile note about something noteworthy that happened during merge."""

    kind: str  # "conflict_resolved" | "assumed_region" | "uncanonicalized_skill" | ...
    detail: str


class TrackedExperience(BaseModel):
    company: TrackedValue[str] | None = None
    title: TrackedValue[str] | None = None
    start: TrackedValue[str] | None = None  # "YYYY" | "YYYY-MM"
    end: TrackedValue[str] | None = None  # None == ongoing
    summary: TrackedValue[str] | None = None


class TrackedEducation(BaseModel):
    institution: TrackedValue[str] | None = None
    degree: TrackedValue[str] | None = None
    field: TrackedValue[str] | None = None
    end_year: TrackedValue[int] | None = None


class CanonicalProfile(BaseModel):
    candidate_id: str  # deterministic (hash of strongest stable anchor)
    full_name: TrackedValue[str] | None = None
    emails: list[TrackedValue[str]] = Field(default_factory=list)  # confidence-sorted
    phones: list[TrackedValue[str]] = Field(default_factory=list)  # confidence-sorted
    location: TrackedValue[dict] | None = None  # {city, region, country, raw}
    links: TrackedValue[dict] | None = None  # {linkedin, github, portfolio, other[]}
    headline: TrackedValue[str] | None = None  # time-varying (§9.3)
    skills: list[TrackedValue[str]] = Field(default_factory=list)
    experience: list[TrackedExperience] = Field(default_factory=list)
    education: list[TrackedEducation] = Field(default_factory=list)
    years_experience: float | None = None
    overall_confidence: float = 0.0
    flags: list[Flag] = Field(default_factory=list)
