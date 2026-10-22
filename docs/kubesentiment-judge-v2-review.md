# KubeSentiment separated judge evaluation review

Review date: 2026-10-22. Week 2 step 3 technical acceptance passed on Windows.
The candidate assigned faithfulness 2 to every reviewed answer, including all
four human faithfulness-zero cases. Relevance agreement improved, but inspection
found unsupported explanations in both dimensions. Keep the judge report-only;
calibration and release approval remain false.

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

The subsequent review inspected all 20 uploaded candidate rows and 40 reasons,
joined them to the original uploaded 30-row baseline and the previously supplied
human agreement audit, and reconstructed the two judge inputs for each case.

| Consistency check | Result |
| --- | --- |
| Candidate cases | 20 unique IDs, exactly matching the reviewed human sample; no missing or extra cases |
| Frozen answers | All 20 answer SHA-256 values and request IDs match the original uploaded baseline |
| Historical scores | All 40 audit scores match their original baseline scores |
| Candidate calls | 40 typed call records; dimension scores/reasons equal the aggregate fields |
| Judge inputs and rubrics | All 40 input hashes and rubric hashes match reconstruction using the local v2 code |
| Cited source text | Chunk content hashes checked; all cited text occurs in the pinned source at commit `1aa3ebfd3f0467ea61142dff72d6534aa6968e20` |
| Usage | Per-call counts sum to each row and to the supplied summary |
| Metrics | Both dimensions reproduce the supplied agreement, MAE and human-zero mismatch counts |

Reconstruction used the cited chunks embedded in the original baseline rows,
not newly retrieved text or neighboring source code. This rules out mismatched
answers or reconstructed judge payloads in the supplied files as an explanation
for the observed disagreement. It does not independently attest the Ollama
runtime, reconstruct the legacy generator's full context, or validate the
unprovided experiment manifest. No model calls were made for this review.

The original attested human reasons have not been supplied. Numeric human
labels remain frozen; source inspection below records observable support gaps
and ambiguous cases without silently replacing those labels. See the earlier
[human agreement review](kubesentiment-human-agreement-review.md) for sample
limitations.

Uploaded input SHA-256 values, for reproducibility:

| Input | SHA-256 |
| --- | --- |
| Candidate `results.jsonl` | `a07a7468a43a52195e91680756a7809b87a5d8985686343e300da817b4d5a9a5` |
| Original baseline transcript `Вставленный текст(1).txt` | `080d73598af775e52a15a18a1bcb95a0f900bed70d7f39b02b587b1dc1f3b613` |
| Original human audit transcript `Вставленный текст(5).txt` | `f80d0b8a4f1f85d5f874af44bc4e2497f8204400d0f91bfc9e4d15a9369bdd16` |

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
gate false accepts: semantic judge scores remain report-only.

## Faithfulness: constant maximum scores

Candidate score distribution is 0/0/20 for scores 0/1/2. The candidate therefore
behaves exactly like a constant-2 scorer on this sample. Its 40% agreement is
simply the proportion of human faithfulness labels equal to 2. It provides no
score discrimination among the reviewed answers.

The agreement decline decomposes exactly:

- Eight previously matched human-1 cases changed from judge 1 to 2, losing eight
  exact matches.
- Three human-2 cases improved from judge 1 to 2: `explanation-01`,
  `explanation-03`, `debugging-04`, gaining three exact matches.
- The four human-0 cases changed from judge 1 to 2. They remain disagreements,
  and each absolute error increases from one point to two.
- Five previously matched human-2 cases remain matched.

Thus exact matches are `13 - 8 + 3 = 8`; absolute error is
`7 + 8 - 3 + 4 = 16`, giving MAE `16/20 = 0.80`. All 12 remaining disagreements
are overratings relative to the supplied human labels. Dependency cases account
for four of the nine additional absolute-error points, and change-impact cases
for three; the complete category decomposition is below.

| Category (four cases each) | Faithfulness matches, old to new | Absolute-error change |
| --- | ---: | ---: |
| Locating | 4 to 2 | +2 |
| Explanation | 2 to 3 | -1 |
| Dependency | 1 to 0 | +4 |
| Debugging | 2 to 2 | +1 |
| Change impact | 4 to 1 | +3 |

Verified examples of support failures in the candidate reasons:

| Case | Observed reason versus the actual judge input |
| --- | --- |
| `debugging-06` | The reason says S2 explicitly contains an `if detector.baseline_established is False` return. S2 is `app/api/routes/monitoring_routes.py:221-232`, a response-dictionary fragment. It contains no such condition or `return None`. The reason invents evidence outside the supplied fragment. |
| `dependency-06` | The answer generically says the factory calls a PyTorch backend getter. S2 is `app/models/factory.py:30-41`, a docstring describing backend selection and caching; it contains no getter call. The reason treats that general description as direct proof of the specific behavior. |
| `dependency-01` | S1 is `app/core/dependencies.py:94-106`, an injection-provider signature/docstring. It describes supplying collaborators, not retaining them as constructor attributes. The reason promotes injection into direct evidence of retention. |
| `dependency-05` | The cited fragments describe dispatch and shutdown waiting, but omit the done-callback implementation. The reason asserts support for tracking and removal on completion. Shutdown cleanup does not by itself establish that lifecycle claim. Its 500-character reason also ends mid-sentence; a valid length bound did not ensure a complete explanation. |
| `locating-03` | The reason says all three factual claims are directly supported. The cited RedisConfig fragment does not include the numerical TTL assignment, so it cannot establish the answer's 3600-second TTL claim. |

Several other disagreements need care rather than automatic relabeling. For
example, `changeimpact-01` states current prefix-matching behavior while the
question asks about a hypothetical equality change. Faithfulness receives no
question by design, so this counterfactual omission primarily belongs to
relevance. Similarly, partial or vague wording is not automatically an
unsupported factual claim. The human rubric also separates support from
completeness. Read the original human reasons before classifying every human-1
versus candidate-2 disagreement as the same failure.

## Relevance: gains with important counterexamples

Candidate scores are 0 for seven cases, 1 for six, and 2 for seven. Its two
dimension scores differ on 13 of the 20 cases, whereas historical dimension
scores were identical on all 20. This confirms different observed outputs, not
that the separated protocol caused the improvement.

Six cases gain an exact match: `explanation-01`, `dependency-05`,
`debugging-03`, `debugging-06`, `changeimpact-01`, `changeimpact-04`.
`locating-03` loses an exact match. Hence matches increase from 9 to 14.
Absolute error decreases by six points on the improved cases and increases by
one point each on `locating-03`, `dependency-02` and `dependency-06`:
`11 - 6 + 3 = 8`, giving MAE `8/20 = 0.40`.

| Case | Observed relevance issue |
| --- | --- |
| `locating-03` | Judge 0, human 1. The reason treats the answer as unrelated TTL information, overlooking its first sentence naming `RedisCacheClient._make_key`. The missing key format warrants incompleteness, but the reason falsely denies the direct partial answer. |
| `dependency-02` | Judge 0, human 2. The answer explicitly identifies `max_text_length` in `ModelConfig` as the setting controlling the named service's input length. The reason claims this introduces an unrelated concept instead of addressing the question. |
| `dependency-06` | Judge 2, human 0. The answer repeats that a getter is called without naming it. The reference names `get_sentiment_analyzer`; the answer omits the essential requested fact. |
| `dependency-05` | Judge 0 now matches human 0, but the reason says the answer mentions `self._pending_tasks.discard`. That identifier is in the reference, not the answer. A matching score can conceal an incorrect explanation. |
| `debugging-06` | Judge 0 matches human 0, but its reason attributes disabled-detection and insufficient-sample conditions to the answer. Those are reference facts; the answer only discusses an unestablished baseline. |
| `changeimpact-01` | Judge 0 matches human 0. The answer does explicitly address `/docs/extra`; its error is failing to account for the hypothetical equality change, rather than failing to mention the path as the reason suggests. |

Five human relevance-zero cases now receive 0, but `dependency-06` worsens to 2.
Together with `dependency-02` (human 2, judge 0), it accounts for the two
two-point relevance errors. Good aggregate movement does not justify accepting
the relevance judge as calibrated.

## Complete paired scores

Each score pair is **faithfulness / relevance**. Human and historical values
come from the supplied audit; candidate values come from the uploaded rescore.

| Case | Human | Historical | Candidate |
| --- | ---: | ---: | ---: |
| locating-01 | 1 / 2 | 1 / 1 | 2 / 1 |
| locating-03 | 1 / 1 | 1 / 1 | 2 / 0 |
| locating-05 | 2 / 2 | 2 / 2 | 2 / 2 |
| locating-06 | 2 / 1 | 2 / 2 | 2 / 2 |
| explanation-01 | 2 / 2 | 1 / 1 | 2 / 2 |
| explanation-02 | 1 / 1 | 1 / 1 | 2 / 1 |
| explanation-03 | 2 / 1 | 1 / 1 | 2 / 1 |
| explanation-06 | 2 / 2 | 2 / 2 | 2 / 2 |
| dependency-01 | 0 / 1 | 1 / 1 | 2 / 1 |
| dependency-02 | 1 / 2 | 1 / 1 | 2 / 0 |
| dependency-05 | 0 / 0 | 1 / 1 | 2 / 0 |
| dependency-06 | 0 / 0 | 1 / 1 | 2 / 2 |
| debugging-01 | 2 / 2 | 2 / 2 | 2 / 2 |
| debugging-03 | 1 / 0 | 1 / 1 | 2 / 0 |
| debugging-04 | 2 / 2 | 1 / 1 | 2 / 1 |
| debugging-06 | 0 / 0 | 1 / 1 | 2 / 0 |
| changeimpact-01 | 1 / 0 | 1 / 1 | 2 / 0 |
| changeimpact-02 | 2 / 2 | 2 / 2 | 2 / 2 |
| changeimpact-04 | 1 / 0 | 1 / 1 | 2 / 0 |
| changeimpact-06 | 1 / 1 | 1 / 1 | 2 / 1 |

Reported judge usage was 12,746 input tokens and 2,626 output tokens, with scope
`validated_complete_call_pairs_only`. These counts do not establish a latency
or cost improvement over the historical judge.

## Decision and next diagnostic step

Technical completion of step 3 is accepted from the supplied Windows receipt.
Overall judge quality improvement has not been established. Preserve
`calibrated=false` and `release_threshold_approved=false`; retain report-only
judge scores and the existing deterministic checks.

The observed failure pattern is overly permissive support checking and reasons
that invent or misattribute input content. The model/backend cause remains
unresolved: both the protocol and backend changed, and there is only one
candidate run. This experiment establishes neither that splitting the calls
caused the regression nor that a larger judge would fix it.

Recommended next development experiment, without changing generation/retrieval:

1. Require claim-level faithfulness assessments with source IDs and exact
   evidence spans, or an explicit unsupported/contradicted result. Validate that
   spans occur in supplied cited text. Span membership proves provenance, not
   entailment; a human still needs to check whether the quote supports the claim.
2. Derive the overall score from those claim assessments under a documented
   rule, so a positive rationale cannot silently omit a central unsupported
   claim. Judge which requested facts relevance covers or misses, keeping
   reference text distinct from what the answer actually says.
3. Read the original human reasons for ambiguous disagreements. Any human
   adjudication must be separately versioned; preserve the current attestation
   and publish results against the unchanged labels as well.
4. Rescore the same frozen development sample under the same candidate model
   and Ollama backend, recording new rubric hashes and paired outcomes. Use
   observed score discrimination, disagreement severity and explanation quality
   to assess the revision; schema-valid output alone is insufficient.

This is a proposed experiment, not an implemented or verified fix. Protocol
schema checks can reject missing/invalid evidence spans, but cannot establish
semantic support or make the judge calibrated automatically.

Preserve the historical baseline and attested labels. Any subsequent prompt
revision requires a new, separately identified development experiment. A
rubric-only causal comparison additionally requires the backend to be held
constant. Do not query the holdout for this diagnosis. This purposive sample
does not establish unseen-data performance, statistical significance, a
release threshold, or completion of all Week 2 work.
