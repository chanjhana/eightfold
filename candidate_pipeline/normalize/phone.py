"""Phone normalization to E.164 (PRD §6).

Three cases, never silently guess a region:
  (a) explicit country code              -> E.164, method "normalize:e164", no flag
  (b) no CC but default_region provided  -> E.164, method "assume:default_region" + Flag
  (c) no CC and no default_region        -> keep raw, no E.164, no flag
"""

from __future__ import annotations

from dataclasses import dataclass

import phonenumbers

from candidate_pipeline.models.canonical import Flag


@dataclass
class PhoneResult:
    value: str | None  # E.164, or None when not normalizable
    raw: str
    method: str | None
    flag: Flag | None


def _e164(num: phonenumbers.PhoneNumber) -> str:
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def normalize_phone(raw: str, default_region: str | None = None) -> PhoneResult:
    raw_str = "" if raw is None else str(raw).strip()

    # (a) explicit country code: parseable with no region hint
    try:
        num = phonenumbers.parse(raw_str, None)
        if phonenumbers.is_valid_number(num):
            return PhoneResult(_e164(num), raw_str, "normalize:e164", None)
    except phonenumbers.NumberParseException:
        pass

    # (b) no country code, but a default region is configured
    if default_region:
        try:
            num = phonenumbers.parse(raw_str, default_region)
            if phonenumbers.is_valid_number(num):
                return PhoneResult(
                    _e164(num),
                    raw_str,
                    "assume:default_region",
                    Flag(kind="assumed_region", detail=f"region={default_region}"),
                )
        except phonenumbers.NumberParseException:
            pass

    # (c) cannot normalize without guessing — keep raw, emit nothing
    return PhoneResult(None, raw_str, None, None)
