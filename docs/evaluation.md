# Baseline contract

For offline comparison of saved runs, see
[Week 2 saved-run comparison](week2-comparison.md). The original live baseline
measurement contract below remains applicable.

Run `python -m evals.run --manifest <accepted manifest.json>` from the project
root while the API, Ollama, Docker Qdrant, and Phoenix are running. The runner
uses the saved demo corpus by default and actual cached CPU embeddings. Pass
`--profile evals/datasets/kubesentiment/profile.json` for the pinned repository
dataset; see [the repository runbook](kubesentiment.md). It verifies index/
corpus hashes, source labels, API/prompt/model versions, request/trace IDs, and
citation provenance.

## Measurements

Each of 30 cases has a separate retrieval measurement with the same pinned
backend, language filter, and top-k 3 as its API call. Hits and scores are saved.
New API responses also retain the actual ordered context after the prompt budget
filter. Independent retrieval hits are not substituted for that context.
A target range is covered only when a chunk contains the entire labeled range
in the same source path. Repository profiles additionally require the exact
evidence quote within the asserted line range. References and question bytes
are pinned alongside the complete portable corpus layout.

| Metric | Definition |
| --- | --- |
| Hit rate@3 | Fraction of cases with at least one covered evidence range |
| Range recall@3 | Mean per-case covered ranges / all labeled ranges |
| MRR@3 | Mean reciprocal rank of the first relevant chunk, zero for misses |
| Client p50/p95 | Nearest-rank percentiles of successful query HTTP wall time |
| Model TTFT p50/p95 | Client-observed first nonempty Ollama content fragment, from API telemetry |
| Tokens | Actual generation and judge usage, counted separately |
| Faithfulness/relevance | Judge's explicit 0–2 rubric scores and saved reasons |

One saved warm-up is excluded from metric aggregates. Its initial cache state
is not claimed to be cold. The run is sequential at concurrency 1 with a fixed
question mix; this is not a capacity/load test. Judging executes between API
queries and can affect model residency. Judging and trace downloads are excluded
from measured HTTP duration. TTFT remains model-side, not API streaming latency.

Failed cases retain errors and are never given invented latency or tokens.
Successful-case percentiles include sample counts; judge coverage is reported
separately. A case error or incomplete five-trace export fails technical acceptance.
No quality threshold is agreed yet: a low score remains a valid measurement.

## Judge limitations

`evals/judge.py` versions the rubric and records the actual model digest/backend,
ratings, reasons, and usage. Version 2 uses two separate native calls:
faithfulness receives only the answer and cited source text; relevance receives
only the question, reference and answer. Per-call rubric/input hashes and usage
are saved, with aggregate usage for both calls. Historical v1 scores remain
readable; cross-rubric full-run score deltas are incomparable. The rubric assigns zero to a factual non-answer on
this entirely answerable set. This is not a general abstention-quality metric.

The judge is the same model as generation, so its uncalibrated estimates can share
the generator's errors. Citation validity does not prove semantic faithfulness.
No human score or production-quality claim is implied. Week 2 requires calibration,
holdout data, and agreed regression thresholds.

## Trace and version evidence

Collector readback is checked after warm-up before the longer sequence. Five
complete successful query traces are downloaded using Phoenix's
`GET /v1/projects/codebase-copilot-week1/spans?trace_id=<hex>` endpoint. Each export
must contain the matching request ID/API root and retrieval, rerank, generation,
and citation-validation children. Normally these are the warm-up plus four measured
traces. Local SDK/exporter success alone is insufficient.

The manifest records real running PostgreSQL/Qdrant/Phoenix image IDs and registry
digests, source commit, index/embedding identity, prompt/model/dataset versions,
lockfile, and source-file hashes. Application Git SHA/dirty state are recorded
when available. Archive-only code has a null application Git SHA and an explicit
source-tree hash instead. Native Ollama has no serving-container digest to record.

Results are checkpointed after each case. Every run receives its own timestamped
directory. Retain `version-manifest.json`, `results.jsonl`, `summary.json`,
`report.md`, `warmup.json`, `abstentions.jsonl`, `errors.jsonl`, and `traces/`
together. Repository runs also retain `dataset.jsonl` and `dataset-profile.json`.

## Week 2 dataset separation and human review

See [the dataset/review workflow](week2-dataset-review.md) for the frozen 30/30 development/holdout split, procedural release guard, source-bound 20-item packet and human agreement audit. Preparation leaves all human scores null and does not calibrate or approve release thresholds.

## Frozen-answer judge comparison

[Step 3](week2-judge-context.md) compares the historical v1 judge with separated
v2 calls against the same 20 human-labelled answers. It creates a distinct
judge-rescoring experiment, preserves the original baseline and labels, and
leaves calibration/release approval false. The experiment does not require the
query API, Qdrant or Phoenix. Real v2 agreement must be measured locally.
