"""Field-type merge strategies (PRD §8.2).

- single-valued: trust ranking -> winner; losing values retained as competitors.
- multi-valued: union + dedup, confidence-sorted.
These build TrackedValues and report whether a conflict occurred so the engine
can attach flags / RunReport entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from candidate_pipeline.confidence.scorer import (
    multi_valued_confidence,
    recency_factor,
    single_valued_confidence,
)
from candidate_pipeline.merge.trust import trust_of
from candidate_pipeline.models.canonical import ProvenanceEntry, TrackedValue


@dataclass
class Contribution:
    """One source's offer for a field (post-normalization)."""

    source: str
    value: Any
    raw: Any
    method: str
    is_prose: bool = False
    last_updated: str | None = None


def _str_key(v: Any) -> str:
    return str(v).strip().lower()


def _provenance(contribs: list[Contribution]) -> list[ProvenanceEntry]:
    return [
        ProvenanceEntry(source=c.source, method=c.method, raw=c.raw, value=c.value)
        for c in contribs
    ]


def merge_single_valued(
    contribs: list[Contribution],
    *,
    as_of,
    time_varying: bool,
    key_fn: Callable[[Any], Any] = _str_key,
) -> tuple[TrackedValue | None, bool]:
    """Highest-trust source wins; losers kept as competitors. Returns (tv, had_conflict)."""
    contribs = [c for c in contribs if c.value not in (None, "")]
    if not contribs:
        return None, False

    winner = max(contribs, key=lambda c: trust_of(c.source))
    winner_key = key_fn(winner.value)

    distinct_keys = {key_fn(c.value) for c in contribs}
    had_conflict = len(distinct_keys) >= 2

    agreeing_sources = sorted({c.source for c in contribs if key_fn(c.value) == winner_key})
    recency = recency_factor(winner.last_updated, as_of, time_varying)
    conf = single_valued_confidence(
        winner.source, agreeing_sources, winner.is_prose, had_conflict, recency
    )

    competitors: list[Any] = []
    seen = {winner_key}
    for c in contribs:
        k = key_fn(c.value)
        if k not in seen:
            competitors.append(c.value)
            seen.add(k)

    tv = TrackedValue(
        value=winner.value,
        confidence=conf,
        sources=agreeing_sources,
        provenance=_provenance(contribs),
        competitors=competitors,
    )
    return tv, had_conflict


def merge_multi_valued(
    contribs: list[Contribution],
    *,
    as_of,
    time_varying: bool,
    key_fn: Callable[[Any], Any] = _str_key,
) -> list[TrackedValue]:
    """Union + dedup; each value scored independently; confidence-sorted desc."""
    groups: dict[Any, list[Contribution]] = {}
    order: list[Any] = []
    for c in contribs:
        if c.value in (None, ""):
            continue
        k = key_fn(c.value)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(c)

    results: list[TrackedValue] = []
    for k in order:
        cs = groups[k]
        best = max(cs, key=lambda c: trust_of(c.source))
        agreeing_sources = sorted({c.source for c in cs})
        recency = recency_factor(best.last_updated, as_of, time_varying)
        conf = multi_valued_confidence(best.source, agreeing_sources, best.is_prose, recency)
        results.append(
            TrackedValue(
                value=best.value,
                confidence=conf,
                sources=agreeing_sources,
                provenance=_provenance(cs),
            )
        )

    results.sort(key=lambda t: (-(t.confidence or 0.0), str(t.value)))
    return results
