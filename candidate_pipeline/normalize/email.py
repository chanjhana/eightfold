"""Email normalization (PRD §6).

Lowercase + basic shape validation. An invalid email drops that value (returns
None) — the caller drops the value, not the whole record.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or not _EMAIL_RE.match(s):
        return None
    return s
