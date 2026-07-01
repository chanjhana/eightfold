# Candidate Profile Transformation Pipeline — Technical Design

**Chanjhana Elango · chanjhana29@gmail.com · Eightfold take-home**

**Goal.** Ingest heterogeneous candidate records from multiple sources, resolve which belong to the same person, merge into one canonical profile per person with per-field provenance + confidence, and emit through a runtime-configurable projection. Three invariants everywhere: **never fabricate a value**; **never crash the batch** on one bad record (skip + log); **deterministic & explainable** output.

## 1. Pipeline

`inputs → adapters → normalize → resolve identity → merge (+confidence) → project (+validate) → JSON`, with a **RunReport** (skips / conflicts / assumptions / counts) threaded through every stage.

- **Adapt** — one pluggable `SourceAdapter` per source (recruiter CSV, ATS JSON, GitHub REST, résumé PDF) → a normalized `SourceRecord` carrying raw + normalized per field. `load()` is try/except-wrapped: a bad source/record becomes a skip, not a crash.
- **Normalize (deterministic)** — phone→E.164, dates→`YYYY|YYYY-MM`, country→ISO-3166 α-2, skills→alias map, email→lowercase + validate.
- **Resolve identity** — O(n) blocking, then precision linking.
- **Merge + confidence** — one cluster → one `CanonicalProfile` of `TrackedValue`s.
- **Project + validate** — the only config-aware stage; canonical → flat, validated dict.

## 2. Canonical schema & normalized formats

`CanonicalProfile`: **candidate_id** (deterministic SHA1 of the strongest stable anchor — email → phone → name-key, so reruns are identical), full_name, emails[]•, phones[]• (• = confidence-sorted), location{city, region, country}, links{linkedin, github, portfolio, other[]}, headline, skills[]{name, confidence, sources[]}, experience[], education[], repos[], years_experience, overall_confidence, flags[]. Every value is a `TrackedValue{value, confidence, sources[], provenance[], competitors[]}`.

**Formats.** **Dates** `YYYY` or `YYYY-MM` — granularity preserved, `"Present"`/`""`→None (ongoing), never fabricate a month. **Phones** E.164 via `phonenumbers` — missing country code + `--default-region` → applied & flagged; no region → keep raw, no guess. **Country** ISO-3166 alpha-2 via `pycountry`; unresolved → null (raw kept). **Skills** alias-mapped, preserving `+` and `#` (C++/C#/.NET never collapse to "c"); unknown kept verbatim at lower confidence + flag. **Email** lowercased + shape-validated; a bad value is dropped, not the record.

## 3. Merge / conflict-resolution policy

- **Match keys (union — any shared key co-blocks):** normalized email, github_login, `name_block_key` (sorted set of first letters of name tokens — survives initials/reordering, e.g. "Sri Krishna V" ≡ "V, Sri K."). Exact email or login → link outright; otherwise name-alignment + shared phone ≥ threshold. **No pairwise fuzzy over all records** (keeps it O(n)).
- **Single-valued winner** = highest source trust: **ATS 0.90 > CSV 0.80 > résumé 0.75 > GitHub 0.70**. Losing values are retained as `competitors` (never discarded) + `Flag(conflict_resolved)` + a `ConflictEntry` in the report.
- **Multi-valued** (skills, emails, phones) = union + dedup, each value scored independently.
- **Confidence** = `clamp01(base + corroboration − extraction − conflict) × recency`: base = winner's trust; corroboration +0.05 per extra agreeing source × independence weight (ATS↔CSV 0.5, any↔GitHub 1.0), capped at +0.10; extraction −0.10 for prose/heuristic values (GitHub bio, résumé, free-text location); conflict −0.05; recency decays **only** time-varying fields (company/title/location/headline) via `last_updated`. **Overall** = weighted Σ over core fields (name .25, email .20, phone .15, company .15, title .15, location .10); an absent field contributes 0 (sparse profiles honestly score lower).

## 4. Runtime custom-output config (projection + validation)

A JSON config is an ordered list of `FieldSpec`: `path` (output key), `from` (canonical source path — supports `field`, `field.sub`, `field[].sub`; defaults to `path`), `type` (`string | string[] | number | object | object[]` — drives a dynamically built model), `required`, `normalize` (**assert-only**: verify the value already matches `E164`/`iso3166-a2`/`canonical`; a mismatch is treated as **missing**; the projector never recomputes — avoiding double-normalization/drift), `on_missing` (`null | omit | error`), and `include_confidence`/`include_provenance`; plus global `on_missing` + `include_flags`. The **Projector is the only config-aware component** (hard boundary at `CanonicalProfile` — nothing upstream knows config exists). Output is validated by a Pydantic model built **at runtime** from the config (`create_model`); a profile that fails validation is skipped + logged and the batch continues. The default config reproduces the required output schema verbatim; a custom config renames fields / reshapes / toggles confidence + provenance **with zero code change**.

## 5. Edge cases & deliberate descopes

**Handled:** **(a) Company conflict** (ATS *Stripe* vs CSV *Shopify*) → trust picks the winner, losers kept as competitors, conflict_penalty + flag. **(b) Name variants, no shared email** (*Sri Krishna V* / *Vijayarajan*) → blocking on `name_block_key` + github_login collapses them to one cluster; a GitHub record with no email/login and a non-aligning name stays an **orphan** (documented limitation). **(c) Garbage source** — malformed CSV/JSON, corrupt PDF, or a scanned (no-text) résumé → adapter try/except → RunReport skip, other sources still emit. **(d) Phone without country code** → `--default-region` applied + `assume:default_region` method + `Flag(assumed_region)`; with no region, the raw is kept and never guessed. **(e) Skill alias + unknown** → `ReactJS`→React, `C++`/`C#`/`.NET` preserved intact, unknown kept verbatim @0.60 + flag.

**Deliberately deferred under time pressure** (all pluggable behind existing seams): live LinkedIn / recruiter-notes adapters; résumé experience/education parsing (lean scope today); fuzzy/embedding **name** & **skill** matching (deterministic alias + blocking chosen for explainability); embedding skill-similarity for the long tail (design noted in the README).
