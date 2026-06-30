# GitHub repos & languages ingestion — design

**Date:** 2026-06-30
**Context:** The assignment's source spec lists the GitHub profile as exposing
`name, bio, repos, languages`. The current adapter ingests only the
`/users/{login}` scalar fields (`login, name, company, location, bio, blog,
email`). `repos` and `languages` are absent. This adds them, modeled exactly as
the real GitHub REST API surfaces them, while keeping the no-network static
fixture stance (PRD §4.3 / §18).

## Goal

Make the GitHub adapter behave as it would against the live API: aggregate
languages from a user's repositories into the candidate's skills, and surface
notable repositories as profile links. No live calls — the repo list ships in
the fixture, shaped like `GET /users/{login}/repos`.

## Design decisions (confirmed with user)

1. **Languages feed `skills` (and repos feed `links`).** Each distinct repo
   `language` is canonicalized through the *existing* `canonicalize_skill`
   alias map and merged into the canonical `skills` list, identical to a CSV/ATS
   skill. The merge engine's corroboration logic (§9.2) then naturally rewards
   agreement when a language matches an already-listed skill. Additionally, the
   top non-fork repos by star count are surfaced as URLs in `links.other[]`.
   No new top-level canonical schema field — repos are an *input*, not an output.

2. **Forks are excluded from both signals.** A fork's language and stars reflect
   the upstream project, not the candidate's own work, so forked repos
   contribute neither languages (skills) nor notable-repo links.

## Fixture shape

Each GitHub object gains an optional `repos` array mirroring the trimmed
`GET /users/{login}/repos` response:

```json
"repos": [
  { "name": "payments-api", "language": "Go", "fork": false, "stargazers_count": 142, "html_url": "https://github.com/aishakhan/payments-api" }
]
```

Only `name`, `language`, `fork`, `stargazers_count`, `html_url` are kept (the
fields we use). A missing/empty `repos` is valid (older fixture entries stay as
they are functionally — but all main-fixture entries get repos for realism).

## Adapter logic (`sources/github_api.py`)

For each object, after the existing scalar parsing:

1. Iterate `repos` (tolerate non-list → treat as empty; non-dict entry → skip).
2. For each repo, read `fork` (coerce non-bool/missing → `False` only if
   genuinely false-y; a truthy non-bool is treated as a fork to be safe — i.e.
   `bool(fork)`). **Skip forks.**
3. From non-fork repos:
   - Collect distinct `language` values (case-insensitive dedup, ignore
     null/non-str). Feed each through `self._skills(...)` (the shared helper that
     runs `canonicalize_skill`), producing `SourceRecord.skills` with method
     `normalize:skill-alias` (canonical) or `verbatim` (unknown, flagged).
   - Select the **top 2 by `stargazers_count`** (descending; tie-break by name
     for determinism), store their `html_url` in
     `link_hints["notable_repos"]` (a list).

Robustness matches the rest of the adapter: a malformed repo entry never crashes
the record; the record is still produced with whatever survived.

## Merge surfacing (`merge/engine.py`)

- Skills already flow through `merge_multi_valued` unchanged — a GitHub repo
  language that matches an existing skill corroborates it; a new one becomes a
  GitHub-only skill at 0.70 (0.60 + flag if unmapped).
- `_merge_links` appends every `link_hints["notable_repos"]` URL (deduped,
  order-preserved) into the existing `links.value["other"]` list, and the
  return guard gains `or value["other"]` so a repos-only link set still emits.

## Fixture data (main `github.json`)

| Candidate (`login`) | Non-fork repos (lang, ★) | Fork repos | Resulting effect |
|---|---|---|---|
| Aisha Khan (`aishakhan`) | payments-api (Go, 142), checkout-service (Python, 58) | dotfiles (Shell) | Go = new GitHub-only skill; Python corroborated to 3 sources; fork excluded; 2 notable links |
| Sri Krishna (`sri-krishna`) | distributed-scheduler (Go, 230), k8s-operators (Go, 95), raft-consensus (Java, 12) | — | Java corroborates CSV Java; top-2-by-stars caps links to the two Go repos |
| Jordan Lee (`jlee`) | task-queue (Python), api-gateway (Go) | — | GitHub-only person → both skills at 0.70 |
| Pat Morgan (`ghost-coder`) | — | forked-cms (PHP) | Only repo is a fork → zero language signal, stays sparse/low-confidence |

## Test & golden impact

- **Intentional ground-truth change:** `test_merge.py` asserts Aisha's
  `skills["Python"] == 0.925` (2-source ATS+CSV). With GitHub now also
  contributing Python it becomes 3-source:
  `0.90 + 0.05×0.5 (CSV) + 0.05×1.0 (GitHub) = 0.975`. Update the literal with a
  comment. This is recomputed truth from intentionally changed fixtures, not a
  loosened assertion.
- The three confidence anchors (~0.88 / ~0.78 / ~0.42) are **unaffected** —
  `overall_confidence` does not weight skills (§9.4).
- New adapter unit tests: language→skill, fork exclusion (skills + links),
  notable-repo link, top-2-by-stars cap.
- `github_messy.json` gains a malformed-`repos` case (non-list / non-dict entry
  / junk language type / non-bool fork) + a no-crash assertion. Record count
  stays 4 so existing resilience assertions hold.
- Regenerate `tests/golden/canonical.json` and `profiles_default.json` by
  re-running the pipeline (skills/links arrays change for github-touched
  profiles). Golden files are regenerated deliberately, not by loosening tests.
- One-line README/docstring note: GitHub now also ingests `repos`/`languages`.

## Out of scope

- No live API call (`--live` stays a no-op stub per PRD §4.3).
- No new canonical schema field for raw repos (§10 schema unchanged).
