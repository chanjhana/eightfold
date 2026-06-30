"""Projector (PRD §11.3): the ONLY config-aware component.

Per field: resolve `from` -> assert `normalize`/format (check only; mismatch =>
missing) -> apply on_missing -> gate confidence/provenance by include flags ->
emit under output key `path`. The top-level `provenance` aggregate (sentinel
source "@provenance") and `flags` (config include_flags) are built-in views.
"""

from __future__ import annotations

import re

from candidate_pipeline.config.schema import FieldSpec, ProjectionConfig
from candidate_pipeline.models.canonical import CanonicalProfile
from candidate_pipeline.project.resolver import is_missing, resolve

PROVENANCE_SENTINEL = "@provenance"


class ProjectionError(Exception):
    """Raised for a required/error field that is missing."""


# ---- view construction -----------------------------------------------------

def _tv(tv):
    if tv is None:
        return None
    return {
        "value": tv.value,
        "confidence": tv.confidence,
        "sources": list(tv.sources),
        "provenance": [pe.model_dump() for pe in tv.provenance],
    }


def _skill(tv):
    node = _tv(tv)
    if node is None:
        return None
    node["name"] = node.pop("value")
    return node


def _exp(e):
    return {
        "company": _tv(e.company),
        "title": _tv(e.title),
        "start": _tv(e.start),
        "end": _tv(e.end),
        "summary": _tv(e.summary),
    }


def _edu(ed):
    return {
        "institution": _tv(ed.institution),
        "degree": _tv(ed.degree),
        "field": _tv(ed.field),
        "end_year": _tv(ed.end_year),
    }


def _build_view(p: CanonicalProfile) -> dict:
    return {
        "candidate_id": p.candidate_id,
        "full_name": _tv(p.full_name),
        "emails": [_tv(e) for e in p.emails],
        "phones": [_tv(ph) for ph in p.phones],
        "location": _tv(p.location),
        "links": _tv(p.links),
        "headline": _tv(p.headline),
        "skills": [_skill(s) for s in p.skills],
        "experience": [_exp(e) for e in p.experience],
        "education": [_edu(ed) for ed in p.education],
        "repos": [
            {"name": r.name, "language": r.language, "stars": r.stars, "url": r.url}
            for r in p.repos
        ],
        "years_experience": p.years_experience,
        "overall_confidence": p.overall_confidence,
    }


# ---- normalize assertion (check only, never recompute) ---------------------

def _assert_format(value, normalize: str | None) -> bool:
    if not normalize:
        return True
    if not isinstance(value, str):
        return False
    if normalize == "E164":
        return bool(re.match(r"^\+\d{7,15}$", value))
    if normalize == "iso3166-a2":
        return bool(re.match(r"^[A-Z]{2}$", value))
    if normalize == "canonical":
        from candidate_pipeline.normalize.skills import canonicalize_skill

        r = canonicalize_skill(value)
        return r.is_canonical and r.value == value
    return True  # unknown assertion name: lenient pass


# ---- leaf helpers ----------------------------------------------------------

def _leaf_value(node):
    if isinstance(node, dict):
        if "value" in node:
            return node["value"]
        if "name" in node:
            return node["name"]
    return node


def _is_scalar_tracked(node) -> bool:
    return (
        isinstance(node, dict)
        and ("value" in node or "name" in node)
        and "confidence" in node
        and "sources" in node
    )


# ---- shaping ---------------------------------------------------------------

def _shape(resolved, spec: FieldSpec):
    """Return (present, value)."""
    if is_missing(resolved):
        return False, None
    t = spec.type

    if t in ("string", "number"):
        base = _leaf_value(resolved)
        if base is None or not _assert_format(base, spec.normalize):
            return False, None
        if spec.include_confidence or spec.include_provenance:
            out = {"value": base}
            if spec.include_confidence:
                out["confidence"] = resolved.get("confidence") if isinstance(resolved, dict) else None
            if spec.include_provenance:
                out["provenance"] = resolved.get("provenance") if isinstance(resolved, dict) else None
            return True, out
        return True, base

    if t == "string[]":
        items = resolved if isinstance(resolved, list) else [resolved]
        vals = []
        for it in items:
            v = _leaf_value(it)
            if v is None or not _assert_format(v, spec.normalize):
                continue
            vals.append(v)
        return True, vals

    if t == "object":
        base = _leaf_value(resolved)
        if base is None:
            return False, None
        if spec.include_confidence or spec.include_provenance:
            out = dict(base) if isinstance(base, dict) else {"value": base}
            if spec.include_confidence and isinstance(resolved, dict):
                out["confidence"] = resolved.get("confidence")
            if spec.include_provenance and isinstance(resolved, dict):
                out["provenance"] = resolved.get("provenance")
            return True, out
        return True, base

    if t == "object[]":
        items = resolved if isinstance(resolved, list) else [resolved]
        return True, [_shape_object_element(it, spec) for it in items]

    return False, None


def _shape_object_element(node, spec: FieldSpec):
    if _is_scalar_tracked(node):
        label = "name" if "name" in node else "value"
        out = {label: node[label], "confidence": node.get("confidence"), "sources": node.get("sources")}
        if spec.include_provenance:
            out["provenance"] = node.get("provenance")
        return out
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if isinstance(v, dict) and "value" in v:
                out[k] = {"value": v["value"], "confidence": v.get("confidence")} if spec.include_confidence else v["value"]
            else:
                out[k] = v
        return out
    return node


# ---- provenance aggregate (built-in view) ----------------------------------

def _provenance_aggregate(p: CanonicalProfile) -> list[dict]:
    rows: list[dict] = []

    def add(field: str, tv):
        if tv:
            for pe in tv.provenance:
                rows.append({"field": field, "source": pe.source, "method": pe.method})

    add("full_name", p.full_name)
    for e in p.emails:
        add("emails", e)
    for ph in p.phones:
        add("phones", ph)
    add("location", p.location)
    add("headline", p.headline)
    for s in p.skills:
        add("skills", s)
    for ex in p.experience:
        for fld in ("company", "title", "start", "end", "summary"):
            add(f"experience.{fld}", getattr(ex, fld))
    for ed in p.education:
        for fld in ("institution", "degree", "field", "end_year"):
            add(f"education.{fld}", getattr(ed, fld))

    seen, out = set(), []
    for r in rows:
        key = (r["field"], r["source"], r["method"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


# ---- entry point -----------------------------------------------------------

def project(profile: CanonicalProfile, config: ProjectionConfig) -> dict:
    view = _build_view(profile)
    out: dict = {}

    for spec in config.fields:
        if spec.source == PROVENANCE_SENTINEL:
            out[spec.path] = _provenance_aggregate(profile)
            continue

        resolved = resolve(view, spec.source)
        present, value = _shape(resolved, spec)

        if not present:
            effective = spec.on_missing or config.on_missing
            if spec.required or effective == "error":
                raise ProjectionError(
                    f"missing required field '{spec.path}' (from '{spec.source}')"
                )
            if effective == "omit":
                continue
            out[spec.path] = None
            continue

        out[spec.path] = value

    if config.include_flags:
        out["flags"] = [{"kind": f.kind, "detail": f.detail} for f in profile.flags]

    return out
