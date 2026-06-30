"""Dynamic output validation (PRD §11.4).

Build a Pydantic model from the config via create_model (each field's type comes
from FieldSpec.type) and validate the projected dict. A profile that fails
validation is skipped by the pipeline (a SkipEntry is logged), batch continues.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import ConfigDict, create_model

from candidate_pipeline.config.schema import FieldSpec, ProjectionConfig

_BASE_TYPE = {
    "string": str,
    "number": float,
    "string[]": list,
    "object": dict,
    "object[]": list,
}


def _field_type(spec: FieldSpec):
    # include flags wrap a scalar into an object
    if spec.type in ("string", "number") and (spec.include_confidence or spec.include_provenance):
        return dict
    return _BASE_TYPE[spec.type]


def build_output_model(config: ProjectionConfig):
    fields: dict[str, tuple] = {}
    for spec in config.fields:
        t = _field_type(spec)
        if spec.required:
            fields[spec.path] = (t, ...)
        else:
            fields[spec.path] = (Optional[t], None)
    if config.include_flags:
        fields["flags"] = (list, [])
    return create_model(
        "ProjectedProfile",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )


def validate_output(out: dict, model) -> dict[str, Any]:
    obj = model.model_validate(out)
    return obj.model_dump()
