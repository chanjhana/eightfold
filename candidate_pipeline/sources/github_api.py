"""GitHub adapter (PRD §4.3). Unstructured-ish: company/location/bio are free text.

Reads a cached JSON fixture. `--live` would hit the real API; here it is a no-op
stub that defaults to the fixture so the demo never flakes.
"""

from __future__ import annotations

import json

from candidate_pipeline.models.canonical import Flag
from candidate_pipeline.models.source_record import SourceRecord, SourceValue
from candidate_pipeline.normalize.country import normalize_country
from candidate_pipeline.sources.base import SourceAdapter


class GithubApiAdapter(SourceAdapter):
    source_name = "github_api"

    def __init__(self, report=None, default_region=None, live: bool = False):
        super().__init__(report=report, default_region=default_region)
        self.live = live  # no-op: always reads the fixture

    def _load_impl(self, path: str) -> list[SourceRecord]:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [self._obj_to_record(obj, i) for i, obj in enumerate(data)]

    def _obj_to_record(self, obj: dict, index: int) -> SourceRecord:
        flags: list[Flag] = []
        login = obj.get("login")
        name = obj.get("name")

        emails = self._emails([obj.get("email")] if obj.get("email") else [], method="github:field")

        bio = obj.get("bio")
        headline = (
            SourceValue(value=bio, raw=bio, method="github:field") if bio else None
        )

        loc_raw = obj.get("location")
        location = (
            SourceValue(
                value={
                    "city": None,
                    "region": None,
                    "country": normalize_country(loc_raw),
                },
                raw=loc_raw,
                method="github:field",
            )
            if loc_raw
            else None
        )

        link_hints = {}
        if login:
            link_hints["github_login"] = login
        if obj.get("blog"):
            link_hints["blog"] = obj.get("blog")

        return SourceRecord(
            source_name=self.source_name,
            record_id=login or f"{self.source_name}:{index}",
            full_name=SourceValue(value=name, raw=name, method="github:field") if name else None,
            emails=emails,
            github_login=SourceValue(value=login, raw=login, method="github:field") if login else None,
            current_company=SourceValue(
                value=obj.get("company"), raw=obj.get("company"), method="github:field"
            )
            if obj.get("company")
            else None,
            location=location,
            headline=headline,
            link_hints=link_hints,
            last_updated=obj.get("updated_at"),
            flags=flags,
        )
