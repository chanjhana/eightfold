"""Skill canonicalization (PRD §6, edge case §15 #6).

Alias map is checked on the RAW string first, then on a normalized-for-match
form that *preserves `+` and `#`* (so C++/C#/.NET never collapse to "c"). Unknown
skills are kept verbatim at lower confidence and flagged uncanonicalized.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from candidate_pipeline.models.canonical import Flag

_ALIASES_PATH = Path(__file__).with_name("aliases.json")


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    with _ALIASES_PATH.open(encoding="utf-8") as fh:
        return {k.lower(): v for k, v in json.load(fh).items()}


@dataclass
class SkillResult:
    value: str  # canonical name, or the verbatim raw if unknown
    raw: str
    is_canonical: bool
    method: str | None  # "normalize:skill-alias" when matched, else None
    flag: Flag | None  # Flag(uncanonicalized_skill) when not canonical


def normalize_for_match(s: str) -> str:
    """Lowercase and strip dots/hyphens/whitespace, but PRESERVE + and #."""
    s = s.lower()
    return re.sub(r"[.\-\s]", "", s)


def canonicalize_skill(raw: str) -> SkillResult:
    s = str(raw).strip()
    aliases = _aliases()

    # 1. raw lookup first (raw-symbol preservation, e.g. ".net", "react.js")
    raw_key = s.lower()
    if raw_key in aliases:
        return SkillResult(aliases[raw_key], s, True, "normalize:skill-alias", None)

    # 2. normalized-for-match lookup (+ and # preserved)
    norm = normalize_for_match(s)
    if norm in aliases:
        return SkillResult(aliases[norm], s, True, "normalize:skill-alias", None)

    # 3. unknown -> keep verbatim, lower confidence, flagged
    return SkillResult(
        s,
        s,
        False,
        "verbatim",
        Flag(kind="uncanonicalized_skill", detail=s),
    )


def split_skills(s: str) -> list[str]:
    """Split a skills string into trimmed tokens.

    Recruiters use a range of separators — comma, semicolon, pipe, newline, tab.
    `/` is deliberately NOT a separator (it would split "CI/CD", "TCP/IP").
    """
    if not s:
        return []
    return [tok.strip() for tok in re.split(r"[,;|\n\t]", str(s)) if tok.strip()]
