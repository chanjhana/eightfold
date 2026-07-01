# 11. Edge cases and robustness

This catalog lists the hostile and awkward inputs the pipeline is built to
survive, how each is handled, and where it is tested. Robustness is not an
afterthought here: roughly 95 of the 220 tests exist specifically to prove the
pipeline degrades gracefully rather than crashing or fabricating.

The hostile fixtures live in
[`data/fixtures/edge/`](../candidate_pipeline/data/fixtures/edge/), separate from
the clean demo fixtures.

## The core demonstrated edge cases

These six are each exercised by a demo fixture and asserted in a test. They are
the cases the pipeline was explicitly designed around.

| # | Edge case | Handling | Test |
|---|---|---|---|
| 1 | Company conflict between two sources | Trust picks the winner; loser kept as a competitor; `conflict_resolved` flag and `ConflictEntry` | `test_merge` |
| 2 | Name variants with no shared email | Blocked on name key plus github_login, then linked; a truly unmatchable record stays an orphan | `test_identity` |
| 3 | Garbage source (malformed file) | Adapter try/except, `adapter:` skip, batch continues | `test_garbage_source` |
| 4 | Phone with no country code | `--default-region` applied and flagged, or raw kept if no region | `test_merge` |
| 5 | Partial or "Present" dates | Granularity preserved; `years_experience` still computes | `test_dates`, `test_merge` |
| 6 | Skill alias plus unknown skill | `ReactJS` becomes `React`; `C++`, `C#`, `.NET` preserved; unknown kept verbatim and flagged | `test_skills`, `test_merge` |

## Resilience against hostile input

Beyond the six above, the torture fixtures and edge tests probe deeper failure
modes.

### Per-record resilience

One poison row or object is skipped and logged (a `record:<source>` entry), while
the rest of the file still loads. A CSV row with an embedded NUL raises a
`csv.Error` that is caught per row. A non-object entry in a JSON array is skipped.
Tested in `test_adapter_resilience`.

### Shape tolerance

A top-level JSON object where an array was expected is accepted by wrapping it in
a list (`_as_record_list`). An explicit `"candidate": null` is handled by the
`or {}` idiom rather than crashing. Non-object elements inside `experience` or
`education` arrays are skipped individually. Tested in `test_adapter_resilience`
and `test_core_logic_edge`.

### Encoding tolerance

A UTF-8 byte-order mark is stripped from CSV, JSON, and config files (all opened
with `utf-8-sig`). CSV headers are matched case- and whitespace-insensitively.
Output is always written as UTF-8, so names such as `李明` or `José` never crash a
Windows console. Tested in `test_adapter_resilience` and `test_config_validation`.

### No silent-wrong values

This class is the most subtle, because the failure is not a crash but a plausible
wrong answer:

- A `mailto:` prefix and trailing punctuation are stripped from emails before
  validation.
- An out-of-range month such as `2020-13` is rejected, never padded into a fake
  date.
- Skills split on comma, semicolon, pipe, newline, and tab, but not on `/`, so
  `CI/CD` and `TCP/IP` survive intact.
- A phone-like run in a resume must contain at least eight digits, so a year or id
  is not mistaken for a phone.

Tested in `test_normalizers_edge`.

### Config validation

A duplicate or empty output `path` is rejected at load time. A duplicate used to
silently overwrite an earlier field, which is data loss, so it became a hard error.
Unknown field types and unknown `on_missing` values are also rejected. Tested in
`test_config_validation`.

### Multiple files per type

The `:label` suffix on an input key lets several files of one type be ingested in
one run, for example `csv:primary=a.csv csv:backfill=b.csv`. Tested in
`test_adapters`.

## Deliberately descoped hard cases

Some cases are genuinely hard and are consciously left unsolved, pinned by tests
with an explanatory comment so they are recognized as known limitations rather
than bugs:

- **A shared inbox linking two different people.** Two distinct people using the
  same team email would be merged, because a shared email is treated as strong
  identity evidence. Distinguishing them reliably needs more signal than the
  pipeline assumes.
- **`Georgia` the country versus the US state.** An ambiguous place name may
  resolve to the wrong entity, or be left unresolved with the raw value preserved.
- **Vanity phone letters** such as `1-800-FLOWERS`. These are not normalized to
  E.164, because interpreting letters as digits is a guess.

The orphan case (a GitHub-only record with no shared identifier and a non-aligning
name, like Pat Morgan in the fixtures) is also a documented limitation; the
extension for it is fuzzy name matching. See
[Identity resolution](06-identity-resolution.md) and
[Extending the pipeline](13-extending.md).

## The guiding principle

Every entry above resolves the same way: **degrade, log, and continue, and never
emit a value the input did not support.** A crash loses the whole batch; a
fabricated value is worse than an honest gap. The report is the record of every
such decision, so nothing that happened during a run is invisible.

## Where to go next

- [Testing](12-testing.md) shows how these cases are structured into suites.
- [Design decisions](10-design-decisions.md) explains the reasoning behind the descoped cases.
