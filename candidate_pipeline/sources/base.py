"""SourceAdapter ABC (PRD §5).

The public `load` wraps the subclass `_load_impl` in try/except so a bad source
never crashes the run: it records a SkipEntry and returns []. Subclasses also get
shared helpers for building normalized identity values.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from candidate_pipeline.models.canonical import Flag
from candidate_pipeline.models.report import RunReport
from candidate_pipeline.models.source_record import SourceRecord, SourceValue
from candidate_pipeline.normalize.email import normalize_email
from candidate_pipeline.normalize.phone import normalize_phone
from candidate_pipeline.normalize.skills import canonicalize_skill


class SourceAdapter(ABC):
    source_name: str

    def __init__(self, report: RunReport | None = None, default_region: str | None = None):
        self.report = report if report is not None else RunReport()
        self.default_region = default_region

    def load(self, path: str) -> list[SourceRecord]:
        try:
            return self._load_impl(path)
        except Exception as exc:  # noqa: BLE001 - robustness: never crash the batch
            self.report.add_skip(
                f"adapter:{self.source_name}", str(path), f"{type(exc).__name__}: {exc}"
            )
            return []

    @abstractmethod
    def _load_impl(self, path: str) -> list[SourceRecord]:
        ...

    # ---- shared robustness helpers -----------------------------------------

    @staticmethod
    def _as_record_list(data) -> list:
        """Tolerate a top-level shape that is a single object or a list.

        Many real ATS / API payloads are a single object rather than an array;
        wrapping it keeps one odd shape from skipping the whole source. Anything
        that is neither a list nor a dict yields no records (the caller logs it).
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        return []

    def _record_skip(self, path: str, index: int, exc: Exception) -> None:
        """Log a per-record skip so one poison record never drops the rest."""
        self.report.add_skip(
            f"record:{self.source_name}", f"{path}#{index}", f"{type(exc).__name__}: {exc}"
        )

    # ---- shared normalization helpers --------------------------------------

    def _emails(self, raws, method: str) -> list[SourceValue]:
        out: list[SourceValue] = []
        for raw in raws:
            norm = normalize_email(raw)
            if norm is None:
                if raw:
                    self.report.add_skip("normalize:email", str(raw), "invalid email shape")
                continue
            out.append(SourceValue(value=norm, raw=raw, method=method))
        return out

    def _phones(self, raws, method: str, flags: list[Flag]) -> list[SourceValue]:
        out: list[SourceValue] = []
        for raw in raws:
            if raw is None or str(raw).strip() == "":
                continue
            res = normalize_phone(str(raw), default_region=self.default_region)
            out.append(SourceValue(value=res.value, raw=res.raw, method=res.method))
            if res.flag is not None:
                flags.append(res.flag)
        return out

    def _skills(self, raws, flags: list[Flag]) -> list[SourceValue]:
        out: list[SourceValue] = []
        for raw in raws:
            res = canonicalize_skill(raw)
            out.append(SourceValue(value=res.value, raw=res.raw, method=res.method))
            if res.flag is not None:
                flags.append(res.flag)
        return out
