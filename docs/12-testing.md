# 12. Testing

The suite has 220 tests and runs in a few seconds. Its structure mirrors the
pipeline: focused unit tests per component, then integration tests, then torture
tests against hostile input.

```bash
uv run pytest            # or: pytest, with the virtual environment active
```

Test fixtures and shared setup are in
[`tests/conftest.py`](../tests/conftest.py). Clean demo inputs are in
[`data/fixtures/`](../candidate_pipeline/data/fixtures/); hostile inputs are in
[`data/fixtures/edge/`](../candidate_pipeline/data/fixtures/edge/).

## What each suite covers

| Test file | Focus |
|---|---|
| `test_phone`, `test_dates`, `test_country`, `test_email`, `test_skills` | Per-normalizer units |
| `test_adapters` | Each adapter's field mapping, multiple files per type |
| `test_resume` | Resume text extraction and the heuristic parser |
| `test_identity` | Variant collapse, orphan isolation, same-block precision |
| `test_merge` | Conflict resolution, asserted winner and confidence |
| `test_confidence` | The scoring formulas and the three overall-confidence anchors |
| `test_projection` | Default and custom config, assertion-only normalize, `on_missing` |
| `test_e2e` | A full run against golden JSON (canonical and default output) |
| `test_garbage_source` | A malformed source is skipped and the batch continues |
| `test_normalizers_edge` | The silent-wrong and fabrication classes |
| `test_adapter_resilience` | Per-record survival, single-object JSON, null nesting, BOM, non-string scalars |
| `test_core_logic_edge` | Identity (login case, transitivity, shared email), merge safety, confidence clamps, malformed paths |
| `test_config_validation` | Duplicate or empty path rejected, BOM config, bad type or `on_missing` |
| `test_torture_e2e` | All edge fixtures at once: survives, schema-valid, no fabrication, deterministic |
| `test_cli_strict` | `--strict` turns an output-stage drop into a non-zero exit |

## Two testing styles

The suite deliberately uses two different assertion styles, because they catch
different kinds of regression.

### Golden-file tests (exact output)

`test_e2e` runs the full pipeline against the demo fixtures and compares the
result byte for byte against committed golden files in
[`tests/golden/`](../tests/golden/). These are the contract: if the canonical
profiles or the default output change at all, the test fails and the diff shows
exactly what changed. This is only possible because the pipeline is deterministic
(invariant 3), including the `candidate_id` hashes and the `--as-of` pin.

### Invariant tests (properties, not exact output)

The edge and torture suites do not memorize output. They assert invariants:

- The batch survived (no exception escaped).
- The output validates against its schema.
- Nothing was fabricated (a missing value is `null` or absent, never invented).
- The run is deterministic (the same input twice gives the same output).
- Counts are consistent (records in, profiles out, skips).

`test_torture_e2e` throws every hostile fixture at the pipeline at once and checks
these properties hold. This style is robust to intentional output changes: adding
a field does not break an invariant test the way it breaks a golden test, so the
two styles complement each other.

## The golden files

Golden files are regenerated intentionally, not automatically. When a change to
the merge or projection logic is meant to change the output, the golden files are
updated in the same commit, so the diff is reviewed rather than silently accepted.
The committed sample output in [`sample_output/`](../sample_output/) is produced
by the same fixtures and kept in sync.

## Running a subset

```bash
pytest tests/test_merge.py            # one suite
pytest tests/test_merge.py -k conflict  # one case by keyword
pytest -q                              # quiet summary
```

## Where to go next

- [Edge cases](11-edge-cases.md) catalogs the inputs behind the resilience suites.
- [Extending the pipeline](13-extending.md) explains which tests to add when you extend the pipeline.
