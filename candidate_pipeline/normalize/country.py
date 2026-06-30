"""Country normalization to ISO-3166 alpha-2 (PRD §6).

Best-effort on free text; unresolvable -> None (but the caller keeps the raw).
"""

from __future__ import annotations

import re

import pycountry


def _lookup(token: str) -> str | None:
    t = token.strip()
    if not t:
        return None

    if len(t) == 2:
        c = pycountry.countries.get(alpha_2=t.upper())
        if c:
            return c.alpha_2
    if len(t) == 3:
        c = pycountry.countries.get(alpha_3=t.upper())
        if c:
            return c.alpha_2

    for kw in ("name", "official_name", "common_name"):
        try:
            c = pycountry.countries.get(**{kw: t})
        except KeyError:
            c = None
        if c:
            return c.alpha_2

    try:
        res = pycountry.countries.search_fuzzy(t)
        if res:
            return res[0].alpha_2
    except LookupError:
        pass
    return None


def normalize_country(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    hit = _lookup(s)
    if hit:
        return hit

    # free text like "Bengaluru, India" — try comma/slash tokens, last first
    parts = [p.strip() for p in re.split(r"[,/|]", s) if p.strip()]
    for p in reversed(parts):
        hit = _lookup(p)
        if hit:
            return hit
    return None
