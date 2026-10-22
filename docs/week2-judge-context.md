# Week 2 step 3: exact generator context and separated judge calls

Version 0.5.0 adds recorded API context, two isolated judge calls and a local
experiment for re-scoring the same 20 reviewed development answers. The generator
prompt, model, ingestion, embeddings and index configuration are unchanged.
No new dependencies are required.

## Recorded context

New POST /query responses include:

- context_sources: all whole source ranges actually included in the model input,
  in prompt order, with their S1/S2/... labels and chunk/citation metadata.
- generation_input_sha256: SHA-256 of canonical UTF-8 JSON for the exact system
  and user messages. This does not hash the whole native HTTP request/options.

The context includes sources the answer did not cite. Oversized retrieved chunks
are skipped before these records are made; labels reflect the remaining prompt
sources. If generation is skipped, context_sources is [] and the message hash is
null. A model abstention can still have nonempty context and a message hash.
Legacy responses retain context_sources=null; unknown context is never inferred
from their citations or an independent retrieval measurement.

The normal evaluation runner requires this context contract and records it in
its manifest as ordered-source-context-v1. It validates source records, language,
label order, unique chunk IDs, cited-source membership and the message hash.
Saved-run comparison retains compatibility with historical records. For a
recorded context with another historical prompt hash, it can check source and
label metadata but cannot recompute the old full message hash using current
instructions. Hashes provide integrity, not an independent runtime attestation.

The API traces record source labels and chunk IDs without raw questions or code.
Restart the API with version 0.5.0 before a future live pipeline evaluation.
Frozen-answer re-scoring below does not call the query API.

## Judge v2

The rubric identity is codebase-judge-v2-separated. Each response receives two
native Ollama calls using strict DimensionAssessment JSON (score and reason).

| Dimension | Input data |
| --- | --- |
| Faithfulness | Answer and the complete text of its cited sources |
| Relevance | Question, reference and answer |

Faithfulness receives neither the question nor the reference. Relevance receives
no source-context field. Supported but incomplete claims can receive high
faithfulness and low relevance. Embedded instructions are treated as untrusted
input in both rubrics; this does not prove prompt-injection resistance.

Both whole inputs are checked before the first call. Each call has a 14,000-byte
combined system/user limit, num_ctx=8192, num_predict=512, temperature=0 and seed=42.
Truncated output, unsupported tools, wrong schemas, invalid usage or changed
model identity fail scoring. The model identity is checked before and after each
call. Input and output token usage are retained per call and summed per answer.
Failed pairs may consume tokens not represented in successful-pair totals.

The manifest pins both rubric/schema/options hashes and their aggregate hash.
Each saved judge_calls record includes the dimension, rubric hash, message hash,
assessment and usage. The comparator validates the two ordered records, declared
rubrics, aggregate scores/reasons and summed usage; it recomputes input hashes
for the currently known v2 rubric. Historical v1 scores remain readable and
report-only. Cross-rubric deltas in the full-run comparator are incomparable.

## Frozen-answer experiment

The existing human agreement review found exact agreement of 65% for
faithfulness and 45% for relevance on the purposive 20-case development sample.
See kubesentiment-human-agreement-review.md for the original evidence and limits.

The new experiment:

1. Validates the complete original baseline, source corpus and completed,
   attested human review packet before model calls.
2. Matches each reviewed question, answer, request ID and cited source to the
   original saved response. Requires the same judge revision. The Ollama backend
   must also match by default; the explicit backend-change experiment below
   records an exception without weakening the model-revision check.
3. Re-scores only the 20 selected frozen answers: 40 scoring calls, plus identity
   checks. It does not call generation, retrieval, embeddings, Qdrant or Phoenix.
4. Writes a new experiment directory and checks that the original baseline,
   corpus, packet and label bytes remain unchanged. Existing output is refused.
5. Recomputes old/new exact agreement, MAE and human-zero/judge-nonzero counts
   against the same human labels. A partial failure produces no candidate
   agreement summary and exits unsuccessfully.

The output is a judge-rescoring experiment, not a new full-pipeline baseline.
Legacy generator context remains unknown. The evidence already preserved for
faithfulness is the cited source text, so no context is reconstructed for it.
The selected data is development data; agreement changes do not establish unseen
accuracy, statistical significance or production readiness. The holdout is not
queried. calibrated and release_threshold_approved remain false even if agreement
improves. Review disagreements before proposing any calibration approval.

## Windows acceptance

Apply the source patch to the same working copy used for the accepted 179-test
step. The patch does not stage, commit or publish files. Keep the original .git,
.env, .venv and artifacts directories. All written source is UTF-8 without BOM.

First run the offline code checks:

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
if ($LASTEXITCODE -ne 0) { throw "Code acceptance failed" }
```

Then ensure the same historical local Ollama model/backend is available. No query
API or Docker services are required for re-scoring. The original local corpus
must still be present.

```powershell
$Baseline = ".\artifacts\baselines\20261015T103820.268147Z"
$Packet = ".\artifacts\acceptance\week2-step2\20261022T104137.655038Z\human-review"

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-judge.ps1 -Baseline $Baseline -Packet $Packet
if ($LASTEXITCODE -ne 0) { throw "Week 2 step 3 acceptance failed" }
```

The wrapper runs code checks again and performs the real 40-call experiment.
For a direct run after code acceptance, use:

```powershell
uv run --locked python -m evals.rejudge --baseline $Baseline --packet $Packet
if ($LASTEXITCODE -ne 0) { throw "Frozen-answer re-scoring failed" }
```

The command prints the new artifacts/judge-rescores/<timestamp> directory.
Retain identity-check.json, version-manifest.json, results.jsonl, agreement.json
and report.md together.
The manifest retains original run hashes, packet/labels identity, judge identity,
rubric hashes and current source hashes. An optional --labels argument selects
an external completed labels file; --corpora-root and --ollama-port support local
paths/ports. Exit 0 means all cases completed, 1 means a scoring experiment had
case errors, and 2 means an input, identity or I/O failure. Success does not imply
an agreement or calibration threshold has been met.

## Acceptance criteria

- Existing ingestion, retrieval, query, comparison and human-review tests pass.
- New tests verify actual context ordering, budget exclusions, uncited sources,
  empty-context abstention, legacy unknown context and tamper detection.
- Native mock HTTP tests verify disjoint judge inputs, independent scores,
  summed usage, malformed responses and changed identity rejection.
- Temporary Git/corpus fixtures verify frozen-answer re-scoring, pending-label
  rejection, preserved inputs, refused overwrites and partial-failure behavior.
- Local Windows re-scoring completes all 20 cases and retains the paired report.

No real v2 model measurement is claimed by the offline tests. No release gate,
calibration approval, full Week 2 completion, commit or publication is performed
by these commands.

Commit message:
`feat: preserve generation context and separate judge evaluations`

## Local verification receipt

On 2026-10-22, Linux with CPython 3.12.14: 219 tests passed; Ruff lint passed;
Ruff format checked 58 files; strict mypy passed over 56 source files. Tests
include the actual re-scoring CLI with a native HTTP mock and explicit synthetic
answers/labels. The real local Ollama re-scoring experiment and Windows wrapper
have not been executed in this environment. Run the Windows acceptance command
above to produce the actual v2 agreement report before making a quality claim.

## Diagnosing a judge identity mismatch

Before scoring, rejudge writes identity-check.json in the new experiment
folder. It records the expected and observed model name, model revision and
Ollama backend version, plus the fields that differ. This is a preflight
snapshot: scoring_calls_started=false describes the moment of the check.
A mismatch stops before any scoring call and includes both values and the
report path in the error. The historical manifest and human labels are preserved.

The same rubric/model comparison requires the original identity. Inspect the
report before restoring software or model assets; do not edit the historical
manifest to match the current installation. A backend change would require a
separately identified experiment rather than silently relaxing this comparison.
For quick diagnosis after code checks have passed, invoke evals.rejudge directly;
there is no need to rerun all tests merely to display the mismatch.

Identity diagnostics verification: 220 tests passed, Ruff clean, strict mypy
clean over 56 files. Revision and backend mismatch tests verify that no scoring
calls are made and that expected/observed values are retained.

## Explicit experiment with a changed Ollama backend

If only the Ollama backend differs, --allow-backend-change permits a separately
identified configuration comparison. It never permits a changed model name or
model revision. Without the flag, the historical identity check remains strict.
The observed candidate identity is still pinned before and after every call;
a mid-experiment backend or model change fails scoring.

For the observed local transition ollama:0.40.3 to ollama:0.40.5, run:

```powershell
uv run --locked python -m evals.rejudge --baseline $Baseline --packet $Packet --allow-backend-change
if ($LASTEXITCODE -ne 0) { throw "Backend-change judge experiment failed" }
```

The full acceptance wrapper also exposes the option:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-judge.ps1 -Baseline $Baseline -Packet $Packet -AllowBackendChange
if ($LASTEXITCODE -ne 0) { throw "Week 2 step 3 acceptance failed" }
```

identity-check.json retains matched=false and accepted=true for this allowed
backend-only difference. It preserves expected/observed values and records the
explicit option. Both version-manifest.json and agreement.json retain
historical_backend_version, candidate_backend_version, backend_changed=true
and rubric_only_comparison=false. report.md states that score differences
cannot be attributed to the rubric alone. The old and candidate scores are
still measured against the same frozen answers and human labels.

The historical manifest and labels are not edited. Calibration and release
approval remain false. Do not use the new scores as evidence that changing only
the rubric caused a quality change: the backend changed too.

Local verification: 223 tests passed; cases cover strict rejection without the
flag, accepted backend-only changes, rejected revision changes even with the
flag, and rejection of backend changes during scoring. The real 40-call model
measurement remains a local Windows acceptance task.
