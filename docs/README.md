# Project Knowledge Base

This directory is the complete reference for the Candidate Profile Transformation
Pipeline. The top-level [`../README.md`](../README.md) is the quick start and
feature tour; the documents here go deeper, explain why each part works the way
it does, and record the design decisions behind them.

Everything here is written to be read by someone who has never seen the code
before. Start at the overview, then follow whichever track fits your goal.

## Reading tracks

**"I want to understand the whole thing quickly."**
1. [Overview](01-overview.md): the problem, the goals, the three invariants, and the vocabulary.
2. [Architecture](02-architecture.md): the stages, the module map, and the one boundary that holds the design together.
3. [Data model](03-data-model.md): the three record types the whole pipeline passes around.

**"I need to work on a specific stage."**
- [Sources and adapters](04-sources.md): reading the four input formats.
- [Normalization](05-normalization.md): turning raw values into canonical formats.
- [Identity resolution](06-identity-resolution.md): deciding which records are the same person.
- [Merge and confidence](07-merge-and-confidence.md): combining records and scoring them.
- [Projection and configuration](08-projection-and-config.md): reshaping output at runtime.
- [CLI reference](09-cli-reference.md): commands, flags, and output.

**"I want to know why it was built this way."**
- [Design decisions](10-design-decisions.md): every notable choice, its rationale, and the alternatives that were rejected.
- [Edge cases and robustness](11-edge-cases.md): the hostile inputs the pipeline is built to survive.

**"I want to change or extend it."**
- [Testing](12-testing.md): how the suite is organized and what it guarantees.
- [Extending the pipeline](13-extending.md): adding a source, a normalizer, or an output shape.

## Document index

| Document | Covers |
|---|---|
| [01 Overview](01-overview.md) | Problem, goals, invariants, glossary, mental model |
| [02 Architecture](02-architecture.md) | Stages, module map, the CanonicalProfile boundary, data flow |
| [03 Data model](03-data-model.md) | SourceRecord, CanonicalProfile, TrackedValue, RunReport |
| [04 Sources and adapters](04-sources.md) | The adapter framework and the four input sources |
| [05 Normalization](05-normalization.md) | Phone, date, country, skill, and email normalizers |
| [06 Identity resolution](06-identity-resolution.md) | Blocking, linking, and clustering |
| [07 Merge and confidence](07-merge-and-confidence.md) | Conflict resolution and confidence scoring |
| [08 Projection and configuration](08-projection-and-config.md) | Runtime output shaping and validation |
| [09 CLI reference](09-cli-reference.md) | Commands, flags, output modes, exit codes |
| [10 Design decisions](10-design-decisions.md) | Rationale for every significant choice |
| [11 Edge cases and robustness](11-edge-cases.md) | Hostile-input handling and deliberate scope limits |
| [12 Testing](12-testing.md) | Test organization, golden files, invariants |
| [13 Extending the pipeline](13-extending.md) | How to add sources, normalizers, and configs |

## Conventions used in these documents

- Code identifiers, file paths, and field names are written in `monospace`.
- Diagrams are written in Mermaid and render directly on GitHub.
- Source references point at real files, for example [`merge/engine.py`](../candidate_pipeline/merge/engine.py), so you can jump from a description to the code.
- "The PRD" refers to [`../prd.md`](../prd.md), the original product requirements document that the implementation follows.
