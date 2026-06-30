"""Confidence scoring constants and functions (PRD §9).

ALL confidence-tuning numbers live in this constants block. Scoring functions
are fleshed out in milestone M6; the constants are fixed contracts from the PRD.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Constants block (PRD §9 tables) — do not scatter these elsewhere.
# --------------------------------------------------------------------------

# base = winning source's trust (mirrors merge/trust.SOURCE_TRUST by design)
BASE_BY_SOURCE: dict[str, float] = {
    "ats_json": 0.90,
    "recruiter_csv": 0.80,
    "github_api": 0.70,
}

CORROBORATION_PER_SOURCE = 0.05  # per additional agreeing source
CORROBORATION_CAP = 0.10  # capped total corroboration bonus

# independence_weight: how much an additional agreeing source counts
INDEPENDENCE_ATS_CSV = 0.5  # ATS<->CSV may share an upstream import
INDEPENDENCE_WITH_GITHUB = 1.0  # any<->GitHub treated as independent

EXTRACTION_PENALTY_STRUCTURED = 0.00
EXTRACTION_PENALTY_PROSE = 0.10  # github bio, free-text location, etc.

CONFLICT_PENALTY = 0.05  # single-valued only, when >=2 distinct value-clusters competed

# recency: factor = 1 - min(RECENCY_MAX_DECAY, months_stale * RECENCY_PER_MONTH)
RECENCY_PER_MONTH = 0.01
RECENCY_MAX_DECAY = 0.20

# overall_confidence weights over core fields (PRD §9.4)
OVERALL_WEIGHTS: dict[str, float] = {
    "name": 0.25,
    "email": 0.20,  # email[0]
    "phone": 0.15,  # phone[0]
    "company": 0.15,  # current experience entry
    "title": 0.15,  # current experience entry
    "location": 0.10,
}

# fields that decay with staleness (PRD §9.3); identifiers never decay
TIME_VARYING_FIELDS = {"company", "title", "location", "headline"}


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def independence_weight(source_a: str, source_b: str) -> float:
    """Weight for corroboration between two sources (PRD §9.1)."""
    pair = {source_a, source_b}
    if "github_api" in pair and len(pair) > 1:
        return INDEPENDENCE_WITH_GITHUB
    if pair == {"ats_json", "recruiter_csv"}:
        return INDEPENDENCE_ATS_CSV
    # same source, or any other pairing: full weight by default
    return 1.0


def _base(source: str) -> float:
    return BASE_BY_SOURCE.get(source, 0.0)


def _corroboration(winner: str, agreeing_sources) -> float:
    """+0.05 per *additional* agreeing source x independence_weight, capped."""
    additional = [s for s in dict.fromkeys(agreeing_sources) if s != winner]
    total = sum(CORROBORATION_PER_SOURCE * independence_weight(winner, s) for s in additional)
    return min(total, CORROBORATION_CAP)


def recency_factor(last_updated, as_of, time_varying: bool) -> float:
    """Recency multiplier (PRD §9.2/§9.3). Only time-varying fields decay."""
    if not time_varying or not last_updated or as_of is None:
        return 1.0
    from dateutil import parser as dateparser

    try:
        lu = dateparser.parse(str(last_updated))
    except (ValueError, OverflowError, TypeError):
        return 1.0
    months_stale = (as_of.year - lu.year) * 12 + (as_of.month - lu.month)
    if months_stale < 0:
        months_stale = 0
    return 1.0 - min(RECENCY_MAX_DECAY, months_stale * RECENCY_PER_MONTH)


def single_valued_confidence(
    winner_source: str,
    agreeing_sources,
    is_prose: bool,
    had_conflict: bool,
    recency: float,
) -> float:
    """PRD §9.1: clamp01(base + corroboration - extraction - conflict) x recency."""
    base = _base(winner_source)
    corrob = _corroboration(winner_source, agreeing_sources)
    extraction = EXTRACTION_PENALTY_PROSE if is_prose else EXTRACTION_PENALTY_STRUCTURED
    conflict = CONFLICT_PENALTY if had_conflict else 0.0
    return clamp01(base + corrob - extraction - conflict) * recency


def multi_valued_confidence(
    best_source: str,
    agreeing_sources,
    is_prose: bool,
    recency: float,
) -> float:
    """PRD §9.2: clamp01(best_base + corroboration - extraction) x recency. No conflict term."""
    base = _base(best_source)
    corrob = _corroboration(best_source, agreeing_sources)
    extraction = EXTRACTION_PENALTY_PROSE if is_prose else EXTRACTION_PENALTY_STRUCTURED
    return clamp01(base + corrob - extraction) * recency


def overall_confidence(field_confidences: dict[str, float]) -> float:
    """PRD §9.4 weighted sum over core fields; an absent field contributes 0."""
    total = 0.0
    for field, weight in OVERALL_WEIGHTS.items():
        total += weight * field_confidences.get(field, 0.0)
    return total
