# Candidate Profile Transformation Pipeline

A batch pipeline that ingests candidate data from **four heterogeneous sources**
(recruiter CSV, ATS JSON, GitHub, and résumé PDF), resolves which records belong to
the **same person**, merges them into **one canonical profile per person** with
**per-field provenance and confidence**, and emits output through a
**runtime-configurable projection layer**.

Built for the Eightfold take-home (talent-intelligence domain).

---

## Demo video

> **[▶ Watch the 2-minute demo (TODO: link)]**
>
> The recording runs the pipeline end-to-end on the sample inputs, shows the default
> and custom-config outputs side-by-side, and walks through one design decision
> (trust-ranked conflict resolution) and one edge case handled (per-record poison
> resilience).

---

## Quick start

Requires Python 3.11+. Uses [`uv`](https://github.com/astral-sh/uv) for environment
management, but plain `pip` works too.

```bash
# with uv
uv venv
uv pip install -e ".[dev]"
uv run pytest              # 220 tests, all green

# or with pip
python -m venv .venv
.venv/Scripts/activate     # Windows  (Linux/Mac: . .venv/bin/activate)
pip install -e ".[dev]"
pytest
```

### Run the pipeline — default schema

```bash
uv run candidate-pipeline transform \
  --inputs csv=candidate_pipeline/data/fixtures/recruiter.csv \
           ats=candidate_pipeline/data/fixtures/ats.json \
           github=candidate_pipeline/data/fixtures/github.json \
           resume=candidate_pipeline/data/fixtures/resume.pdf \
  --default-region IN \
  --as-of 2026-06-30 \
  --out profiles.json \
  --report report.json \
  --pretty
```

Writes two files:
- **`profiles.json`** — one projected object per resolved person (`candidate_id`, `full_name`, `emails`, `phones`, `location`, `links`, `headline`, `years_experience`, `skills [{name, confidence, sources[]}]`, `experience`, `education`, `overall_confidence`, `provenance`).
- **`report.json`** — batch audit trail: every skip, conflict, assumption, and count.

### Run with a custom projection config

```bash
uv run candidate-pipeline transform \
  --inputs csv=candidate_pipeline/data/fixtures/recruiter.csv \
           ats=candidate_pipeline/data/fixtures/ats.json \
           github=candidate_pipeline/data/fixtures/github.json \
           resume=candidate_pipeline/data/fixtures/resume.pdf \
  --config candidate_pipeline/data/configs/custom_config.json \
  --default-region IN \
  --as-of 2026-06-30 \
  --pretty
```

Same underlying data, different shape: fields are renamed (`full_name` → `name`),
`skill_names` is a flat `string[]`, `name` carries inline confidence, `location`
carries inline provenance. Pat Morgan is dropped (no email; `primary_email` is
`required: true` in that config — demonstrating `on_missing: error`). No code change.

> Shortcut: `./demo.sh` (default schema) and `./demo.sh custom` wrap the two runs
> above, writing pretty JSON to `sample_output/` with a clean terminal.

### Validate a config file

```bash
uv run candidate-pipeline validate-config \
  --config candidate_pipeline/data/configs/custom_config.json
```

---

## Sample output

Pre-computed output from the commands above is committed at [`sample_output/`](sample_output/):

| File | Description |
|---|---|
| [`sample_output/profiles.json`](sample_output/profiles.json) | 4 profiles, default schema |
| [`sample_output/report.json`](sample_output/report.json) | Batch audit trail |
| [`sample_output/profiles_custom.json`](sample_output/profiles_custom.json) | 3 profiles, custom config (Pat Morgan dropped — no email) |

The pipeline resolves **4 people** from **8 source records** across 4 inputs:

| Person | Sources merged | Overall confidence |
|---|---|---|
| Aisha Khan | CSV + ATS + GitHub + résumé (4 sources) | **0.906** |
| Sri Krishna V | CSV + GitHub, name variants resolved | **0.785** |
| Jordan Lee | GitHub only, sparse | **0.435** |
| Pat Morgan | GitHub only, orphan (no shared identifier) | **0.295** |

Golden files used by the test suite are at [`tests/golden/`](tests/golden/).

---

## CLI flags

| Flag | Purpose |
|---|---|
| `--inputs key=path ...` | One or more sources. Keys: `csv`, `ats`, `github`, `resume`. Use `csv:label=path` for multiple files of one type. |
| `--config cfg.json` | Swap the projection layer. Omit for the built-in default schema. |
| `--default-region CC` | Resolves phones that lack a country code (e.g. recruiter CSV). |
| `--as-of YYYY-MM-DD` | Pins recency decay and `years_experience`. Defaults to today. |
| `--live` | Enriches each GitHub record from the real REST API (`GET /users/{login}/repos`). Falls back to fixture on any error. Set `GITHUB_TOKEN` to raise rate limit to 5,000/hr. |
| `--out path` | Write output JSON to a file (default: stdout). |
| `--report path` | Write the batch audit trail (skips/conflicts/assumptions/counts). |
| `--pretty` | Pretty-print JSON output. |
| `--strict` | Exit non-zero if any profile is dropped at the output stage (`on_missing: error` / required miss). Graceful adapter skips are not strict failures. |

---

## Architecture

```
inputs → adapters → SourceRecords → IdentityResolver → clusters
       → MergeEngine(+ConfidenceScorer) → CanonicalProfiles
       → Projector(+config) → validated dicts → CLI writes JSON
```

with a `RunReport` threaded through every stage.

The hard boundary is **`CanonicalProfile`**: nothing upstream of it knows the
projection config exists, and the `Projector` is the **only** config-aware
component. This keeps "what we know about a person" cleanly separate from "how a
given consumer wants it shaped."

| Layer | Module | Responsibility |
|---|---|---|
| Sources | `sources/` | Parse each raw source → normalized `SourceRecord`; never crash (try/except → skip + log) |
| Normalize | `normalize/` | Deterministic phone/date/country/skill/email normalization |
| Resolve | `resolve/identity.py` | O(n) blocking + precision linking → clusters of one person |
| Merge | `merge/` | Cluster → `CanonicalProfile`; trust-ranked conflict resolution |
| Confidence | `confidence/scorer.py` | All confidence constants + scoring (per-field and overall) |
| Project | `project/` | Apply a config to a profile → flat, validated output dict |
| Config | `config/` | Pydantic models for the config file + loader |
| Models | `models/` | `CanonicalProfile`, `SourceRecord`, `RunReport` |

All tunable numbers live in exactly two places: `confidence/scorer.py` and `merge/trust.py`.

### Sources

Two structured sources (**recruiter CSV**, **ATS JSON**) and two unstructured ones
(**GitHub**, **résumé PDF**):

- **GitHub** mirrors the real REST API shape (`/users/{login}` + `/users/{login}/repos`). Non-fork repo languages canonicalize through the skill alias map and corroborate existing skills. Top-2 repos by stars surface as `links.other[]`. Forks are excluded (their language/stars reflect the upstream project, not the candidate).
- **Résumé PDF** text is extracted via pypdf then parsed with a deterministic heuristic parser (`parse_resume_text`): name, emails, phones, headline, location, skills — each normalized through the same pipeline as every other source. Experience/education parsing stays an extension point; the parser only emits what it's confident about and never fabricates. Trust: **0.75** (above GitHub bio, below CSV/ATS). A scanned/image PDF with no text is an honest skip.

`--live` opts into the real GitHub REST API; any failure falls back to the fixture record (logged to report), so the demo never flakes.

---

## Design rationale

### Trust order & conflict resolution

Single-valued fields (name, current company/title, location) are resolved by
**source trust**: `ATS (0.90) > CSV (0.80) > résumé (0.75) > GitHub (0.70)`.
The winner is kept; losing values are retained as `competitors` in provenance,
never discarded. A conflict raises a `Flag(conflict_resolved)` on the profile
and a `ConflictEntry` in the `RunReport`. Multi-valued fields (skills, emails,
phones) are **unioned and deduped**, not contested.

### Confidence scoring

```
single-valued = clamp01(base + corroboration − extraction_penalty − conflict_penalty) × recency
multi-valued  = clamp01(best_base + corroboration − extraction_penalty) × recency
```

- **corroboration** — +0.05 per additional agreeing source, weighted by independence (ATS↔CSV = 0.5 since they may share an upstream import; anything↔GitHub = 1.0), capped at +0.10.
- **extraction_penalty** — 0.10 for prose/heuristic values (GitHub bio, résumé free-text); 0 for structured.
- **conflict_penalty** — 0.05 when ≥2 distinct values competed (single-valued only).
- **recency** — decays only time-varying fields (company, title, location, headline) by 1% per month stale, capped at 20%.

### Identity resolution

**Blocking** (O(n) hashmap) groups records sharing any of: normalized email, `github_login`, or `name_block_key` (sorted first-letters of name tokens — so "Sri Krishna V", "Sri Krishna Vijayarajan", "V, Sri K." all key to `ksv`). **Linking** then applies positive-evidence tiers: exact email/login links outright; otherwise initial-aware name-token alignment + corroborating identifiers, linked at ≥ 0.70. No all-pairs fuzzy matching — comparisons happen only within a shared block.

### `normalize` in configs is assert-only

All normalization happens deterministically upstream (`normalize/`). A config's
`normalize: "E164"` is a **format assertion**, not a recompute: the projector
verifies the value matches and treats a mismatch as missing. This avoids
double-normalization and silent drift.

### Core principles

Never fabricate a value (year-only dates stay `YYYY`, we never invent a month);
never crash the batch on one bad record; deterministic `candidate_id` (hash of
email → phone → name_block_key) so reruns and golden tests are stable.

---

## Configuration

`data/configs/default_config.json` reproduces the assignment's default output
shape. `data/configs/custom_config.json` renames fields, inlines
confidence/provenance, and reshapes `skills` to a flat `string[]` — all at
runtime with no code change.

The path resolver supports `field`, `field.sub`, `field[].sub` (map over array),
and `field[N]` (index, e.g. `emails[0]`).

### `on_missing` and `--strict`

`on_missing` (`null` / `omit` / `error`) and `required: true` decide what happens
when a projected value is absent. A dropped profile is recorded as a `projection`
skip and the batch continues (exit 0) by default. Pass `--strict` to turn any
output-stage drop into a non-zero exit for CI use. Graceful adapter/record skips
are not strict failures.

---

## Edge cases (each exercised by a fixture + asserted in a test)

| # | Edge case | Where |
|---|---|---|
| 1 | Company conflict → trust winner + competitors + flag | A (ATS > CSV), B (CSV > GitHub) — `test_merge` |
| 2 | Name variants, no shared email → blocked & linked; orphan stays separate | B links by `name_block_key`; Pat Morgan orphaned — `test_identity` |
| 3 | Garbage source → skip, batch continues | `test_garbage_source` |
| 4 | Phone with no country code → `--default-region` + flag + assumption | B's CSV phone — `test_merge` |
| 5 | Partial / "Present" dates → granularity preserved, `years_experience` still computes | A's ATS experience — `test_dates`, `test_merge` |
| 6 | Skill alias + unknown → `ReactJS`→`React`, `C++`/`C#`/`.NET` intact, unknown verbatim + flag | `test_skills`, `test_merge` |

---

## Robustness

Beyond the demo fixtures, synthetic torture fixtures (`data/fixtures/edge/`) and
~95 edge tests probe the pipeline against hostile inputs:

- **Per-record resilience** — one poison row/object is skipped and logged (`record:<source>` in the report); the rest of the file still loads.
- **Shape tolerance** — a top-level JSON object (not an array) is accepted; explicit `null` nested values and non-object array elements degrade gracefully.
- **Encoding tolerance** — UTF-8 BOM stripped in CSV, JSON, and configs; CSV headers matched case/whitespace-insensitively; output always written UTF-8 (so `李明`/`José` never crash stdout).
- **No silent-wrong values** — `mailto:`/trailing-punctuation emails cleaned; an out-of-range month like `2020-13` is rejected, never padded to a fake date; skills split on `, ; | ⏎ ⇥` but not `/` (so `CI/CD` stays intact).
- **Config validation** — duplicate/empty output `path`s are rejected at load time (a duplicate used to silently overwrite — data loss).
- **Multiple files per type** — `--inputs csv:primary=a.csv csv:backfill=b.csv`.

Genuine hard problems are deliberately descoped and pinned by test with a comment: shared inbox linking two different people; `Georgia` the country vs US state; vanity phone letters (`1-800-FLOWERS`).

---

## Testing

```bash
uv run pytest            # 220 tests
```

| Test file | What it covers |
|---|---|
| `test_phone`, `test_dates`, `test_country`, `test_email`, `test_skills` | Per-normalizer units |
| `test_identity` | Variant collapse, orphan isolation, same-block precision |
| `test_merge` | Conflict → asserted winner and confidence |
| `test_confidence` | §9 formula units + the three overall anchors |
| `test_projection` | Default + custom config, assert-only normalize, `on_missing` |
| `test_e2e` | Full run vs golden JSON (canonical + default output) |
| `test_garbage_source` | Malformed source → skip, batch continues |
| `test_normalizers_edge` | Silent-wrong / fabrication class coverage |
| `test_adapter_resilience` | Per-record survival, single-object ATS, null-nested, BOM, non-string scalars |
| `test_core_logic_edge` | Identity (login case, transitive, shared-email), merge safety, confidence clamps, malformed paths |
| `test_config_validation` | Duplicate/empty path rejected, BOM config, bad type/on_missing |
| `test_torture_e2e` | All edge fixtures at once → survives, schema-valid, no fabrication, deterministic |
| `test_cli_strict` | `--strict` turns an output-stage drop into a non-zero exit |

Golden files (`tests/golden/`) are the contract. Edge suites assert **invariants**
(counts, "no crash", "missing → null"), not memorized outputs.

---

## Descoped (deliberate, with clear extension points)

| What | Why descoped | Extension point |
|---|---|---|
| LinkedIn / recruiter notes | No public API / NLP-heavy | Another `SourceAdapter` in the same registry; `link_hints` already accommodates a LinkedIn URL |
| Résumé experience/education | Free-form date parsing is unreliable; lean scope chosen | `parse_resume_text` section-aware parser is where that logic slots in |
| Fuzzy / embedding name matching | Alias-map + blocking is deterministic; fuzzy adds non-determinism | Identity linker's tiered structure has a clean insertion point |
| Embedding-based skill canonicalization | Alias map covers common vocabulary; long tail needs model | `canonicalize_skill` has a single insertion point for an optional embedding fallback before verbatim; method would be `normalize:skill-embedding`; OFF by default so goldens stay byte-identical |
| Recency decay when no timestamp | Fully implemented; documented as ×1.0 when `last_updated` absent | Already wired via the `last_updated` hook |

## Known limitations

- A GitHub record with no email/login and a non-aligning name stays **orphaned** (Pat Morgan in the fixtures). Fuzzy name matching is the production extension.
- Free-text country resolution is best-effort; ambiguous tokens (e.g. bare state code) may not resolve — country is left `null` with raw value preserved.
