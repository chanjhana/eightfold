"""Minimal path resolver (PRD §11.2). No JSONPath dependency.

Supported forms (composable across dotted segments):
  field
  field.subfield
  field[].subfield   (maps over a list)
  field[N]           (index into a list)

Operates on a plain-dict "view" of the canonical profile (built by the projector),
where tracked values are dicts like {"value": ..., "confidence": ..., "sources": [...]}.
"""

from __future__ import annotations

import re

_MISSING = object()

_SEGMENT = re.compile(r"^(?P<name>[^.\[\]]+)(?:\[(?P<idx>\d*)\])?$")


def _parse(path: str):
    segments = []
    for raw in path.split("."):
        m = _SEGMENT.match(raw)
        if not m:
            return None
        name = m.group("name")
        idx = m.group("idx")
        if idx is None:
            segments.append((name, None))  # plain key
        elif idx == "":
            segments.append((name, "MAP"))  # field[] -> map over list
        else:
            segments.append((name, int(idx)))  # field[N]
    return segments


def resolve(view, path: str):
    """Return the resolved node, or _MISSING if any step is absent."""
    segments = _parse(path)
    if segments is None:
        return _MISSING

    current = view
    for name, op in segments:
        current = _step(current, name, op)
        if current is _MISSING:
            return _MISSING
    return current


def is_missing(value) -> bool:
    return value is _MISSING


def _get(node, name):
    if isinstance(node, dict) and name in node:
        return node[name]
    return _MISSING


def _step(current, name, op):
    if op == "MAP":
        # map over the list at `name`, returning the list itself; the *next*
        # segment (if any) is applied per-element by _step_map via marker.
        container = _get(current, name)
        if container is _MISSING or not isinstance(container, list):
            return _MISSING
        return _MappedList(container)

    if isinstance(current, _MappedList):
        # apply this segment to each element of the mapped list
        out = []
        for el in current.items:
            v = _step(el, name, op)
            if v is not _MISSING:
                out.append(v)
        return out

    value = _get(current, name)
    if value is _MISSING:
        return _MISSING
    if op is None:
        return value
    if isinstance(op, int):
        if isinstance(value, list) and 0 <= op < len(value):
            return value[op]
        return _MISSING
    return _MISSING


class _MappedList:
    """Marker wrapper: a list awaiting a per-element subfield access."""

    def __init__(self, items):
        self.items = items
