# Week 2, step 1: saved-run comparison

The accepted Week 1 baseline is Git tag `week1-baseline`, commit
`db0eff2e89b0492228b7f5cdc1f65fe5de239952`. Windows acceptance included 120
tests, the real KubeSentiment baseline, and a successful one-command startup
using existing model assets and a verified complete index. The startup evidence
is `artifacts/launcher/20261015T115845.750620Z`; this was not an empty-cache
Windows cold-start measurement.

This step compares saved evaluation artifacts without starting the API, Docker,
Ollama, Phoenix, or embedding inference. It establishes comparison mechanics;
it does not change the prompt, model, chunking, or retrieval algorithm.
The API/package version remains 0.4.1; the independent comparator identifies
itself as `saved-run-comparison-v1`.

## Inputs and integrity

Each run directory must contain these original files together:

- `version-manifest.json` with dataset, source, index, generator, and judge identities.
- `dataset.jsonl` containing the exact questions, references, and evidence labels.
- `results.jsonl` containing every case once, including explicit execution failures.

The complete source corpus must remain under
`artifacts/corpora/<repo>/<corpus_version>`. Override its parent with
`--corpora-root` when the archived corpora live elsewhere. Each run may use a
different corpus/index version, but both must evaluate the same repository,
source commit, dataset name, and exact dataset bytes. Generator/prompt changes
are permitted and retained in the report.

The comparator verifies index fingerprints, complete corpus integrity, dataset
bytes, case coverage, saved case contents, per-run response identities, and
request/trace ID uniqueness. Saved retrieved records must exactly match the
complete source corpus and contain at most three unique hits. Metrics are
recomputed from those records; an inconsistent saved metric is an input error.
`summary.json` is not used as an authority. Responses are checked for nonempty
answers, citation labels, cited chunk existence and metadata, and valid timing.

Citation checks join by `chunk_id`. An API source label such as S1 is not
assumed to mean rank 1 in the separately measured retrieval. Citation metadata
can be valid even when the answer misinterprets the cited text.

Missing files, changed dataset bytes, duplicate/missing cases, invalid schemas,
or inconsistent identities fail closed. Explicit case errors remain in the
fixed case denominator and fail the gate; missing stages on these errors
contribute zero to gate metrics. Timings use completed, non-error requests and
show their sample counts. Invalid response/citation contracts also fail the
gate even if all aggregate scores are unchanged.

The comparator trusts the saved manifest as the declared provenance. Hashes
detect inconsistency; they are not signatures or independent attestations.
It does not re-execute the historical code, scan for secrets, inspect saved
Phoenix exports, or establish the semantic correctness of a response.

## Development policy

`evals/policies/development-v1.json` is an explicit provisional development
policy, not an agreed production release threshold:

| Measurement | Default treatment |
| --- | --- |
| Hit rate@3, range recall@3, MRR@3 | Reject any aggregate decrease |
| Case execution or deterministic response checks | Reject any failure in either run |
| Faithfulness/relevance judge scores | Report only |
| Latency and token usage | Descriptive only |

Tolerances are absolute metric differences, not relative percentages.
For example, 0.02 allows recall to decline from 0.80 to 0.78. Every per-case
metric decrease is still reported, including decreases offset by improvements
elsewhere. The aggregate policy does not prohibit every individual regression.
No statistical significance or quality improvement is inferred from one run.

Judge deltas require the same saved judge model, revision, rubric, calibration
flags, and model backend version. Otherwise the two scores are shown with an
incomparable delta. Enabling `gate_judge_scores` requires matching judge
identities marked calibrated in both manifests. A boolean is not calibration
evidence: the planned human review and calibration artifact remain necessary.
The historical same-model judge is uncalibrated and stays report-only.

## Windows acceptance

Extract the complete step archive into `C:\Projects`, replacing source files.
Preserve `.git`, `.env`, `.venv`, and `artifacts`. Use the original baseline
directory from the accepted real-repository run:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Baseline = ".\artifacts\baselines\20261015T103820.268147Z"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-comparison.ps1 -Baseline $Baseline
if ($LASTEXITCODE -ne 0) { throw "Week 2 step 1 acceptance failed" }
```

The command runs lint, formatting, strict typing, and all tests, then invokes
the actual comparison CLI for these checks:

| Input | Expected exit | Expected result |
| --- | ---: | --- |
| Original baseline against itself | 0 | All comparable deltas zero |
| Edited copy with all independent retrieval hits removed | 1 | Retrieval gate fails and lists affected cases |
| Edited copy with a nonexistent cited chunk | 1 | Citation contract fails |
| Edited copy with judge scores lowered to zero | 0 | Decreases reported; uncalibrated judge cannot gate |
| Edited copy missing one case | 2 | Input rejected |

Success prints `WEEK 2 STEP 1 ACCEPTANCE PASSED`. Evidence, CLI stdout/stderr,
reports, and edited fixtures are retained under a unique timestamped directory
in `artifacts/acceptance/week2-step1/`. The baseline is read-only throughout.
Edited fixture manifests explicitly identify the synthetic mutation and its
parent results hash. These copies are not model or retrieval measurements and
must not be selected as a new baseline.

If the original manifest, dataset, or corpus is missing, restore the complete
archived artifacts. Do not reconstruct a historical manifest from current
versions. A pasted `results.jsonl` alone is not a complete run. Historical demo
runs did not always retain `dataset.jsonl`; future demo evaluations now save it,
as the repository runner already did.

## Compare a measured candidate

Create a separate candidate evaluation using the existing runner and retain
its printed directory. Once both measured runs exist:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Baseline = ".\artifacts\baselines\20261015T103820.268147Z"
$Candidate = Read-Host "Path to the measured candidate evaluation directory"
uv run --locked python -m evals.compare --baseline $Baseline --candidate $Candidate
if ($LASTEXITCODE -ne 0) { throw "Evaluation comparison did not pass" }
```

The default report directory is `artifacts/comparisons/<UTC timestamp>`.
`comparison.json` retains file hashes, complete declared manifests, effective
policy and its file hash, comparator source-tree hashes and Python version,
observations, technical failures, aggregate deltas, and per-case decreases.
`report.md` summarizes the gate and individual cases.
Use `--output` for a chosen new directory; existing output is never replaced.
The CLI returns 0 for a passed comparison, 1 for a valid failed gate, and 2
for invalid inputs, incompatible runs, policy errors, or output I/O errors.

## Remaining Week 2 work

- Treat the already inspected 30 questions as development/regression data;
  author an independent holdout instead of claiming unseen data from this set.
- Preserve actual ordered API context IDs for each measured answer.
- Separate faithfulness and relevance judge inputs, then calibrate against
  20 genuinely human-labeled examples and agree release tolerances.
- Add secret-detection and semantic regression fixtures.
- Add PR smoke and full evaluation CI with candidate/baseline reports, then
  demonstrate an actual broken-pipeline failure in CI.

No GitHub Actions workflow, branch protection, new holdout acceptance, human
labels, or full Week 2 completion is claimed by this step.
