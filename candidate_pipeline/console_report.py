"""Human-facing terminal rendering for the CLI (rich).

Everything here writes to **stderr** on purpose: stdout carries the JSON
output, which must stay pure so `| jq` and file redirects keep working. When
stderr is not an interactive terminal (piped, CI, captured by tests), the CLI
falls back to a plain `key=value` line instead of these tables, so logs stay
stable and grep-able.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

# Source keys as they appear in provenance -> short display labels.
_SOURCE_LABELS = {
    "recruiter_csv": "CSV",
    "ats_json": "ATS",
    "github_api": "GitHub",
    "resume_pdf": "résumé",
}


def _confidence_style(value: float) -> str:
    if value >= 0.80:
        return "bold green"
    if value >= 0.50:
        return "yellow"
    return "red"


def _profile_sources(profile) -> list[str]:
    """Union of contributing sources across a profile's tracked values,
    in first-seen order, mapped to short display labels."""
    seen: list[str] = []

    def add(tracked) -> None:
        if tracked is None:
            return
        for src in getattr(tracked, "sources", None) or []:
            if src not in seen:
                seen.append(src)

    add(profile.full_name)
    add(profile.location)
    add(profile.links)
    add(profile.headline)
    for tracked in (*profile.emails, *profile.phones, *profile.skills):
        add(tracked)

    return [_SOURCE_LABELS.get(src, src) for src in seen]


def render_run_summary(console: Console, profiles: list, report) -> None:
    """A table of resolved profiles plus a one-line batch summary."""
    table = Table(title="Resolved profiles", title_style="bold", header_style="bold cyan")
    table.add_column("Candidate")
    table.add_column("Sources")
    table.add_column("Confidence", justify="right")
    table.add_column("Flags")

    for profile in sorted(profiles, key=lambda p: p.overall_confidence, reverse=True):
        name = profile.full_name.value if profile.full_name else "(unknown)"
        sources = " + ".join(_profile_sources(profile)) or "-"
        conf = Text(f"{profile.overall_confidence:.3f}", style=_confidence_style(profile.overall_confidence))
        flag_kinds = sorted({flag.kind for flag in profile.flags})
        flags = Text(", ".join(flag_kinds), style="yellow") if flag_kinds else Text("-", style="dim")
        # Text() (not str) so hostile field values are never parsed as rich markup.
        table.add_row(Text(name), Text(sources), conf, flags)

    console.print()
    console.print(table)

    counts = report.counts
    skipped = counts.get("sources_skipped", 0)
    summary = Text()
    summary.append(f"{counts.get('profiles_out', 0)} profiles", style="bold")
    summary.append(f" from {counts.get('records_in', 0)} records")
    summary.append("  ·  ")
    summary.append(
        f"{skipped} sources skipped",
        style="red" if skipped else "dim",
    )
    if report.conflicts:
        summary.append("  ·  ")
        summary.append(f"{len(report.conflicts)} conflict(s) resolved", style="yellow")
    if report.assumptions:
        summary.append("  ·  ")
        summary.append(f"{len(report.assumptions)} assumption(s)", style="yellow")
    console.print(summary)


def render_config_ok(console: Console, field_count: int, on_missing: str) -> None:
    console.print(
        Text("OK", style="bold green")
        + Text(f"  {field_count} fields, on_missing={on_missing}")
    )


def render_config_invalid(console: Console, message: str) -> None:
    console.print(Text("INVALID", style="bold red") + Text(f"  {message}"))
