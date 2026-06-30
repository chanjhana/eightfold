"""GitHub adapter (PRD §4.3). Unstructured-ish: company/location/bio are free text.

Reads a cached JSON fixture. With `--live`, it enriches each fixture record from
the real GitHub REST API (`GET /users/{login}` + `/users/{login}/repos`), falling
back to the fixture on any failure so the demo never flakes — see `_fetch_live`.

Repos mirror `GET /users/{login}/repos`: each candidate's non-fork repositories
contribute their `language` as a skill (via the shared alias map, exactly like a
CSV/ATS skill), their most-starred repos as profile links, and the raw (own,
non-fork) repo list as `CanonicalProfile.repos`. Forks are excluded from all
three — a fork's language and stars reflect the upstream project, not the
candidate's own work.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from candidate_pipeline.models.canonical import Flag, RepoEntry
from candidate_pipeline.models.source_record import SourceRecord, SourceValue
from candidate_pipeline.normalize.country import normalize_country
from candidate_pipeline.sources.base import SourceAdapter

# Real GitHub REST API. Unauthenticated calls are limited to 60/hour per IP;
# set GITHUB_TOKEN to lift that to 5,000/hour. No token is required for public data.
_API_BASE = "https://api.github.com"
_HTTP_TIMEOUT = 8  # seconds; a slow/blocked network falls back to the fixture
_REPOS_PER_PAGE = 100


class GithubApiAdapter(SourceAdapter):
    source_name = "github_api"

    def __init__(self, report=None, default_region=None, live: bool = False):
        super().__init__(report=report, default_region=default_region)
        self.live = live

    def _load_impl(self, path: str) -> list[SourceRecord]:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        records: list[SourceRecord] = []
        for i, obj in enumerate(self._as_record_list(data)):
            try:
                if not isinstance(obj, dict):
                    raise TypeError(f"expected object, got {type(obj).__name__}")
                if self.live:
                    obj = self._fetch_live(obj)  # API overlay, fixture fallback
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
        """From a `/users/{login}/repos`-shaped list, return
        (language_strings, notable_repo_urls, repo_entries) where repo_entries are
        the candidate's own (non-fork) repos as star-sorted `RepoEntry`s. Forks are
        excluded from all three. Malformed entries are skipped, never raised — one
        bad repo must not drop the record."""
        languages: list[str] = []
        seen_langs: set[str] = set()
        entries: list[RepoEntry] = []
        if not isinstance(repos, list):
            return languages, [], entries
        for repo in repos:
            if not isinstance(repo, dict):
                continue  # a non-object repo entry is skipped, not stringified
            if bool(repo.get("fork")):
                continue  # fork: language/stars reflect the upstream, not the candidate
            name = self._text(repo.get("name"))
            if not name:
                continue  # a repo with no usable name is not a meaningful entry
            lang = self._text(repo.get("language"))
            entries.append(
                RepoEntry(
                    name=name,
                    language=lang,
                    stars=self._stars(repo.get("stargazers_count")),
                    url=self._text(repo.get("html_url")),
                    fork=False,
                )
            )
            if lang and lang.lower() not in seen_langs:
                seen_langs.add(lang.lower())
                languages.append(lang)

        entries.sort(key=lambda e: (-e.stars, e.name))
        urls = [e.url for e in entries if e.url][: self._NOTABLE_REPO_LIMIT]
        return languages, urls, entries

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

        languages, notable_repos, repos = self._parse_repos(obj.get("repos"))
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
            repos=repos,
            link_hints=link_hints,
            last_updated=obj.get("updated_at"),
            flags=flags,
        )

    # ---- live API (PRD §4.3: --live enriches; fixture is the offline fallback) --

    def _fetch_live(self, fixture_obj: dict) -> dict:
        """Overlay live GitHub REST data onto a fixture record, keyed by `login`.

        On ANY failure (no login, network error, rate limit, bad JSON) the fixture
        object is returned unchanged, so `--live` never crashes or flakes the run.
        A non-fatal note is logged so the report is honest about what was used.
        """
        login = self._text(fixture_obj.get("login"))
        if not login:
            return fixture_obj
        try:
            profile = self._api_get(f"/users/{login}")
            repos = self._api_get(f"/users/{login}/repos?per_page={_REPOS_PER_PAGE}")
            if not isinstance(profile, dict) or not isinstance(repos, list):
                raise ValueError("unexpected API response shape")
            merged = dict(profile)
            merged["repos"] = repos
            return merged
        except Exception as exc:  # noqa: BLE001 - live is best-effort; fixture is the fallback
            self.report.add_skip(
                "github:live", login, f"live fetch failed, used fixture: {type(exc).__name__}: {exc}"
            )
            return fixture_obj

    @staticmethod
    def _api_get(endpoint: str):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "candidate-pipeline",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(_API_BASE + endpoint, headers=headers)
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.load(resp)
