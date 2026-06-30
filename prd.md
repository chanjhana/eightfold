# PRD — Candidate Profile Transformation Pipeline

**Owner:** Krijan
**Context:** Eightfold take-home assignment (talent-intelligence domain)
**Audience for this doc:** an engineer (or Claude Code) implementing the full pipeline from scratch
**Language / stack:** Python 3.11+, Pydantic v2, `phonenumbers`, `python-dateutil`, `pycountry`, `pytest`

> **How to read this PRD.** Every architectural decision is already made — do **not** re-litigate them. Where a number, constant, key name, or behavior is specified, treat it as a hard contract. Build in the milestone order in §17. When something is ambiguous in code, prefer the explicit example in this doc over your own judgment.

---

## 1. Goal & "Definition of Done"

Build a batch pipeline that ingests candidate data from **three heterogeneous sources**, resolves which records belong to the **same person**, merges them into **one canonical profile per person**, attaches **per-field provenance and confidence**, and emits output through a **runtime-configurable projection layer**.

**Done means all of the following exist and pass:**

1. A working Python package `candidate_pipeline/` with the module layout in §3.
2. Synthetic fixtures (§4) covering every featured edge case in §15.
3. A CLI (§12) that runs end-to-end: `transform --inputs csv=… ats=… github=… [--config …] --out … --report …`.
4. A **golden-profile** test plus unit tests for every normalizer and a garbage-source test (§16) — all green.
5. A `README.md` explaining how to run it, the architecture, and the descope rationale (§17 framing).

**Core principles (apply everywhere):** never fabricate a value, never crash the batch on one bad record, always be honest about what failed and why (skip + log). These map directly to the assignment's three constraints — **deterministic & explainable** (stable `candidate_id` + per-field provenance/method), **robust** (skip + log; unknown ⇒ null/verbatim, never invented), and **scale** (O(n) blocking in §7, fine on thousands of candidates).

---

## 2. Tech Stack & Project Setup

- **Python** 3.11+
- **Pydantic v2** — all models, config validation, and dynamic output validation (`create_model`)
- **phonenumbers** — phone → E.164
- **python-dateutil** — lenient date parsing
- **pycountry** — country → ISO-3166 alpha-2
- **pytest** — tests
- Packaging: `pyproject.toml`, installable in editable mode (`pip install -e .`). Entry point `candidate-pipeline` → `candidate_pipeline.cli:main`.

No network calls at runtime (GitHub is a static fixture; see §4). Keep all tunable numbers as named constants in **one module** (`confidence/scorer.py` constants block + `merge/trust.py`).

---

## 3. Repository Structure (build exactly this)

```
candidate_pipeline/
  cli.py                  # argparse: `transform` / `validate-config`
  pipeline.py             # orchestration (the only place stages are wired together)
  config/
    schema.py             # ProjectionConfig, FieldSpec (Pydantic models for the config file)
    loader.py             # load + validate a config JSON into ProjectionConfig
  models/
    canonical.py          # TrackedValue[T], TrackedExperience, TrackedEducation, CanonicalProfile, Flag
    source_record.py      # SourceRecord (the normalized per-source intermediate)
    report.py             # RunReport, SkipEntry, ConflictEntry, Assumption
  sources/
    base.py               # SourceAdapter ABC
    recruiter_csv.py
    ats_json.py
    github_api.py         # reads a cached JSON fixture; --live flag optional/no-op stub
    registry.py           # maps --inputs keys -> adapter classes
  normalize/
    phone.py  dates.py  country.py  skills.py  email.py
    aliases.json          # skill alias map
  resolve/
    identity.py           # blocking + linking
  merge/
    engine.py  strategies.py  trust.py
  confidence/
    scorer.py             # all confidence constants + scoring functions
  project/
    resolver.py           # minimal path resolver (field, field.sub, field[].sub)
    projector.py          # applies a ProjectionConfig to a CanonicalProfile
    validator.py          # builds a Pydantic model from config, validates output
  data/
    fixtures/             # synthetic source inputs (§4)
    configs/              # default_config.json + at least one custom config
tests/
  test_phone.py test_dates.py test_country.py test_skills.py test_email.py
  test_identity.py test_merge.py test_confidence.py test_projection.py
  test_e2e.py test_garbage_source.py
  golden/                 # expected canonical/output JSON for the e2e fixture
README.md
pyproject.toml
```

**Data flow (one line):**
`inputs → adapters → SourceRecords → IdentityResolver → clusters → MergeEngine(+ConfidenceScorer) → CanonicalProfiles → Projector(+config) → validated dicts → CLI writes JSON`, with `RunReport` threaded throughout.

**The canonical/projection boundary is at `CanonicalProfile`.** Nothing upstream of it knows config exists. `Projector` is the **only** config-aware component.

---

## 4. Data Sources & Synthetic Fixtures

Three sources. Generate synthetic fixtures (no real data). Design them so they **deliberately disagree** in places — that is what gives the merge engine something to resolve.

> The assignment requires **at least one structured and at least one unstructured** source. These three satisfy that: **Recruiter CSV** and **ATS JSON** are the *structured* sources; **GitHub** (free-text `bio` / `company` / `location`) is the *unstructured* representative. LinkedIn / résumé / recruiter-notes are deliberately descoped as pluggable adapters behind the same `SourceAdapter` seam (§18).

### 4.1 Recruiter CSV (`data/fixtures/recruiter.csv`) — structured anchor
Columns: `full_name, email, phone, current_company, current_title, city, country, skills`
- `skills` is a comma- or semicolon-separated string (mix casings/aliases, e.g. `ReactJS, node.js, C++`).
- Phone often **without** country code (forces `--default-region`).
- This is the identity anchor — clean name + email + phone per row.

### 4.2 ATS JSON (`data/fixtures/ats.json`) — structured, field-mapping challenge
A list of objects whose field names **do not match** the canonical schema (the adapter maps them). Include:
- `candidate.fullName`, `candidate.emails[]`, `candidate.phoneNumbers[]`
- `employment.current.employer`, `employment.current.role`
- `experience[]` with `{ employer, role, startDate, endDate, summary }` where dates are a **mix** of `YYYY-MM`, year-only `YYYY`, and `"Present"` / `""`.
- `education[]` with `{ school, degree, fieldOfStudy, endYear }`
- `location { city, region, country }`
- `skills[]`
- Optional `last_updated` ISO timestamp per record (drives recency decay — see §9).

ATS is **highest trust** (§8). Make at least one ATS value disagree with CSV (e.g. different `current_company`).

### 4.3 GitHub REST-API fixture (`data/fixtures/github.json`) — unstructured-ish
Shape mirrors the GitHub `/users/{login}` payload: `{ login, name, company, location, bio, blog, email, ... }`.
- `company` / `location` / `bio` are free-text and should **conflict** with CSV/ATS in at least one record (verifiable-but-stale style).
- Some GitHub records have **no email** → they become "orphaned" and may not link (documented limitation, §15 #2).
- `--live` is an optional flag that would hit the real API; ship it as a **no-op stub that defaults to the fixture** so the demo never flakes.

### 4.4 Coverage requirement
Across the fixtures, include **at least 3 candidates** that exercise:
- a clean 3-source corroborated profile (high confidence ~0.88),
- a 2-source profile with one conflict (mid confidence ~0.78),
- a sparse / GitHub-orphan / stale profile (low confidence ~0.42).

These three target overall scores are the **golden test anchors** (§16).

---

## 5. Source Adapters (`sources/`)

`SourceAdapter` ABC (`base.py`) with:
```python
class SourceAdapter(ABC):
    source_name: str            # "ats_json" | "recruiter_csv" | "github_api"
    @abstractmethod
    def load(self, path: str) -> list[SourceRecord]: ...
```
- Each adapter parses its raw input and returns a list of `SourceRecord` (normalized intermediate, §6).
- **Robustness:** wrap the whole `load` in try/except. On failure, append a `SkipEntry` to the `RunReport` and return `[]`. A bad source must never crash the run.
- `registry.py` maps CLI keys (`csv`, `ats`, `github`) → adapter classes.

**`SourceRecord`** (`models/source_record.py`) holds the per-source, post-normalization view of one record: identity fields (name, emails, phones, github_login), flat current company/title, `experience[]`, `education[]`, `location`, `skills[]`, plus the `source_name` and optional `last_updated`. Every field carries the **raw** value alongside the normalized one so provenance can record both.

---

## 6. Normalization Layer (`normalize/`) — all deterministic

| Normalizer | Rule |
|---|---|
| **phone.py** | E.164 via `phonenumbers`. Three cases: (a) the number carries an explicit country code → `normalize:e164`, no flag; (b) no country code but config `default_region` is set → apply it, method `assume:default_region` + `Flag(assumed_region)`; (c) no country code **and** no `default_region` → keep `raw`, emit no E.164, no flag. Never silently guess a region. |
| **dates.py** | Output `YYYY` or `YYYY-MM`. `"Present"`, `""`, `None` → `None` (ongoing). Use `dateutil` leniently; preserve granularity (don't invent a month). **Deliberate refinement of the schema's `YYYY-MM` hint:** we keep year-only as `YYYY` rather than fabricate `-01`, because inventing a month would violate "never fabricate a value." The projection `format` assertion accepts both forms. |
| **country.py** | ISO-3166 **alpha-2** via `pycountry`, best-effort on free text. Unresolvable → `None` but keep `raw`. |
| **skills.py** | **Alias map checked on the RAW string first** (`aliases.json`), then normalize for match: lowercase, strip dots/hyphens/spaces, **preserve `+` and `#`**. Re-check alias map. Unknown skills kept **verbatim** at lower confidence + `Flag(uncanonicalized_skill)`. This ordering is what prevents `C++`, `C#`, `.NET` collapsing to `"c"`. |
| **email.py** | Lowercase + validate basic shape. Invalid → drop that email value (not the record), log. |

`aliases.json` seed examples: `{"reactjs": "React", "react.js": "React", "node.js": "Node.js", "nodejs": "Node.js", "py": "Python", ...}`. The map is keyed on the **normalized-for-match** form except where raw-symbol preservation matters; the lookup tries raw first, then normalized.

---

## 7. Identity Resolution (`resolve/identity.py`)

Two phases: **blocking** (high recall) then **linking** (precision). O(n) hashmap grouping — **no pairwise fuzzy over all records.**

### 7.1 Blocking keys (union — any shared key co-blocks two records)
- normalized **email**
- **github_login**
- **name_block_key** — sorted set of the first letter of every name token:
```python
def name_block_key(name: str) -> str:
    toks = re.sub(r"[^a-z\s]", " ", strip_accents(name).lower()).split()
    return "".join(sorted({t[0] for t in toks}))
# "Sri Krishna V", "Sri Krishna Vijayarajan", "V, Sri K." -> all "ksv"
```

### 7.2 Linking (within a block, decide if two records are the same person)
Use **positive evidence tiers** with named constants — never a fragile weighted sum, and **never penalize** mismatches on time-varying attributes (company/title/location change over time):

```python
INITIAL_MATCH     = 0.60   # baseline when blocked together
NAME_STRONG       = 0.85   # strong name-token alignment
NAME_WITH_CORROB  = 0.70   # name + a corroborating signal (shared phone/login)
LINK_THRESHOLD    = 0.70   # >= links into the same cluster
```
- **Exact email match** or **exact github_login match** → link outright.
- Otherwise score by name-token alignment (survives initials & reordering) and corroborating identifiers (shared phone). Link if `>= LINK_THRESHOLD`.
- Output: clusters (lists of `SourceRecord`s), one cluster per resolved person.

**Known limitation to document:** GitHub records with no email/login and a name that doesn't align stay **orphaned** (their own cluster). Fuzzy/embedding name matching is the production extension. State this in the README.

---

## 8. Merge Engine (`merge/`)

Input: one cluster (records about one person). Output: one `CanonicalProfile` with `TrackedValue`s.

### 8.1 Trust order (single-valued field conflicts)
`merge/trust.py`:
```python
SOURCE_TRUST = {"ats_json": 0.90, "recruiter_csv": 0.80, "github_api": 0.70}
# tie-break / precedence: ATS > CSV > GitHub
```
For a single-valued field (name, current company, current title, location), the **highest-trust source wins**; losing values are retained in provenance, not discarded.

### 8.2 Field-type strategies (`strategies.py`)
- **Single-valued** (name, current_company, current_title, location): trust ranking → winner; record competitors.
- **Multi-valued** (skills, emails, phones): **union + dedup** (canonicalized). Canonical stores each as a confidence-sorted `list[TrackedValue[str]]` (§10); the **projection layer** flattens these to the assignment's output shapes — a confidence-sorted `string[]` for emails/phones, and `{name, confidence, sources[]}` for skills.
- **`links`** (`{linkedin, github, portfolio, other[]}`): assembled from source identifiers — `github_login` → `https://github.com/{login}`, GitHub `blog` → `portfolio`, LinkedIn URL when a (descoped) source supplies one. Union, no conflict contest.
- **`headline`** (single-valued, time-varying): sourced from prose (e.g. GitHub `bio`) → `extraction_penalty` 0.10 + recency applies (§9.1/§9.3); `None` when no source provides one.
- **`experience[]`**: dedup on key `company+title+start`; merge sub-fields per-source-tracked.
- **`education[]`**: dedup on key `institution+degree`.
- **Flat current employer/title** from CSV/ATS reconcile into the **current** `experience[]` entry (the one with `end == None`); that entry is the **single source of truth** for current company/title (it is what §9.4 scores). Do **not** add duplicate top-level fields.

### 8.3 `years_experience`
Computed as a **merged interval** over all `experience[]` date ranges (union of intervals, summed), **pinned to an `as_of` date** (default = run date). Ongoing entries (`end == None`) run to `as_of`. Partial dates: `YYYY` → treat as Jan; `YYYY-MM` → that month.

---

## 9. Confidence Scoring (`confidence/scorer.py`)

Every write produces a `TrackedValue` with a `confidence`. **All constants live here.**

### 9.1 Single-valued field formula
```
field_confidence = clamp01( base + corroboration − extraction_penalty − conflict_penalty ) × recency_factor
```

| Term | Value |
|---|---|
| **base** (winning source) | ATS 0.90 · CSV 0.80 · GitHub 0.70 |
| **corroboration** | +0.05 per *additional* agreeing source × independence_weight, **capped at +0.10** |
| **independence_weight** | ATS↔CSV = 0.5 (possible shared import) · any↔GitHub = 1.0 |
| **extraction_penalty** | structured field 0.00 · prose/heuristic (github bio, free-text location) 0.10 |
| **conflict_penalty** | 0.05 if ≥2 distinct value-clusters competed *(single-valued only)* |
| **recency_factor** | ×1.0 default; with `last_updated`: ×(1 − min(0.2, months_stale × 0.01)) |

### 9.2 Multi-valued (per value, e.g. each skill)
```
clamp01( best_base + corroboration − extraction_penalty ) × recency
```
No conflict penalty (it's a union, not a contest). Skills are not time-varying, so `recency` = ×1.0 here (§9.3); the term is kept only for symmetry with §9.1. Examples:
- `"Python"` from GitHub(0.70)+ATS(0.90), independence 1.0 → 0.90 + 0.05 = **0.95**
- GitHub-only skill → **0.70**
- unknown kept verbatim → 0.70 − 0.10 = **0.60**, flagged.

### 9.3 Recency scope
Recency decay applies **only to time-varying fields**: current company, current title, location, headline. **Never** to stable identifiers (name, email, phone).

### 9.4 Overall profile confidence
```
overall_confidence = Σ(wᵢ · cᵢ)  over core fields; absent field → cᵢ = 0
weights: name .25 · email[0] .20 · phone[0] .15 · company .15 · title .15 · location .10
```
`company` and `title` are scored from the **current** `experience[]` entry (`end == None`); if a profile has no current entry, each contributes cᵢ = 0. Sparse profiles honestly score lower (a missing field contributes 0, not a skipped term).

---

## 10. Canonical Model (`models/canonical.py`)

```python
T = TypeVar("T")

class ProvenanceEntry(BaseModel):
    source: str            # "ats_json" | ...
    method: str            # "csv:column" | "normalize:e164" | "merge:trusted-source" | "assume:default_region" | ...
    raw: Any | None        # pre-normalization value
    value: Any             # post-normalization value

class TrackedValue(BaseModel, Generic[T]):
    value: T | None
    confidence: float | None
    sources: list[str]
    provenance: list[ProvenanceEntry]
    competitors: list[Any] = []     # values that lost the conflict

class Flag(BaseModel):
    kind: str              # "conflict_resolved" | "assumed_region" | "uncanonicalized_skill" | ...
    detail: str

class TrackedExperience(BaseModel):
    company: TrackedValue[str] | None = None
    title:   TrackedValue[str] | None = None
    start:   TrackedValue[str] | None = None   # "YYYY" | "YYYY-MM"
    end:     TrackedValue[str] | None = None   # None == ongoing
    summary: TrackedValue[str] | None = None

class TrackedEducation(BaseModel):
    institution: TrackedValue[str] | None = None
    degree:      TrackedValue[str] | None = None
    field:       TrackedValue[str] | None = None
    end_year:    TrackedValue[int] | None = None

class CanonicalProfile(BaseModel):
    candidate_id: str                  # deterministic (hash of strongest stable anchor)
    full_name:        TrackedValue[str] | None = None
    emails:           list[TrackedValue[str]] = []   # confidence-sorted
    phones:           list[TrackedValue[str]] = []   # confidence-sorted
    location:         TrackedValue[dict] | None = None   # {city, region, country, raw}
    links:            TrackedValue[dict] | None = None    # {linkedin, github, portfolio, other[]}
    headline:         TrackedValue[str] | None = None      # short professional headline (time-varying, §9.3)
    skills:           list[TrackedValue[str]] = []
    experience:       list[TrackedExperience] = []
    education:        list[TrackedEducation] = []
    years_experience: float | None = None
    overall_confidence: float
    flags:            list[Flag] = []
```

`candidate_id` is **deterministic** (e.g. stable hash of normalized primary email, else phone, else name_block_key) so reruns produce identical IDs (golden tests depend on this).

---

## 11. Projection Layer (`project/`)

The **only** config-aware stage. Internal record is rich; output is a flat projection.

### 11.1 Config schema (`config/schema.py`)
```python
class FieldSpec(BaseModel):
    # Keys mirror the assignment's example config (path / from / type / normalize).
    path: str                   # OUTPUT key, e.g. "full_name", "primary_email", "phone"
    from_: str | None = Field(default=None, alias="from")  # canonical SOURCE path; defaults to `path` if omitted
    type: Literal["string", "string[]", "number", "object", "object[]"] = "string"  # drives create_model (§11.4)
    required: bool = False
    normalize: str | None = None   # ASSERTION ONLY (e.g. "E164", "canonical", "iso3166-a2") — NEVER recompute
    on_missing: Literal["null", "omit", "error"] | None = None  # overrides global
    include_confidence: bool = False
    include_provenance: bool = False

class ProjectionConfig(BaseModel):
    on_missing: Literal["null", "omit", "error"] = "null"   # global default
    include_flags: bool = False
    fields: list[FieldSpec]
```
`from_` carries `alias="from"` so config JSON uses the bare key `"from"` (a Python reserved word); enable population by alias in model config. **`normalize` is assert-only** — a deliberate refinement of the assignment's "set per-field normalization": all normalization already happened deterministically upstream (§6), so the projector **verifies** the value matches the named format and treats a mismatch as **missing**; it never re-runs a normalizer (which would risk double-normalization and silent drift). `type` feeds the dynamic output-validation model (§11.4).

Example custom config (the assignment's sample, in this schema):
```json
{
  "fields": [
    { "path": "full_name",     "type": "string",   "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string",   "required": true },
    { "path": "phone",         "from": "phones[0]", "type": "string",   "normalize": "E164" },
    { "path": "skills",        "from": "skills[].name", "type": "string[]", "normalize": "canonical" }
  ],
  "include_confidence": true,
  "on_missing": "null"
}
```
Validate the **config itself first** (`loader.py`). A malformed config is a hard error before any profile is processed.

### 11.2 Minimal path resolver (`resolver.py`)
Support exactly three forms — **no JSONPath dependency**:
- `field`
- `field.subfield`
- `field[].subfield` (maps over a list)

### 11.3 Per-field projection algorithm (`projector.py`)
For each `FieldSpec`: **resolve** `from` (the canonical source path; defaults to `path`) → **assert `normalize`/format** (check only; if the value doesn't satisfy the asserted format, treat as **missing**) → apply **`on_missing`** (per-field override else global; `error` → raise) → **gate** confidence/provenance by the include flags → **emit under the output key `path`**.

### 11.4 Output validation (`validator.py`)
Build a Pydantic model from the config via `create_model` (each field's type comes from `FieldSpec.type`) and validate the projected dict.
- Output failing validation → **skip that profile**, log a `SkipEntry` to the `RunReport`, keep the batch running.
- Default output = `project(profile, DEFAULT_CONFIG)` — no special-casing.

`data/configs/default_config.json` **reproduces the assignment's "Default output schema" verbatim** — `candidate_id, full_name, emails, phones, location, links, headline, years_experience, skills` (`{name, confidence, sources[]}`), `experience, education, overall_confidence`, plus a **top-level `provenance` array** of `{field, source, method}` aggregated across all fields. That aggregate is a built-in projector view (the simple path resolver can't synthesize it), while the per-field `include_provenance` flag still gates inline provenance for custom configs. Ship at least one **custom** config too (e.g. one that includes confidence + provenance inline and renames fields) to prove the layer is real.

---

## 12. CLI (`cli.py`)

```
transform --inputs csv=<path> ats=<path> github=<path> \
          [--config cfg.json] [--default-region IN] \
          [--out profiles.json] [--report report.json] [--live] [--pretty] [--as-of YYYY-MM-DD]

validate-config --config cfg.json
```
- No `--config` → default projection.
- Writes JSON to `--out` (and optionally stdout with `--pretty`).
- `--report` writes the `RunReport`.
- `--live` is the no-op GitHub stub (defaults to fixture).

---

## 13. Run Report (`models/report.py`)

```python
class SkipEntry(BaseModel):    stage: str; identifier: str; reason: str
class ConflictEntry(BaseModel): candidate_id: str; field: str; winner: Any; losers: list[Any]
class Assumption(BaseModel):   candidate_id: str; field: str; assumption: str   # e.g. default-region applied

class RunReport(BaseModel):
    skips: list[SkipEntry] = []
    conflicts: list[ConflictEntry] = []
    assumptions: list[Assumption] = []
    counts: dict[str, int] = {}     # records_in, profiles_out, sources_skipped, ...
```
Threaded through every stage. This is the batch-level audit trail (distinct from per-profile `flags`).

---

## 14. Provenance Method Vocabulary

Use a consistent `method` string vocabulary on every `ProvenanceEntry`:
`csv:column` · `ats:path` · `github:field` · `normalize:e164` · `normalize:iso-date` · `normalize:iso3166` · `normalize:skill-alias` · `merge:trusted-source` · `merge:union` · `assume:default_region`.

---

## 15. Featured Edge Cases (each must be exercised by a fixture + asserted in a test)

1. **Company conflict** → trust ranking picks winner; losers in provenance; `conflict_penalty` applied + `Flag(conflict_resolved)`.
2. **Identity: name variants, no shared email** → blocking on `name_block_key` (+ github_login) collapses them to one cluster; orphan-with-no-signal documented.
3. **Garbage source** (malformed CSV/JSON) → adapter try/except → `RunReport.skip`, run continues, other sources still produce output.
4. **Phone with no country code** → `--default-region` applied + `Flag(assumed_region)` + `assume:default_region` method.
5. **Partial / "Present" dates** → `YYYY` kept as-is; ongoing → `end == None`; `years_experience` still computes.
6. **Skill alias + unknown** → `ReactJS` → `React`; `C++` / `C#` preserved intact; unknown kept verbatim @0.60 + `Flag(uncanonicalized_skill)`.

---

## 16. Testing Plan (`tests/`, pytest)

- **Per-normalizer units:** phone, dates, country, skills (must include the `C++` / `C#` / `.NET` / `ReactJS` table), email.
- **`test_identity`:** name-variant records collapse to exactly one cluster; orphan stays separate.
- **`test_merge`:** conflict → asserts expected winner **and** expected confidence value.
- **`test_confidence`:** the three worked examples land at ~0.88 / ~0.78 / ~0.42 (assert within tolerance).
- **`test_projection`:** default config + one custom config; `required`-missing → error; unsatisfiable `normalize`/format assertion → treated as missing; `from`-defaults-to-`path` and the top-level `provenance` aggregate both covered.
- **`test_e2e`:** full run over the fixtures, compared against **golden** JSON in `tests/golden/` (canonical + default output). Deterministic `candidate_id` makes this stable.
- **`test_garbage_source`:** inject a malformed source → assert no crash, correct `SkipEntry`, other profiles still emitted.

Golden files are the contract. If a change is intentional, regenerate goldens deliberately — never loosen an assertion to make a test pass.

---

## 17. Build Order (milestones for Claude Code)

Build in this sequence; each milestone should be runnable/testable before the next.

1. **Scaffold** — `pyproject.toml`, package skeleton, `models/` (canonical, source_record, report), constants in `confidence/scorer.py` + `merge/trust.py`.
2. **Normalizers** — `normalize/*` + `aliases.json` + their unit tests. (Self-contained, high-leverage, easy to verify first.)
3. **Fixtures** — generate `data/fixtures/*` covering all six edge cases and the three confidence targets.
4. **Adapters** — `sources/*` → `SourceRecord`, with try/except + run-report skips. Test each adapter loads its fixture.
5. **Identity** — `resolve/identity.py` (blocking + linking) + `test_identity`.
6. **Merge + Confidence** — `merge/*` and `confidence/scorer.py` wired together → `CanonicalProfile` + `test_merge`, `test_confidence`.
7. **Projection** — `config/*`, `project/*` + `test_projection`; write `default_config.json` and one custom config.
8. **Pipeline + CLI** — `pipeline.py`, `cli.py`; run end-to-end; generate golden files; `test_e2e` + `test_garbage_source`.
9. **README** — run instructions, architecture diagram (the §3 data-flow line), confidence/trust rationale, and the **descope section** (below) framed as deliberate.

---

## 18. Descope List (frame as pluggable modules, not omissions — for the README)

- **LinkedIn** — no public API; modeled as a pluggable `SourceAdapter` the registry can add later.
- **Resume parsing** — NLP complexity disproportionate to scope; the adapter interface already accommodates it.
- **Recruiter notes** — same adapter seam.
- **Fuzzy / embedding name matching** — the identity linker's tiered structure leaves a clean insertion point; alias-map + blocking is the deterministic choice for this scope.
- **Embedding-based skill similarity** — production path for the long tail; alias map handles the common vocabulary deterministically.
- **Recency decay** — fully implemented via the `last_updated` hook (we control the fixtures), documented as a no-op when a source lacks reliable timestamps.

Each cut is a **defensible judgment call**, not a gap. State the reasoning explicitly — that reasoning is what the reviewers grade.

---

## 19. Acceptance Criteria (final checklist)

- [ ] `pip install -e .` then `candidate-pipeline transform --inputs csv=… ats=… github=… --out out.json --report report.json` runs clean.
- [ ] Output is one profile per resolved person, with per-field confidence + provenance available (gated by config).
- [ ] A bad source produces a skip in the report, not a crash.
- [ ] `C++`, `C#`, `.NET` survive canonicalization; `ReactJS` → `React`.
- [ ] Default config emits the PS-style shape; a custom config changes the output shape at runtime with no code change.
- [ ] All tests green, including the three confidence targets and the golden e2e comparison.
- [ ] README explains architecture + descope rationale.