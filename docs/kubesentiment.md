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

## Update and prepare

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
