# Candidate Profile Transformation Pipeline

A batch pipeline that ingests candidate data from **three heterogeneous sources**,
resolves which records belong to the **same person**, merges them into **one
canonical profile per person** with **per-field provenance and confidence**, and
emits output through a **runtime-configurable projection layer**.

Built for the Eightfold take-home (talent-intelligence domain). The full
specification lives in [`prd.md`](prd.md); this README covers how to run it, the
architecture, the design rationale, and the deliberate descopes.

---

## Quick start

The project uses [`uv`](https://github.com/astral-sh/uv) for environment
management, but it is a standard `pyproject.toml` package, so plain `pip` works too.

```bash
# with uv
uv venv
uv pip install -e ".[dev]"
uv run pytest                     # 101 tests, all green

# or with pip
python -m venv .venv && . .venv/Scripts/activate   # .venv/bin/activate on POSIX
pip install -e ".[dev]"
pytest
```

### Run the pipeline

```bash
uv run candidate-pipeline transform \
  --inputs csv=candidate_pipeline/data/fixtures/recruiter.csv \
           ats=candidate_pipeline/data/fixtures/ats.json \
           github=candidate_pipeline/data/fixtures/github.json \
  --default-region IN \
  --as-of 2026-06-30 \
  --out profiles.json \
  --report report.json \
  --pretty
```

- `--config cfg.json` swaps the projection layer (default: built-in PS-style schema).
- `--default-region IN` resolves phones that lack a country code (e.g. the recruiter CSV).
- `--as-of YYYY-MM-DD` pins recency decay and `years_experience` (omit → today).
- `--live` is a **no-op GitHub stub** that defaults to the fixture, so the demo never flakes.
- `--report` writes the batch audit trail (skips / conflicts / assumptions / counts).

```bash
uv run candidate-pipeline validate-config --config candidate_pipeline/data/configs/custom_config.json
```

---

## Architecture

**Data flow (one line):**

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

All tunable numbers live in exactly two places: `confidence/scorer.py` and
`merge/trust.py`.

---

## Design rationale

### Trust order & conflict resolution
Single-valued fields (name, current company/title, location) are resolved by
**source trust**: `ATS (0.90) > recruiter CSV (0.80) > GitHub (0.70)`. The winner
is kept; losing values are **retained as `competitors` in provenance**, never
discarded. A conflict raises a `Flag(conflict_resolved)` on the profile and a
`ConflictEntry` in the `RunReport`. Multi-valued fields (skills, emails, phones)
are **unioned and deduped**, not contested.

### Confidence (the §9 formulas)
```
single-valued = clamp01(base + corroboration − extraction_penalty − conflict_penalty) × recency
multi-valued  = clamp01(best_base + corroboration − extraction_penalty) × recency
```
- **corroboration** +0.05 per *additional* agreeing source, weighted by independence
  (ATS↔CSV count 0.5 — they may share an upstream import; anything↔GitHub counts 1.0), capped at +0.10.
- **extraction_penalty** 0.10 for prose/heuristic values (GitHub bio, free-text location); 0 for structured.
- **conflict_penalty** 0.05 when ≥2 distinct values competed (single-valued only).
- **recency** decays only **time-varying** fields (company, title, location, headline) —
  never stable identifiers — by 1% per month stale, capped at 20%.

The three engineered fixtures land almost exactly on the PRD's anchor targets:

| Profile | Shape | Overall confidence | Target |
|---|---|---|---|
| Aisha Khan | 3-source, corroborated, one stale conflict | **0.886** | ~0.88 |
| Sri Krishna V | 2-source, company conflict, name variants | **0.785** | ~0.78 |
| Jordan Lee | sparse GitHub-only, stale | **0.435** | ~0.42 |

### Identity resolution
**Blocking** (high recall, O(n) hashmap) groups records sharing any of: normalized
email, github_login, or `name_block_key` (sorted first-letters of name tokens — so
"Sri Krishna V", "Sri Krishna Vijayarajan", "V, Sri K." all key to `ksv`).
**Linking** (precision) then decides real matches with positive-evidence tiers:
exact email/login links outright; otherwise initial-aware, order-independent
name-token alignment plus corroborating identifiers (shared phone), linked at
`≥ 0.70`. There is **no all-pairs fuzzy matching** — comparisons happen only
within a shared block.

### `normalize` in configs is assert-only
All normalization happens deterministically upstream (`normalize/`). A config's
`normalize: "E164"` is therefore a **format assertion**, not a recompute: the
projector verifies the value matches and treats a mismatch as **missing**. This
avoids double-normalization and silent drift.

### Provenance vs flags vs report
- **Per-field provenance** (`ProvenanceEntry`): where each value came from (source + method + raw + normalized).
- **Per-profile flags** (`Flag`): conflict_resolved, assumed_region, uncanonicalized_skill.
- **Batch `RunReport`**: skips, conflicts, assumptions, counts — the run-level audit trail.

### Core principles, everywhere
Never fabricate a value (year-only dates stay `YYYY`, we never invent a month);
never crash the batch on one bad record (a malformed source becomes a skip);
deterministic `candidate_id` (hash of email → phone → name_block_key) so reruns
and golden tests are stable.

---

## Configuration

`data/configs/default_config.json` reproduces the assignment's default output
shape verbatim — `candidate_id, full_name, emails, phones, location, links,
headline, years_experience, skills ({name, confidence, sources[]}), experience,
education, overall_confidence`, plus a top-level `provenance` aggregate.

`data/configs/custom_config.json` proves the layer is real: it renames fields,
inlines confidence/provenance, and reshapes `skills` to a flat `string[]` — all at
runtime, **with no code change**. The path resolver supports `field`,
`field.sub`, `field[].sub` (map), and `field[N]` (index, e.g. `emails[0]`).

---

## Edge cases (each exercised by a fixture + asserted in a test)

| # | Edge case | Where |
|---|---|---|
| 1 | Company conflict → trust winner + competitors + flag | A (ATS>CSV), B (CSV>GitHub) — `test_merge` |
| 2 | Name variants, no shared email → blocked & linked; orphan stays separate | B links by `name_block_key`; Pat Morgan orphaned — `test_identity` |
| 3 | Garbage source → skip, batch continues | `test_garbage_source` |
| 4 | Phone with no country code → `--default-region` + flag + assumption | B's CSV phone — `test_merge` |
| 5 | Partial / "Present" dates → granularity preserved, `years_experience` still computes | A's ATS experience — `test_dates`, `test_merge` |
| 6 | Skill alias + unknown → `ReactJS`→`React`, `C++`/`C#`/`.NET` intact, unknown verbatim + flag | `test_skills`, `test_merge` |

---

## Testing

```bash
uv run pytest            # 101 tests
```

- **Per-normalizer units** (phone, dates, country, skills incl. the C++/C#/.NET table, email)
- **`test_identity`** — variant collapse, orphan isolation, same-block-different-person precision
- **`test_merge`** — conflict → asserted winner *and* confidence
- **`test_confidence`** — §9 formula units + the three overall anchors
- **`test_projection`** — default + custom config, assert-only normalize, on_missing semantics
- **`test_e2e`** — full run compared against golden JSON (canonical + default output)
- **`test_garbage_source`** — malformed source → skip, batch continues

Golden files (`tests/golden/`) are the contract; an intentional change is
regenerated deliberately, never papered over by loosening an assertion.

---

## Descope (pluggable modules, not gaps)

Each cut is a deliberate judgment call; the seams to extend them already exist.

- **LinkedIn / résumé / recruiter notes** — no public API / NLP-heavy; modeled as
  additional `SourceAdapter`s the registry can add behind the same seam. The
  adapter interface and `link_hints` (for a LinkedIn URL) already accommodate them.
- **Fuzzy / embedding name matching** — the identity linker's tiered structure
  leaves a clean insertion point; alias-map + blocking is the deterministic choice
  for this scope.
- **Embedding-based skill similarity** — production path for the long tail; the
  alias map handles the common vocabulary deterministically today.
- **Recency decay** — fully implemented via the `last_updated` hook; documented as
  a no-op (×1.0) when a source lacks reliable timestamps.

## Known limitations

- A GitHub record with no email/login and a non-aligning name stays **orphaned**
  (its own cluster) — see Pat Morgan in the fixtures. Fuzzy name matching is the
  production extension.
- Free-text country resolution is best-effort; ambiguous tokens (e.g. a bare state
  code) may not resolve, in which case the country is left `null` and the raw value
  is preserved.
