"""Metrics, source binding, judge protocol, and Phoenix trace export contracts."""

import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.contracts import ModelIdentity, QueryResponse, TokenUsage
from app.main import SERVICE_VERSION
from app.model import OllamaModel
from app.prompt import PROMPT_SHA256, PROMPT_VERSION
from evals import run
from evals.contracts import EvalCase, Evidence, JudgeAssessment, retrieval_metrics
from evals.datasets import DatasetProfile, load_repository_dataset, source_layout
from evals.judge import assess
from evals.phoenix import fetch_trace
from evals.run import load_dataset, percentile, summarize
from indexing.config import ROOT
from indexing.corpus import Corpus
from indexing.store import IndexManifest, RetrievalHit
from ingestion.chunking import chunk_source
from ingestion.models import IngestionConfig, LanguageName


def demo_corpus() -> Corpus:
    chunks = []
    for path in (ROOT / "examples/demo-repo").iterdir():
        languages: dict[str, LanguageName] = {
            ".py": "python",
            ".go": "go",
            ".cpp": "cpp",
            ".md": "markdown",
        }
        language = languages[path.suffix]
        # Parsing all fixtures binds range labels to the actual saved source.
        parsed, _ = chunk_source(
            text=path.read_text(),
            repo="demo",
            commit="a" * 40,
            path=path.name,
            language=language,
            max_chars=4000,
        )
        chunks.extend(parsed)
    return Corpus("demo", "a" * 40, "b" * 64, "c" * 64, chunks)


def test_dataset_has_source_bound_labels_and_all_five_categories() -> None:
    cases, version = load_dataset(demo_corpus())
    assert len(cases) == 30 and len(version) == 64
    assert len({case.category for case in cases}) == 5


def repository_profile(directory: Path, corpus: Corpus) -> Path:
    cases, _ = load_dataset(corpus)
    quoted = []
    for case in cases:
        evidence = []
        for target in case.evidence:
            chunk = next(
                c
                for c in corpus.chunks
                if c.path == target.path
                and c.start_line <= target.start_line
                and c.end_line >= target.end_line
            )
            quote = "\n".join(
                chunk.text.split("\n")[
                    target.start_line - chunk.start_line : target.end_line - chunk.start_line + 1
                ]
            )
            evidence.append(target.model_copy(update={"quote": quote}))
        quoted.append(case.model_copy(update={"evidence": evidence}))
    raw = ("\n".join(case.model_dump_json() for case in quoted) + "\n").encode()
    (directory / "questions.jsonl").write_bytes(raw)
    profile = DatasetProfile(
        name="fixture-v1",
        repo=corpus.repo,
        source_url="https://github.com/example/fixture",
        commit_sha=corpus.commit_sha,
        ingestion=IngestionConfig(),
        questions_file="questions.jsonl",
        questions_sha256=hashlib.sha256(raw).hexdigest(),
        source_layout_sha256=source_layout(corpus.chunks),
        case_count=30,
        annotation_origin="assistant-authored-from-source",
    )
    path = directory / "profile.json"
    path.write_text(profile.model_dump_json(), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "damage", ["commit", "layout", "bytes", "quote", "missing", "range", "count"]
)
def test_repository_dataset_rejects_changed_sources_or_labels(tmp_path: Path, damage: str) -> None:
    corpus = demo_corpus()
    path = repository_profile(tmp_path, corpus)
    cases, digest = load_repository_dataset(corpus, path)
    assert len(cases) == 30 and len(digest) == 64
    profile = json.loads(path.read_text())
    if damage in ("commit", "layout"):
        field = "commit_sha" if damage == "commit" else "source_layout_sha256"
        profile[field] = "0" * len(profile[field])
    else:
        data_path = tmp_path / "questions.jsonl"
        data = [json.loads(line) for line in data_path.read_text().splitlines()]
        if damage == "quote":
            data[0]["evidence"][0]["quote"] = "invented source statement"
        if damage == "missing":
            data[0]["evidence"][0]["quote"] = None
        if damage == "range":
            # The quote still exists in this chunk, but not at the asserted line.
            data[0]["evidence"][0]["start_line"] = 1
            data[0]["evidence"][0]["end_line"] = 1
        if damage == "count":
            data.pop()
        raw = ("\n".join(json.dumps(row) for row in data) + "\n").encode()
        data_path.write_bytes(raw)
        if damage != "bytes":
            profile["questions_sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError):
        load_repository_dataset(corpus, path)


@pytest.mark.parametrize("mode", ["validate-only", "oversized", "index"])
def test_repository_preparation_preflights_before_index_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: str
) -> None:
    from indexing.corpus import IndexingError
    from ingestion.pipeline import CorpusResult
    from scripts import prepare_repository as prepare

    corpus = demo_corpus()
    profile_path = repository_profile(tmp_path, corpus)
    calls = []

    class Backend:
        def check_input(self, text: str) -> None:
            calls.append("token-check")
            if mode == "oversized":
                raise IndexingError("Too many tokens")

    class Client:
        def close(self) -> None:
            calls.append("closed")

    def connect(*, local: bool) -> Client:
        calls.append("connected")
        return Client()

    def ingest(*args: object, **kwargs: object) -> CorpusResult:
        assert kwargs["revision"] == corpus.commit_sha
        assert kwargs["repo_id"] == corpus.repo
        return CorpusResult(
            tmp_path / "corpus", corpus.commit_sha, corpus.version, 4, len(corpus.chunks)
        )

    def index(*args: object, **kwargs: object) -> tuple[None, Path]:
        calls.append("indexed")
        return None, tmp_path / "manifest.json"

    monkeypatch.setattr(prepare, "ROOT", tmp_path)
    monkeypatch.setattr(prepare, "ingest", ingest)
    monkeypatch.setattr(prepare, "load_corpus", lambda path: corpus)
    monkeypatch.setattr(prepare, "CpuEmbeddings", lambda *args, **kwargs: Backend())
    monkeypatch.setattr(prepare, "connect", connect)
    monkeypatch.setattr(prepare, "index_corpus", index)
    arguments = [
        "prepare_repository",
        "--repository",
        str(tmp_path),
        "--profile",
        str(profile_path),
    ]
    if mode == "validate-only":
        arguments.append("--validate-only")
    monkeypatch.setattr("sys.argv", arguments)
    if mode == "oversized":
        with pytest.raises(ValueError, match="token budget exceeded"):
            prepare.main()
    else:
        prepare.main()
    pointer = tmp_path / "artifacts/repository-indexes/fixture-v1.json"
    if mode == "index":
        assert calls[-3:] == ["connected", "indexed", "closed"]
        assert json.loads(pointer.read_text())["index_manifest"] == str(tmp_path / "manifest.json")
        assert "REPOSITORY PREPARATION PASSED" in capsys.readouterr().out
    else:
        assert "connected" not in calls and not pointer.exists()
        assert "REPOSITORY PREPARATION PASSED" not in capsys.readouterr().out


def test_retrieval_metrics_use_complete_ranges_and_include_misses() -> None:
    corpus = demo_corpus()
    hit = RetrievalHit(
        index_version="d" * 64,
        corpus_version=corpus.version,
        score=1,
        chunk=next(c for c in corpus.chunks if c.path == "calculator.py" and c.symbol == "add"),
    )
    case = EvalCase(
        id="example-01",
        category="dependency",
        question="Counter and add?",
        language="python",
        reference="Both symbols exist.",
        evidence=[
            Evidence(path="calculator.py", start_line=4, end_line=6),
            Evidence(path="calculator.py", start_line=9, end_line=17),
        ],
    )
    assert retrieval_metrics(case, [hit]) == {"hit": 1, "recall": 0.5, "reciprocal_rank": 1}
    assert retrieval_metrics(case, []) == {"hit": 0, "recall": 0, "reciprocal_rank": 0}
    assert percentile([10, 20, 30, 40], 0.5) == 20
    assert percentile([10, 20, 30, 40], 0.95) == 40
    assert percentile([], 0.95) is None
    assert summarize([{"error": {"detail": "test failure"}}])["errors"] == 1


def test_judge_is_pinned_and_uses_native_structured_output() -> None:
    corpus = demo_corpus()
    case = load_dataset(corpus)[0][0]
    body = QueryResponse.model_validate(
        {
            "request_id": "00000000-0000-0000-0000-000000000001",
            "status": "answered",
            "answer": "The Python add function returns left + right. [S1]",
            "citations": [],
            "model": "qwen2.5-coder:3b",
            "model_revision": "sha256:" + "e" * 64,
            "model_backend_version": "ollama:test",
            "prompt_version": "test",
            "prompt_sha256": "f" * 64,
            "index_version": "d" * 64,
            "corpus_version": corpus.version,
            "repo": corpus.repo,
            "commit_sha": corpus.commit_sha,
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "retrieval_ms": 1,
            "generation_ms": 2,
            "model_ttft_ms": 1,
            "total_ms": 3,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": body.model, "digest": "e" * 64}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        payload = json.loads(request.content)
        assert payload["stream"] is False and payload["format"]["type"] == "object"
        return httpx.Response(
            200,
            json={
                "model": body.model,
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "faithfulness": 1,
                            "relevance": 2,
                            "faithfulness_reason": "No cited text supplied.",
                            "relevance_reason": "Answers the task.",
                        }
                    )
                },
                "prompt_eval_count": 100,
                "eval_count": 40,
            },
        )

    model = OllamaModel(
        "http://ollama",
        body.model,
        httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler)),
    )
    try:
        result, usage = assess(model, model.identity(), case, body, {})
        assert result.relevance == 2 and usage.output_tokens == 40
    finally:
        model.close()


def test_phoenix_exports_only_matching_complete_query_tree() -> None:
    trace_id, root_id = "a" * 32, "b" * 16
    spans = [
        {
            "name": name,
            "context": {
                "trace_id": trace_id,
                "span_id": root_id if name == "POST /query" else f"{number:016x}",
            },
            "parent_id": None if name == "POST /query" else root_id,
            "attributes": {"copilot.request_id": "request-1"} if name == "POST /query" else {},
        }
        for number, name in enumerate(
            ["POST /query", "retrieval", "rerank", "generation", "citation_validation"]
        )
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["trace_id"] == trace_id
        return httpx.Response(200, json={"data": spans, "next_cursor": None})

    with httpx.Client(base_url="http://phoenix", transport=httpx.MockTransport(handler)) as client:
        exported = fetch_trace(client, trace_id, "request-1")
        assert len(exported["spans"]) == 5
        with pytest.raises(ValueError, match="request ID"):
            fetch_trace(client, trace_id, "other-request")
        spans.append(spans[1])
        with pytest.raises(ValueError, match="duplicate"):
            fetch_trace(client, trace_id, "request-1")


@pytest.mark.parametrize("fail_one_case", [False, True])
@pytest.mark.parametrize("use_profile", [False, True])
def test_baseline_cli_exports_reports_and_counts_failed_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_one_case: bool, use_profile: bool
) -> None:
    """Exercise the complete CLI with explicitly synthetic external services."""
    corpus = demo_corpus()
    cases, _ = load_dataset(corpus)
    original_root = ROOT
    shutil.copytree(original_root / "examples", tmp_path / "examples")
    (tmp_path / "evals").mkdir()
    shutil.copyfile(original_root / "evals/dataset.jsonl", tmp_path / "evals/dataset.jsonl")
    index = IndexManifest(
        repo=corpus.repo,
        commit_sha=corpus.commit_sha,
        corpus_version=corpus.version,
        corpus_sha256=corpus.sha256,
        chunk_count=len(corpus.chunks),
        embeddings={"test_only": True},
        dimension=3,
        index_version="d" * 64,
        collection="test-only",
    )
    identity = ModelIdentity(
        model="qwen2.5-coder:3b", revision="sha256:" + "e" * 64, backend_version="ollama:test"
    )
    captured_traces: dict[str, list[dict[str, object]]] = {}
    calls = 0

    class Dependency:
        def close(self) -> None:
            pass

        def identity(self) -> ModelIdentity:
            return identity

        def check(self) -> None:
            pass

        def retrieve(self, question: str, top_k: int, language: object) -> list[RetrievalHit]:
            case = next(case for case in cases if case.question == question)
            chunks = [
                chunk
                for chunk in corpus.chunks
                if any(
                    chunk.path == evidence.path
                    and chunk.start_line <= evidence.start_line
                    and chunk.end_line >= evidence.end_line
                    for evidence in case.evidence
                )
            ]
            return [
                RetrievalHit(
                    index_version=index.index_version,
                    corpus_version=corpus.version,
                    score=1,
                    chunk=chunk,
                )
                for chunk in chunks[:top_k]
            ]

    dependency = Dependency()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"version": SERVICE_VERSION})
        if request.url.path == "/readyz":
            return httpx.Response(200, json={"status": "ready"})
        if request.url.path.startswith("/v1/projects/"):
            trace_id = request.url.params["trace_id"]
            return httpx.Response(
                200, json={"data": captured_traces[trace_id], "next_cursor": None}
            )
        assert request.url.path == "/query"
        calls += 1
        if fail_one_case and calls == 8:
            return httpx.Response(503, json={"error": "service_busy", "request_id": "test-busy"})
        payload = json.loads(request.content)
        case = next(case for case in cases if case.question == payload["question"])
        hit = dependency.retrieve(case.question, 3, case.language)[0]
        request_id, trace_id = str(uuid4()), uuid4().hex
        chunk = hit.chunk
        root_id = "b" * 16
        captured_traces[trace_id] = [
            {
                "name": name,
                "context": {
                    "trace_id": trace_id,
                    "span_id": root_id if name == "POST /query" else f"{number:016x}",
                },
                "parent_id": None if name == "POST /query" else root_id,
                "attributes": {"copilot.request_id": request_id} if name == "POST /query" else {},
            }
            for number, name in enumerate(
                ["POST /query", "retrieval", "rerank", "generation", "citation_validation"]
            )
        ]
        return httpx.Response(
            200,
            headers={"X-Request-ID": request_id, "X-Trace-ID": trace_id},
            json={
                "request_id": request_id,
                "trace_id": trace_id,
                "status": "answered",
                "answer": case.reference + " [S1]",
                "citations": [
                    {
                        "source_id": "S1",
                        "chunk_id": chunk.chunk_id,
                        "repo": chunk.repo,
                        "commit_sha": chunk.commit_sha,
                        "path": chunk.path,
                        "symbol": chunk.symbol,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                    }
                ],
                "model": identity.model,
                "model_revision": identity.revision,
                "model_backend_version": identity.backend_version,
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": PROMPT_SHA256,
                "index_version": index.index_version,
                "corpus_version": corpus.version,
                "repo": corpus.repo,
                "commit_sha": corpus.commit_sha,
                "usage": {"input_tokens": 100, "output_tokens": 25},
                "retrieval_ms": 1,
                "generation_ms": 2,
                "model_ttft_ms": 1,
                "total_ms": 3,
            },
        )

    original_client = httpx.Client

    def client(*, base_url: str, timeout: int, trust_env: bool) -> httpx.Client:
        return original_client(base_url=base_url, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setattr(run, "dataset_role", lambda *args: "custom")
    monkeypatch.setattr(run, "load_manifest", lambda path: index)
    monkeypatch.setattr(run, "load_corpus", lambda path: corpus)
    monkeypatch.setattr(run, "container_identities", lambda: {"test_only": True})
    monkeypatch.setattr(run, "manifest", lambda *args: {"test_only": True})
    monkeypatch.setattr(run, "OllamaModel", lambda *args: dependency)
    monkeypatch.setattr(run, "connect", lambda: dependency)
    monkeypatch.setattr(run, "CpuEmbeddings", lambda *args, **kwargs: dependency)
    monkeypatch.setattr(run, "QdrantRetriever", lambda *args: dependency)
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(
        run,
        "assess",
        lambda *args: (
            JudgeAssessment(
                faithfulness=2,
                relevance=2,
                faithfulness_reason="Synthetic test.",
                relevance_reason="Synthetic test.",
            ),
            TokenUsage(input_tokens=50, output_tokens=10),
        ),
    )
    arguments = ["evals.run", "--manifest", str(tmp_path / "unused.json")]
    if use_profile:
        arguments.extend(["--profile", str(repository_profile(tmp_path, corpus))])
    monkeypatch.setattr("sys.argv", arguments)
    if fail_one_case:
        with pytest.raises(SystemExit, match="Baseline incomplete"):
            run.main()
    else:
        run.main()
    directory = next((tmp_path / "artifacts/baselines").iterdir())
    summary = json.loads((directory / "summary.json").read_text())
    assert calls == 31 and summary["cases"] == 30
    assert summary["errors"] == int(fail_one_case)
    assert summary["http_successes"] == 30 - int(fail_one_case)
    assert summary["client_end_to_end_ms"]["n"] == 30 - int(fail_one_case)
    assert summary["generation_input_tokens"] == 100 * (30 - int(fail_one_case))
    assert summary["judge_input_tokens"] == 50 * (30 - int(fail_one_case))
    assert len(list((directory / "traces").glob("*.json"))) == 5
    assert len((directory / "results.jsonl").read_text().splitlines()) == 30
    assert len((directory / "errors.jsonl").read_text().splitlines()) == int(fail_one_case)
    assert (directory / "abstentions.jsonl").read_bytes() == b""
    if use_profile:
        assert (directory / "dataset-profile.json").is_file()
        assert (directory / "dataset.jsonl").read_bytes() == (
            tmp_path / "questions.jsonl"
        ).read_bytes()
        versions = json.loads((directory / "version-manifest.json").read_text())
        assert versions["dataset_name"] == summary["dataset_name"] == "fixture-v1"
