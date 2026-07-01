# 09. CLI reference

The command-line interface is defined in
[`cli.py`](../candidate_pipeline/cli.py). It exposes two commands: `transform`
(run the pipeline) and `validate-config` (check a config file). Human-facing
terminal output is rendered by
[`console_report.py`](../candidate_pipeline/console_report.py).

The console entry point is registered as `candidate-pipeline` (see
`pyproject.toml`). When a virtual environment is active it is on the path
directly; otherwise prefix with `uv run`.

## transform

Runs the full pipeline end to end.

```bash
candidate-pipeline transform \
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

### Flags

| Flag | Purpose |
|---|---|
| `--inputs key=path ...` | One or more sources. Keys: `csv`, `ats`, `github`, `resume`. Use `csv:label=path` to ingest several files of one type in a single run. |
| `--config cfg.json` | Swap the projection layer. Omit for the built-in default schema. |
| `--default-region CC` | ISO region used to resolve phones that lack a country code. Applied and flagged; never guessed without it. |
| `--as-of YYYY-MM-DD` | Pins recency decay and `years_experience`. Defaults to today. Pin it for reproducible output. |
| `--live` | Enriches each GitHub record from the real REST API. Falls back to the fixture on any error. Set `GITHUB_TOKEN` to raise the rate limit to 5,000 per hour. |
| `--out path` | Write output JSON to a file. Default is standard output. |
| `--report path` | Write the batch audit trail (skips, conflicts, assumptions, counts). |
| `--pretty` | Pretty-print the JSON output. |
| `--strict` | Exit non-zero if any profile is dropped at the output stage. Graceful adapter skips are not strict failures. |

### What it writes

- **Standard output** carries the JSON when `--pretty` is set or `--out` is not.
  This stream is always pure JSON: it is safe to pipe into `jq` or redirect to a
  file. The human-facing summary never contaminates it.
- **`--out`** writes the same JSON to a file.
- **`--report`** writes the `RunReport` as JSON.
- **Standard error** carries the human-facing summary (see Output modes below).

### --as-of and determinism

`--as-of` fixes "now" for the run. It affects two things: the recency decay of
time-varying fields, and the `years_experience` calculation for ongoing roles.
Pinning it (as the examples and golden tests do) is what makes output byte
identical across runs on different days.

## validate-config

Checks that a config file loads and is well-formed, without running the pipeline.

```bash
candidate-pipeline validate-config --config candidate_pipeline/data/configs/custom_config.json
```

On success it prints the field count and the global `on_missing`. On failure it
prints the reason and exits non-zero. This catches duplicate or empty output
paths, unknown field types, and unknown `on_missing` values before they reach a
real run.

## Output modes

The summary adapts to where standard error goes:

- **Interactive terminal.** A colored table of resolved profiles (candidate,
  merged sources, confidence colored by tier, and flags), followed by a one-line
  batch summary. This is what the hero screenshot in the top-level README shows.
- **Piped or captured (CI, tests, redirection).** A stable plain line:
  `profiles_out=N records_in=N sources_skipped=N`. This keeps logs grep-able and
  makes the summary deterministic for tests.

The distinction is made by `Console.is_terminal`. The important guarantee is that
the rich output is written only to standard error, so standard output stays pure
JSON in every mode.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. Includes runs where profiles were dropped at the output stage, unless `--strict` is set. |
| 2 | `--strict` was set and at least one profile was dropped at the projection or validation stage. |
| non-zero | `validate-config` failed to load the config. |

`--strict` keys off the skip stage: only `projection` and `validation` skips (an
`on_missing: error`, a required miss, or invalid output) count as strict
failures. Graceful adapter and record skips (a bad source, a poison row) are a
core robustness feature, not an error, so they never trip `--strict`.

## Encoding

The CLI reconfigures standard output and error to UTF-8 at startup, regardless of
the console code page. This is why non-ASCII names never crash output on a Windows
console whose default code page would otherwise fail on them.

## Where to go next

- [Projection and configuration](08-projection-and-config.md) explains the `--config` file format.
- [Edge cases](11-edge-cases.md) explains what produces each kind of report entry.
