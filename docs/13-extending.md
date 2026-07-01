# 13. Extending the pipeline

The architecture is built so the common extensions are additive: a new source, a
new skill, a new output shape, or a new normalizer each slot into an existing seam
without touching unrelated code. This document is a set of how-to guides for those
extensions, and a map of the deliberately descoped work.

## Add a new output shape (no code change)

This is the easiest extension and needs no Python at all, because of the
`CanonicalProfile` boundary (see [Architecture](02-architecture.md)).

1. Write a JSON config with the fields you want. Start from
   [`default_config.json`](../candidate_pipeline/data/configs/default_config.json)
   or [`custom_config.json`](../candidate_pipeline/data/configs/custom_config.json).
2. Use the path language in `from` to pull from any canonical field:
   `emails[0]`, `skills[].name`, `repos[0].name`, `location.city`.
3. Choose per-field `type`, `required`, `on_missing`, and whether to
   `include_confidence` or `include_provenance`.
4. Validate it: `candidate-pipeline validate-config --config your_config.json`.
5. Run: `candidate-pipeline transform --config your_config.json ...`.

The full format is documented in [Projection and configuration](08-projection-and-config.md).

## Add a skill alias (data change)

Skill vocabulary lives in
[`normalize/aliases.json`](../candidate_pipeline/normalize/aliases.json), a plain
lowercase-key to canonical-value map. To teach the pipeline a new alias, add an
entry, for example `"gh actions": "GitHub Actions"`. No code changes. Add a case
to `test_skills` to lock the behavior in.

## Add a new source

A new input format is a new adapter. The framework does most of the work.

1. Create a class in [`sources/`](../candidate_pipeline/sources/) that subclasses
   `SourceAdapter` and sets `source_name`.
2. Implement `_load_impl(path)` to read the file and return `SourceRecord`s. Use
   the base-class helpers (`_emails`, `_phones`, `_skills`, `_as_record_list`,
   `_record_skip`) so normalization and per-record resilience come for free.
3. Wrap per-record parsing in try/except and call `_record_skip` on failure, so
   one bad record does not drop the file. The outer `load` already guards the whole
   file.
4. Register the adapter in
   [`sources/registry.py`](../candidate_pipeline/sources/registry.py) under a new
   `--inputs` key.
5. Decide the source's trust and add it to
   [`merge/trust.py`](../candidate_pipeline/merge/trust.py) and the matching base
   in [`confidence/scorer.py`](../candidate_pipeline/confidence/scorer.py).
6. Add an adapter test alongside the others.

Because merge, resolution, and projection operate on `SourceRecord` and
`CanonicalProfile`, none of them need to change to accommodate a new source.

## Add a new normalizer

1. Add a pure function in [`normalize/`](../candidate_pipeline/normalize/) that
   takes a raw value and returns a canonical form or `None`. Keep it free of
   source knowledge and side effects, and uphold invariant 1: never fabricate.
2. Call it from the relevant adapter(s), storing both raw and normalized forms in
   the `SourceValue`.
3. If the format should be assertable in a config, add a branch to `_assert_format`
   in [`project/projector.py`](../candidate_pipeline/project/projector.py) (a check
   only, never a recompute; see [Design decisions](10-design-decisions.md)).
4. Add a focused unit test and an entry in `test_normalizers_edge` for the
   fabrication and silent-wrong classes.

## Change trust or scoring

All tunable numbers are confined to two files by design:

- Source trust: [`merge/trust.py`](../candidate_pipeline/merge/trust.py).
- Confidence constants (corroboration, independence weights, penalties, recency,
  overall-confidence weights): [`confidence/scorer.py`](../candidate_pipeline/confidence/scorer.py).

Editing there changes behavior everywhere consistently. Update `test_confidence`
and, if the output changes, the golden files.

## The descoped work, as extension guides

These were consciously left out (see [Design decisions](10-design-decisions.md)),
each with a clean seam:

### LinkedIn or recruiter-notes source

Add it as a new `SourceAdapter`, exactly as above. `SourceRecord.link_hints`
already accepts a `linkedin` URL, so the link plumbing is in place; the work is
parsing the source's format.

### Resume experience and education parsing

The resume parser, `parse_resume_text` in
[`sources/resume_pdf.py`](../candidate_pipeline/sources/resume_pdf.py), currently
extracts identity, contact, headline, location, and skills. Section-aware parsing
of experience and education slots in there. The hard part, and the reason it was
descoped, is reliable free-form date parsing; anything added must still never
fabricate a date it cannot recover.

### Fuzzy or embedding name matching

The identity linker's `_link_score` in
[`resolve/identity.py`](../candidate_pipeline/resolve/identity.py) uses positive
evidence tiers. A fuzzy or embedding-based tier would slot in as an additional
branch, most usefully to catch cross-block matches (the orphan case). The trade-off
to preserve is determinism and explainability; any fuzzy tier should be reproducible
and should be able to state why it linked two records.

### Embedding-based skill canonicalization

`canonicalize_skill` in
[`normalize/skills.py`](../candidate_pipeline/normalize/skills.py) has a single
insertion point for an optional embedding fallback, tried after the alias map and
before keeping a skill verbatim. Its provenance method would be
`normalize:skill-embedding`. Keep it off by default so golden output stays byte
identical.

## A checklist for any extension

- Uphold the three invariants (never fabricate, never crash the batch, stay
  deterministic and explainable).
- Reuse the base-class helpers so resilience and normalization are consistent.
- Keep tunable numbers in the two designated files.
- Add tests: a focused unit test, plus an invariant assertion if the change
  touches robustness.
- Regenerate golden files intentionally, in the same commit, if output changes.

## Where to go next

- Return to the [knowledge base index](README.md), or
- Re-read [Design decisions](10-design-decisions.md) for the reasoning these seams protect.
