"""RunReport: batch-level audit trail, threaded through every stage (PRD §13).

Distinct from per-profile `flags`: this records what happened to the *batch*
(skips, conflicts, assumptions, counts).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkipEntry(BaseModel):
    stage: str  # "adapter:recruiter_csv" | "projection" | ...
    identifier: str  # record id / source path
    reason: str


class ConflictEntry(BaseModel):
    candidate_id: str
    field: str
    winner: Any
    losers: list[Any] = Field(default_factory=list)


class Assumption(BaseModel):
    candidate_id: str
    field: str
    assumption: str  # e.g. "default-region IN applied"


class RunReport(BaseModel):
    skips: list[SkipEntry] = Field(default_factory=list)
    conflicts: list[ConflictEntry] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)  # records_in, profiles_out, ...

    def add_skip(self, stage: str, identifier: str, reason: str) -> None:
        self.skips.append(SkipEntry(stage=stage, identifier=identifier, reason=reason))

    def bump(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount
