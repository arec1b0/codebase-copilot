"""Measure the actual local pipeline and save five traces read back from Phoenix."""

import argparse
import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.contracts import QueryResponse
from app.main import SERVICE_VERSION
from app.model import OllamaModel
from app.prompt import PROMPT_SHA256, PROMPT_VERSION
from app.service import QdrantRetriever
from evals.contracts import EvalCase, retrieval_metrics
from evals.datasets import load_repository_dataset, read_profile
from evals.judge import RUBRIC_SHA256, RUBRIC_VERSION, assess
from evals.phoenix import fetch_trace
from evals.versions import container_identities, manifest
from indexing.config import ROOT, connect
from indexing.corpus import Corpus, load_corpus
from indexing.embeddings import CpuEmbeddings
from indexing.store import load_manifest
from observability.tracing import phoenix_url


def percentile(values: list[float], percent: float) -> float | None:
    """Nearest-rank percentile; no interpolation or invented value for empty input."""
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(percent * len(values)) - 1)]


def load_dataset(corpus: Corpus) -> tuple[list[EvalCase], str]:
    raw = (ROOT / "evals/dataset.jsonl").read_bytes()
    cases = [EvalCase.model_validate_json(line) for line in raw.splitlines()]
    if not 30 <= len(cases) <= 50 or len({case.id for case in cases}) != len(cases):
        raise ValueError("Dataset must contain 30–50 uniquely identified cases.")
    fixtures = {
        path.name: path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        for path in (ROOT / "examples/demo-repo").iterdir()
        if path.is_file()
    }
    if {chunk.path for chunk in corpus.chunks} != set(fixtures):
        raise ValueError("This dataset is bound to the supplied four-file demo corpus.")
    for chunk in corpus.chunks:
        if chunk.text != fixtures[chunk.path][chunk.start_char : chunk.end_char]:
            raise ValueError("Corpus source differs from the dataset's demo source.")
    for case in cases:
        for target in case.evidence:
            if target.end_line < target.start_line or not any(
                chunk.path == target.path
                and chunk.start_line <= target.start_line
                and chunk.end_line >= target.end_line
                for chunk in corpus.chunks
            ):
                raise ValueError(f"Ground-truth source range is missing for {case.id}.")
    return cases, hashlib.sha256(raw).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def summarize(rows: list[dict[str, Any]]) -> dict[str, object]:
    successful = [row for row in rows if "response" in row]
    judged = [row for row in rows if "judge" in row]

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    def latency(key: str) -> dict[str, float | None]:
        values = [float(row[key]) for row in successful if row.get(key) is not None]
        return {
            "p50": percentile(values, 0.5),
            "p95": percentile(values, 0.95),
            "n": float(len(values)),
        }

    return {
        "cases": len(rows),
        "http_successes": len(successful),
        "judge_successes": len(judged),
        "errors": sum("error" in row for row in rows),
        "retrieval_hit_rate_at_3": mean(
            [row["retrieval"]["hit"] for row in rows if "retrieval" in row]
        ),
        "retrieval_recall_at_3": mean(
            [row["retrieval"]["recall"] for row in rows if "retrieval" in row]
        ),
        "retrieval_mrr_at_3": mean(
            [row["retrieval"]["reciprocal_rank"] for row in rows if "retrieval" in row]
        ),
        "faithfulness_judge_mean_0_to_2": mean(
            [float(row["judge"]["faithfulness"]) for row in judged]
        ),
        "relevance_judge_mean_0_to_2": mean([float(row["judge"]["relevance"]) for row in judged]),
        "abstentions": sum(
            row["response"]["status"] == "insufficient_context" for row in successful
        ),
        "client_end_to_end_ms": latency("client_ms"),
        "model_ttft_ms": latency("model_ttft_ms"),
        "generation_input_tokens": sum(
            row["response"]["usage"]["input_tokens"] for row in successful
        ),
        "generation_output_tokens": sum(
            row["response"]["usage"]["output_tokens"] for row in successful
        ),
        "judge_input_tokens": sum(row["judge_usage"]["input_tokens"] for row in judged),
        "judge_output_tokens": sum(row["judge_usage"]["output_tokens"] for row in judged),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--profile", type=Path, help="Pinned real-repository dataset profile.")
    args = parser.parse_args()
    index = load_manifest(args.manifest)
    corpus = load_corpus(ROOT / "artifacts/corpora" / index.repo / index.corpus_version)
    if corpus.sha256 != index.corpus_sha256 or corpus.commit_sha != index.commit_sha:
        raise ValueError("Evaluation corpus differs from the selected index.")
    if args.profile is None:
        cases, dataset_sha = load_dataset(corpus)
        dataset_name = "training-demo"
    else:
        cases, dataset_sha = load_repository_dataset(corpus, args.profile)
        dataset_name = read_profile(args.profile).name
    containers = container_identities()
    directory = ROOT / "artifacts/baselines" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    directory.mkdir(parents=True)
    (directory / "traces").mkdir()
    model = OllamaModel(
        os.environ.get("COPILOT_OLLAMA_URL", "http://127.0.0.1:11434"), "qwen2.5-coder:3b"
    )
    client = connect()
    rows: list[dict[str, Any]] = []
    saved_traces = 0
    try:
        identity = model.identity()
        backend = CpuEmbeddings(ROOT / "artifacts/models", local_only=True)
        retriever = QdrantRetriever(client, index, backend, corpus.chunks)
        retriever.check()
        with (
            httpx.Client(base_url="http://127.0.0.1:8000", timeout=210, trust_env=False) as api,
            httpx.Client(base_url=phoenix_url(), timeout=5, trust_env=False) as phoenix,
        ):
            health = api.get("/healthz")
            health.raise_for_status()
            if health.json()["version"] != SERVICE_VERSION:
                raise ValueError("Restart the API with the Step 6 sources.")
            api.get("/readyz").raise_for_status()

            def query(case: EvalCase) -> QueryResponse:
                response = api.post(
                    "/query",
                    json={"question": case.question, "language": case.language, "top_k": 3},
                )
                if not response.is_success:
                    error = response.json()
                    raise ValueError(
                        f"API HTTP {response.status_code}: {error.get('error', 'unknown')}; "
                        f"request {error.get('request_id', 'unknown')}"
                    )
                body = QueryResponse.model_validate_json(response.content)
                if (
                    body.index_version != index.index_version
                    or body.commit_sha != index.commit_sha
                    or body.corpus_version != corpus.version
                    or body.model_revision != identity.revision
                    or body.model_backend_version != identity.backend_version
                    or body.prompt_version != PROMPT_VERSION
                    or body.prompt_sha256 != PROMPT_SHA256
                    or response.headers.get("X-Request-ID") != str(body.request_id)
                    or response.headers.get("X-Trace-ID") != body.trace_id
                    or not body.trace_id
                ):
                    raise ValueError(
                        "Response version, request, or trace identity differs from the pinned run."
                    )
                expected = {chunk.chunk_id: chunk for chunk in corpus.chunks}
                for citation in body.citations:
                    chunk = expected.get(citation.chunk_id)
                    if chunk is None or (
                        citation.path,
                        citation.symbol,
                        citation.start_line,
                        citation.end_line,
                        citation.commit_sha,
                        citation.repo,
                    ) != (
                        chunk.path,
                        chunk.symbol,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.commit_sha,
                        chunk.repo,
                    ):
                        raise ValueError("Response citation differs from its saved source record.")
                return body

            print("Running one excluded warm-up query...", flush=True)
            warmup = query(cases[0])
            write_json(directory / "warmup.json", warmup.model_dump(mode="json"))
            if warmup.status != "answered":
                raise ValueError("The answerable warm-up question was not answered.")
            # Verify collector readback before starting the longer evaluation sequence.
            exported = fetch_trace(phoenix, warmup.trace_id or "", str(warmup.request_id))
            write_json(directory / "traces" / f"{warmup.trace_id}.json", exported)
            saved_traces = 1
            versions = manifest(index, warmup, dataset_sha, containers)
            versions["dataset_name"] = dataset_name
            if args.profile is not None:
                profile_content = args.profile.read_bytes()
                versions["dataset_profile"] = json.loads(profile_content)
                versions["dataset_profile_sha256"] = hashlib.sha256(profile_content).hexdigest()
                (directory / "dataset-profile.json").write_bytes(profile_content)
                selected = read_profile(args.profile)
                (directory / "dataset.jsonl").write_bytes(
                    (args.profile.parent / selected.questions_file).read_bytes()
                )
            versions["judge"] = {
                "model": identity.model,
                "revision": identity.revision,
                "rubric_version": RUBRIC_VERSION,
                "rubric_sha256": RUBRIC_SHA256,
                "calibrated": False,
                "same_model_as_generator": True,
            }
            write_json(directory / "version-manifest.json", versions)
            chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
            for number, case in enumerate(cases, 1):
                row: dict[str, Any] = {"case": case.model_dump(), "case_id": case.id}
                try:
                    hits = retriever.retrieve(case.question, 3, case.language)
                    row["retrieval"] = retrieval_metrics(case, hits)
                    row["retrieved_chunks"] = [hit.model_dump(mode="json") for hit in hits]
                    start = time.perf_counter()
                    body = query(case)
                    row["client_ms"] = (time.perf_counter() - start) * 1000
                    row["model_ttft_ms"] = body.model_ttft_ms
                    row["response"] = body.model_dump(mode="json")
                    if saved_traces < 5 and body.status == "answered":
                        exported = fetch_trace(phoenix, body.trace_id or "", str(body.request_id))
                        write_json(directory / "traces" / f"{body.trace_id}.json", exported)
                        saved_traces += 1
                    judgment, usage = assess(model, identity, case, body, chunks)
                    row["judge"], row["judge_usage"] = judgment.model_dump(), usage.model_dump()
                except Exception as error:
                    row["error"] = {"type": type(error).__name__, "detail": str(error)[:500]}
                rows.append(row)
                with (directory / "results.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                outcome = "ERROR" if "error" in row else "measured"
                print(f"[{number}/{len(cases)}] {case.id}: {outcome}", flush=True)
    finally:
        client.close()
        model.close()
    summary = summarize(rows)
    summary["dataset_name"] = dataset_name
    summary["saved_phoenix_traces"] = saved_traces
    write_json(directory / "summary.json", summary)
    for name, selected_rows in (
        (
            "abstentions",
            [
                row
                for row in rows
                if row.get("response", {}).get("status") == "insufficient_context"
            ],
        ),
        ("errors", [row for row in rows if "error" in row]),
    ):
        (directory / f"{name}.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in selected_rows),
            encoding="utf-8",
        )
    report = f"# {dataset_name} baseline\n\n```json\n" + json.dumps(summary, indent=2) + "\n```\n\n"
    report += (
        "Sequential concurrency 1; one warm-up excluded. Nearest-rank percentiles. "
        "Retrieval measured separately with the same pinned query configuration. "
        "Judge scores are same-model, uncalibrated estimates. Questions are authored "
        "from source; labels need human review. This is not a capacity limit.\n"
    )
    (directory / "report.md").write_text(report, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Baseline: {directory}")
    if summary["errors"] or saved_traces != 5 or len(rows) != len(cases):
        raise SystemExit("Baseline incomplete. Inspect results.jsonl; no acceptance claimed.")
    print("BASELINE ACCEPTANCE PASSED")


if __name__ == "__main__":
    main()
