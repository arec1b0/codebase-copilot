# Codebase Copilot

This project implements the supplied six-week LLMOps plan. Week 1 builds a local
request path from source ingestion to retrieval, generation, citations, and tracing.
Step 1 delivers the Python project and a running HTTP API with a tested liveness
contract. Step 2 adds Qdrant, PostgreSQL, and Phoenix through Docker Compose, plus
an executable readiness and restart-persistence check. Step 3 adds a versioned
Git-source corpus with bounded code and documentation chunks, source locations,
and integrity metadata. Step 4 adds CPU embeddings, versioned Qdrant collections,
and dense plus BM25 retrieval with RRF. Step 5 adds local Ollama generation,
validated citations, pinned versions, request IDs, and dependency readiness.
Step 6 adds OpenTelemetry/Phoenix tracing, a source-bound demo evaluation set,
baseline measurements, runtime manifests, and a one-command demo launcher.
The user accepted Steps 1–6 on Windows, including the 30-case demo baseline.
The pinned KubeSentiment corpus and 30-case Windows baseline are accepted.
Version 0.4.1 adds [one-command repository startup](docs/kubesentiment.md#one-command-startup),
including first-use downloads and a live query/Phoenix readback probe.

## Requirements

- Windows 11 and PowerShell.
- uv available on PATH.
- Python 3.12, which uv can install when needed.
- Git available on PATH for ingestion and its tests.
- Internet access for the first dependency synchronization.

If uv is missing, install it with the Windows package manager, then reopen PowerShell:

```powershell
winget install --id astral-sh.uv --exact
```

## Run KubeSentiment with one command

Install Git, uv, Docker Desktop, and the native Ollama CLI. Start Docker Desktop
with Linux containers. From the project root, with port 8000 free:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-repository.ps1
```

The launcher creates credentials if absent, starts the Compose services, prepares
the pinned source and CPU index, starts/reuses Ollama, and verifies one cited
query with Phoenix trace readback. First use requires Internet access and downloads
the model assets. A complete validated index is reused on subsequent starts.
After `ONE COMMAND ACCEPTANCE PASSED`, the API stays available until Ctrl+C.
See [the runbook](docs/kubesentiment.md) for check-only mode and saved evidence.

## First run

Extract the archive into `C:\Projects`, producing `C:\Projects\codebase-copilot`.
The archive includes `uv.lock`; use it without regenerating dependencies.

```powershell
Set-Location "C:\Projects\codebase-copilot"
uv python install 3.12
if ($LASTEXITCODE -ne 0) { throw "Python installation failed." }
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave the server running. In another PowerShell window:

```powershell
$Response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/healthz" -Method Get
if ($Response.status -ne "ok") { throw "Unexpected health status." }
if ($Response.service -ne "codebase-copilot") { throw "Unexpected service." }
if ($Response.version -ne "0.4.1") { throw "Unexpected version." }
$Response | ConvertTo-Json
```

Expected response:

```json
{
  "status": "ok",
  "service": "codebase-copilot",
  "version": "0.4.1"
}
```

API documentation is available at `http://127.0.0.1:8000/docs`.
Stop the server with Ctrl+C. The server binds only to the local loopback interface.

## Acceptance check

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
if ($LASTEXITCODE -ne 0) { throw "Step 1 acceptance failed." }
```

The process-level execution policy override applies only to the launched script
process. The script synchronizes locked dependencies and checks lint, formatting,
static types, HTTP behavior, and source ingestion. Success prints
`CODE ACCEPTANCE PASSED`.

## Layout

- `app/`: HTTP application, grounded query service, prompt, and Ollama transport.
- `ingestion/`: Git snapshot reading, syntax-aware chunking, and corpus publication.
- `indexing/`: model identity, corpus verification, vector indexing, and hybrid search.
- `evals/`: source-bound questions, local judge, metrics, and baseline runner.
- `deploy/`: local service configuration and later Kubernetes manifests.
- `observability/`: explicit metadata-only OpenTelemetry/OpenInference tracing.
- `tests/`: executable checks of observable behavior.
- `docs/`: architecture decisions and operating documentation.
- `scripts/`: Windows acceptance commands.

`deploy/` contains the local infrastructure definition. `examples/demo-repo/`
provides source fixtures for ingestion acceptance.

## Design decisions

Python 3.12 and uv provide a consistent environment across Windows and Linux.
FastAPI and Pydantic follow the supplied plan. The application factory creates
independent test instances and performs no network work at import time.

`/healthz` reports process liveness. It does not assert that a model, index,
database, or telemetry collector is ready. `/readyz` checks the pinned retrieval
index and model identity. Starting without an index still serves liveness and
documentation; readiness and queries return 503.

Source ingestion, retrieval, and generation use separate modules. Small protocol
interfaces allow tests to isolate transport failures without downloading an LLM.

## Accepted Week 1 and Week 2 work

Week 1 is accepted on Windows and published at tag `week1-baseline`, commit
`db0eff2`. The latest accepted code suite contained 120 tests; one-command
startup reused existing assets and a complete verified source index.

Week 2 starts with [offline baseline/candidate comparison](docs/week2-comparison.md).
It recomputes retrieval metrics, validates saved source/response contracts, and
reports aggregate and individual regressions. Its default provisional policy
rejects retrieval decreases while keeping uncalibrated judge scores report-only.
The new Windows comparison acceptance remains pending.

Question/reference review, judge calibration, holdout data, agreed release
thresholds, and evaluation CI remain Week 2 work. The accepted baseline and its
[failure analysis](docs/kubesentiment-baseline-review.md) remain the starting point.

Step 1 does not meet the final Week 1 acceptance criteria by itself.

## Step 2 local infrastructure

Start Docker Desktop with Linux containers and the WSL 2 backend. Docker Compose
must support `up --wait` and `--wait-timeout`. The commands below use a stable
project name, a root `.env`, and the project root as the base for relative paths.

Extract the Step 2 archive into `C:\Projects`, allowing its source files to replace
the Step 1 versions. The archive excludes `.env` and `.venv`; existing credentials
and environments are preserved. Do not move `compose.yaml` out of `deploy/`.

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
if ($LASTEXITCODE -ne 0) { throw "Code acceptance failed." }
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\infra.ps1 -Action up
if ($LASTEXITCODE -ne 0) { throw "Infrastructure acceptance failed." }
```

The startup script performs these operations:

1. Verify that the Docker daemon is available and uses Linux containers.
2. Generate `.env` once with independent random PostgreSQL and Qdrant credentials.
3. Validate Compose configuration without printing resolved secrets, then download
   the specified image tags and start the services.
4. Check PostgreSQL queries, authenticated Qdrant requests, Phoenix readiness, and
   Phoenix database migrations.
5. Verify that Qdrant rejects unauthenticated collection requests.
6. Write a probe row and vector point, restart all three infrastructure services,
   verify the probe data, then remove the row and temporary collection.

Success prints `STEP 2 ACCEPTANCE PASSED`. The check restarts this development
stack on every run; run it before ingestion or application traffic is active.
It leaves an empty `infra_acceptance.probes` table for subsequent checks. A failed
check can leave its randomly named probe collection or row if cleanup cannot
reach a service. It never deletes an application collection or Docker volume.

| Service | Image tag | Local endpoint |
| --- | --- | --- |
| PostgreSQL | `postgres:17.11-bookworm` | `127.0.0.1:15432` |
| Qdrant HTTP | `qdrant/qdrant:v1.19.2` | `http://127.0.0.1:6333` |
| Phoenix UI and OTLP HTTP | `arizephoenix/phoenix:20.20.0` | `http://127.0.0.1:6006` |
| Phoenix OTLP gRPC | Same Phoenix container | `127.0.0.1:4317` |

Phoenix's HTTP trace ingestion URL is `http://127.0.0.1:6006/v1/traces`.
Step 6 instruments the application to send traces. Phoenix authentication is
disabled for this loopback-only development deployment. Container-to-container
traffic uses the private Compose network; do not expose these ports publicly.

PostgreSQL stores application metadata in `copilot` and Phoenix data in `phoenix`.
The initial SQL creates the Phoenix database only on a new PostgreSQL volume.
The shared `copilot` database role is the local development administrator; separate
application and telemetry roles belong in a later deployment hardening step.

Docker named volumes preserve PostgreSQL data and Qdrant indexes independently of
the extracted source directory. PostgreSQL uses a PostgreSQL 17-compatible data
mount. Keep `.env` with its original password when reusing the volume. Replacing
the password in `.env` does not rotate an already initialized database password.

Qdrant and Phoenix readiness is checked by the Python acceptance script from the
host. Their images do not need curl, wget, or a shell for these probes. Compose
itself waits for PostgreSQL health and for the other container processes to start.

## Infrastructure operations

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\infra.ps1 -Action status
if ($LASTEXITCODE -ne 0) { throw "Status inspection failed." }
```

Repeat readiness and persistence acceptance on an already running stack:

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\infra.ps1 -Action check
if ($LASTEXITCODE -ne 0) { throw "Infrastructure acceptance failed." }
```

Stop the stack while retaining data:

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\infra.ps1 -Action down
if ($LASTEXITCODE -ne 0) { throw "Infrastructure shutdown failed." }
```

Inspect recent logs if startup or acceptance fails:

```powershell
Set-Location "C:\Projects\codebase-copilot"
docker compose --project-directory . --env-file .env -f .\deploy\compose.yaml logs --tail 100 postgres qdrant phoenix
if ($LASTEXITCODE -ne 0) { throw "Log inspection failed." }
```

If a host port is occupied, stop this stack, update only the corresponding port
in `.env`, and rerun `-Action up`. The acceptance script uses the same values.
Do not remove the named volumes to fix a port conflict.

The image versions are fixed tags, not immutable digests. Record resolved image
digests in the Week 1 version manifest before claiming full reproducibility.

## Step 3 source ingestion

The local infrastructure has passed the user's Step 2 acceptance. This step
creates a source corpus without making Docker requests or model calls. Extract
the Step 3 archive into `C:\Projects`, replacing the source files while retaining
the existing `.env`, `.venv`, and Docker volumes.

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ingestion.ps1
if ($LASTEXITCODE -ne 0) { throw "Ingestion acceptance failed." }
```

Success prints `STEP 3 ACCEPTANCE PASSED`. The script runs code checks, creates a
temporary local Git repository from the supplied Python, Go, C++, and Markdown
fixtures, ingests its commit, changes its working tree, and ingests the same
commit again. It checks that the corpus remains identical and that an invalid
revision fails. It stores the resulting corpus under
`artifacts/corpora/training-demo/` and removes the temporary Git repository.

To ingest a real repository, run the CLI from the project root:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Repository = Read-Host "Full path to the local Git repository"
$Revision = Read-Host "Commit, tag, or branch (leave blank for HEAD)"
if ([string]::IsNullOrWhiteSpace($Revision)) { $Revision = "HEAD" }
uv run --locked python -m ingestion --repo "$Repository" --revision "$Revision" --repo-id primary
if ($LASTEXITCODE -ne 0) { throw "Repository ingestion failed." }
```

Use a different `--repo-id` for each repository. Record the full commit SHA printed
by the CLI; ingesting a branch name after it moves selects a new snapshot.
See [the ingestion contract](docs/ingestion.md) for source formats, limits, output
fields, and recovery behavior. Indexing into Qdrant is the next step; the corpus
version does not claim that an embedding model or vector index already exists.

## Step 4 embeddings and hybrid retrieval

The first four steps have passed the user's Windows acceptance. This step reads
a verified source corpus, produces real CPU embeddings, and stores them alongside
BM25 vectors in Qdrant. The following step adds generation over this index.

Extract the Step 4 archive into `C:\Projects`, replacing its source files. Existing
`.env`, `.venv`, `artifacts/`, and Docker volumes are excluded from the archive and
remain available. Keep Docker Desktop and the Step 2 stack running. If the stack
is stopped, start it with `scripts/infra.ps1 -Action up` before this check.

For the exact corpus reported by the Windows Step 3 acceptance:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Corpus = ".\artifacts\corpora\training-demo\e8cd6bc68de1d64e2a7e41ef9c224fdc6d89789953bd7554c9a6029f7e18fa53"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-retrieval.ps1 -Corpus $Corpus
if ($LASTEXITCODE -ne 0) { throw "Hybrid retrieval acceptance failed." }
```

The first run downloads the public embedding model and BM25 resources into
`artifacts/models/`. A GPU and Hugging Face account are not required. The dense
model is `BAAI/bge-small-en-v1.5`, producing 384-dimensional vectors through ONNX
Runtime's CPU provider. It is an English model; multilingual retrieval quality is
not established by this step.

Acceptance checks real-model indexing, repeated-run stability, source metadata,
language filtering, and locating three known symbols after reconnecting to the
store. It prints `STEP 4 ACCEPTANCE PASSED` only when using the Docker server.
It leaves the versioned collection and index manifest available for the next step.

The generic build CLI accepts any supported corpus:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Corpus = Read-Host "Full path to the source corpus directory"
uv run --locked python -m indexing build --corpus "$Corpus"
if ($LASTEXITCODE -ne 0) { throw "Index build failed." }
```

Use the printed manifest path to query the same version:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Manifest = Read-Host "Full path to the index manifest.json"
uv run --locked python -m indexing search --manifest "$Manifest" --query "Counter increment amount" --language python --top-k 5 --offline-models
if ($LASTEXITCODE -ne 0) { throw "Hybrid search failed." }
```

`--offline-models` loads existing model files without downloading them. Omit it
only when the required assets are not cached. Returned JSON contains each chunk's
commit, path, symbol, source coordinates, text, and index version. RRF scores are
ranking scores, not probabilities that a result is correct.

See [the retrieval contract](docs/retrieval.md) for version identity, limits,
partial-upload recovery, and the distinction between local SDK checks and Docker
acceptance.

## Step 5 local generation API

Extract the Step 5 archive into `C:\Projects`, replacing source files. Preserve
`.env`, `artifacts/`, and Docker volumes. Locked Python dependencies are unchanged.
Keep Docker Desktop and the Step 2 stack running.

Install Ollama if missing, then reopen PowerShell:

```powershell
winget install --id Ollama.Ollama --exact
```

Download the model and check the background server:

```powershell
ollama pull qwen2.5-coder:3b
if ($LASTEXITCODE -ne 0) { throw "Model download failed." }
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags"
```

If the tags request cannot connect, start Ollama from the Start menu or run
`ollama serve` in another window. Keep it running. No model API key is required.
Ollama manages its own model cache; embedding assets remain in `artifacts/models/`.

Start the API with the exact manifest reported by Windows Step 4:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Index = ".\artifacts\indexes\training-demo\d3f340bf704cfc04d0a5694c69fc6c06baf6777c21fc1e3f8eb67c35f33effef\manifest.json"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-query-api.ps1 -IndexManifest $Index
```

Leave the API running. Run acceptance in another window:

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-query.ps1
if ($LASTEXITCODE -ne 0) { throw "Generation acceptance failed." }
```

Success prints `STEP 5 ACCEPTANCE PASSED` and saves the response in
`artifacts/acceptance/step5-query.json`. The demo check validates an answer about
`Counter.increment`, citations, versions, tokens and timings, empty context, and
invalid input. This is a smoke check, not a quality or performance baseline.
The first generation includes model loading and may be slower than later requests.

If an HTTP request fails, the check prints its endpoint, status, API error code,
detail, and request ID, then saves `artifacts/acceptance/step5-query-error.json`.
Use that report to identify the failing contract. A generic 502 alone does not
distinguish invalid model JSON from incomplete output or invalid citations.

The citation fix uses API version `0.2.1` and prompt `grounded-codebase-v2`.
Stop the old API with Ctrl+C, replace source files, and restart it with the same
index manifest. The model now returns sourced statements; the API renders inline
citation markers and deduplicates response citations. No index rebuild or model
download is needed. The live check rejects an older API or prompt version.

Use `http://127.0.0.1:8000/docs` for further queries. See [query contract](docs/query.md),
[model card](docs/model-card.md), and [prompt card](docs/prompt-card.md).
Failed startup still serves liveness but readiness returns 503. Check the original
corpus, index, model cache, Qdrant credentials, and Ollama, then restart the API.

## Step 6 tracing and baseline

Step 5 is accepted on Windows, including the citation fix. Extract Step 6 into
`C:\Projects`, replacing source files while retaining `.env` and `artifacts/`.
Stop the old API with Ctrl+C, then restart with the accepted index manifest using
the Step 5 startup command. The current API version is `0.4.1`.
Tracing is enabled by default and uses the local Phoenix port configured in `.env`.
The original embedding identity and index remain compatible.

Run acceptance in another PowerShell window:

```powershell
Set-Location "C:\Projects\codebase-copilot"
$Index = ".\artifacts\indexes\training-demo\d3f340bf704cfc04d0a5694c69fc6c06baf6777c21fc1e3f8eb67c35f33effef\manifest.json"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-week1.ps1 -IndexManifest $Index
if ($LASTEXITCODE -ne 0) { throw "Week 1 demo acceptance failed." }
```

This runs code checks, the accepted generation smoke, one excluded warm-up, and
30 sequential question/answer/judge evaluations. The local judge is the same
Ollama model as generation. Progress is printed after each case; allow several
minutes. Avoid other queries because the API has one generation slot.

Success prints `BASELINE ACCEPTANCE PASSED` and `STEP 6 ACCEPTANCE PASSED`.
A new directory under `artifacts/baselines/` contains results, a summary/report,
a version manifest, and five traces downloaded back from Phoenix. No quality
score is predetermined or substituted for a failure. Metrics include nearest-rank
p50/p95 client latency and model-side TTFT, retrieval hit rate/range recall/MRR,
token counts, and uncalibrated local-judge estimates.
See [evaluation contract](docs/evaluation.md), [dataset card](docs/dataset-card.md),
[architecture](docs/architecture-v1.md), and [operations](docs/week1-runbook.md).

A new developer with uv, Git, Docker Desktop, and a running Ollama can prepare
and serve the demo with one command:

```powershell
Set-Location "C:\Projects\codebase-copilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-demo.ps1
```

The launcher synchronizes dependencies, starts and acceptance-checks infrastructure,
downloads the generation model only if missing, creates a demo Git snapshot,
builds its index, and serves the API. It reuses matching artifacts and credentials.
Its infrastructure check restarts services; run it before other traffic. It is not
required when retaining the accepted Step 4 index.

## References

- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- uv project synchronization: https://docs.astral.sh/uv/concepts/projects/sync/
- Phoenix Docker deployment: https://arize.com/docs/phoenix/self-hosting/deployment-options/docker
- Phoenix selected release: https://github.com/Arize-ai/phoenix/releases/tag/arize-phoenix-v20.20.0
- Qdrant selected release: https://github.com/qdrant/qdrant/releases/tag/v1.19.2
- PostgreSQL official image tags: https://github.com/docker-library/official-images/blob/master/library/postgres
- Ollama Windows: https://docs.ollama.com/windows
- Ollama native chat API: https://docs.ollama.com/api/chat
- Generation model: https://ollama.com/library/qwen2.5-coder:3b
- OpenTelemetry Python: https://opentelemetry.io/docs/languages/python/instrumentation/
- Phoenix tracing: https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel
