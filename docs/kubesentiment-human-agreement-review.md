# KubeSentiment human agreement review

Review date: 2026-10-22. This report records the completed Week 2 development
review and the decision to keep the historical judge report-only.

## Evidence and scope

The maintainer completed and attested all 20 selected human labels. Packet
validation reported completed=20, pending=0 and ready_for_agreement_audit=true.
The agreement audit completed successfully against the original saved results.
Both JSON copies in the supplied PowerShell transcript contain the same audit.

- Sampling: purposive development sample, four cases per task category.
- Packet ID: `55f70b57d4362caf00762d184b07a65566843c06a93800c044829c6b7f70edee`.
- Labels SHA-256: `ecc072da0974f3381c8de260ff4169c592cae170e8c6a65e98c9ded3dd766a39`.
- Runtime manifest SHA-256: `46241156a08c13b74d2d902ee204270edb7dd0236d5a072bc2d83fe293fccc13`.
- Declared judge: `qwen2.5-coder:3b`, also used as the generator.
- Model revision: `sha256:f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225`.
- Rubric version: `codebase-judge-v1`.
- Rubric SHA-256: `adc1f7c316763242d31417c53f73c594fac8936fe615bf8a951d146b5f356886`.

The uploaded audit contains numeric labels and differences, not the reviewer
reasons or full answers. This report verifies the arithmetic and records the
supplied human labels as the comparison reference; it does not independently
adjudicate answer correctness or attest the historical runtime.

## Recomputed results

Scores use the ordinal 0-2 rubric. Mean absolute error is in score points.

| Measurement | Faithfulness | Relevance |
| --- | ---: | ---: |
| Reviewed cases | 20 | 20 |
| Exact matches | 13/20 (65%) | 9/20 (45%) |
| Mean absolute error | 0.35 | 0.55 |
| Human mean | 1.20 | 1.10 |
| Judge mean | 1.25 | 1.25 |
| Judge score above human score | 4 | 7 |
| Judge score below human score | 3 | 4 |
| Human score 0, judge score 1 | 4 | 6 |
| Judge score 0 | 0 | 0 |

Every disagreement is one score point. Similar average scores conceal material
case-level differences, particularly the failure to assign score 0 to any of
the cases assigned 0 by the reviewer.

Faithfulness counts, with human labels as rows and judge labels as columns:

| Human / judge | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 0 | 4 | 0 |
| 1 | 0 | 8 | 0 |
| 2 | 0 | 3 | 5 |

Relevance counts:

| Human / judge | 0 | 1 | 2 |
| --- | ---: | ---: | ---: |
| 0 | 0 | 6 | 0 |
| 1 | 0 | 5 | 1 |
| 2 | 0 | 4 | 4 |

## Cases requiring attention

All four human faithfulness-zero cases received judge score 1:
`dependency-01`, `dependency-05`, `dependency-06`, `debugging-06`.

All six human relevance-zero cases received judge score 1:
`dependency-05`, `dependency-06`, `debugging-03`, `debugging-06`,
`changeimpact-01`, `changeimpact-04`.

The judge assigned identical faithfulness and relevance scores in all 20 cases.
The human assigned different scores across the two dimensions in eight cases.
This pattern motivates testing separate judge inputs and calls. It does not
establish that a shared prompt caused the observed disagreements.

These zero-score mismatches are disagreements with the supplied review labels,
not measured release-gate false accepts: no semantic judge gate was enabled.

## Decision

Human review and agreement measurement are complete for this sample. Calibration
approval remains pending. Retain `calibrated=false` and
`release_threshold_approved=false`; keep semantic judge scores report-only.
Continue using deterministic integrity, citation and retrieval checks under the
existing provisional comparison policy.

The 20 cases were selected from previously inspected development data. They
cannot establish unseen-data performance, population agreement or a production
release threshold. Prior exposure to historical model ratings also limits
blinding. No holdout model evaluation was performed as part of this review.

## Next implementation step

1. Preserve the ordered source labels and chunk IDs actually supplied to the
   generator. Distinguish them from a later independent retrieval measurement.
2. Evaluate faithfulness with the answer and cited source text only; evaluate
   relevance with the question, reference and answer in a separate call.
3. Version both judge rubrics and schemas, and retain usage and model identity.
   Preserve the historical v1 run, human labels and agreement audit.
4. Re-score the same frozen answers against the same human labels to measure
   development agreement changes without introducing generator changes.
5. Review residual disagreements before proposing calibration or gate
   tolerances. Improvements on this development sample require separate
   validation before a release claim; preserve the holdout release-only policy.

Suggested commit message for this report:
`docs: record KubeSentiment human judge agreement review`
