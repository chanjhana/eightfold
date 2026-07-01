# 10. Design decisions

This is the rationale record: the significant, voluntary choices made in the
project, why each was made, and what alternatives were rejected. Where the problem
statement left room for judgment, this is where that judgment is documented. Each
entry is written so a newcomer can understand not just what the code does but why
it does it that way.

## D1. Three invariants as the deciding rule

**Decision.** Every ambiguous choice is settled by three fixed rules: never
fabricate a value, never crash the batch on one bad record, and keep output
deterministic and explainable.

**Why.** Talent data drives real decisions about people. A fabricated month on a
job, a silently dropped record, or an unexplainable score are all worse than an
honest gap. Fixing the rules up front made the rest of the design fall out
consistently rather than being decided case by case.

**Consequences.** Normalizers keep raw values instead of guessing; adapters catch
and log instead of raising; identifiers are hashes of stable anchors; every value
carries provenance. These invariants are referenced throughout the other
documents.

## D2. CanonicalProfile as a hard boundary

**Decision.** Nothing upstream of `CanonicalProfile` knows the output
configuration exists. Only the projector reads it.

**Why.** It cleanly separates "what we know about a person" from "how a consumer
wants it shaped." Merge logic never thinks about output naming, and the projector
never thinks about trust or scoring.

**Alternatives rejected.** Threading the config through every stage (couples
unrelated concerns, and makes merge output-format-aware). Post-processing the JSON
after merge with ad hoc transforms (loses type safety and provenance).

**Consequences.** A new output shape is a config file, not a code change. Merge
and projection are independently testable. See [Architecture](02-architecture.md).

## D3. Blocking plus tiered linking, not all-pairs fuzzy matching

**Decision.** Identity resolution blocks on shared keys (email, github_login,
name block key), then links within blocks using positive-evidence tiers.

**Why.** All-pairs fuzzy matching is O(n squared) and its ranking is
non-deterministic and hard to explain. Blocking plus tiers is linear, fully
deterministic, and explainable: you can always name the key that blocked two
records and the tier that linked them.

**Alternatives rejected.** Global fuzzy similarity with a threshold (slow,
non-deterministic, opaque). A machine-learned matcher (needs training data, not
explainable, not deterministic).

**Consequences.** A real match with no shared block key stays separate (the Pat
Morgan orphan). This is an accepted, documented limitation with a clear extension
point (fuzzy name matching). See [Identity resolution](06-identity-resolution.md).

## D4. The name block key

**Decision.** Block names by the sorted set of the first letter of each name
token, so "Sri Krishna V", "Sri Krishna Vijayarajan", and "V, Sri K." all key to
`ksv`.

**Why.** Real names arrive reordered, abbreviated to initials, and with surnames
added or dropped. A key that survives all three, while staying cheap to compute,
gives high recall in blocking without any fuzzy comparison.

**Alternatives rejected.** Blocking on the exact normalized name (misses every
variant). Blocking on a phonetic code such as Soundex (locale-specific, and
weaker on non-Western names).

## D5. Source trust order: ATS > CSV > resume > GitHub

**Decision.** Single-valued conflicts are resolved by a fixed trust order:
ATS 0.90, recruiter CSV 0.80, resume 0.75, GitHub 0.70.

**Why.** ATS is a verified system of record. The recruiter CSV is human-entered
but curated. A resume is a deliberate professional document, but self-authored and
prose-extracted, so it ranks below the curated sources. A GitHub bio is public,
free-text, and self-authored, so it ranks lowest.

**Alternatives rejected.** Newest-wins by timestamp (a stale ATS record is still
more reliable than a fresh GitHub bio for identity fields; recency is handled
separately, as a decay on time-varying fields only). Equal trust with majority
vote (a single authoritative source should beat two copies of a weaker one).

**Consequences.** Trust lives in exactly one file,
[`merge/trust.py`](../candidate_pipeline/merge/trust.py), so re-ranking sources is
a one-line change.

## D6. Losers become competitors, never discarded

**Decision.** When trust picks a winner for a single-valued field, the losing
distinct values are preserved on the `TrackedValue` as `competitors`, and a
`conflict_resolved` flag plus a `ConflictEntry` are recorded.

**Why.** Invariant 1 and explainability. A resolved conflict is information, not
noise. A downstream consumer, or a human auditor, can see that Shopify lost to
Stripe rather than that Shopify never existed.

## D7. Confidence as an additive model with independence-weighted corroboration

**Decision.** Confidence is `base + corroboration - extraction - conflict`, times
a recency factor, clamped to 0 to 1. Corroboration is weighted by source
independence and capped.

**Why.** It is simple, inspectable, and every term maps to a real-world notion:
how reliable the winning source is, how many independent sources agree, whether
the value was extracted from prose, whether it was contested, and how stale it is.

**Key sub-decisions.**
- **Independence weighting.** ATS and CSV corroborating each other count at half,
  because they may share an upstream import; anything corroborated by GitHub counts
  full, because a public self-authored profile agreeing with a system of record is
  genuine independent evidence.
- **Corroboration cap (0.10).** No value can be lifted more than two independent
  sources' worth, so a long tail of weak agreements cannot inflate a score.
- **Extraction penalty (0.10).** Prose and heuristic values are penalized relative
  to structured fields.
- **Recency decay on time-varying fields only.** Company, title, location, and
  headline decay with staleness; identifiers such as name and email never decay,
  because a name does not become less true with age.

**Consequences.** All scoring constants live in one file,
[`confidence/scorer.py`](../candidate_pipeline/confidence/scorer.py).

## D8. Assertion-only normalization in the projection config

**Decision.** A config's `normalize` (`E164`, `iso3166-a2`, `canonical`) is a
format assertion, checked at projection time, not a recompute. A value that fails
the assertion is treated as missing.

**Why.** Normalization must happen exactly once, at ingestion, where the raw value
and full context are available. Re-running a normalizer at projection time would
risk double-normalization and drift between the canonical model and the output.
Checking, rather than recomputing, keeps a single source of truth for every
value's format.

**Consequences.** The projector stays simple and cannot silently transform data.
See [Projection](08-projection-and-config.md).

## D9. Runtime output model built from the config

**Decision.** The output validator builds a Pydantic model from the config at
runtime with `create_model`, then validates each projected profile against it.

**Why.** It gives real type validation of a user-defined output shape without a
hand-written model per config. A profile that does not match its declared schema
is caught and skipped rather than emitted malformed.

**Alternatives rejected.** No validation (malformed output leaks downstream).
Fixed, code-defined output models (defeats the point of runtime configuration).

## D10. Two levels of skip, distinguished in the report

**Decision.** A whole unreadable source is an `adapter:` skip; a single bad record
inside a readable file is a `record:` skip; a value that fails normalization is a
`normalize:` skip; a profile dropped at output is a `projection` or `validation`
skip.

**Why.** Invariant 2 with visibility. The prefix makes it clear, from the report
alone, whether the pipeline lost a file, a record, a value, or a whole profile,
and `--strict` can treat output-stage drops differently from graceful input skips.

## D11. GitHub repositories feed three parts of the profile, forks excluded

**Decision.** A candidate's non-fork repos contribute their language as a skill,
their most-starred repos as links, and the raw non-fork list as
`CanonicalProfile.repos`. Forks are excluded from all three.

**Why.** A person's own repositories are real signal about their skills and work.
A fork's language and star count reflect the upstream project, not the candidate,
so counting them would misattribute skill and popularity.

## D12. --live is best-effort with a fixture fallback

**Decision.** `--live` overlays real GitHub API data onto the fixture, and on any
failure returns the fixture unchanged with a non-fatal note.

**Why.** It demonstrates real integration without making the pipeline depend on
network availability or rate limits. A demo never flakes, and the report is honest
about whether live or fixture data was used.

## D13. Resume promoted to a real source, but with lean scope

**Decision.** The resume PDF is a full source (a second unstructured one), but its
parser extracts only the fields it can recover reliably (name, emails, phones,
headline, location, skills). Experience and education parsing is left as an
extension point.

**Why.** Free-form resume date parsing is unreliable, and inventing structure
would risk invariant 1. Extracting only the confident fields keeps the source
honest while still adding real value (extra corroboration and skills).

## D14. Deterministic candidate_id from a stable anchor

**Decision.** `candidate_id` is a SHA1 hash of the strongest stable anchor
available (email, then phone, then name key).

**Why.** Determinism (invariant 3) and stable golden tests. The same person always
gets the same id across runs, and the id does not depend on input ordering.

**Alternatives rejected.** A random UUID (breaks determinism and golden tests). A
sequential counter (depends on input order, so not stable).

## D15. Tunable numbers confined to two files

**Decision.** All source trust lives in `merge/trust.py`, and all confidence
constants live in `confidence/scorer.py`. Nothing else hardcodes these numbers.

**Why.** Tuning behavior should be a small, localized, reviewable change, not a
hunt through the codebase.

## Deliberate scope limits

These were consciously left out under time pressure, each with a clean extension
point. They are collected here and expanded in [Extending the pipeline](13-extending.md).

| Not built | Why | Extension point |
|---|---|---|
| LinkedIn / recruiter-notes sources | No public API, NLP-heavy | A new `SourceAdapter` in the registry; `link_hints` already accepts a LinkedIn URL |
| Resume experience/education parsing | Free-form dates unreliable; kept scope lean | `parse_resume_text` is where section-aware parsing slots in |
| Fuzzy / embedding name matching | Deterministic alias plus blocking chosen for explainability | The linker's tiered structure has a clean insertion point |
| Embedding-based skill canonicalization | Alias map covers common vocabulary; the long tail needs a model | `canonicalize_skill` has one insertion point for an optional embedding fallback, off by default so goldens stay stable |

Some genuinely hard cases are also deliberately out of scope and pinned by tests
with a comment, so they are not mistaken for bugs: a shared inbox that links two
different people, `Georgia` the country versus the US state, and vanity phone
letters such as `1-800-FLOWERS`. See [Edge cases](11-edge-cases.md).

## Where to go next

- [Edge cases and robustness](11-edge-cases.md) shows these decisions under hostile input.
- [Extending the pipeline](13-extending.md) turns the scope limits into how-to guides.
