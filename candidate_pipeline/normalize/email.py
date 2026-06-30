"""Email normalization (PRD §6).

Lowercase + basic shape validation. An invalid email drops that value (returns
None) — the caller drops the value, not the whole record.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# A `mailto:` (with optional whitespace) is a common copy-paste artifact.
_MAILTO_RE = re.compile(r"^mailto:\s*", re.IGNORECASE)
# Trailing punctuation from prose ("email me at a@b.com.") is not part of the address.
_TRAILING_PUNCT = ".,;:!?\"')]}>"


def normalize_email(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    s = _MAILTO_RE.sub("", s).strip()
    s = s.rstrip(_TRAILING_PUNCT)
    if not s or not _EMAIL_RE.match(s):
        return None
    return s
