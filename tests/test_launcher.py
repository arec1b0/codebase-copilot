"""Bootstrap contracts with declared fake services, plus real Git and process checks."""

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest

from app.main import SERVICE_VERSION
from app.prompt import PROMPT_SHA256, PROMPT_VERSION
from evals.contracts import EvalCase, Evidence
from evals.datasets import read_profile
from indexing.config import ROOT
from indexing.corpus import Corpus
from indexing.store import IndexManifest
from ingestion.chunking import chunk_source
from scripts import run_repository as launcher


class FakeProcess:
    """Explicit fake; no external process is terminated by orchestration tests."""

    def poll(self) -> int | None:
        return None

    def wait(self) -> int:
        return 0


@pytest.mark.parametrize("missing", ["git", "docker", "ollama"])
def test_missing_prerequisite_fails_before_starting_services(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.setattr(shutil, "which", lambda command: None if command == missing else command)
    with pytest.raises(launcher.StartupError, match=f"{missing} is required"):
        launcher.check_prerequisites()


def test_occupied_api_port_fails_before_docker_inspection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda command: command)

    def no_inspection(*args: object) -> str:
        raise AssertionError("Occupied API port must fail before Docker inspection.")

    monkeypatch.setattr(launcher, "output", no_inspection)
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 8000))
            listener.listen()
        except OSError:
            pass  # A pre-existing listener also satisfies the occupied-port scenario.
        with pytest.raises(launcher.StartupError, match="Port 8000 is occupied"):
            launcher.check_prerequisites()


@pytest.mark.parametrize("failure", ["version", "not-ready"])
def test_api_readiness_rejects_old_api_and_dependency_timeout(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(
                200, json={"version": "old" if failure == "version" else SERVICE_VERSION}
            )
        return httpx.Response(503, json={"error": "not_ready"})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    with pytest.raises(launcher.StartupError):
        launcher.wait_for_api(cast(subprocess.Popen[bytes], FakeProcess()), timeout=0)


def test_infrastructure_startup_waits_without_restart_or_forced_image_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    waited: list[tuple[str, str, str]] = []
    values = {
        "POSTGRES_PORT": "15432",
        "QDRANT_PORT": "6333",
        "PHOENIX_PORT": "6006",
        "QDRANT_API_KEY": "explicit-test-key",
    }
    monkeypatch.setattr(launcher, "initialize_environment", lambda: None)
    monkeypatch.setattr(launcher, "load_environment", lambda: values)
    monkeypatch.setattr(launcher, "COMPOSE", ["docker", "compose"])
    monkeypatch.setattr(launcher, "run", lambda arguments, **kwargs: calls.append(arguments))
    monkeypatch.setattr(launcher, "wait_until_ready", lambda q, p, k: waited.append((q, p, k)))
    assert launcher.start_infrastructure() == values
    assert calls == [
        ["docker", "compose", "config", "--quiet"],
        ["docker", "compose", "up", "-d", "--pull", "missing", "--wait", "--wait-timeout", "180"],
    ]
    assert waited == [("http://127.0.0.1:6333", "http://127.0.0.1:6006", "explicit-test-key")]


@pytest.mark.parametrize("failure", [None, "prepare", "ready", "query", "interrupt"])
@pytest.mark.parametrize("own_model", [False, True])
def test_launcher_orders_bootstrap_and_cleans_up_only_owned_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str | None,
    own_model: bool,
) -> None:
    profile = read_profile(ROOT / "evals/datasets/kubesentiment/profile.json")
    events: list[str] = []
    api, model = FakeProcess(), FakeProcess()
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "read_profile", lambda path: profile)
    monkeypatch.setattr(launcher, "check_prerequisites", lambda: "http://127.0.0.1:11434")

    def infrastructure() -> dict[str, str]:
        events.append("infrastructure")
        return {"PHOENIX_PORT": "6006"}

    def source(*args: object) -> None:
        events.append("source")

    def ensure(*args: object) -> FakeProcess | None:
        events.append("model")
        return model if own_model else None

    def prepare(arguments: list[str], **kwargs: object) -> None:
        events.append("prepare")
        assert "--download-models" in arguments and "--reuse-index" in arguments
        if failure == "prepare":
            raise launcher.StartupError("Injected preparation failure")
        pointer = tmp_path / "artifacts/repository-indexes" / f"{profile.name}.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(json.dumps({"index_manifest": str(tmp_path / "manifest.json")}))

    def spawn(arguments: list[str], env: dict[str, str]) -> FakeProcess:
        events.append("api")
        assert env["COPILOT_TRACING"] == "1"
        assert env["COPILOT_INDEX_MANIFEST"] == str(tmp_path / "manifest.json")
        assert "uvicorn" in arguments and arguments[-1] == "8000"
        return api

    def ready(*args: object) -> None:
        events.append("ready")
        if failure == "ready":
            raise launcher.StartupError("Injected readiness failure")
        if failure == "interrupt":
            raise KeyboardInterrupt

    def verify(*args: object) -> Path:
        events.append("query")
        if failure == "query":
            raise launcher.StartupError("Injected query failure")
        return tmp_path / "evidence"

    def stop(process: object) -> None:
        if process is not None:
            events.append("stop-api" if process is api else "stop-model")

    monkeypatch.setattr(launcher, "start_infrastructure", infrastructure)
    monkeypatch.setattr(launcher, "prepare_source", source)
    monkeypatch.setattr(launcher, "ensure_ollama", ensure)
    monkeypatch.setattr(launcher, "run", prepare)
    monkeypatch.setattr(launcher, "load_manifest", lambda path: object())
    monkeypatch.setattr(launcher, "spawn", spawn)
    monkeypatch.setattr(launcher, "wait_for_api", ready)
    monkeypatch.setattr(launcher, "verify_query", verify)
    monkeypatch.setattr(launcher, "stop_owned", stop)
    monkeypatch.setattr("sys.argv", ["launcher", "--check-only"])
    if failure is None:
        launcher.main()
    else:
        expected = KeyboardInterrupt if failure == "interrupt" else launcher.StartupError
        with pytest.raises(expected):
            launcher.main()
    assert events[:4] == ["infrastructure", "source", "model", "prepare"]
    assert ("stop-api" in events) == (failure != "prepare")
    assert ("stop-model" in events) == own_model
    assert ("ONE COMMAND ACCEPTANCE PASSED" in capsys.readouterr().out) == (failure is None)


@pytest.mark.parametrize(
    "already_running,fail_pull", [(True, False), (False, False), (False, True)]
)
def test_ollama_bootstrap_download_and_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, already_running: bool, fail_pull: bool
) -> None:
    process = FakeProcess()
    events: list[str] = []
    installed = already_running
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if not already_running and calls == 1:
            raise httpx.ConnectError("Explicit simulated absent daemon", request=request)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        models = [{"name": launcher.MODEL, "digest": "a" * 64}] if installed else []
        return httpx.Response(200, json={"models": models})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(launcher, "ROOT", tmp_path)

    def spawn(*args: object, **kwargs: object) -> FakeProcess:
        events.append("serve")
        return process

    def pull(arguments: list[str], **kwargs: object) -> None:
        nonlocal installed
        assert arguments == ["ollama", "pull", launcher.MODEL]
        assert kwargs["env"] == {"OLLAMA_HOST": "http://127.0.0.1:11434"}
        events.append("pull")
        if fail_pull:
            raise launcher.StartupError("Injected download failure")
        installed = True

    monkeypatch.setattr(launcher, "spawn", spawn)
    monkeypatch.setattr(launcher, "run", pull)
    monkeypatch.setattr(launcher, "stop_owned", lambda p: events.append("stop") if p else None)
    if fail_pull:
        with pytest.raises(launcher.StartupError, match="download"):
            launcher.ensure_ollama(
                "http://127.0.0.1:11434", {"OLLAMA_HOST": "http://127.0.0.1:11434"}
            )
        assert events == ["serve", "pull", "stop"]
    else:
        result = launcher.ensure_ollama(
            "http://127.0.0.1:11434", {"OLLAMA_HOST": "http://127.0.0.1:11434"}
        )
        assert result is (None if already_running else cast(subprocess.Popen[bytes], process))
        assert events == ([] if already_running else ["serve", "pull"])


def git(directory: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(directory),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def test_source_clone_and_missing_commit_fetch_preserve_dirty_worktree(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "--initial-branch=main")
    (upstream / "a.py").write_text("x = 1\n")
    git(upstream, "add", ".")
    git(upstream, "commit", "-m", "First")
    pinned = git(upstream, "rev-parse", "HEAD")
    (upstream / "a.py").write_text("x = 2\n")
    git(upstream, "commit", "-am", "Second")
    # Local Git transport substitutes for the network only in this explicit fixture.
    profile = read_profile(ROOT / "evals/datasets/kubesentiment/profile.json").model_copy(
        update={"source_url": upstream.as_uri(), "commit_sha": pinned}
    )
    fresh = tmp_path / "fresh"
    launcher.prepare_source(fresh, profile)
    assert not (fresh / "a.py").exists()  # no upstream checkout or code execution
    assert git(fresh, "cat-file", "-t", pinned) == "commit"

    shallow = tmp_path / "shallow"
    git(tmp_path, "clone", "--depth", "1", upstream.as_uri(), str(shallow))
    (shallow / "a.py").write_text("dirty = True\n")
    (shallow / "untracked.py").write_text("private = True\n")
    before = git(shallow, "status", "--porcelain")
    head = git(shallow, "rev-parse", "HEAD")
    launcher.prepare_source(shallow, profile)
    assert git(shallow, "status", "--porcelain") == before
    assert git(shallow, "rev-parse", "HEAD") == head
    assert (shallow / "a.py").read_text() == "dirty = True\n"
    assert (shallow / "untracked.py").read_text() == "private = True\n"
    assert git(shallow, "cat-file", "-t", pinned) == "commit"
    nested = shallow / "nested"
    nested.mkdir()
    with pytest.raises(launcher.StartupError, match="root of its own"):
        launcher.prepare_source(nested, profile)


@pytest.mark.parametrize("damage", [None, "version", "request", "citation", "trace", "abstain"])
def test_live_query_probe_checks_identity_citations_and_actual_collector_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str | None
) -> None:
    chunks, _ = chunk_source(
        text="def increment():\n    return 1\n",
        repo="fixture",
        commit="a" * 40,
        path="a.py",
        language="python",
        max_chars=600,
    )
    chunk = chunks[0]
    corpus = Corpus("fixture", "a" * 40, "b" * 64, "c" * 64, chunks)
    index = IndexManifest(
        repo=corpus.repo,
        commit_sha=corpus.commit_sha,
        corpus_version=corpus.version,
        corpus_sha256=corpus.sha256,
        chunk_count=1,
        embeddings={"explicit_test_backend": True},
        dimension=3,
        index_version="d" * 64,
        collection="explicit-test",
    )
    case = EvalCase(
        id="fixture-01",
        category="locating",
        question="Where is increment?",
        language="python",
        reference="a.py",
        evidence=[Evidence(path="a.py", start_line=1, end_line=2)],
    )
    request_id, trace_id, root_id = str(uuid4()), uuid4().hex, "b" * 16
    citation = {
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
    body = {
        "request_id": request_id,
        "trace_id": trace_id,
        "status": "answered",
        "answer": "The function is in a.py. [S1]",
        "citations": [citation],
        "model": launcher.MODEL,
        "model_revision": "sha256:" + "e" * 64,
        "model_backend_version": "ollama:test",
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
        "index_version": index.index_version,
        "corpus_version": corpus.version,
        "repo": corpus.repo,
        "commit_sha": corpus.commit_sha,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "retrieval_ms": 1,
        "generation_ms": 2,
        "model_ttft_ms": 1,
        "total_ms": 3,
    }
    if damage == "version":
        body["index_version"] = "0" * 64
    if damage == "citation":
        citation["path"] = "invented.py"
    if damage == "abstain":
        body.update(status="insufficient_context", citations=[])
    events: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": launcher.MODEL, "digest": "e" * 64}]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        if request.url.path == "/query":
            return httpx.Response(
                200,
                json=body,
                headers={
                    "X-Request-ID": "wrong" if damage == "request" else request_id,
                    "X-Trace-ID": trace_id,
                },
            )
        assert request.url.path.endswith("/spans")
        assert request.url.params["trace_id"] == trace_id
        spans = [
            {
                "name": name,
                "context": {"trace_id": trace_id, "span_id": root_id if n == 0 else f"{n:016x}"},
                "parent_id": None if n == 0 else root_id,
                "attributes": {"copilot.request_id": "wrong" if damage == "trace" else request_id}
                if n == 0
                else {},
            }
            for n, name in enumerate(
                ["POST /query", "retrieval", "rerank", "generation", "citation_validation"]
            )
        ]
        return httpx.Response(200, json={"data": spans, "next_cursor": None})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "load_corpus", lambda path: corpus)
    monkeypatch.setattr(launcher, "load_repository_dataset", lambda *args: ([case], "f" * 64))
    monkeypatch.setattr(launcher, "container_identities", lambda: {"test_only": True})
    monkeypatch.setattr(launcher, "manifest", lambda *args: {"test_only": True})
    if damage is not None:
        with pytest.raises((launcher.StartupError, ValueError)):
            launcher.verify_query(
                index, tmp_path / "profile.json", "http://ollama", {"PHOENIX_PORT": "6006"}
            )
        assert not list(tmp_path.rglob("version-manifest.json"))
    else:
        directory = launcher.verify_query(
            index, tmp_path / "profile.json", "http://ollama", {"PHOENIX_PORT": "6006"}
        )
        assert (directory / "trace.json").is_file() and (directory / "response.json").is_file()
        assert (directory / "version-manifest.json").is_file()
        assert sum(path.endswith("/spans") for path in events) == 1


def test_real_uvicorn_readiness_and_graceful_owned_process_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "shutdown.txt"
    fixture = tmp_path / "launcher_fixture.py"
    fixture.write_text(
        "from fastapi import FastAPI\nfrom contextlib import asynccontextmanager\n"
        "from pathlib import Path\n@asynccontextmanager\nasync def lifespan(app):\n"
        f"    yield\n    Path({str(marker)!r}).write_text('closed')\n"
        "app=FastAPI(lifespan=lifespan)\n@app.get('/healthz')\ndef health():\n"
        f"    return {{'version':{SERVICE_VERSION!r}}}\n"
        "@app.get('/readyz')\ndef ready():\n    return {'status':'ready'}\n",
        encoding="utf-8",
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(launcher, "API_URL", f"http://127.0.0.1:{port}")
    process = launcher.spawn(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "launcher_fixture:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        {**os.environ, "PYTHONPATH": str(tmp_path)},
        log=tmp_path / "uvicorn.log",
    )
    try:
        launcher.wait_for_api(process, timeout=15)
    finally:
        launcher.stop_owned(process)
    assert process.poll() is not None and marker.read_text() == "closed"
    launcher.stop_owned(process)  # repeated cleanup is harmless
