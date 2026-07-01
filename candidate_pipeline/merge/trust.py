"""Source trust ordering for single-valued conflict resolution (PRD §8.1).

These constants — and the confidence constants in confidence/scorer.py — are the
ONLY two places tunable numbers live.
"""

from __future__ import annotations

# Higher = more trusted. Tie-break / precedence: ATS > CSV > resume > GitHub.
# Résumé is a deliberate professional document (above a GitHub bio) but self-
# authored and prose-extracted (below the recruiter CSV / verified ATS).
SOURCE_TRUST: dict[str, float] = {
    "ats_json": 0.90,
    "recruiter_csv": 0.80,
    "resume_pdf": 0.75,
    "github_api": 0.70,
}


def trust_of(source: str) -> float:
    """Trust weight for a source name; unknown sources sort lowest."""
    return SOURCE_TRUST.get(source, 0.0)
