# Demo evaluation dataset card

The demo is retained for regression checks. The separate selected-repository set
is described in [the KubeSentiment runbook](kubesentiment.md), with pinned labels
and a human-readable review copy under `evals/datasets/kubesentiment/`.

| Field | Value |
| --- | --- |
| Dataset | `evals/dataset.jsonl` |
| Version | SHA-256 of exact JSONL bytes, captured in each baseline manifest |
| Source | Supplied four-file `training-demo` Git snapshot |
| Size | 30 authored answerable questions |
| Categories | Six each: locating, explanation, dependency, debugging, change-impact |
| Languages | Python, Go, C++, Markdown |
| Ground truth | Reference answer and source path/line ranges |
| Binding | Chunk text checked against demo files; run records source Git SHA |
| Split | Baseline/development only; no independent holdout |
| Authorship | Assistant-authored from code, not collected user questions or human quality scores |

Labels use complete source ranges rather than environment-dependent chunk UUIDs.
Different corpus paths/text or missing labeled ranges fail dataset validation.
Changes to labels or sources require a fresh dataset identity and baseline.

The source is a small calculator fixture, making the questions repetitive.
This tests a reproducible end-to-end implementation, not general repository
understanding. It excludes realistic dependency graphs, ambiguous bug reports,
long contexts, multilingual questions, and production traffic.

Replace it with 30–50 actual questions about a working repository and reviewed
labels before claiming the corresponding real-repository baseline from the
original plan. Add holdout data and judge calibration in Week 2. This archive
contains no invented generation-quality score.
