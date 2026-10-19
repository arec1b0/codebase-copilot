# Week 2 step 2: dataset separation and human judge review

The 30 previously inspected KubeSentiment cases are development data. This step
adds 30 assistant-authored holdout cases and a source-bound packet for 20 human
reviews. Preparation does not complete human annotation or calibrate the judge.

## Source and split

Both profiles bind KubeSentiment commit
1aa3ebfd3f0467ea61142dff72d6534aa6968e20 and the same portable 600-character chunk
layout. Each split has six questions in each of five categories: locating,
explanation, dependency, debugging and change-impact.

Development question bytes and profile remain unchanged. Development SHA-256:
e37fad215160bab13414d459f60063e00cfe9eb8d5f7cf70a5ce5b19c1d25f59

Holdout SHA-256: 60ee766e4174f3f2d1b0c9e92e099d83932ef2f7763f790c46c011adc9d8d0ac

The holdout uses correlation middleware, online normalization, anomaly buffering,
feedback publishing, priority queues and result caching. Its six evidence files
are disjoint from the eight development evidence files. Validation checks profile
and question checksums, category balance, unique IDs, normalized question overlap,
portable source layout, exact quotes and containment of each source range in one
accepted chunk.

The holdout is public and assistant-authored, awaiting maintainer review.
File separation reduces direct evidence leakage; it does not prove independence
or prevent deliberate copying. No holdout retrieval, answer generation or model
scoring is run during preparation.

The runner checks registered dataset identity before loading an index or live
clients. Default development runs reject the holdout. Explicit --purpose release
permits it for a release measurement; do not use that measurement for tuning.
This guard is procedural, not an authorization boundary.

## Review package

selection-v1.json fixes a purposive sample of 20 existing development results,
four per category, by canonical parsed-results checksum. Historical answers, model ratings and request metadata are not published in this
branch. Prepare the packet locally from the complete original baseline. The
acceptance wrapper binds the original manifest and checks its declared response
identities. If using the packet CLI without its optional --run-manifest argument,
judge identity and runtime-manifest hash remain null; they are never synthesized.

The packet contains items.jsonl, rubric.md, faithfulness.md, relevance.md,
SOURCE-LICENSE.txt, README.md, packet.json and labels.json. The faithfulness view
shows answers and cited source only; relevance adds questions and references.
Neither view contains judge ratings. Prior exposure to old results means this
is not an independently blinded study.

Packet identity, item digests, immutable file digests and a provenance checksum
detect accidental modification. They are not signatures. Re-running creation
refuses an existing output directory, protecting saved annotations.

All 20 human labels start null. The reviewer must enter both integer scores,
separate reasons, an annotator identifier, label_origin=human and a timezone-aware
review timestamp. Reference issues need notes and adjudication. Validation with
--require-complete returns 3 while labels or attestation are pending; invalid
packets return 2. Audit only runs after all 20 items are complete and attested.
It reports exact agreement and mean absolute error for both dimensions.
It always leaves calibrated=false and release_threshold_approved=false.

## Windows acceptance

Keep the stash created before switching to the Step 1 branch. Fetch this branch
and switch from a clean working tree; do not extract an archive over a checkout.

~~~powershell
Set-Location "C:\Projects\codebase-copilot"
git fetch origin
git switch --track origin/feat/week2-datasets-human-review
if ($LASTEXITCODE -ne 0) { throw "Branch switch failed" }

$Baseline = ".\artifacts\baselines\20261015T103820.268147Z"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-dataset-review.ps1 -Baseline $Baseline
if ($LASTEXITCODE -ne 0) { throw "Dataset/review preparation failed" }
~~~

This wrapper runs code checks, validates the full original saved run and corpus,
checks source-only split contracts, builds the packet twice, verifies byte
reproducibility and confirms that incomplete labels block an agreement audit.
It preserves original baseline files. Success means preparation acceptance;
human review remains pending.

Use the printed packet directory:

~~~powershell
$Packet = ".\artifacts\acceptance\week2-step2\<timestamp>\human-review"
uv run --locked python -m evals.human_review validate --packet $Packet --require-complete
# Expected exit 3 before the human fills labels.json.
~~~

After manually filling labels.json:

~~~powershell
uv run --locked python -m evals.human_review validate --packet $Packet --require-complete
if ($LASTEXITCODE -ne 0) { throw "Human review incomplete or invalid" }
uv run --locked python -m evals.human_review audit --packet $Packet --results "$Baseline\results.jsonl" --output ".\artifacts\human-agreement.json"
if ($LASTEXITCODE -ne 0) { throw "Agreement audit failed" }
~~~

## Remote verification and recovery

The initial workspace disconnected after a local 178-test run and a subsequent
provenance change. Files were reconstructed from the work log and pinned source.
The restored holdout wording is newly frozen with the checksum above; do not use
an earlier unpublished holdout checksum or packet ID for this branch.

GitHub Actions verifies the final branch, builds a real pinned-source corpus,
validates the split without models and uploads source and review-tools ZIPs.
The review-tools ZIP contains instructions, selection and rubric; it is not the
20-answer review packet. Create that packet locally from the original baseline.
CI has no generation, Qdrant or Ollama dependency. Tests contain explicitly
synthetic answers and labels only to exercise review and audit mechanics.
