# KubeSentiment repository baseline

This extends the accepted Week 1 demo to the selected working repository.
It reads committed Git blobs; it does not install, import, or run KubeSentiment.
It creates a separate corpus and Qdrant collection, preserving the demo data.

| Item | Pin |
| --- | --- |
| Source | https://github.com/arec1b0/KubeSentiment |
| Commit | `1aa3ebfd3f0467ea61142dff72d6534aa6968e20` |
| Dataset | `evals/datasets/kubesentiment/questions.jsonl` |
| Profile | `evals/datasets/kubesentiment/profile.json` |
| Questions | 30; six each in five categories |
| Question language | English; Python source evidence |
| Corpus | 262 supported files; 6,801 chunks at this commit/configuration |
| Chunking | `symbol-method-boundaries-v2`, maximum 600 characters |
| Embedding limit | Preflight checks actual tokenizer inputs including source headers |
| Review copy | [Questions, references, and pinned source links](../evals/datasets/kubesentiment/questions-review.md) |

The questions cover prediction validation, feature engineering, batch input
handling, API-key middleware, model factory paths/caching, Redis behavior, drift
checks, and shadow tasks. References describe the pinned implementation, including
its edge cases; they are not upstream behavior guarantees across future revisions.

## One-command startup

Version 0.4.1 provides a launcher for a fresh checkout with no `.env`, corpus,
index, or project embedding cache. Install Git, uv, Docker Desktop, and native
Ollama on PATH first; start Docker Desktop using Linux containers. Python 3.12
is selected by uv. Internet access is needed for initial dependencies/images,
the public source repository, and public model assets. Port 8000 must be free.

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-repository.ps1
```

The launcher performs the following sequence:

1. Synchronize the locked Python dependencies and check local prerequisites.
2. Create `.env` once, then start the existing Compose definition with
   `--pull missing --wait`. Existing credentials and named volumes are retained.
   It waits for authenticated Qdrant, PostgreSQL queries, and Phoenix migrations.
   It does not invoke the restart/persistence test during normal startup.
3. Clone source into `artifacts/repositories/KubeSentiment` without checkout if
   absent, then fetch the pinned commit if necessary. It does not install or
   execute upstream code. An existing checkout can be supplied with
   `-Repository "C:\Projects\KubeSentiment"`; its HEAD and working tree are retained.
4. Reuse the local Ollama endpoint on port 11434, or start `ollama serve` if it
   is absent. Pull `qwen2.5-coder:3b` only when missing; retain an installed model
   revision. The launcher uses its child-process environment for `OLLAMA_HOST`.
5. Download missing embedding assets, ingest the pinned source, validate the
   dataset, and preflight every embedding input. Validate an existing index's
   schema, count, and every saved source payload before reusing its embeddings.
   An incomplete consistent index is rebuilt; foreign or changed source records
   cause failure. A changed embedding identity creates a separate versioned index.
6. Start the API, wait for readiness, make one real query, validate its answer
   status/citations/version IDs, and read the matching complete trace from Phoenix.

Success prints `ONE COMMAND ACCEPTANCE PASSED`. The API remains available at
`http://127.0.0.1:8000/docs` until Ctrl+C. The launcher enables tracing for its
API child process. Ctrl+C gracefully stops that API and any Ollama server that
this launcher started. An already-running Ollama server and Docker services stay
available. API shutdown flushes telemetry. Ollama startup output is saved under
`artifacts/launcher/ollama.log` when the launcher owns the daemon.

To run the same startup check and then stop owned API/Ollama processes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-repository.ps1 -CheckOnly
if ($LASTEXITCODE -ne 0) { throw "One-command startup acceptance failed." }
```

Each probe writes `response.json`, `trace.json`, and `version-manifest.json` to
its own timestamped directory under `artifacts/launcher/`. The single-query
startup probe establishes technical availability and provenance; it is not a
new 30-case quality or performance baseline. The accepted historical baseline
and its failure analysis are retained. The old prompt, dataset, and embedding
algorithms/identities are not changed by this launcher release.

If a stage fails, the command exits nonzero and does not print the success
marker. The failed query's HTTP body is retained when available. Stop an old
API before retrying; occupied port 8000 fails before infrastructure changes.
Compose may recreate containers if their configuration has changed; no image
refresh or volume deletion is forced. Initial preparation can take several
minutes. Subsequent starts reuse verified assets and complete source indexes.

The one-command cold start still requires live acceptance on the target Windows
machine. A test with synthetic services does not establish that result.

CLI behavior was checked against the official
[Compose up reference](https://docs.docker.com/reference/cli/docker/compose/up/)
and [Ollama environment configuration](https://docs.ollama.com/faq).

## Manual update and preparation

Stop the existing API with Ctrl+C, then extract the full archive into
`C:\Projects`, allowing source replacement. Existing `.env`, `.venv`, and
`artifacts` are excluded from the archive. Keep Docker Desktop, the accepted
Qdrant/PostgreSQL/Phoenix stack, and the accepted native Ollama model running.
The embedding models are reused from `artifacts/models`; preparation fails if
they are unavailable rather than silently changing model assets.

In PowerShell:

```powershell
Set-Location "C:\Projects\codebase-copilot"
if (-not (Test-Path "C:\Projects\KubeSentiment\.git")) {
    git clone https://github.com/arec1b0/KubeSentiment.git "C:\Projects\KubeSentiment"
    if ($LASTEXITCODE -ne 0) { throw "Source clone failed." }
}
git -C "C:\Projects\KubeSentiment" cat-file -e "1aa3ebfd3f0467ea61142dff72d6534aa6968e20^{commit}"
if ($LASTEXITCODE -ne 0) {
    git -C "C:\Projects\KubeSentiment" fetch origin 1aa3ebfd3f0467ea61142dff72d6534aa6968e20
    if ($LASTEXITCODE -ne 0) { throw "Pinned commit fetch failed." }
}
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-repository.ps1 -Repository "C:\Projects\KubeSentiment"
if ($LASTEXITCODE -ne 0) { throw "Repository preparation failed." }
```

No checkout or working-tree changes are needed. Even a dirty source checkout is
read at the pinned commit. Expect `REPOSITORY PREPARATION PASSED`, a corpus path,
and a manifest path. Initial embedding/index creation takes longer than the
13-chunk demo. Failed partial indexing can be retried with the same command.

The pointer file selects this run's real manifest; Windows/Linux corpus IDs may
differ because the Python patch version is part of ingestion identity. The
profile binds portable source text and coordinates across those environments.

## Start and measure

Start the API in the first terminal:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Prepared = Get-Content ".\artifacts\repository-indexes\kubesentiment-v1.json" -Raw | ConvertFrom-Json
$Index = $Prepared.index_manifest
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-query-api.ps1 -IndexManifest $Index
```

Leave it running. In another terminal:

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-repository.ps1
if ($LASTEXITCODE -ne 0) { throw "Real repository acceptance failed." }
```

Expected final marker: `REAL REPOSITORY ACCEPTANCE PASSED`. The script runs code
checks, then 30 measured queries plus one excluded warm-up. It requires the real
API/index/model identities and five complete traces read back from Phoenix.
It does not run the old Counter-only query smoke test against KubeSentiment.

The printed `artifacts/baselines/<timestamp>` directory retains the copied
dataset/profile, version manifest, all results, summary/report, traces, and
separate `abstentions.jsonl` and `errors.jsonl`. Empty files mean no such cases.
Inspect abstentions and low judge scores even when technical acceptance passes.
Judge results remain uncalibrated estimates from the generator's own model.

## Source binding and scope

Preparation and evaluation reject changed source layout, commit, question bytes,
missing quotes, or evidence that does not fit within its labeled chunk/range.
Changing the source pin or labels requires a deliberately revised dataset profile
and a fresh baseline. The optional method chunking gives Python methods qualified
names such as `PredictionService.predict`; the accepted v1 demo default is retained.
No tokenizer truncation is allowed. No reranker or new generation prompt is added.

Supported ingestion formats remain Python, Go, C/C++ headers/source, Markdown,
RST, and text. YAML, Helm templates, shell scripts, notebooks, and hidden paths
are not indexed; see the corpus manifest's skipped-file reasons. This dataset
does not measure Kubernetes configuration understanding or whole-repository coverage.

These are assistant-authored questions and references grounded in the source,
not questions collected from production users. They need maintainer review and
an independent holdout before quality claims. Upstream source is MIT licensed;
the dataset folder includes its license and pinned attribution links.

The Linux SDK-local retrieval check is development evidence only. Windows
repository acceptance passed on 2026-10-15, with baseline
`artifacts/baselines/20261015T103820.268147Z`. The
[baseline failure review](kubesentiment-baseline-review.md) records the observed
answer, retrieval, judge, and latency limitations across all 30 cases.
Technical acceptance does not establish calibrated answer accuracy. Retain the
raw baseline artifacts separately from this review. The prior accepted demo
baseline remains a separate measurement and is not transferred to this repository.
