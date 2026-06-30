"""GitHub adapter (PRD §4.3). Unstructured-ish: company/location/bio are free text.

Reads a cached JSON fixture. `--live` would hit the real API; here it is a no-op
stub that defaults to the fixture so the demo never flakes.

Repos mirror `GET /users/{login}/repos`: each candidate's non-fork repositories
contribute their `language` as a skill (via the shared alias map, exactly like a
CSV/ATS skill) and their most-starred repos as profile links. Forks are excluded
from both — a fork's language and stars reflect the upstream project, not the
candidate's own work.
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

    @staticmethod
    def _text(value):
        """Coerce a scalar field to clean text. A number (e.g. `login: 12345`)
        becomes its string form; a list/dict (a meaningless name/company) is
        treated as absent rather than stringified into junk."""
        if value is None or isinstance(value, (list, dict, bool)):
            return None
        s = str(value).strip()
        return s or None

    # Number of most-starred non-fork repos to surface as profile links.
    _NOTABLE_REPO_LIMIT = 2

    @staticmethod
    def _stars(value) -> int:
        """Coerce stargazers_count to a sortable int; junk (e.g. "lots") -> 0."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _parse_repos(self, repos):
        """From a `/users/{login}/repos`-shaped list, return (language_strings,
        notable_repo_urls). Forks are excluded from both. Malformed entries are
        skipped, never raised — one bad repo must not drop the record."""
        languages: list[str] = []
        seen_langs: set[str] = set()
        non_fork: list[dict] = []
        if not isinstance(repos, list):
            return languages, []
        for repo in repos:
            if not isinstance(repo, dict):
                continue  # a non-object repo entry is skipped, not stringified
            if bool(repo.get("fork")):
                continue  # fork: language/stars reflect the upstream, not the candidate
            non_fork.append(repo)
            lang = self._text(repo.get("language"))
            if lang and lang.lower() not in seen_langs:
                seen_langs.add(lang.lower())
                languages.append(lang)

        notable = sorted(
            (r for r in non_fork if self._text(r.get("html_url"))),
            key=lambda r: (-self._stars(r.get("stargazers_count")), str(r.get("name") or "")),
        )
        urls = [self._text(r.get("html_url")) for r in notable[: self._NOTABLE_REPO_LIMIT]]
        return languages, urls

    def _obj_to_record(self, obj: dict, index: int) -> SourceRecord:
        flags: list[Flag] = []
        login = self._text(obj.get("login"))
        name = self._text(obj.get("name"))

        email_raw = obj.get("email")
        emails = self._emails([email_raw] if email_raw else [], method="github:field")

        bio = self._text(obj.get("bio"))
        headline = (
            SourceValue(value=bio, raw=bio, method="github:field") if bio else None
        )

        loc_raw = self._text(obj.get("location"))
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

        languages, notable_repos = self._parse_repos(obj.get("repos"))
        skills = self._skills(languages, flags=flags)

        link_hints = {}
        if login:
            link_hints["github_login"] = login
        if obj.get("blog"):
            link_hints["blog"] = obj.get("blog")
        if notable_repos:
            link_hints["notable_repos"] = notable_repos

        return SourceRecord(
            source_name=self.source_name,
            record_id=login or f"{self.source_name}:{index}",
            full_name=SourceValue(value=name, raw=name, method="github:field") if name else None,
            emails=emails,
            github_login=SourceValue(value=login, raw=login, method="github:field") if login else None,
            current_company=(
                SourceValue(value=company, raw=company, method="github:field")
                if (company := self._text(obj.get("company")))
                else None
            ),
            location=location,
            headline=headline,
            skills=skills,
            link_hints=link_hints,
            last_updated=obj.get("updated_at"),
            flags=flags,
        )
