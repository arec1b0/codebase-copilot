# KubeSentiment baseline failure review

Reviewed on 2026-10-15. Baseline: `20261015T103820.268147Z`.

This source-based assistant review examines all 30 uploaded result records. It is not an independent human annotation or a newly calibrated accuracy score. No application code, accepted baseline, or dataset labels were changed.

## Evidence and integrity

- Input: uploaded `results.jsonl`, supplied as `Вставленный текст(1).txt`; SHA-256 `080d73598af775e52a15a18a1bcb95a0f900bed70d7f39b02b587b1dc1f3b613`.
- All 30 case objects match the frozen `kubesentiment-v1` questions and references.
- All 90 measured retrieval records match the pinned local corpus byte-for-byte, including their source hashes.
- All 49 returned citation records match source UUID/path/symbol/line/commit/repository metadata. This establishes source identity, not semantic support for each claim.
- Source commit: `1aa3ebfd3f0467ea61142dff72d6534aa6968e20`.
- Declared Windows corpus: `e1314616e9fb8b47e366a2d37fc6652bdc27d2465d4162f76817c79e9406b19e`.
- Declared Windows index: `4008b192d8cba11dcab880454a1c84dd928efb47d86c5f53d6a369e8f755880b`.
- Generator: `qwen2.5-coder:3b`, revision `sha256:f72c60cabf6237b07f6e632b2c48d533cef25eda2efbd34bed21c5e9c01e6225`, backend `ollama:0.40.3`.
- Prompt: `grounded-codebase-v2`.
- The uploaded records have 30 distinct case/request/trace identities and consistent declared runtime versions. The original version manifest, raw Ollama timing events, and Phoenix trace exports were not attached and were not independently inspected in this review.

## Main findings

The technical request/citation path succeeded, while answer quality fails in several independent ways: missing implementation fragments, ignoring already-retrieved evidence, answering a different method or premise, and unreliable grading. A blanket increase in top-k cannot address all of these.

### Retrieval coverage is a strict implementation-range metric

- 21/30 cases cover every labeled range; 4 cover only part; 5 cover none.
- Misses: `locating-06`, `dependency-01`, `dependency-05`, `dependency-06`, `debugging-06`.
- Partial: `debugging-02`, `changeimpact-01`, `changeimpact-03`, `changeimpact-04`.
- `locating-06` is an important qualification: the exact `return v.strip()` line is absent, but the correctly cited validator docstring explicitly describes whitespace stripping. Calling its answer unsupported merely because hit@3 is zero would be wrong.
- `dependency-01` also has useful alternative context: the dependency-provider signature/docstring names all three injected collaborators, although it does not prove constructor attribute retention. The answer only names one.
- Several labels demand more detail than the question needs. For example, proving backend cache-key normalization does not require the ONNX backend import line. Review minimal evidence requirements and alternative evidence groups without rewriting historical scores.

| Category | Cases with a labeled hit | Mean range recall@3 | Saved relevance mean / 2 |
|---|---:|---:|---:|
| locating | 5/6 | 0.8333 | 1.667 |
| explanation | 6/6 | 1.0000 | 1.333 |
| dependency | 3/6 | 0.5000 | 1.333 |
| debugging | 5/6 | 0.7778 | 1.333 |
| change-impact | 6/6 | 0.7917 | 1.167 |

### Answer generation fails even with complete labeled retrieval

- `debugging-03`: full evidence for `predict` is present, but the answer discusses `predict_batch`.
- `explanation-03`: `pickle.dumps` and `ex=ttl` are both retrieved; the answer explains only serialization.
- `changeimpact-04`: the raw-length guard is present, but the response changes the premise from stripped text fitting to stripped text exceeding the limit.
- `changeimpact-01`: the model gives current prefix-exemption behavior instead of the hypothetical exact-match behavior. Its context also lacks the exact exemption set.
- `dependency-06`: the getter name is absent from retrieval; the output repeats the question rather than naming the getter or declaring insufficient evidence.

### Citation identity checks do not establish claim-level support

All citation IDs are real. Some cited fragments omit the mechanism asserted by the answer. In `locating-05`, the first cache-existence claim points to the fragment preceding the operative cache branch; the stronger implementation evidence is in another available source. In `dependency-05`, stop-time waiting is used as evidence about removal at task completion, although the done callback is absent.

This supports adding claim-to-evidence review; it does not justify weakening the existing source-identity validation.

### The judge conflates faithfulness and completeness

The saved score pairs are exactly `(1,1)` for 19 cases and `(2,2)` for 11. Every case receives identical faithfulness and relevance; no zero is used. The mean 1.3667/2 is the correct aggregation of those stored scores, but its calibration is not established.

- `explanation-03`: the stated serialization fact is fully supported. Omitting TTL makes the answer incomplete; the judge incorrectly uses that omission to reduce faithfulness too.
- `dependency-02`: the judge says the answer does not state that the setting controls the maximum length, despite the answer explicitly saying that it does.
- `debugging-04`: the judge imports connection-testing/performance requirements from answer additions into its description of the reference.
- `changeimpact-04`: the judge attributes a raw-before-stripping explanation to an answer that actually describes the after-stripping condition.
- `dependency-06` is a non-answer, and `changeimpact-01` answers the counterfactual incorrectly, yet both receive relevance 1. The current rubric assigns 0 to incorrect or non-answers.

The grading prompt currently supplies the reference next to the cited source text. The observed rationales are consistent with reference/answer confusion and dimension conflation; this is a diagnosis to test, not proof of one isolated cause. Some judgments are too lenient and others too harsh, so this review does not infer the direction of aggregate bias.

### Source-label order must come from the API request

The runner performs a separate retrieval before making the API request. Actual citation labels differ from that separate retrieval order in `locating-06`, `debugging-03`, and `debugging-05`. All cited chunks still belong to the recorded top-3 sets.

For example, `locating-06` cites API source S3, which is the validator docstring at lines 49–66. In the independent retrieval record that same chunk is second. A review that joins on S-number/rank would inspect the wrong text. This review joins on `citation.chunk_id`. The reason for ordering variation is not established by these records.

### Latency is dominated by the generation stage

| Stage | p50, seconds | p95, seconds |
|---|---:|---:|
| Client end-to-end | 30.127 | 43.160 |
| API retrieval | 0.155 | 0.503 |
| API generation | 29.451 | 42.053 |
| Model TTFT | 11.964 | 18.882 |

Generation accounts for 97.79% of summed API total time across the 30 cases. This stage includes the model HTTP operation, so the ratio does not isolate pure device computation. The median API retrieval time is about 0.155 seconds; optimizing retrieval latency alone cannot materially remove the roughly 30-second median client duration.

TTFT is the client-observed first nonempty model content fragment. It does not isolate model loading, prefill, scheduling, structured-output work, or device placement. These records cannot establish which of those explains the delay. Generator/judge calls alternate in the baseline and may affect model state. New placement/load/prefill/decode telemetry is needed before attributing the latency to a particular hardware or configuration cause.

## Case-by-case inspection

These are qualitative assistant review notes, not replacement numeric scores.

| Case | Observation | Source-based review |
|---|---|---|
| `locating-01` | Core answer supported; extra topic | The empty-input rejection is correct. The additional predict_batch discussion is outside the question and does not explain the validation-to-None link within its cited merge fragment. |
| `locating-02` | Core answer supported | Correct dispatch location and constant-time comparison. The branch implementation is in the cited auth fragment. |
| `locating-03` | Incomplete answer | Names _make_key but omits namespace:cache_type:key, which the question explicitly requests. Adds unrelated namespace configuration and TTL facts. |
| `locating-04` | Core answer supported | Correct average of confidence_psi and length_psi; citation identifies the check_drift implementation. |
| `locating-05` | Core answer supported; citation precision | The reuse condition is correct. Its first statement cites S2, whose fragment ends before the operative _model_cache branch; S3 contains that branch. The comment in S2 is weaker evidence than the implementation. |
| `locating-06` | Strict implementation miss; alternative evidence | The labeled v.strip() line is absent, but the actual API-cited TextInput.validate_text docstring explicitly describes stripping. Tests also describe it. Do not interpret this strict range miss as absence of all useful evidence. |
| `explanation-01` | Core answer supported | Feature flag, extraction, and the features result key are supported by the cited implementation. Omitted stripping/model-call details affect completeness, not the truth of these claims. |
| `explanation-02` | Imprecise and incomplete | The answer blurs prevalidation with the merge-stage None check and calls texts invalid while describing stripping/length checks. It does not clearly explain filtering valid inputs and restoring positions with result_iter. |
| `explanation-03` | Incomplete; grading dimensions conflated | The only claim, pickle.dumps serialization, is fully supported by S1. It omits the TTL handoff even though ex=ttl is retrieved in S2. Missing TTL warrants a relevance/completeness penalty, not a faithfulness penalty for the supported serialization claim. |
| `explanation-04` | Core sampling explanation supported | Random percentage sampling is correct. The answer omits disabled/missing-model guards; decide consistently whether those are required for full relevance. |
| `explanation-05` | Core baseline logic supported; details omitted | Appending reference predictions, threshold check, and baseline flag explain the central mechanism. The answer omits confidence/text-length data and uses minimum_samples as a loose name for actual min_samples. The judge says the answer does not explain baseline establishment despite describing that mechanism. |
| `explanation-06` | Core answer supported | The three-stage ONNX path fallback is correct. The operative evidence is the factory body; additional citations are unnecessary. |
| `dependency-01` | Incomplete despite alternative evidence | Only model is named. The retrieved dependency-provider signature/docstring names model, settings, and feature_engineer. The constructor retention lines are a strict range miss, but the context still supplies all collaborator names. |
| `dependency-02` | Core answer supported; judge rationale conflicts | Correctly identifies ModelConfig.max_text_length. The judge claims the answer does not state that it controls the limit, although the answer explicitly says it is the setting that controls the maximum length. |
| `dependency-03` | Core answer supported | Correct reference_predictions and current_predictions lists, supported by the chi_squared_test call. |
| `dependency-04` | Core answer supported; broad summary | The namespace prefix explanation is correct. Exact colon-separated format and constructor fallback are omitted; apply a consistent completeness policy. |
| `dependency-05` | Mechanism unsupported and omitted | The answer names ShadowModeService but never explains _pending_tasks.add and add_done_callback(discard). Dispatch documentation and stop-time waiting do not establish automatic removal on task completion. |
| `dependency-06` | Non-answer | The question asks which getter. The answer repeats that a backend getter is called without naming get_sentiment_analyzer. The actual backend branch is not retrieved. |
| `debugging-01` | Core answer supported | Correct missing/wrong-key explanation, 401 response, and comparison behavior. |
| `debugging-02` | Core answer supported by documentation | The no-key no-op behavior is correctly explained. Strict evidence misses the return line, but the cited class docstring supports the main behavior. The exempt-path aside is unnecessary. |
| `debugging-03` | Wrong target method despite full retrieval | The question concerns PredictionService.predict, but the response explains predict_batch. Both fragments for the correct predict guard and raise are present in top-3. This is not resolved by improving recall alone. |
| `debugging-04` | Core answer supported; irrelevant additions | Catching RedisError and returning None directly explains the requested behavior. Extra connection-testing/performance/retry discussion distracts. The judge incorrectly imports these extra topics into the reference requirements. |
| `debugging-05` | Core answer supported | The absolute-path guard and errors are supported. Additional parent-directory validation is true but broader than requested. |
| `debugging-06` | Question premise ignored; wrong source role | The question assumes an established baseline. The answer instead discusses a baseline not established, and cites route response fields rather than detector guards. The required enabled/current-sample checks are missing from retrieval. |
| `changeimpact-01` | Incorrect counterfactual | After replacing prefix matching with exact equality, /docs/extra would lose the /docs prefix exemption. The answer says it remains exempt, answering current behavior rather than the requested change. The exact exemption set is also missing from retrieved context. |
| `changeimpact-02` | Core answer supported | ttl=60 leads to ex=60 and a 60-second expiration request. The configuration citation is unnecessary; the client.set call is the relevant evidence. |
| `changeimpact-03` | Partially answers the change; weak citation | States that normalized backend values drive cache entries, but does not explain ONNX/onnx key unification. The cited S1 lacks key construction; the available S2 contains it. The missing ONNX import range is not essential to deriving the key-normalization effect. |
| `changeimpact-04` | Question premise changed | The question says stripped text WOULD fit. The response describes text that exceeds the limit AFTER stripping instead. Raw len(text) causes the actual rejection; the guard is already retrieved. The judge rationale attributes a raw-before-strip explanation that the answer never gives. |
| `changeimpact-05` | Core answer supported | Synchronous dispatch accurately summarizes the awaited else branch. Explicitly saying that the caller awaits completion would be clearer. Do not infer event-loop blocking from this wording. |
| `changeimpact-06` | Ambiguous Boolean effect | A larger threshold can change false to true, but may leave the flag unchanged. Saying it increases prediction_drift_detected overstates the result unless interpreted weakly. The flag is Boolean, not a magnitude. |

## Next experiments, in order

1. Preserve this baseline and freeze the original case/label identities. Obtain maintainer-reviewed annotations for the clear wrong-method, wrong-premise, counterfactual, missing-getter, and missing-TTL examples. Do not convert these assistant notes into claimed human ground truth.
2. Separate faithfulness assessment from relevance/completeness assessment. Give faithfulness only the answer and cited evidence, including path/symbol metadata; keep the reference for relevance. Calibrate disagreements against reviewed labels before adding numerical quality gates. A new judge version must not be silently compared as the old metric.
3. Run a bounded retrieval/context experiment: retrieve a wider candidate pool, prioritize the requested qualified symbol where identifiable, and add adjacent existing chunks from the selected method within the existing context budget. Preserve individual chunk provenance. This directly targets the selected-method docstring/body separation seen in factory and shadow-task misses.
4. Test generation coverage and task fidelity separately: require the named method and stated hypothetical premise to be respected, answer every requested part, and use insufficient_context when a required mechanism cannot be supported. Include regressions where the evidence is already complete, so retrieval improvements cannot mask generation failures.
5. Record actual API retrieval/context chunk IDs in order for every evaluated query. Continue matching citations by chunk_id. Treat the independent retrieval measurement as a separate observation.
6. Investigate latency in a separate experiment using model load/prefill/decode timing and actual CPU/GPU placement. Hold model, context, prompt, question mix, and warm-up policy fixed when comparing one setting. No latency target has yet been agreed.
7. Add independently reviewed holdout questions before claiming general improvement; the 30 inspected cases are now development/regression data.

Suggested regression outcomes are categorical: getter named or explicit evidence abstention; correct predict method; raw-before-strip reasoning under the actual premise; no false /docs/extra exemption after exact matching; TTL handoff explained when both code fragments are supplied. Technical HTTP success and valid source IDs remain necessary checks, but do not replace these behavior checks.

No new implementation or runtime performance improvement is claimed by this review.
