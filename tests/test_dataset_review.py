"""Review mechanics use synthetic answers and real temporary Git source ingestion."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from evals import human_review, run
from evals.comparison import digest, read_json
from evals.contracts import EvalCase, Evidence, retrieval_metrics
from evals.datasets import source_layout
from evals.human_review import agreement_audit, create_packet, validate_packet, write_json
from evals.splits import dataset_role, split_profiles, validate_split
from indexing.corpus import Corpus, load_corpus
from indexing.store import IndexManifest, RetrievalHit
from ingestion.models import IngestionConfig
from ingestion.pipeline import fingerprint, ingest

CATEGORIES = ("locating", "explanation", "dependency", "debugging", "change-impact")


@pytest.fixture(scope="module")
def review_seed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Corpus]:
    root = tmp_path_factory.mktemp("dataset-review")
    repository = root / "source"
    repository.mkdir()
    for name in ("dev.py", "holdout.py"):
        (repository / name).write_text(
            "\n\n".join(f"def f{i}():\n    return {i}" for i in range(6)) + "\n",
            encoding="utf-8",
        )
    for arguments in (("init", "--initial-branch=main"), ("add", "."), ("commit", "-m", "Fixture")):
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Review Test",
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
    config = IngestionConfig(max_chars=600)
    prepared = ingest(repository, root / "corpora", repo_id="review-fixture", config=config)
    corpus = load_corpus(prepared.directory)
    profiles = root / "profiles"
    profiles.mkdir()
    (profiles / "SOURCE-LICENSE.txt").write_text("Synthetic source fixture.\n", encoding="utf-8")
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
        update={
            "index_version": version,
            "collection": f"copilot_{corpus.repo}_{version[:24]}",
        }
    )
    rows: list[dict[str, Any]] = []
    for role, filename in (("dev", "dev.py"), ("holdout", "holdout.py")):
        cases = []
        for category in CATEGORIES:
            for i in range(6):
                chunk = next(c for c in corpus.chunks if c.path == filename and c.symbol == f"f{i}")
                case = EvalCase(
                    id=f"{role}{category.replace('-', '')}-{i + 1:02}",
                    category=category,
                    question=f"Synthetic {role} {category} question {i}?",
                    language="python",
                    reference=f"Synthetic reference for {role} {category} {i}.",
                    evidence=[
                        Evidence(
                            path=chunk.path,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            quote=chunk.text,
                        )
                    ],
                )
                cases.append(case)
                if role != "dev":
                    continue
                hit = RetrievalHit(
                    index_version=version, corpus_version=corpus.version, score=1.0, chunk=chunk
                )
                rows.append(
                    {
                        "case": case.model_dump(),
                        "case_id": case.id,
                        "retrieval": retrieval_metrics(case, [hit]),
                        "retrieved_chunks": [hit.model_dump()],
                        "response": {
                            "request_id": str(uuid4()),
                            "trace_id": uuid4().hex,
                            "status": "answered",
                            "answer": f"Synthetic answer: f{i} returns {i}. [S1]",
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
                            "prompt_version": "synthetic-v1",
                            "prompt_sha256": "b" * 64,
                            "index_version": version,
                            "corpus_version": corpus.version,
                            "repo": corpus.repo,
                            "commit_sha": corpus.commit_sha,
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                            "retrieval_ms": 2.0,
                            "generation_ms": 8.0,
                            "total_ms": 10.0,
                            "model_ttft_ms": 3.0,
                        },
                        "client_ms": 11.0,
                        "model_ttft_ms": 3.0,
                        "judge": {
                            "faithfulness": 2,
                            "relevance": 2,
                            "faithfulness_reason": "Synthetic judge reason hidden from views.",
                            "relevance_reason": "Synthetic judge reason hidden from views.",
                        },
                        "judge_usage": {"input_tokens": 5, "output_tokens": 5},
                    }
                )
        data = ("\n".join(c.model_dump_json() for c in cases) + "\n").encode()
        (profiles / f"{role}.jsonl").write_bytes(data)
        write_json(
            profiles / f"{role}.json",
            {
                "schema_version": 1,
                "name": f"synthetic-{role}",
                "repo": corpus.repo,
                "source_url": "https://github.com/example/synthetic",
                "commit_sha": corpus.commit_sha,
                "ingestion": config.model_dump(),
                "questions_file": f"{role}.jsonl",
                "questions_sha256": digest(data),
                "source_layout_sha256": source_layout(corpus.chunks),
                "case_count": 30,
                "annotation_origin": "assistant-authored-from-source",
            },
        )
    write_json(
        profiles / "split.json",
        {
            "schema_version": 1,
            "name": "synthetic-split",
            "dev_profile": "dev.json",
            "holdout_profile": "holdout.json",
            "dev_profile_sha256": digest((profiles / "dev.json").read_bytes()),
            "holdout_profile_sha256": digest((profiles / "holdout.json").read_bytes()),
            "dev_status": "previously-inspected-development",
            "holdout_policy": "release-only-no-tuning",
            "separation": "evidence-file-disjoint",
            "annotation_status": "assistant-authored-awaiting-maintainer-review",
        },
    )
    (root / "results.jsonl").write_bytes(
        ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    )
    write_json(
        root / "selection.json",
        {
            "schema_version": 1,
            "name": "synthetic-selection",
            "sampling": "purposive-development-sample",
            "results_canonical_sha256": fingerprint(rows),
            "dataset_sha256": digest((profiles / "dev.jsonl").read_bytes()),
            "case_ids": [row["case_id"] for row in rows if int(row["case_id"].split("-")[1]) <= 4],
        },
    )
    (root / "rubric.md").write_text("Synthetic review rubric.\n", encoding="utf-8")
    return root, corpus


@pytest.fixture
def review_inputs(tmp_path: Path, review_seed: tuple[Path, Corpus]) -> tuple[Path, Corpus]:
    root, corpus = review_seed
    target = tmp_path / "inputs"
    shutil.copytree(root, target)
    return target, corpus


def packet(root: Path, corpus: Corpus, name: str = "packet") -> Path:
    output = root / name
    create_packet(
        root / "results.jsonl",
        corpus,
        root / "profiles/dev.json",
        root / "selection.json",
        root / "rubric.md",
        output,
    )
    return output


def rebind_profiles(root: Path) -> None:
    profiles = root / "profiles"
    split = read_json((profiles / "split.json").read_bytes())
    for role in ("dev", "holdout"):
        path = profiles / f"{role}.json"
        profile = read_json(path.read_bytes())
        profile["questions_sha256"] = digest((profiles / f"{role}.jsonl").read_bytes())
        write_json(path, profile)
        split[f"{role}_profile_sha256"] = digest(path.read_bytes())
    write_json(profiles / "split.json", split)


def test_split_and_release_guard(review_inputs: tuple[Path, Corpus]) -> None:
    root, corpus = review_inputs
    path = root / "profiles/split.json"
    report = validate_split(corpus, path)
    assert report["development_cases"] == report["holdout_cases"] == 30
    assert report["holdout_model_evaluation_performed"] is False
    _, dev, holdout = split_profiles(path)
    assert dataset_role(dev, path, "development") == "development"
    with pytest.raises(ValueError, match="purpose release"):
        dataset_role(holdout, path, "development")
    assert dataset_role(holdout, path, "release") == "holdout"


@pytest.mark.parametrize("damage", ["bytes", "id", "question", "path"])
def test_split_rejects_drift_and_leakage(
    review_inputs: tuple[Path, Corpus],
    damage: str,
) -> None:
    root, corpus = review_inputs
    profiles = root / "profiles"
    path = profiles / "holdout.jsonl"
    dev = [read_json(x) for x in (profiles / "dev.jsonl").read_bytes().splitlines()]
    held = [read_json(x) for x in path.read_bytes().splitlines()]
    if damage == "bytes":
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        if damage == "id":
            held[0]["id"] = dev[0]["id"]
        elif damage == "question":
            held[0]["question"] = dev[0]["question"].upper() + "!!!"
        else:
            held[0]["evidence"] = deepcopy(dev[0]["evidence"])
        path.write_bytes(("\n".join(json.dumps(x) for x in held) + "\n").encode())
        rebind_profiles(root)
    with pytest.raises(ValueError):
        validate_split(corpus, profiles / "split.json")


def test_packet_is_reproducible_unlabelled_and_view_blinded(
    review_inputs: tuple[Path, Corpus],
) -> None:
    root, corpus = review_inputs
    first, second = packet(root, corpus), packet(root, corpus, "copy")
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    labels, state = validate_packet(first)
    assert state["completed"] == 0 and state["pending"] == 20
    assert not state["ready_for_agreement_audit"] and not state["calibrated"]
    assert all(x.faithfulness is None and x.relevance is None for x in labels.labels)
    view = (first / "faithfulness.md").read_text()
    assert "Synthetic dev locating question" not in view and "Synthetic reference" not in view
    assert "Synthetic judge reason" not in "".join(p.read_text() for p in first.iterdir())


def test_pending_human_review_blocks_audit(review_inputs: tuple[Path, Corpus]) -> None:
    root, corpus = review_inputs
    with pytest.raises(ValueError, match="pending"):
        agreement_audit(packet(root, corpus), root / "results.jsonl")


@pytest.mark.parametrize(
    "damage", ["score", "boolean", "duplicate", "item", "packet", "reference", "timestamp"]
)
def test_invalid_labels_rejected(review_inputs: tuple[Path, Corpus], damage: str) -> None:
    root, corpus = review_inputs
    target = packet(root, corpus)
    path = target / "labels.json"
    labels = read_json(path.read_bytes())
    if damage == "score":
        labels["labels"][0]["faithfulness"] = 3
    elif damage == "boolean":
        labels["labels"][0]["faithfulness"] = True
    elif damage == "duplicate":
        labels["labels"][1] = labels["labels"][0]
    elif damage == "item":
        labels["labels"][0]["item_sha256"] = "f" * 64
    elif damage == "packet":
        labels["packet_id"] = "f" * 64
    elif damage == "reference":
        labels["labels"][0]["reference_issue"] = True
    else:
        labels["reviewed_at"] = "2026-10-19T12:00:00"
    write_json(path, labels)
    with pytest.raises(ValueError):
        validate_packet(target)


@pytest.mark.parametrize(
    "name",
    ["items.jsonl", "rubric.md", "faithfulness.md", "relevance.md", "identity", "provenance"],
)
def test_packet_integrity_including_provenance(
    review_inputs: tuple[Path, Corpus],
    name: str,
) -> None:
    root, corpus = review_inputs
    target = packet(root, corpus)
    if name in ("identity", "provenance"):
        path = target / "packet.json"
        data = read_json(path.read_bytes())
        if name == "identity":
            data["identity"]["source_commit_sha"] = "f" * 40
        else:
            data["runtime_manifest_sha256"] = "f" * 64
        write_json(path, data)
    else:
        path = target / name
        path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(ValueError):
        validate_packet(target)


def synthetic_complete_labels(target: Path, *, attest: bool) -> None:
    """Synthetic scores exercise audit mechanics; never treat these as human evidence."""
    path = target / "labels.json"
    data = read_json(path.read_bytes())
    for label in data["labels"]:
        label.update(
            faithfulness=2,
            relevance=2,
            faithfulness_reason="Synthetic test only.",
            relevance_reason="Synthetic test only.",
        )
    if attest:
        data.update(
            label_origin="human",
            annotator="synthetic-test-only",
            reviewed_at="2026-10-19T12:00:00Z",
        )
    write_json(path, data)


def test_completed_synthetic_audit_does_not_calibrate(review_inputs: tuple[Path, Corpus]) -> None:
    root, corpus = review_inputs
    target = packet(root, corpus)
    synthetic_complete_labels(target, attest=True)
    audit = agreement_audit(target, root / "results.jsonl")
    assert audit["summary"]["faithfulness"]["exact_agreement"] == 1.0
    assert audit["summary"]["relevance"]["mean_absolute_error"] == 0.0
    assert audit["calibrated"] is False and audit["release_threshold_approved"] is False
    raw = (root / "results.jsonl").read_bytes().replace(b"Synthetic answer", b"Changed answer")
    (root / "results.jsonl").write_bytes(raw)
    with pytest.raises(ValueError, match="differ"):
        agreement_audit(target, root / "results.jsonl")


def test_scores_without_attestation_do_not_unlock_audit(review_inputs: tuple[Path, Corpus]) -> None:
    root, corpus = review_inputs
    target = packet(root, corpus)
    synthetic_complete_labels(target, attest=False)
    _, state = validate_packet(target)
    assert state["completed"] == 20 and not state["ready_for_agreement_audit"]
    with pytest.raises(ValueError, match="attestation"):
        agreement_audit(target, root / "results.jsonl")


def test_crlf_input_preserves_packet_identity(review_inputs: tuple[Path, Corpus]) -> None:
    root, corpus = review_inputs
    first = packet(root, corpus)
    path = root / "results.jsonl"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    second = packet(root, corpus, "crlf")
    assert (
        read_json((first / "packet.json").read_bytes())["packet_id"]
        == (read_json((second / "packet.json").read_bytes())["packet_id"])
    )


def test_pending_cli_and_existing_packet_preserves_labels(
    review_inputs: tuple[Path, Corpus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, corpus = review_inputs
    target = packet(root, corpus)
    before = (target / "labels.json").read_bytes()
    monkeypatch.setattr(
        "sys.argv", ["human-review", "validate", "--packet", str(target), "--require-complete"]
    )
    assert human_review.main() == 3
    with pytest.raises(FileExistsError):
        packet(root, corpus)
    assert (target / "labels.json").read_bytes() == before


def test_runner_guards_holdout_before_loading_any_live_client(
    review_inputs: tuple[Path, Corpus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = review_inputs
    registry = root / "profiles/split.json"
    original = dataset_role
    monkeypatch.setattr(
        run, "dataset_role", lambda profile, path, purpose: original(profile, registry, purpose)
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "evals.run",
            "--manifest",
            str(root / "missing-index.json"),
            "--profile",
            str(root / "profiles/holdout.json"),
        ],
    )
    with pytest.raises(ValueError, match="purpose release"):
        run.main()


def test_local_preparation_acceptance_preserves_baseline(
    review_inputs: tuple[Path, Corpus],
) -> None:
    from scripts.check_dataset_review import check

    root, corpus = review_inputs
    baseline = root / "baseline"
    baseline.mkdir()
    (baseline / "results.jsonl").write_bytes((root / "results.jsonl").read_bytes())
    (baseline / "dataset.jsonl").write_bytes((root / "profiles/dev.jsonl").read_bytes())
    rows = [read_json(line) for line in (baseline / "results.jsonl").read_bytes().splitlines()]
    index = IndexManifest(
        repo=corpus.repo,
        commit_sha=corpus.commit_sha,
        corpus_version=corpus.version,
        corpus_sha256=corpus.sha256,
        chunk_count=len(corpus.chunks),
        embeddings={"backend": "synthetic-test-only"},
        dimension=3,
        index_version=rows[0]["response"]["index_version"],
        collection=f"copilot_{corpus.repo}_{rows[0]['response']['index_version'][:24]}",
    )
    write_json(
        baseline / "version-manifest.json",
        {
            "dataset_sha256": digest((baseline / "dataset.jsonl").read_bytes()),
            "dataset_name": "synthetic-dev",
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
                "rubric_version": "synthetic-v1",
                "rubric_sha256": "c" * 64,
                "calibrated": False,
                "same_model_as_generator": True,
            },
        },
    )
    before = {path.name: path.read_bytes() for path in baseline.iterdir()}
    output = root / "acceptance"
    check(
        baseline,
        root / "corpora",
        output,
        split_path=root / "profiles/split.json",
        selection=root / "selection.json",
    )
    assert before == {path.name: path.read_bytes() for path in baseline.iterdir()}
    _, state = validate_packet(output / "human-review")
    assert state["pending"] == 20 and not state["ready_for_agreement_audit"]
    metadata = read_json((output / "human-review/packet.json").read_bytes())
    assert metadata["declared_judge_identity"]["model"] == "synthetic-test-only"
    assert metadata["runtime_manifest_sha256"] == digest(
        (baseline / "version-manifest.json").read_bytes()
    )
