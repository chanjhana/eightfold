"""Résumé adapter (PRD §18 — promoted from descoped to a real source).

A résumé is candidate-authored prose, so this is a second *unstructured* source
alongside GitHub. Text is extracted from a PDF (via pypdf) or read directly from
a `.txt` twin, then a deterministic, heuristic parser pulls out the fields we can
recover reliably: name, emails, phones, headline, location, skills.

Scope is deliberately **lean** — experience/education parsing stays out (still a
documented extension point in the README). Everything extracted goes through the
same normalizers as every other source, and nothing is ever fabricated: a field
the parser can't recover stays absent.
"""

from __future__ import annotations

import re

from candidate_pipeline.models.canonical import Flag
from candidate_pipeline.models.source_record import SourceRecord, SourceValue
from candidate_pipeline.normalize.country import normalize_country
from candidate_pipeline.normalize.skills import split_skills
from candidate_pipeline.sources.base import SourceAdapter

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# a phone-like run: optional +, then >= 8 digits' worth of digits/separators
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_LOCATION_LABEL_RE = re.compile(r"^\s*location\s*[:\-]\s*(.+)$", re.IGNORECASE)

# Section headers that bound the skills block / disqualify a line from being a name.
_KNOWN_HEADERS = {
    "experience", "work experience", "professional experience", "employment",
    "education", "projects", "summary", "profile", "objective", "skills",
    "technical skills", "core skills", "certifications", "awards", "publications",
    "interests", "contact", "languages", "references",
}
_SKILLS_HEADERS = {"skills", "technical skills", "core skills"}
# A name line: 1-4 tokens of letters plus . ' - (no digits, no @).
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z.'\-]+){0,3}$")


def _header_key(line: str) -> str | None:
    """The known-header this line *is* (colon/whitespace-insensitive), else None."""
    key = line.strip().rstrip(":").strip().lower()
    return key if key in _KNOWN_HEADERS else None


def parse_resume_text(text: str) -> dict:
    """Best-effort deterministic extraction. Returns raw strings (pre-normalization);
    unrecoverable fields come back as None / []. Never fabricates a value."""
    lines = [ln.strip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    nonblank = [(i, ln) for i, ln in enumerate(lines) if ln]

    emails = list(dict.fromkeys(_EMAIL_RE.findall(text or "")))

    phones: list[str] = []
    for _, ln in nonblank:
        m = _PHONE_RE.search(ln)
        # a match with < 8 digits is more likely a year/id than a phone
        if m and sum(c.isdigit() for c in m.group()) >= 8:
            phones.append(m.group().strip())
            break

    name = None
    name_line_idx = None
    for idx, (_, ln) in enumerate(nonblank):
        if "@" in ln or _URL_RE.search(ln) or _header_key(ln):
            continue
        if any(c.isdigit() for c in ln):
            continue
        if _NAME_RE.match(ln):
            name = ln
            name_line_idx = idx
            break

    headline = None
    if name_line_idx is not None and name_line_idx + 1 < len(nonblank):
        cand = nonblank[name_line_idx + 1][1]
        if (
            "@" not in cand
            and not _URL_RE.search(cand)
            and not _header_key(cand)
            and not (_PHONE_RE.search(cand) and sum(c.isdigit() for c in cand) >= 8)
            and len(cand) <= 80
        ):
            headline = cand

    location = _parse_location(lines, nonblank, name, headline)
    skills = _parse_skills(lines)

    return {
        "name": name,
        "emails": emails,
        "phones": phones,
        "headline": headline,
        "location": location,
        "skills": skills,
    }


def _parse_location(lines, nonblank, name, headline) -> str | None:
    # 1. an explicit "Location:" label wins
    for ln in lines:
        m = _LOCATION_LABEL_RE.match(ln)
        if m and m.group(1).strip():
            return m.group(1).strip()
    # 2. else a "City, Country"-shaped header line whose tail resolves to a country
    for _, ln in nonblank[:8]:
        if ln in (name, headline) or "@" in ln or _URL_RE.search(ln):
            continue
        if "," in ln and normalize_country(ln) is not None:
            return ln
    return None


def _parse_skills(lines) -> list[str]:
    raw: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        key = line.strip().rstrip(":").strip().lower()
        # inline form: "Skills: a, b, c"
        if ":" in line:
            head, _, tail = line.partition(":")
            if head.strip().lower() in _SKILLS_HEADERS and tail.strip():
                raw.append(tail.strip())
                i += 1
                continue
        # section form: a bare "Skills" header, then following lines until a blank
        # line or the next known header
        if key in _SKILLS_HEADERS:
            j = i + 1
            while j < n:
                nxt = lines[j]
                if nxt.strip() == "" or _header_key(nxt):
                    break
                raw.append(nxt)
                j += 1
            i = j
            continue
        i += 1
    tokens: list[str] = []
    for chunk in raw:
        tokens.extend(split_skills(chunk))
    return tokens


class ResumePdfAdapter(SourceAdapter):
    source_name = "resume_pdf"

    def _extract_text(self, path: str) -> str:
        if path.lower().endswith(".pdf"):
            from pypdf import PdfReader  # lazy: .txt use never needs pypdf

            reader = PdfReader(path)
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()

    def _load_impl(self, path: str) -> list[SourceRecord]:
        text = self._extract_text(path)
        if not text.strip():
            # a scanned/image-only PDF yields no text — honest skip, not a crash
            self.report.add_skip(
                f"adapter:{self.source_name}", str(path),
                "no extractable text (scanned/image PDF?)",
            )
            return []
        parsed = parse_resume_text(text)
        return [self._to_record(parsed, 0)]

    def _to_record(self, parsed: dict, index: int) -> SourceRecord:
        flags: list[Flag] = []
        name = parsed["name"]

        emails = self._emails(parsed["emails"], method="resume:contact")
        phones = self._phones(parsed["phones"], method="resume:contact", flags=flags)
        skills = self._skills(parsed["skills"], flags=flags)

        headline = (
            SourceValue(value=parsed["headline"], raw=parsed["headline"], method="resume:heuristic")
            if parsed["headline"]
            else None
        )

        loc_raw = parsed["location"]
        location = (
            SourceValue(
                value={
                    "city": (loc_raw.split(",")[0].strip() or None) if loc_raw else None,
                    "region": None,
                    "country": normalize_country(loc_raw),
                },
                raw=loc_raw,
                method="resume:heuristic",
            )
            if loc_raw
            else None
        )

        return SourceRecord(
            source_name=self.source_name,
            record_id=(emails[0].value if emails else f"{self.source_name}:{index}"),
            full_name=(
                SourceValue(value=name, raw=name, method="resume:heuristic") if name else None
            ),
            emails=emails,
            phones=phones,
            location=location,
            headline=headline,
            skills=skills,
            flags=flags,
        )
