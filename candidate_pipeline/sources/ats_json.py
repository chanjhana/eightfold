"""ATS JSON adapter (PRD §4.2). Nested field names that don't match canonical;
this adapter maps them. ATS is the highest-trust source (§8)."""

from __future__ import annotations

import json

from candidate_pipeline.models.canonical import Flag
from candidate_pipeline.models.source_record import (
    SourceEducation,
    SourceExperience,
    SourceRecord,
    SourceValue,
)
from candidate_pipeline.normalize.country import normalize_country
from candidate_pipeline.normalize.dates import normalize_date
from candidate_pipeline.sources.base import SourceAdapter


def _sv(value, raw, method) -> SourceValue | None:
    if value is None and (raw is None or raw == ""):
        return None
    return SourceValue(value=value, raw=raw, method=method)


class AtsJsonAdapter(SourceAdapter):
    source_name = "ats_json"

    def _load_impl(self, path: str) -> list[SourceRecord]:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        records: list[SourceRecord] = []
        for i, obj in enumerate(self._as_record_list(data)):
            try:
                if not isinstance(obj, dict):
                    raise TypeError(f"expected object, got {type(obj).__name__}")
                records.append(self._obj_to_record(obj, i))
            except Exception as exc:  # noqa: BLE001 - one bad object must not drop the rest
                self._record_skip(path, i, exc)
        return records

    def _date_value(self, raw) -> SourceValue | None:
        norm = normalize_date(raw)
        if norm is None:
            return None  # "Present"/"" -> ongoing
        return SourceValue(value=norm, raw=raw, method="normalize:iso-date")

    def _obj_to_record(self, obj: dict, index: int) -> SourceRecord:
        flags: list[Flag] = []
        # `.get(k, {})` only defaults on a MISSING key, not an explicit null —
        # `or {}` covers both so a `"candidate": null` can't crash the record.
        cand = obj.get("candidate") or {}
        name = cand.get("fullName")

        emails = self._emails(cand.get("emails") or [], method="ats:path")
        phones = self._phones(cand.get("phoneNumbers") or [], method="ats:path", flags=flags)
        skills = self._skills(obj.get("skills") or [], flags=flags)

        employment = obj.get("employment") or {}
        current = employment.get("current") or {}

        experience = []
        for e in obj.get("experience") or []:
            if not isinstance(e, dict):
                continue  # skip a non-object experience entry rather than crash
            experience.append(
                SourceExperience(
                    company=_sv(e.get("employer"), e.get("employer"), "ats:path"),
                    title=_sv(e.get("role"), e.get("role"), "ats:path"),
                    start=self._date_value(e.get("startDate")),
                    end=self._date_value(e.get("endDate")),
                    summary=_sv(e.get("summary") or None, e.get("summary"), "ats:path"),
                )
            )

        education = []
        for ed in obj.get("education") or []:
            if not isinstance(ed, dict):
                continue  # skip a non-object education entry rather than crash
            education.append(
                SourceEducation(
                    institution=_sv(ed.get("school"), ed.get("school"), "ats:path"),
                    degree=_sv(ed.get("degree"), ed.get("degree"), "ats:path"),
                    field=_sv(ed.get("fieldOfStudy"), ed.get("fieldOfStudy"), "ats:path"),
                    end_year=_sv(ed.get("endYear"), ed.get("endYear"), "ats:path"),
                )
            )

        loc = obj.get("location", {}) or {}
        location = SourceValue(
            value={
                "city": loc.get("city"),
                "region": loc.get("region"),
                "country": normalize_country(loc.get("country")),
            },
            raw=loc,
            method="ats:path",
        )

        return SourceRecord(
            source_name=self.source_name,
            record_id=(emails[0].value if emails else f"{self.source_name}:{index}"),
            full_name=_sv(name, name, "ats:path"),
            emails=emails,
            phones=phones,
            current_company=_sv(current.get("employer"), current.get("employer"), "ats:path"),
            current_title=_sv(current.get("role"), current.get("role"), "ats:path"),
            location=location,
            skills=skills,
            experience=experience,
            education=education,
            last_updated=obj.get("last_updated"),
            flags=flags,
        )
