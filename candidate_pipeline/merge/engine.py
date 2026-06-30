"""Merge engine (PRD §8): one cluster -> one CanonicalProfile with TrackedValues.

The current employment entry (the experience row with end == None) is the single
source of truth for current company/title; flat current employer/title from
CSV/ATS/GitHub reconcile into it (§8.2). years_experience is a merged interval
pinned to an as_of date (§8.3).
"""

from __future__ import annotations

import hashlib
from datetime import date

from candidate_pipeline.confidence.scorer import overall_confidence
from candidate_pipeline.merge.strategies import (
    Contribution,
    merge_multi_valued,
    merge_single_valued,
)
from candidate_pipeline.models.canonical import (
    CanonicalProfile,
    Flag,
    TrackedEducation,
    TrackedExperience,
    TrackedValue,
)
from candidate_pipeline.models.report import Assumption, ConflictEntry, RunReport
from candidate_pipeline.models.source_record import SourceRecord
from candidate_pipeline.resolve.identity import name_block_key

_SKILL_CANONICAL_METHOD = "normalize:skill-alias"


def _candidate_id(cluster: list[SourceRecord]) -> str:
    emails = sorted({e.value for r in cluster for e in r.emails if e.value})
    phones = sorted({p.value for r in cluster for p in r.phones if p.value})
    if emails:
        anchor = f"email:{emails[0]}"
    elif phones:
        anchor = f"phone:{phones[0]}"
    else:
        names = sorted(r.full_name.value for r in cluster if r.full_name and r.full_name.value)
        anchor = f"name:{name_block_key(names[0]) if names else 'unknown'}"
    return "cand_" + hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:12]


def _country_key(d) -> str:
    return str((d or {}).get("country"))


class MergeEngine:
    def __init__(self, report: RunReport | None = None, as_of: date | None = None):
        self.report = report if report is not None else RunReport()
        self.as_of = as_of or date.today()

    def merge(self, cluster: list[SourceRecord]) -> CanonicalProfile:
        cid = _candidate_id(cluster)
        flags: list[Flag] = []

        full_name, _ = merge_single_valued(
            [
                Contribution(r.source_name, r.full_name.value, r.full_name.raw, r.full_name.method)
                for r in cluster
                if r.full_name
            ],
            as_of=self.as_of,
            time_varying=False,
        )

        emails = merge_multi_valued(
            [
                Contribution(r.source_name, e.value, e.raw, e.method)
                for r in cluster
                for e in r.emails
            ],
            as_of=self.as_of,
            time_varying=False,
        )
        phones = merge_multi_valued(
            [
                Contribution(r.source_name, p.value, p.raw, p.method)
                for r in cluster
                for p in r.phones
            ],
            as_of=self.as_of,
            time_varying=False,
        )
        skills = merge_multi_valued(
            [
                Contribution(
                    r.source_name, s.value, s.raw, s.method,
                    is_prose=(s.method != _SKILL_CANONICAL_METHOD),
                )
                for r in cluster
                for s in r.skills
            ],
            as_of=self.as_of,
            time_varying=False,
        )

        location = self._merge_location(cluster)
        headline = self._merge_headline(cluster)
        links = self._merge_links(cluster)
        experience, current_entry = self._merge_experience(cluster, cid, flags)
        education = self._merge_education(cluster)
        years = _years_experience(experience, self.as_of)

        # lift normalization flags (assumed_region, uncanonicalized_skill) onto profile
        for r in cluster:
            for f in r.flags:
                if not any(g.kind == f.kind and g.detail == f.detail for g in flags):
                    flags.append(f)

        # assumptions: any phone resolved via default-region
        if any(p.method == "assume:default_region" for r in cluster for p in r.phones):
            self.report.assumptions.append(
                Assumption(candidate_id=cid, field="phone", assumption="default-region applied")
            )

        overall = self._overall(full_name, emails, phones, current_entry, location)

        return CanonicalProfile(
            candidate_id=cid,
            full_name=full_name,
            emails=emails,
            phones=phones,
            location=location,
            links=links,
            headline=headline,
            skills=skills,
            experience=experience,
            education=education,
            years_experience=years,
            overall_confidence=round(overall, 6),
            flags=flags,
        )

    # ---- field strategies --------------------------------------------------

    def _merge_location(self, cluster) -> TrackedValue | None:
        contribs = []
        for r in cluster:
            if not r.location or not r.location.value:
                continue
            d = dict(r.location.value)
            d["raw"] = r.location.raw
            contribs.append(
                Contribution(
                    r.source_name, d, r.location.raw, r.location.method,
                    is_prose=(r.source_name == "github_api"),
                    last_updated=r.last_updated,
                )
            )
        tv, _ = merge_single_valued(
            contribs, as_of=self.as_of, time_varying=True, key_fn=_country_key
        )
        return tv

    def _merge_headline(self, cluster) -> TrackedValue | None:
        contribs = [
            Contribution(
                r.source_name, r.headline.value, r.headline.raw, r.headline.method,
                is_prose=True, last_updated=r.last_updated,
            )
            for r in cluster
            if r.headline and r.headline.value
        ]
        tv, _ = merge_single_valued(contribs, as_of=self.as_of, time_varying=True)
        return tv

    def _merge_links(self, cluster) -> TrackedValue | None:
        value = {"linkedin": None, "github": None, "portfolio": None, "other": []}
        sources: list[str] = []
        for r in cluster:
            login = r.github_login.value if r.github_login else None
            if login:
                value["github"] = f"https://github.com/{login}"
                sources.append(r.source_name)
            if r.link_hints.get("blog"):
                value["portfolio"] = r.link_hints["blog"]
            if r.link_hints.get("linkedin"):
                value["linkedin"] = r.link_hints["linkedin"]
            for url in r.link_hints.get("notable_repos") or []:
                if url and url not in value["other"]:
                    value["other"].append(url)
                    sources.append(r.source_name)
        if value["github"] or value["portfolio"] or value["linkedin"] or value["other"]:
            return TrackedValue(value=value, confidence=None, sources=sorted(set(sources)))
        return None

    def _merge_experience(self, cluster, cid: str, flags: list[Flag]):
        cur_company, cur_title, cur_start, cur_summary = [], [], [], []
        past: dict[tuple, dict[str, list[Contribution]]] = {}

        def field_contrib(r, sv, is_prose=False, tv=False):
            return Contribution(
                r.source_name, sv.value, sv.raw, sv.method,
                is_prose=is_prose, last_updated=(r.last_updated if tv else None),
            )

        for r in cluster:
            if r.experience:
                for e in r.experience:
                    is_current = e.end is None or e.end.value is None
                    if is_current:
                        if e.company:
                            cur_company.append(field_contrib(r, e.company, tv=True))
                        if e.title:
                            cur_title.append(field_contrib(r, e.title, tv=True))
                        if e.start:
                            cur_start.append(field_contrib(r, e.start))
                        if e.summary:
                            cur_summary.append(field_contrib(r, e.summary))
                    else:
                        key = (
                            str(e.company.value).lower() if e.company else "",
                            str(e.title.value).lower() if e.title else "",
                            e.start.value if e.start else None,
                        )
                        slot = past.setdefault(key, {"company": [], "title": [], "start": [], "end": [], "summary": []})
                        if e.company:
                            slot["company"].append(field_contrib(r, e.company))
                        if e.title:
                            slot["title"].append(field_contrib(r, e.title))
                        if e.start:
                            slot["start"].append(field_contrib(r, e.start))
                        if e.end:
                            slot["end"].append(field_contrib(r, e.end))
                        if e.summary:
                            slot["summary"].append(field_contrib(r, e.summary))
            else:
                # flat current employer/title reconcile into the current entry (§8.2)
                if r.current_company and r.current_company.value:
                    cur_company.append(
                        field_contrib(r, r.current_company, is_prose=(r.source_name == "github_api"), tv=True)
                    )
                if r.current_title and r.current_title.value:
                    cur_title.append(field_contrib(r, r.current_title, tv=True))

        experience: list[TrackedExperience] = []
        current_entry = None
        if cur_company or cur_title:
            company_tv, company_conflict = merge_single_valued(cur_company, as_of=self.as_of, time_varying=True)
            title_tv, _ = merge_single_valued(cur_title, as_of=self.as_of, time_varying=True)
            start_tv, _ = merge_single_valued(cur_start, as_of=self.as_of, time_varying=False)
            summary_tv, _ = merge_single_valued(cur_summary, as_of=self.as_of, time_varying=False)
            current_entry = TrackedExperience(
                company=company_tv, title=title_tv, start=start_tv, end=None, summary=summary_tv
            )
            experience.append(current_entry)
            if company_conflict and company_tv:
                flags.append(
                    Flag(kind="conflict_resolved", detail=f"current company: {company_tv.value} over {company_tv.competitors}")
                )
                self.report.conflicts.append(
                    ConflictEntry(candidate_id=cid, field="current_company", winner=company_tv.value, losers=company_tv.competitors)
                )

        for key, slot in past.items():
            experience.append(
                TrackedExperience(
                    company=merge_single_valued(slot["company"], as_of=self.as_of, time_varying=False)[0],
                    title=merge_single_valued(slot["title"], as_of=self.as_of, time_varying=False)[0],
                    start=merge_single_valued(slot["start"], as_of=self.as_of, time_varying=False)[0],
                    end=merge_single_valued(slot["end"], as_of=self.as_of, time_varying=False)[0],
                    summary=merge_single_valued(slot["summary"], as_of=self.as_of, time_varying=False)[0],
                )
            )
        return experience, current_entry

    def _merge_education(self, cluster) -> list[TrackedEducation]:
        groups: dict[tuple, dict[str, list[Contribution]]] = {}
        order: list[tuple] = []
        for r in cluster:
            for ed in r.education:
                key = (
                    str(ed.institution.value).lower() if ed.institution else "",
                    str(ed.degree.value).lower() if ed.degree else "",
                )
                if key not in groups:
                    groups[key] = {"institution": [], "degree": [], "field": [], "end_year": []}
                    order.append(key)
                slot = groups[key]
                for name, sv in (("institution", ed.institution), ("degree", ed.degree), ("field", ed.field), ("end_year", ed.end_year)):
                    if sv:
                        slot[name].append(Contribution(r.source_name, sv.value, sv.raw, sv.method))
        out = []
        for key in order:
            slot = groups[key]
            out.append(
                TrackedEducation(
                    institution=merge_single_valued(slot["institution"], as_of=self.as_of, time_varying=False)[0],
                    degree=merge_single_valued(slot["degree"], as_of=self.as_of, time_varying=False)[0],
                    field=merge_single_valued(slot["field"], as_of=self.as_of, time_varying=False)[0],
                    end_year=merge_single_valued(slot["end_year"], as_of=self.as_of, time_varying=False, key_fn=lambda v: v)[0],
                )
            )
        return out

    def _overall(self, full_name, emails, phones, current_entry, location) -> float:
        fc: dict[str, float] = {}
        if full_name and full_name.confidence is not None:
            fc["name"] = full_name.confidence
        if emails:
            fc["email"] = emails[0].confidence or 0.0
        if phones:
            fc["phone"] = phones[0].confidence or 0.0
        if current_entry and current_entry.company and current_entry.company.confidence is not None:
            fc["company"] = current_entry.company.confidence
        if current_entry and current_entry.title and current_entry.title.confidence is not None:
            fc["title"] = current_entry.title.confidence
        if location and location.confidence is not None:
            fc["location"] = location.confidence
        return overall_confidence(fc)


# ---- years_experience (PRD §8.3) ------------------------------------------

def _to_month_index(partial: str, as_of: date) -> int | None:
    # "YYYY" -> January; "YYYY-MM" -> that month. Returns None on anything that
    # isn't numeric (defensive depth: the adapter normalizes dates upstream, but
    # a malformed value here is skipped, never raised).
    parts = str(partial).split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
    except (ValueError, IndexError):
        return None
    return year * 12 + month


def _years_experience(experience: list[TrackedExperience], as_of: date) -> float | None:
    as_of_idx = as_of.year * 12 + as_of.month
    intervals: list[tuple[int, int]] = []
    for e in experience:
        if not e.start or not e.start.value:
            continue
        start = _to_month_index(e.start.value, as_of)
        if start is None:
            continue  # unparseable start -> skip this interval, don't invent one
        if e.end and e.end.value:
            end = _to_month_index(e.end.value, as_of)
            if end is None:
                end = as_of_idx  # unparseable end -> treat as ongoing
        else:
            end = as_of_idx  # ongoing
        if end >= start:
            intervals.append((start, end))
    if not intervals:
        return None
    intervals.sort()
    merged: list[list[int]] = [list(intervals[0])]
    for s, en in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], en)
        else:
            merged.append([s, en])
    months = sum(en - s for s, en in merged)
    return round(months / 12.0, 2)
