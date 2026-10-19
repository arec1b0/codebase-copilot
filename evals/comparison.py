"""Compare complete saved runs; never query a model or trust saved aggregates."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.comparison_models import RegressionPolicy, RunManifest, SavedRow
from evals.contracts import EvalCase, retrieval_metrics
from indexing.corpus import load_corpus
from ingestion.models import Chunk
from ingestion.pipeline import fingerprint

RETRIEVAL_KEYS = {"hit_rate_at_3": "hit", "recall_at_3": "recall", "mrr_at_3": "reciprocal_rank"}
JUDGE_KEYS = ("faithfulness", "relevance")
COMPARISON_VERSION = "saved-run-comparison-v1"


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(raw: bytes) -> Any:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"Non-finite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_constant)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SavedRun:
    directory: Path
    versions: RunManifest
    rows: dict[str, SavedRow]
    issues: dict[str, list[str]]
    file_hashes: dict[str, str]


def response_issues(row: SavedRow, chunks: dict[str, Chunk]) -> list[str]:
    """Check source metadata by chunk UUID, never by independent retrieval rank."""
    body = row.response
    if body is None:
        return ["missing_response"]
    issues = []
    if not body.answer.strip():
        issues.append("empty_answer")
    labels = re.findall(r"\[(S[^\]]*)\]", body.answer)
    ids = [citation.source_id for citation in body.citations]
    if body.status == "answered":
        if not ids or len(set(ids)) != len(ids) or set(labels) != set(ids):
            issues.append("invalid_citation_labels")
        if any(re.fullmatch(r"S[1-3]", label) is None for label in ids):
            issues.append("invalid_source_label")
    elif ids or labels:
        issues.append("cited_abstention")
    for citation in body.citations:
        chunk = chunks.get(citation.chunk_id)
        fields = ("repo", "commit_sha", "path", "symbol", "start_line", "end_line")
        if chunk is None or any(getattr(citation, f) != getattr(chunk, f) for f in fields):
            issues.append("citation_source_mismatch")
    values = [body.retrieval_ms, body.generation_ms, body.total_ms]
    if body.model_ttft_ms is not None:
        values.append(body.model_ttft_ms)
    if any(not math.isfinite(value) or value < 0 for value in values):
        issues.append("invalid_response_timing")
    if row.model_ttft_ms != body.model_ttft_ms:
        issues.append("ttft_record_mismatch")
    return sorted(set(issues))


def load_run(directory: Path, corpora_root: Path) -> SavedRun:
    directory = directory.resolve()
    names = ("version-manifest.json", "dataset.jsonl", "results.jsonl")
    raw = {name: (directory / name).read_bytes() for name in names}
    versions = RunManifest.model_validate(read_json(raw["version-manifest.json"]))
    if versions.judge.same_model_as_generator and (
        versions.judge.model != versions.model or versions.judge.revision != versions.model_revision
    ):
        raise ValueError("Same-model judge identity differs from the declared generator.")
    index = versions.index
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", index.repo):
        raise ValueError("Unsafe repository namespace in run manifest.")
    if not re.fullmatch(r"[a-f0-9]{64}", index.corpus_version):
        raise ValueError("Invalid corpus version in run manifest.")
    expected_index = fingerprint(index.model_dump(exclude={"index_version", "collection"}))
    if index.index_version != expected_index or index.collection != (
        f"copilot_{index.repo}_{expected_index[:24]}"
    ):
        raise ValueError("Index manifest integrity check failed.")
    corpus = load_corpus(corpora_root / index.repo / index.corpus_version)
    if (
        corpus.repo != index.repo
        or corpus.commit_sha != index.commit_sha
        or corpus.version != versions.corpus_version
        or corpus.sha256 != index.corpus_sha256
        or len(corpus.chunks) != index.chunk_count
        or corpus.commit_sha != versions.source_commit_sha
    ):
        raise ValueError("Saved run does not match its complete local source corpus.")
    if digest(raw["dataset.jsonl"]) != versions.dataset_sha256:
        raise ValueError("Dataset bytes differ from the saved manifest.")
    cases = [EvalCase.model_validate(read_json(line)) for line in raw["dataset.jsonl"].splitlines()]
    expected = {case.id: case for case in cases}
    if not cases or len(expected) != len(cases):
        raise ValueError("Dataset must contain unique, nonempty case IDs.")
    # JSON validation retains UUID handling while rejecting duplicate object keys first.
    rows = [
        SavedRow.model_validate_json(json.dumps(read_json(line), allow_nan=False))
        for line in raw["results.jsonl"].splitlines()
    ]
    by_id = {row.case_id: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != set(expected):
        raise ValueError("Results contain missing, additional, or duplicate cases.")
    chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
    issues: dict[str, list[str]] = {}
    request_ids: set[str] = set()
    trace_ids: set[str] = set()
    for row in rows:
        if row.case != expected[row.case_id] or row.case.id != row.case_id:
            raise ValueError(f"Question/reference/labels changed for {row.case_id}.")
        hits = row.retrieved_chunks
        if hits is None or row.retrieval is None:
            if row.error is None or hits is not None or row.retrieval is not None:
                raise ValueError(f"Missing or partial retrieval data for {row.case_id}.")
        else:
            if len(hits) > 3 or len({hit.chunk.chunk_id for hit in hits}) != len(hits):
                raise ValueError(
                    f"Retrieval must contain at most three unique hits: {row.case_id}."
                )
            for hit in hits:
                if (
                    hit.index_version != index.index_version
                    or hit.corpus_version != corpus.version
                    or hit.chunk != chunks.get(hit.chunk.chunk_id)
                    or hit.chunk.language != row.case.language
                    or not math.isfinite(hit.score)
                ):
                    raise ValueError(f"Retrieved source record is invalid: {row.case_id}.")
            measured = retrieval_metrics(row.case, hits)
            if any(
                not math.isclose(value, getattr(row.retrieval, key), rel_tol=0, abs_tol=1e-12)
                for key, value in measured.items()
            ):
                raise ValueError(f"Saved retrieval metrics are inconsistent: {row.case_id}.")
        found = response_issues(row, chunks)
        if row.error is not None:
            found.append("execution_error")
        if row.judge is None or row.judge_usage is None:
            found.append("missing_judge")
        if row.client_ms is None:
            found.append("missing_client_timing")
        body = row.response
        if body is not None:
            identity = {
                "model": versions.model,
                "model_revision": versions.model_revision,
                "model_backend_version": versions.model_backend_version,
                "prompt_version": versions.prompt_version,
                "prompt_sha256": versions.prompt_sha256,
                "index_version": index.index_version,
                "corpus_version": corpus.version,
                "repo": corpus.repo,
                "commit_sha": corpus.commit_sha,
            }
            if any(getattr(body, key) != value for key, value in identity.items()):
                raise ValueError(f"Response identity differs from the run manifest: {row.case_id}.")
            request_id = str(body.request_id)
            if request_id in request_ids:
                raise ValueError("Duplicate response request ID.")
            request_ids.add(request_id)
            if not body.trace_id or not re.fullmatch(r"[a-f0-9]{32}", body.trace_id):
                found.append("invalid_trace_id")
            elif body.trace_id in trace_ids:
                raise ValueError("Duplicate response trace ID.")
            else:
                trace_ids.add(body.trace_id)
        if found:
            issues[row.case_id] = sorted(set(found))
    return SavedRun(directory, versions, by_id, issues, {k: digest(v) for k, v in raw.items()})


def case_scores(row: SavedRow) -> dict[str, float]:
    # Missing stages on explicit execution failures count as zero for the gate.
    retrieval = retrieval_metrics(row.case, row.retrieved_chunks or [])
    return {
        **{key: retrieval[value] for key, value in RETRIEVAL_KEYS.items()},
        **{key: float(getattr(row.judge, key)) if row.judge else 0.0 for key in JUDGE_KEYS},
    }


def timings(run: SavedRun) -> dict[str, object]:
    def summarize(values: list[float]) -> dict[str, float | int | None]:
        values.sort()
        return {
            "n": len(values),
            **{
                key: values[max(0, math.ceil(percent * len(values)) - 1)] if values else None
                for key, percent in (("p50", 0.5), ("p95", 0.95))
            },
        }

    successful = [
        row for row in run.rows.values() if row.response is not None and row.error is None
    ]
    return {
        "client_ms": summarize([row.client_ms for row in successful if row.client_ms is not None]),
        "model_ttft_ms": summarize(
            [row.model_ttft_ms for row in successful if row.model_ttft_ms is not None]
        ),
        "input_tokens": sum(row.response.usage.input_tokens for row in successful if row.response),
        "output_tokens": sum(
            row.response.usage.output_tokens for row in successful if row.response
        ),
        "abstentions": sum(
            row.response.status == "insufficient_context" for row in successful if row.response
        ),
    }


def compare_runs(
    baseline: SavedRun, candidate: SavedRun, policy: RegressionPolicy
) -> dict[str, Any]:
    if (
        baseline.versions.dataset_sha256 != candidate.versions.dataset_sha256
        or baseline.versions.dataset_name != candidate.versions.dataset_name
        or baseline.versions.source_commit_sha != candidate.versions.source_commit_sha
        or baseline.versions.index.repo != candidate.versions.index.repo
        or set(baseline.rows) != set(candidate.rows)
    ):
        raise ValueError("Runs require the same dataset bytes, repository, and source commit.")
    judge_comparable = (
        baseline.versions.judge == candidate.versions.judge
        and baseline.versions.model_backend_version == candidate.versions.model_backend_version
    )
    if policy.gate_judge_scores and (
        not judge_comparable
        or not baseline.versions.judge.calibrated
        or not candidate.versions.judge.calibrated
    ):
        raise ValueError("Judge gating requires the same calibrated judge/rubric identity.")
    metrics = []
    regressions = []
    scores = {
        name: {case_id: case_scores(row) for case_id, row in run.rows.items()}
        for name, run in (("baseline", baseline), ("candidate", candidate))
    }
    for key in (*RETRIEVAL_KEYS, *JUDGE_KEYS):
        gated = key in RETRIEVAL_KEYS or policy.gate_judge_scores
        comparable = key in RETRIEVAL_KEYS or judge_comparable
        tolerance = (
            getattr(policy.max_retrieval_drop, key)
            if key in RETRIEVAL_KEYS
            else policy.max_judge_drop
        )
        old = sum(row[key] for row in scores["baseline"].values()) / len(baseline.rows)
        new = sum(row[key] for row in scores["candidate"].values()) / len(candidate.rows)
        delta = new - old if comparable else None
        metrics.append(
            {
                "metric": key,
                "baseline": old,
                "candidate": new,
                "delta": delta,
                "gated": gated,
                "max_drop": tolerance,
                "failed": bool(gated and delta is not None and delta < -tolerance - 1e-12),
            }
        )
        if comparable:
            for case_id in sorted(baseline.rows):
                before, after = scores["baseline"][case_id][key], scores["candidate"][case_id][key]
                if after < before - 1e-12:
                    regressions.append(
                        {
                            "case_id": case_id,
                            "category": baseline.rows[case_id].case.category,
                            "metric": key,
                            "baseline": before,
                            "candidate": after,
                            "delta": after - before,
                        }
                    )
    identities = {}
    for name, run in (("baseline", baseline), ("candidate", candidate)):
        identities[name] = {
            "directory": str(run.directory),
            "file_sha256": run.file_hashes,
            "versions": run.versions.model_dump(mode="json"),
            "observations": timings(run),
            "technical_issues": run.issues,
        }
    passed = not baseline.issues and not candidate.issues and not any(m["failed"] for m in metrics)
    return {
        "schema_version": 1,
        "comparison_version": COMPARISON_VERSION,
        "status": "passed" if passed else "failed",
        "cases": len(baseline.rows),
        "policy": policy.model_dump(mode="json"),
        "runs": identities,
        "judge_comparable": judge_comparable,
        "metrics": metrics,
        "regressions": regressions,
        "limitations": [
            "Saved independent retrieval is measured; actual ordered API context is not recorded.",
            "Citation metadata validity does not establish semantic claim support.",
            "Judge scores are report-only by default and are not accuracy percentages.",
            "Artifact hashes provide integrity, not independent authenticity or attestation.",
            "Missing stages on explicit errors contribute zero to fixed-denominator gate metrics.",
            "Latency and tokens are descriptive; no performance or capacity gate is applied.",
            "This comparison does not scan for secrets or verify saved Phoenix exports.",
            "No PR protection, CI execution, human calibration, or holdout acceptance is implied.",
        ],
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Saved-run comparison",
        "",
        f"Status: **{report['status'].upper()}**",
        "",
        f"Cases: {report['cases']}. Policy: `{report['policy']['name']}` (provisional).",
        "",
        "## Aggregate differences",
        "",
        "| Metric | Baseline | Candidate | Delta | Gate |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for metric in report["metrics"]:
        delta = f"{metric['delta']:+.6f}" if metric["delta"] is not None else "incomparable"
        gate = "FAIL" if metric["failed"] else ("pass" if metric["gated"] else "report only")
        lines.append(
            f"| {metric['metric']} | {metric['baseline']:.6f} | "
            f"{metric['candidate']:.6f} | {delta} | {gate} |"
        )
    lines += [
        "",
        "## Individual regressions",
        "",
        "Every decrease is shown, including decreases offset by other improvements.",
        "",
    ]
    if not report["regressions"]:
        lines.append("No per-case metric decrease.")
    else:
        lines += [
            "| Case | Category | Metric | Baseline | Candidate | Delta |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
        for item in report["regressions"]:
            lines.append(
                f"| {item['case_id']} | {item['category']} | {item['metric']} | "
                f"{item['baseline']:.6f} | {item['candidate']:.6f} | {item['delta']:+.6f} |"
            )
    lines += ["", "## Technical issues", ""]
    for name, run in report["runs"].items():
        lines.append(f"{name}: {len(run['technical_issues'])} affected cases.")
        for case_id, issues in sorted(run["technical_issues"].items()):
            lines.append(f"- `{case_id}`: {', '.join(issues)}")
    lines += [
        "",
        "## Reproduction",
        "",
        "See comparison.json for exact input hashes, identities, policy, timing and usage.",
        "",
        "## Scope and limitations",
        "",
    ]
    lines += [f"- {item}" for item in report["limitations"]]
    return "\n".join(lines) + "\n"
