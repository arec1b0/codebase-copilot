# KubeSentiment separated judge evaluation review

Review date: 2026-10-22. Week 2 step 3 technical acceptance passed on Windows.
The measured quality result is mixed; calibration and release approval remain
false.

## Evidence and scope

This receipt records the maintainer-supplied PowerShell output from:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-judge.ps1 -Baseline $Baseline -Packet $Packet -AllowBackendChange
```

- Code checks: Ruff lint and formatting passed; strict mypy passed over 56
  source files; 223 tests passed.
- Baseline: `artifacts/baselines/20261015T103820.268147Z`.
- Experiment: `artifacts/judge-rescores/20261022T141227.709568Z`.
- Packet ID: `55f70b57d4362caf00762d184b07a65566843c06a93800c044829c6b7f70edee`.
- Evaluation kind: `frozen-answer-judge-rescore`.
- Sampling: `purposive-development-sample`; 20 reviewed development cases.
- All 20 cases completed with no reported errors. Both judge-rescoring and
  step 3 acceptance reported success.
- Generator and retrieval were not called. The experiment compared judge
  ratings against the same human labels on the same frozen answers.

The historical and candidate backend versions were `ollama:0.40.3` and
`ollama:0.40.5`. The explicit backend-change option was enabled, and the report
recorded `backend_changed=true` and `rubric_only_comparison=false`. Observed
differences cannot be attributed to the separated rubric alone.

The aggregate output has been reviewed. The experiment's per-case
`results.jsonl`, reasons and full provenance files have not yet been inspected
for this review. This receipt does not independently verify the Windows files
or adjudicate answer correctness. See the earlier
[human agreement review](kubesentiment-human-agreement-review.md) for historical
scores and sample limitations.

## Paired aggregate results

Scores use the ordinal 0-2 rubric. Changes in agreement are percentage points;
mean absolute error (MAE) is in score points. Lower MAE is better.

| Dimension / measurement | Historical | Candidate | Change |
| --- | ---: | ---: | ---: |
| Faithfulness exact agreement | 13/20 (65%) | 8/20 (40%) | -25 percentage points |
| Faithfulness MAE | 0.35 | 0.80 | +0.45 |
| Human faithfulness-zero cases given a nonzero judge score | 4/4 | 4/4 | Unchanged |
| Relevance exact agreement | 9/20 (45%) | 14/20 (70%) | +25 percentage points |
| Relevance MAE | 0.55 | 0.40 | -0.15 |
| Human relevance-zero cases given a nonzero judge score | 6/6 | 1/6 | 5 fewer cases |

Faithfulness agreement deteriorated on both reported measures. All four cases
assigned faithfulness 0 by the human reviewer still received nonzero judge
scores. Relevance agreement improved on both measures, and five of the six
human relevance-zero cases now received judge score 0.

These are disagreements with the supplied human labels, not measured release
gate false accepts: semantic judge scores remain report-only. Aggregate metrics
do not identify which candidate cases changed, the direction of each error, or
the reason for the faithfulness decline.

Reported judge usage was 12,746 input tokens and 2,626 output tokens, with scope
`validated_complete_call_pairs_only`. These counts do not establish a latency
or cost improvement over the historical judge.

## Decision and next diagnostic step

Technical completion of step 3 is accepted from the supplied Windows receipt.
Overall judge quality improvement has not been established. Preserve
`calibrated=false` and `release_threshold_approved=false`; retain report-only
judge scores and the existing deterministic checks.

Inspect the new experiment's `results.jsonl` alongside the frozen answers,
cited source text and original human labels/reasons before changing the rubric
again. Prioritize the four human faithfulness-zero cases and every candidate
faithfulness disagreement, then check whether the relevance gains reflect the
intended rubric. The aggregate summary alone cannot select a justified prompt
repair.

Preserve the historical baseline and attested labels. Any subsequent prompt
revision requires a new, separately identified development experiment. A
rubric-only causal comparison additionally requires the backend to be held
constant. Do not query the holdout for this diagnosis. This purposive sample
does not establish unseen-data performance, statistical significance, a
release threshold, or completion of all Week 2 work.
