# Week 1 operations

Steps 1–6 have passed on the user's Windows demo environment. For the selected
working repository, follow [KubeSentiment preparation and acceptance](kubesentiment.md).
The commands below continue to operate the calculator demo.

## Start and inspect

Retain the accepted corpus/index and use `scripts/start-query-api.ps1` with its
manifest. A new developer with prerequisites installed and Ollama running can
use `scripts/run-demo.ps1` to prepare and start the demo. The launcher acceptance-
checks and restarts infrastructure; run it before other application traffic.

Run `scripts/check-week1.ps1 -IndexManifest <path>` in another terminal while the
API is running. Avoid concurrent callers during the sequential baseline. Look
for `STEP 6 ACCEPTANCE PASSED` and retain the printed baseline directory.

Open Phoenix at the port configured in `.env`, default `http://127.0.0.1:6006`.
Select project `codebase-copilot-week1`. Match `X-Trace-ID` or response `trace_id`
to a trace whose root has `copilot.request_id`. `X-Request-ID` remains unchanged.
Every query is sampled for this local baseline. `COPILOT_TRACING=0` disables
export, causing Step 6 trace acceptance to fail. Restart to change settings.

## Reproducible failure cases

These tests inject failures into isolated stores/backends, preserving the
accepted Qdrant collection and local model:

```powershell
Set-Location "C:\Projects\codebase-copilot"
uv run --locked pytest -q tests/test_indexing.py -k api_retriever_rejects_payload
if ($LASTEXITCODE -ne 0) { throw "Retrieval failure regression failed." }
uv run --locked pytest -q tests/test_query.py -k invalid_model_citations
if ($LASTEXITCODE -ne 0) { throw "Generation failure regression failed." }
```

The retrieval case changes a stored chunk while preserving declared versions and
expects rejection against the saved corpus. Generation cases supply nonexistent,
duplicate, or undeclared model source labels and expect HTTP 502. Full acceptance
includes both. These are injected regressions, not claims that an actual model
was made to fail on demand.

## Recovery

| Symptom | Action |
| --- | --- |
| Liveness 200, readiness 503 | Check corpus/index/cache, Qdrant, credentials, and Ollama; fix then restart |
| API version mismatch | Stop the old process and restart from updated sources |
| Model identity changed | Record the new digest/backend, restart API, and measure a fresh baseline |
| 502 | Read `step5-query-error.json`; retain citation validation |
| Missing Phoenix trace | Check Phoenix/port, enable tracing, restart API, repeat acceptance |
| Baseline case errors | Inspect checkpointed `results.jsonl`; acceptance needs a clean rerun |
| 503 busy | Stop concurrent callers; only one query slot is available |

Stop the API with Ctrl+C; queued spans are flushed on shutdown. Retain all
baseline/version files for future comparisons. These commands do not delete
application collections, models, corpora, or Docker volumes.

After acceptance, commit the source and record a `week1-baseline` Git tag through
your normal repository workflow. A dirty-tree tag does not identify evaluated
code; baseline source-file hashes remain authoritative.
