"""Recruiter CSV adapter (PRD §4.1). The clean identity anchor."""

from __future__ import annotations

import csv

from candidate_pipeline.models.canonical import Flag
from candidate_pipeline.models.source_record import SourceRecord, SourceValue
from candidate_pipeline.normalize.country import normalize_country
from candidate_pipeline.normalize.skills import split_skills
from candidate_pipeline.sources.base import SourceAdapter


class RecruiterCsvAdapter(SourceAdapter):
    source_name = "recruiter_csv"

    def _load_impl(self, path: str) -> list[SourceRecord]:
        records: list[SourceRecord] = []
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for i, row in enumerate(reader):
                records.append(self._row_to_record(row, i))
        return records

    def _row_to_record(self, row: dict, index: int) -> SourceRecord:
        flags: list[Flag] = []
        name = (row.get("full_name") or "").strip()

        emails = self._emails([row.get("email")], method="csv:column")
        phones = self._phones([row.get("phone")], method="csv:column", flags=flags)
        skills = self._skills(split_skills(row.get("skills") or ""), flags=flags)

        country_raw = row.get("country")
        location = SourceValue(
            value={
                "city": (row.get("city") or "").strip() or None,
                "region": None,
                "country": normalize_country(country_raw),
            },
            raw={"city": row.get("city"), "country": country_raw},
            method="csv:column",
        )

        return SourceRecord(
            source_name=self.source_name,
            record_id=emails[0].value if emails else f"{self.source_name}:{index}",
            full_name=SourceValue(value=name or None, raw=row.get("full_name"), method="csv:column"),
            emails=emails,
            phones=phones,
            current_company=SourceValue(
                value=(row.get("current_company") or "").strip() or None,
                raw=row.get("current_company"),
                method="csv:column",
            ),
            current_title=SourceValue(
                value=(row.get("current_title") or "").strip() or None,
                raw=row.get("current_title"),
                method="csv:column",
            ),
            location=location,
            skills=skills,
            flags=flags,
        )
