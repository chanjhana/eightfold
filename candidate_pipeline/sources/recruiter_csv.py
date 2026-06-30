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
        # utf-8-sig transparently strips a BOM; otherwise the first header
        # becomes "﻿full_name" and silently fails to match.
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            # Normalize headers so " Full_Name " matches the canonical "full_name".
            if reader.fieldnames:
                reader.fieldnames = [(h or "").strip().lower() for h in reader.fieldnames]
            row_iter = iter(reader)
            i = 0
            while True:
                try:
                    row = next(row_iter)
                except StopIteration:
                    break
                except csv.Error as exc:
                    # a poison line (e.g. embedded NUL) must not drop the file
                    self._record_skip(path, i, exc)
                    i += 1
                    continue
                try:
                    records.append(self._row_to_record(row, i))
                except Exception as exc:  # noqa: BLE001 - one bad row must not drop the rest
                    self._record_skip(path, i, exc)
                i += 1
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
