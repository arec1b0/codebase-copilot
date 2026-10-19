# Step 1 validation

Validated on 2026-10-12 with CPython 3.12.14 on Linux.

| Check | Result |
| --- | --- |
| uv sync with the final lockfile | Passed |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Mypy strict checking | Passed for three Python files |
| Pytest HTTP contracts | Four tests passed without warnings |
| Live Uvicorn HTTP request to /healthz | Passed |

The user subsequently ran Step 1 acceptance on Windows with CPython 3.12.13:
four tests passed, Ruff and Mypy passed, `/healthz`, `/docs`, and `/openapi.json`
returned HTTP 200, and Uvicorn completed a graceful shutdown. Step 1 is accepted
on the target platform.

The tests validate the initial HTTP contract. They do not establish RAG quality,
load capacity, external dependency readiness, or completion of Week 1.

# Step 2 validation

| Check | Result |
| --- | --- |
| Ruff lint and formatting | Passed for all five Python files |
| Mypy strict checking | Passed for all five Python files |
| Existing API tests | Four tests passed |
| Compose YAML against the official Compose JSON schema | Passed |
| Relative PostgreSQL initialization mount with the explicit project root | Checked |
| All published ports bound to 127.0.0.1 | Checked |
| Credential creation and preservation on a second run | Passed in a temporary directory |
| Docker Compose runtime and image downloads | Not executed because Docker is unavailable here |
| PowerShell orchestration | Not executed because PowerShell is unavailable here |
| Live readiness and restart persistence | Requires the user's Windows acceptance run |

The infrastructure check writes isolated probe data, restarts the three local
services, reads the probe data, and removes it. Its live behavior is not proven
by schema validation or the existing API tests. The user reported
`STEP 2 ACCEPTANCE PASSED` on Windows; Step 2 is accepted on the target platform
based on that reported result.

Image tags follow the upstream Qdrant v1.19.2 and Phoenix 20.20.0 releases and the
PostgreSQL official image listing for 17.11-bookworm. Tags do not provide digest
immutability. No Docker image digest has been invented or recorded.

# Step 3 validation

| Check | Result |
| --- | --- |
| Ruff lint and formatting | Passed for all fourteen Python files |
| Mypy strict checking | Passed for all fourteen Python files |
| Complete test suite | Twenty-one tests passed |
| Temporary Git demo with Python, Go, C++, and Markdown | Four source files and thirteen chunks |
| CLI rerun after tracked and untracked working-tree changes | Identical corpus bytes and manifest |
| Missing revision | Failed as required |
| Source hashes and commit metadata | Checked by the acceptance scenario |
| Windows PowerShell orchestration | Requires the user's Windows acceptance run |

Step 3 publishes a source corpus, not a vector index. There are no embeddings,
retrieval-quality measurements, generation calls, or LLM traces at this stage.
The full Week 1 acceptance criteria remain pending.

The user subsequently reported the Step 3 Windows results: twenty-one tests
passed, lint and typing passed, four demo files produced thirteen chunks, and
reproducibility checks passed. Step 3 is accepted on Windows. The Windows corpus
version differs from the Linux version because the Python patch version is part
of the ingestion identity.

# Step 4 validation

| Check | Result |
| --- | --- |
| Complete unit test suite | Thirty-six tests passed |
| Real CPU dense and BM25 model initialization | Passed with 384 dense dimensions |
| Real-model indexing in Qdrant SDK persistent local mode | Thirteen demo points indexed |
| Repeated indexing and manifest identity | Passed |
| Reconnected search for Python Counter, Go Increment, and C++ add | Passed |
| CLI search with cached models and no model download | Passed |
| Real tokenizer check against overlong input | Input rejected before truncation |
| Docker Qdrant server and Windows orchestration | Require the user's live acceptance run |

The offline unit tests use a declared test-only embedding backend for store
contract checks. The separate local acceptance uses the actual public dense
model and actual BM25 implementation. Neither local mode nor the smoke set
proves a production retrieval-quality baseline or Docker server compatibility.

The user subsequently ran Step 4 on Windows: thirty-six tests passed, real CPU
models downloaded, all three symbol smoke checks passed, and thirteen points
were stored in Docker Qdrant. The manifest was saved and `STEP 4 ACCEPTANCE PASSED`
was reported. Step 4 is accepted on the target platform. Windows cache fallback
warnings did not prevent that run.

# Step 5 validation

Validated on 2026-10-13 with CPython 3.12.14 on Linux.

| Check | Result |
| --- | --- |
| Ruff lint and formatting | Passed |
| Mypy strict checking | Passed for twenty-nine Python files |
| Complete test suite | Sixty tests passed |
| HTTP inputs, citations, versions, IDs, and readiness | Passed with explicit test-only service backends |
| Native Ollama streaming, usage, malformed output, and timeout handling | Passed with HTTP mock transport |
| Changed model digest and occupied query slot | Rejected |
| Changed Qdrant source payload preserving version declarations | Rejected against saved corpus |
| Whole-source context bounds | Passed |
| Real Ollama and Windows PowerShell scripts | Not run here; neither is available |

The live check requires the user's Docker Qdrant, cached real embeddings, saved
demo corpus/index, and actual Ollama model. Only that run may print
`STEP 5 ACCEPTANCE PASSED`. Synthetic offline answers do not prove generation
quality or latency. Phoenix tracing and a labeled baseline remain pending.

The user's first Windows Step 5 attempt passed all sixty tests, lint, formatting,
and typing. Live health and readiness completed, but the generation request
returned HTTP 502. Step 5 remains unaccepted. The traceback did not include the
API error body, so the failing contract has not been identified. The diagnostic
revision prints the structured HTTP error and saves `step5-query-error.json`;
it does not change model behavior or citation validation.

# Step 5 citation fix

The returned diagnostic identified `invalid_citations`: the model's inline
markers did not match its declared source IDs. This did not establish which
specific marker was missing or extra because raw model output was not included.
The v2 prompt replaces the two citation representations with sourced statements.
API 0.2.1 validates each statement and renders inline citations itself. Unknown,
duplicate, or undeclared sources still fail. The public response format remains
compatible; the prompt version and hash change.

| Check | Result |
| --- | --- |
| Complete offline suite | Sixty-seven tests passed |
| Ruff lint and formatting | Passed for twenty-nine Python files |
| Mypy strict checking | Passed for twenty-nine Python files |
| Native mock stream through adapter, service, and query HTTP endpoint | Sourced statements rendered with consistent citations |
| Missing model inline markers | Rendered by the API without a generation retry |
| Repeated valid inline markers | Canonicalized |
| Unknown/duplicate/undeclared source labels and cited abstentions | Rejected |
| Real Ollama generation on Windows after the fix | Requires the user's live acceptance run |

The offline regression uses representative structured responses, not the unseen
raw response from the failed Windows request. It verifies the new citation
contract but does not establish model faithfulness or live generation success.

The user subsequently accepted the Step 5 citation fix on Windows: sixty-seven
tests and all code checks passed, actual Ollama returned the Counter answer with
`[S1]`, and citations, version identities, abstention, and HTTP validation passed.
A second reported run retained model/index identities and also passed.

# Step 6 validation

Validated on 2026-10-13 with CPython 3.12.14 on Linux.

| Check | Result |
| --- | --- |
| Complete offline suite | Seventy-six tests passed |
| Ruff lint/formatting and strict Mypy | Passed for forty Python files |
| Real OTLP HTTP/protobuf serialization into a test receiver | Passed |
| API/child span parentage, request/trace IDs, version attributes, and token usage | Passed |
| Error status for 502/422 and omission of private question/model markers | Passed |
| Thirty demo labels bound to actual source ranges across five categories | Passed |
| Recall/MRR/miss handling, nearest-rank percentiles, and error accounting | Passed |
| Native local-judge and Phoenix REST export contracts | Passed with explicit mock responses |
| Complete baseline CLI with thirty cases, warm-up exclusion, five trace exports, and a failed case | Passed with explicitly synthetic external services |
| Optional repeat of real CPU retrieval after environment recovery | Not completed: restored local embedding cache failed its asset-size check |
| Real Windows Phoenix ingestion/readback, thirty-query baseline, PowerShell launcher | Requires user acceptance; Docker, Ollama, and PowerShell are unavailable here |

Phoenix REST contracts were checked against the downloaded official
`arize-phoenix==20.20.0` package source, matching the pinned container version.
Five traces must be read back from the actual user's Phoenix to pass Step 6;
successful serialization to a test receiver does not establish that result.
No model latency percentile or quality score is invented. The dataset is authored
for the small demo; the original real-repository question-set requirement remains
pending until a working repository and reviewed questions are selected.

## Accepted Windows demo baseline (2026-10-15)

The user subsequently reported `BASELINE ACCEPTANCE PASSED` and
`STEP 6 ACCEPTANCE PASSED`, with 76 tests passing. The saved baseline was
`artifacts/baselines/20261015T053459.621033Z`.

| Measurement | Reported value |
| --- | --- |
| Cases / HTTP successes / judge successes | 30 / 30 / 30 |
| Errors / abstentions | 0 / 5 |
| Retrieval hit rate@3 / range recall@3 | 1.0 / 1.0 |
| Retrieval MRR@3 | 0.9666666667 |
| Faithfulness / relevance, same-model judge | 1.5 / 1.5 on a 0–2 scale |
| Client latency p50 / p95 | 6,766.59 / 7,956.21 ms |
| Model TTFT p50 / p95 | 3,020.57 / 3,819.58 ms |
| Five complete Phoenix traces | Saved |

This accepts the demo execution on the target platform. Five abstentions despite
retrieval coverage require case-level inspection; citation/transport acceptance
does not establish semantic answer quality or calibrated judge accuracy.

## KubeSentiment extension

The selected public repository is pinned at
`1aa3ebfd3f0467ea61142dff72d6534aa6968e20`. Source-backed cases and the new
runbook are under `evals/datasets/kubesentiment/` and `docs/kubesentiment.md`.

Linux checks use CPython 3.12.14 with the locked dependencies. Source validation
binds all 30 cases to real Git-blob text, qualified method boundaries, and exact
line-range quotes. The corpus contains 262 files and 6,801 chunks. Preflight of
every embedding input, including source headers, found a maximum of 414 tokens
against the model's 512-token limit. The accepted v1 demo default is unchanged.

Ruff lint/formatting and strict Mypy pass. The suite checks profile tampering,
missing/incorrect evidence, token-budget rejection before Qdrant connection,
preparation publication, and complete profile-aware baseline exports using
explicit synthetic external services. These tests do not claim live generation
quality. See the separate retrieval validation record below for the actual CPU
embedding and SDK-local storage check.

### Real CPU retrieval check (2026-10-15)

All 90 tests pass; Ruff verifies 43 formatted files and strict Mypy reports no
issues in 42 checked source files. Dependency versions are unchanged from the
accepted Step 6 lockfile; only the application version changes to 0.4.0.

Actual CPU dense/BM25 embeddings indexed all 6,801 source chunks in persistent
Qdrant SDK local mode. A new process reopened the store, verified its manifest,
and measured all 30 pinned questions with the API's retriever and language/top-k
configuration. [The raw development check](kubesentiment-retrieval-check.json)
records the model asset/runtime identity, index/dataset/profile hashes, source
hits, and per-case metrics.

| Retrieval measurement | SDK-local result |
| --- | --- |
| Indexed source points | 6,801 |
| Cases / cases with at least one labeled range hit | 30 / 25 |
| Hit rate@3 | 0.8333333333 |
| Mean range recall@3 | 0.7805555556 |
| MRR@3 | 0.6833333333 |
| Maximum actual document input tokens | 414 / 512 |

Misses: `locating-06`, `dependency-01`, `dependency-05`, `dependency-06`,
`debugging-06`. Partial evidence coverage: `debugging-02`, `changeimpact-01`,
`changeimpact-03`, `changeimpact-04`. These cases are retained for failure analysis.
The authored labels remain unreviewed. This is a retrieval measurement, not an
answer accuracy, latency, or capacity score. Docker server ordering, generation,
judging, and tracing are measured by the separate Windows acceptance run.

The user subsequently reported `REAL REPOSITORY ACCEPTANCE PASSED` on Windows:
30 HTTP/judge successes, zero execution errors, five Phoenix traces, and the same
retrieval aggregates shown above. The saved baseline is
`artifacts/baselines/20261015T103820.268147Z`. Full results were reviewed in
[the baseline failure review](kubesentiment-baseline-review.md). The first project
commit is `47f5c2d`, reported with a clean working tree. These accepted results
remain separate from the original demo and the launcher validation below.

## One-command repository startup, version 0.4.1

The launcher adds first-use setup and a single live query/trace probe. It does
not change the prompt, model choice, dataset labels, or retrieval algorithm, and
does not claim to repair the documented semantic quality failures.

| Check | Result |
| --- | --- |
| Complete offline suite | 120 tests passed |
| Ruff lint/formatting and strict Mypy | Passed; 44 checked source files |
| Windows-specific launcher branches | Passed strict Mypy with platform win32 |
| Fresh source clone and missing pinned commit fetch | Passed with real temporary Git repositories and explicit local transport fixtures |
| Dirty/untracked source files and source HEAD preservation | Passed |
| Bootstrap order, missing commands, occupied port, failure/interrupt cleanup | Passed with explicit fake external services |
| Existing/owned Ollama behavior and missing-model download command | Passed with explicit fake process/HTTP responses |
| Version/citation/request checks and complete Phoenix collector readback | Passed with explicit HTTP test responses; mismatches rejected |
| Actual HTTP readiness and graceful owned process shutdown | Passed against a real temporary Uvicorn process on Linux |
| Complete index reuse and missing-point recovery | Passed with Qdrant SDK local stores and a declared test embedding backend |
| Actual CPU model identity and 6,801-point index reuse | Passed; cached public assets recovered, source payloads checked, manifest unchanged, no embedding batches run |
| Locked dependencies | Package versions unchanged; only project version changes to 0.4.1 |
| Native Windows PowerShell one-command startup with existing model assets/index and live Phoenix probe | Subsequently accepted by the user; evidence `artifacts/launcher/20261015T115845.750620Z` |
| Native Windows first-use startup with all model assets absent | Not established by that cached-assets run |

Docker, native Ollama, and PowerShell were unavailable in the implementation
environment. The user's subsequent Windows run reported 120 tests and
`ONE COMMAND ACCEPTANCE PASSED`, reusing the complete index and cached model
assets. Commit `db0eff2` and tag `week1-baseline` were verified on GitHub.
The full 30-case baseline is not replaced by the one-query startup evidence;
a full empty-cache cold start was not measured by that run.

## Week 2, step 1: offline saved-run comparison

The implementation adds a saved-run comparator, provisional development policy,
and Windows acceptance command. It does not alter serving or retrieval.

| Check | Result |
| --- | --- |
| Complete code suite | 153 tests passed on Linux with Python 3.12.14 |
| Ruff lint/formatting and strict Mypy | Passed; 49 checked source files |
| Actual CLI self-comparison | Exit 0 with equal metrics |
| Edited retrieval/citation fixtures | Exit 1; individual regressions or deterministic failure retained |
| Missing-case fixture | Exit 2; no passing report written |
| Uncalibrated judge decline | Reported; does not gate by default |
| Baseline preservation and refusal to replace output | Passed |
| Historical KubeSentiment rows | All 30 parsed; saved questions/chunks/citations matched the pinned source; recomputed metrics matched the accepted aggregates |
| Full original Windows run replay | Pending; original Windows version manifest/corpus must be read on the target machine |
| Native PowerShell comparison wrapper | Pending target-machine acceptance |
| PR/full evaluation CI, human calibration, unseen holdout | Later Week 2 work |

CLI unit fixtures use a real temporary Git repository and ingestion pipeline
with explicitly synthetic answers/judge scores. They do not claim live model
quality. The historical 30-row compatibility check used the pinned local
KubeSentiment source records; it did not invent the missing Windows run manifest
or claim a full historical-manifest replay. Run
[the comparison acceptance](week2-comparison.md#windows-acceptance) on Windows
with the complete original baseline artifacts to complete this step.
