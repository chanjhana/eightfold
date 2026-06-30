"""Date normalization (PRD §6, §8.3).

Output "YYYY" or "YYYY-MM" only. "Present"/""/None -> None (ongoing).
Granularity is preserved: a year-only input stays "YYYY" — we never fabricate a
month, because inventing "-01" would violate "never fabricate a value".
"""

from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as dateparser

_YEAR = re.compile(r"^(\d{4})$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")


def normalize_date(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s.lower() == "present":
        return None

    m = _YEAR.match(s)
    if m:
        return m.group(1)

    m = _YEAR_MONTH.match(s)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return f"{m.group(1)}-{month:02d}"
        # an out-of-range month (e.g. "2020-13") is not a real date: fall through
        # to free-text parsing, which rejects it rather than inventing a month.

    # Free text: detect which fields were actually present using two differing
    # defaults. A field that ends up equal across both parses was supplied;
    # one that differs was filled from the default (i.e. not provided).
    try:
        d1 = dateparser.parse(s, default=datetime(1000, 1, 1))
        d2 = dateparser.parse(s, default=datetime(2000, 2, 2))
    except (ValueError, OverflowError, TypeError):
        return None

    if d1.year != d2.year:  # year not actually provided -> not a usable date
        return None
    if d1.month == d2.month:  # month was provided
        return f"{d1.year:04d}-{d1.month:02d}"
    return f"{d1.year:04d}"
