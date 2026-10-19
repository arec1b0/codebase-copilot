"""Saved-run gate tests use real temporary Git/ingestion and declared synthetic answers."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from evals import compare
from evals.comparison import compare_runs, digest, load_run, render_report
from evals.comparison_models import RegressionPolicy
from evals.contracts import EvalCase, Evidence, retrieval_metrics
from indexing.corpus import load_corpus
from indexing.store import IndexManifest, RetrievalHit
from ingestion.pipeline import fingerprint, ingest
from scripts.check_comparison import check


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def read_rows(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (directory / "results.jsonl").read_bytes().splitlines()]


def write_rows(directory: Path, rows: list[dict[str, Any]]) -> None:
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def saved_seed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("comparison-seed")
    repository = root / "source"
    repository.mkdir()
    (repository / "calc.py").write_text(
        "def one():\n    return 1\n\ndef two():\n    return 2\n", encoding="utf-8"
    )
    for arguments in (("init", "--initial-branch=main"), ("add", "."), ("commit", "-m", "Fixture")):
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Comparison Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.autocrlf=false",
                *arguments,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    corpora = root / "corpora"
    prepared = ingest(repository, corpora, repo_id="comparison-fixture")
    corpus = load_corpus(prepared.directory)
    index = IndexManifest(
        repo=corpus.repo,
        commit_sha=corpus.commit_sha,
        corpus_version=corpus.version,
        corpus_sha256=corpus.sha256,
        chunk_count=len(corpus.chunks),
        embeddings={"backend": "synthetic-test-only"},
        dimension=3,
        index_version="",
        collection="",
    )
    version = fingerprint(index.model_dump(exclude={"index_version", "collection"}))
    index = index.model_copy(
        update={"index_version": version, "collection": f"copilot_{corpus.repo}_{version[:24]}"}
    )
    directory = root / "baseline"
    directory.mkdir()
    rows: list[dict[str, Any]] = []
    cases = []
    for number, symbol in enumerate(("one", "two"), 1):
        chunk = next(chunk for chunk in corpus.chunks if chunk.symbol == symbol)
        case = EvalCase(
            id=f"locating-{number:02}",
            category="locating",
            question=f"Where is {symbol}?",
            language="python",
            reference=f"calc.py contains {symbol}.",
            evidence=[
                Evidence(path=chunk.path, start_line=chunk.start_line, end_line=chunk.end_line)
            ],
        )
        cases.append(case)
        hit = RetrievalHit(
            index_version=index.index_version, corpus_version=corpus.version, score=1.0, chunk=chunk
        )
        response = {
            "request_id": str(uuid4()),
            "trace_id": uuid4().hex,
            "status": "answered",
            "answer": f"Synthetic fixture: {symbol} is in calc.py. [S1]",
            "citations": [
                {
                    "source_id": "S1",
                    **{
                        key: getattr(chunk, key)
                        for key in (
                            "chunk_id",
                            "repo",
                            "commit_sha",
                            "path",
                            "symbol",
                            "start_line",
                            "end_line",
                        )
                    },
                }
            ],
            "model": "synthetic-test-only",
            "model_revision": "sha256:" + "a" * 64,
            "model_backend_version": "test:1",
            "prompt_version": "synthetic-prompt-v1",
            "prompt_sha256": "b" * 64,
            "index_version": index.index_version,
            "corpus_version": corpus.version,
            "repo": corpus.repo,
            "commit_sha": corpus.commit_sha,
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "retrieval_ms": 2.0,
            "generation_ms": 8.0,
            "model_ttft_ms": 3.0,
            "total_ms": 10.0,
        }
        rows.append(
            {
                "case": case.model_dump(),
                "case_id": case.id,
                "retrieval": retrieval_metrics(case, [hit]),
                "retrieved_chunks": [hit.model_dump()],
                "response": response,
                "client_ms": 11.0,
                "model_ttft_ms": 3.0,
                "judge": {
                    "faithfulness": 2,
                    "relevance": 2,
                    "faithfulness_reason": "Synthetic fixture.",
                    "relevance_reason": "Synthetic fixture.",
                },
                "judge_usage": {"input_tokens": 20, "output_tokens": 10},
            }
        )
    dataset = ("\n".join(case.model_dump_json() for case in cases) + "\n").encode()
    (directory / "dataset.jsonl").write_bytes(dataset)
    write_json(
        directory / "version-manifest.json",
        {
            "dataset_sha256": digest(dataset),
            "dataset_name": "synthetic-comparison-fixture",
            "source_commit_sha": corpus.commit_sha,
            "corpus_version": corpus.version,
            "index": index.model_dump(),
            **{
                key: rows[0]["response"][key]
                for key in (
                    "model",
                    "model_revision",
                    "model_backend_version",
                    "prompt_version",
                    "prompt_sha256",
                )
            },
            "judge": {
                "model": "synthetic-test-only",
                "revision": "sha256:" + "a" * 64,
                "rubric_version": "synthetic-judge-v1",
                "rubric_sha256": "c" * 64,
                "calibrated": False,
                "same_model_as_generator": True,
            },
        },
    )
    write_rows(directory, rows)
    return directory, corpora


@pytest.fixture
def inputs(tmp_path: Path, saved_seed: tuple[Path, Path]) -> tuple[Path, Path, Path]:
    baseline, corpora = saved_seed
    candidate = tmp_path / "candidate"
    shutil.copytree(baseline, candidate)
    return baseline, candidate, corpora


def policy(**updates: Any) -> RegressionPolicy:
    return RegressionPolicy(name="synthetic-test-policy", **updates)


def test_self_comparison_uses_records_not_summary(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    write_json(candidate / "summary.json", {"retrieval_recall_at_3": -999})
    report = compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())
    assert report["status"] == "passed" and not report["regressions"]
    assert all(metric["delta"] == 0 for metric in report["metrics"])
    assert report["runs"]["candidate"]["observations"]["client_ms"] == {
        "n": 2,
        "p50": 11.0,
        "p95": 11.0,
    }
    assert "No per-case metric decrease" in render_report(report)


def test_retrieval_drop_and_absolute_tolerance(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    rows = read_rows(candidate)
    rows[0].update(
        retrieved_chunks=[], retrieval={"hit": 0.0, "recall": 0.0, "reciprocal_rank": 0.0}
    )
    write_rows(candidate, rows)
    before, after = load_run(baseline, corpora), load_run(candidate, corpora)
    report = compare_runs(before, after, policy())
    assert report["status"] == "failed" and len(report["regressions"]) == 3
    assert report["regressions"][0]["case_id"] == "locating-01"
    tolerated = compare_runs(
        before,
        after,
        policy(max_retrieval_drop={"hit_rate_at_3": 0.5, "recall_at_3": 0.5, "mrr_at_3": 0.5}),
    )
    assert tolerated["status"] == "passed" and len(tolerated["regressions"]) == 3


def test_rank_regression_is_distinct_from_hit_and_recall(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    rows = read_rows(candidate)
    rows[0]["retrieved_chunks"].insert(0, deepcopy(rows[1]["retrieved_chunks"][0]))
    rows[0]["retrieval"]["reciprocal_rank"] = 0.5
    write_rows(candidate, rows)
    report = compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())
    failed = [metric["metric"] for metric in report["metrics"] if metric["failed"]]
    assert failed == ["mrr_at_3"]
    # The actual API citation remains S1; independent retrieval now ranks it second.
    assert not report["runs"]["candidate"]["technical_issues"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate",
        "extra",
        "case",
        "metric",
        "text",
        "identity",
        "request",
        "rank-duplicate",
    ],
)
def test_changed_or_incomplete_artifacts_are_rejected(
    inputs: tuple[Path, Path, Path], damage: str
) -> None:
    _, candidate, corpora = inputs
    rows = read_rows(candidate)
    if damage == "missing":
        rows.pop()
    elif damage == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif damage == "extra":
        rows[0]["case_id"] = "locating-99"
    elif damage == "case":
        rows[0]["case"]["reference"] = "Changed ground truth"
    elif damage == "metric":
        rows[0]["retrieval"]["recall"] = 0.0
    elif damage == "text":
        rows[0]["retrieved_chunks"][0]["chunk"]["text"] = "invented source"
    elif damage == "identity":
        rows[0]["response"]["prompt_sha256"] = "d" * 64
    elif damage == "request":
        rows[1]["response"]["request_id"] = rows[0]["response"]["request_id"]
    else:
        rows[0]["retrieved_chunks"] *= 2
    write_rows(candidate, rows)
    with pytest.raises(ValueError):
        load_run(candidate, corpora)


@pytest.mark.parametrize(
    "damage", ["empty", "citation", "labels", "abstain-cited", "timing", "trace"]
)
def test_response_contract_failures_block_even_without_score_drop(
    inputs: tuple[Path, Path, Path], damage: str
) -> None:
    baseline, candidate, corpora = inputs
    rows = read_rows(candidate)
    body = rows[0]["response"]
    if damage == "empty":
        body["answer"] = " "
    elif damage == "citation":
        body["citations"][0]["path"] = "invented.py"
    elif damage == "labels":
        body["answer"] = "Synthetic fixture [S9]"
    elif damage == "abstain-cited":
        body["status"] = "insufficient_context"
    elif damage == "timing":
        body["total_ms"] = -1.0
    else:
        body["trace_id"] = None
    write_rows(candidate, rows)
    report = compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())
    assert report["status"] == "failed" and not report["regressions"]
    assert "locating-01" in report["runs"]["candidate"]["technical_issues"]


def test_errors_are_not_dropped_from_denominator(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    rows = read_rows(candidate)
    rows[0] = {
        "case": rows[0]["case"],
        "case_id": rows[0]["case_id"],
        "error": {"type": "SyntheticFailure", "detail": "Explicit fixture."},
    }
    write_rows(candidate, rows)
    report = compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())
    assert report["status"] == "failed"
    assert report["metrics"][0]["candidate"] == 0.5
    assert report["runs"]["candidate"]["observations"]["client_ms"]["n"] == 1


def test_uncalibrated_judge_is_report_only_and_cannot_be_enabled(
    inputs: tuple[Path, Path, Path],
) -> None:
    baseline, candidate, corpora = inputs
    rows = read_rows(candidate)
    rows[0]["judge"].update(faithfulness=0, relevance=0)
    write_rows(candidate, rows)
    before, after = load_run(baseline, corpora), load_run(candidate, corpora)
    report = compare_runs(before, after, policy())
    assert report["status"] == "passed" and len(report["regressions"]) == 2
    with pytest.raises(ValueError, match="calibrated"):
        compare_runs(before, after, policy(gate_judge_scores=True))


def test_changed_judge_suppresses_misleading_delta(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    path = candidate / "version-manifest.json"
    versions = json.loads(path.read_bytes())
    versions["judge"]["rubric_sha256"] = "d" * 64
    write_json(path, versions)
    report = compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())
    assert report["status"] == "passed" and not report["judge_comparable"]
    assert all(metric["delta"] is None for metric in report["metrics"] if not metric["gated"])


def test_changed_dataset_or_policy_is_rejected(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    with (candidate / "dataset.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="Dataset bytes"):
        load_run(candidate, corpora)
    for fields in (
        {"max_retrieval_drop": {"recall_at_3": -0.1}},
        {"gate_judge_scores": "false"},
        {"unexpected": 1},
    ):
        with pytest.raises(ValueError):
            policy(**fields)
    assert load_run(baseline, corpora).rows


def test_duplicate_json_keys_and_nonfinite_metrics_are_rejected(
    inputs: tuple[Path, Path, Path],
) -> None:
    _, candidate, corpora = inputs
    path = candidate / "version-manifest.json"
    original = path.read_bytes()
    path.write_bytes(original.replace(b"{", b'{"model":"duplicate",', 1))
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        load_run(candidate, corpora)
    path.write_bytes(original)
    rows = read_rows(candidate)
    rows[0]["retrieval"]["recall"] = float("nan")
    write_rows(candidate, rows)
    with pytest.raises(ValueError):
        load_run(candidate, corpora)


def test_actual_cli_acceptance_and_input_preservation(
    tmp_path: Path, saved_seed: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    baseline, corpora = saved_seed
    original = {path.name: path.read_bytes() for path in baseline.iterdir()}
    output = tmp_path / "acceptance"
    check(baseline, corpora, output)
    assert "WEEK 2 STEP 1 ACCEPTANCE PASSED" in capsys.readouterr().out
    assert original == {path.name: path.read_bytes() for path in baseline.iterdir()}
    report = json.loads((output / "retrieval-drop/comparison.json").read_bytes())
    assert report["status"] == "failed" and report["regressions"]
    assert not (output / "missing-case/comparison.json").exists()


def test_offsets_do_not_hide_individual_regressions(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    before_path = candidate.parent / "before"
    shutil.copytree(baseline, before_path)
    before_rows = read_rows(before_path)
    after_rows = read_rows(candidate)
    before_rows[0].update(
        retrieved_chunks=[], retrieval={"hit": 0.0, "recall": 0.0, "reciprocal_rank": 0.0}
    )
    after_rows[1].update(
        retrieved_chunks=[], retrieval={"hit": 0.0, "recall": 0.0, "reciprocal_rank": 0.0}
    )
    write_rows(before_path, before_rows)
    write_rows(candidate, after_rows)
    report = compare_runs(load_run(before_path, corpora), load_run(candidate, corpora), policy())
    assert report["status"] == "passed"  # The declared policy gates aggregates.
    assert all(metric["delta"] == 0 for metric in report["metrics"])
    assert {item["case_id"] for item in report["regressions"]} == {"locating-02"}


def test_different_dataset_cannot_be_compared(inputs: tuple[Path, Path, Path]) -> None:
    baseline, candidate, corpora = inputs
    cases = [json.loads(line) for line in (candidate / "dataset.jsonl").read_bytes().splitlines()]
    rows = read_rows(candidate)
    cases[0]["question"] = "A newly worded question?"
    rows[0]["case"] = cases[0]
    raw = ("\n".join(json.dumps(case) for case in cases) + "\n").encode()
    (candidate / "dataset.jsonl").write_bytes(raw)
    write_rows(candidate, rows)
    versions = json.loads((candidate / "version-manifest.json").read_bytes())
    versions["dataset_sha256"] = digest(raw)
    write_json(candidate / "version-manifest.json", versions)
    with pytest.raises(ValueError, match="same dataset"):
        compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())


@pytest.mark.parametrize("damage", ["digest", "index", "corpus", "namespace"])
def test_manifest_and_corpus_integrity_cannot_be_bypassed(
    inputs: tuple[Path, Path, Path], damage: str
) -> None:
    _, candidate, corpora = inputs
    path = candidate / "version-manifest.json"
    versions = json.loads(path.read_bytes())
    if damage == "digest":
        versions["dataset_sha256"] = "0" * 64
    elif damage == "index":
        versions["index"]["index_version"] = "0" * 64
    elif damage == "corpus":
        versions["corpus_version"] = "0" * 64
    else:
        versions["index"]["repo"] = "../outside"
    write_json(path, versions)
    with pytest.raises(ValueError):
        load_run(candidate, corpora)


def test_cli_never_overwrites_existing_output(
    inputs: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline, candidate, corpora = inputs
    marker = candidate / "report.md"
    marker.write_text("retain me", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "compare",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--corpora-root",
            str(corpora),
            "--output",
            str(candidate),
        ],
    )
    assert compare.main() == 2
    assert marker.read_text(encoding="utf-8") == "retain me"


def test_row_order_and_changed_generator_identity_are_supported(
    inputs: tuple[Path, Path, Path],
) -> None:
    baseline, candidate, corpora = inputs
    rows = list(reversed(read_rows(candidate)))
    versions = json.loads((candidate / "version-manifest.json").read_bytes())
    versions["model_revision"] = "sha256:" + "d" * 64
    versions["judge"]["same_model_as_generator"] = False
    versions["prompt_version"] = "synthetic-prompt-v2"
    versions["prompt_sha256"] = "e" * 64
    for row in rows:
        for key in ("model_revision", "prompt_version", "prompt_sha256"):
            row["response"][key] = versions[key]
    write_rows(candidate, rows)
    write_json(candidate / "version-manifest.json", versions)
    report = compare_runs(load_run(baseline, corpora), load_run(candidate, corpora), policy())
    assert report["status"] == "passed"


def test_calibrated_judge_gate_is_mechanical_not_a_calibration_claim(
    inputs: tuple[Path, Path, Path],
) -> None:
    baseline, candidate, corpora = inputs
    before_path = candidate.parent / "calibrated-before"
    shutil.copytree(baseline, before_path)
    # These flags are explicit synthetic test inputs, not human calibration evidence.
    for directory in (before_path, candidate):
        versions = json.loads((directory / "version-manifest.json").read_bytes())
        versions["judge"]["calibrated"] = True
        write_json(directory / "version-manifest.json", versions)
    rows = read_rows(candidate)
    rows[0]["judge"]["faithfulness"] = 0
    write_rows(candidate, rows)
    report = compare_runs(
        load_run(before_path, corpora), load_run(candidate, corpora), policy(gate_judge_scores=True)
    )
    assert report["status"] == "failed"
    assert [m["metric"] for m in report["metrics"] if m["failed"]] == ["faithfulness"]
