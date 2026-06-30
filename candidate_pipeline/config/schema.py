"""Projection config models (PRD §11.1).

`normalize` is ASSERT-ONLY: all normalization already happened upstream (§6), so
the projector verifies the value matches the named format and treats a mismatch
as missing — it never re-runs a normalizer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OutputType = Literal["string", "string[]", "number", "object", "object[]"]
OnMissing = Literal["null", "omit", "error"]


class FieldSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    path: str  # OUTPUT key
    from_: str | None = Field(default=None, alias="from")  # canonical SOURCE path
    type: OutputType = "string"
    required: bool = False
    normalize: str | None = None  # assertion only: "E164" | "canonical" | "iso3166-a2"
    on_missing: OnMissing | None = None  # overrides global
    include_confidence: bool = False
    include_provenance: bool = False

    @property
    def source(self) -> str:
        return self.from_ or self.path


class ProjectionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    on_missing: OnMissing = "null"  # global default
    include_flags: bool = False
    fields: list[FieldSpec]

    @model_validator(mode="after")
    def _validate_paths(self) -> "ProjectionConfig":
        seen: set[str] = set()
        for spec in self.fields:
            if not spec.path or not spec.path.strip():
                raise ValueError("field 'path' must be a non-empty string")
            if spec.path in seen:
                # a duplicate output path would silently overwrite the earlier
                # field (data loss) — reject it at load time instead.
                raise ValueError(f"duplicate output path '{spec.path}'")
            seen.add(spec.path)
        return self
