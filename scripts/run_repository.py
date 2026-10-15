"""Bootstrap the pinned local repository and prove one traced query before serving."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.contracts import QueryResponse
from app.main import SERVICE_VERSION
from app.model import OllamaModel
from app.prompt import PROMPT_SHA256, PROMPT_VERSION
from evals.datasets import DatasetProfile, load_repository_dataset, read_profile
from evals.phoenix import fetch_trace
from evals.versions import container_identities, manifest
from indexing.config import ROOT
from indexing.corpus import load_corpus
from indexing.store import IndexManifest, load_manifest
from scripts.check_infra import COMPOSE, load_environment, wait_until_ready
from scripts.init_env import main as initialize_environment

MODEL = "qwen2.5-coder:3b"
API_URL = "http://127.0.0.1:8000"


class StartupError(RuntimeError):
    """A bootstrap prerequisite or live acceptance condition failed."""


def run(arguments: list[str], *, timeout: int = 300, env: dict[str, str] | None = None) -> None:
    print("Running: " + " ".join(arguments), flush=True)
    result = subprocess.run(arguments, cwd=ROOT, env=env, timeout=timeout, check=False)
    if result.returncode:
        raise StartupError(f"Command failed with exit code {result.returncode}: {arguments[0]}")


def output(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise StartupError(f"Could not inspect {arguments[0]}; check the local prerequisite.")
    return result.stdout.strip()


def check_prerequisites() -> str:
    for command in ("git", "docker", "ollama"):
        if shutil.which(command) is None:
            raise StartupError(f"{command} is required; install the README prerequisites.")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8000))
        except OSError:
            raise StartupError("Port 8000 is occupied. Stop the old API, then retry.") from None
    if output(["docker", "info", "--format", "{{.OSType}}"]).strip() != "linux":
        raise StartupError("Start Docker Desktop with Linux containers.")
    url = os.environ.get("COPILOT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in ("127.0.0.1", "localhost")
        or parsed.port != 11434
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise StartupError("This local launcher requires Ollama at http://127.0.0.1:11434.")
    return url


def start_infrastructure() -> dict[str, str]:
    initialize_environment()
    environment = load_environment()
    run([*COMPOSE, "config", "--quiet"])
    run(
        [*COMPOSE, "up", "-d", "--pull", "missing", "--wait", "--wait-timeout", "180"], timeout=1800
    )
    wait_until_ready(
        f"http://127.0.0.1:{environment['QDRANT_PORT']}",
        f"http://127.0.0.1:{environment['PHOENIX_PORT']}",
        environment["QDRANT_API_KEY"],
    )
    print("PostgreSQL, Qdrant, and Phoenix are ready.", flush=True)
    return environment


def prepare_source(repository: Path, profile: DatasetProfile) -> None:
    if not repository.exists():
        repository.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--no-checkout", "--", profile.source_url, str(repository)])
    root = output(["git", "-C", str(repository), "rev-parse", "--show-toplevel"])
    if Path(root).resolve() != repository.resolve():
        raise StartupError("The source path must be the root of its own Git repository.")
    revision = f"{profile.commit_sha}^{{commit}}"
    found = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "-e", revision],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if found.returncode:
        # Fetch from the profile URL, independent of any existing origin configuration.
        run(["git", "-C", str(repository), "fetch", "--", profile.source_url, profile.commit_sha])
    actual = output(["git", "-C", str(repository), "rev-parse", "--verify", revision])
    if actual != profile.commit_sha:
        raise StartupError("Source commit differs from the pinned profile.")
    print(f"Source commit available: {actual}; working tree preserved.", flush=True)


def spawn(
    arguments: list[str], env: dict[str, str], *, log: Path | None = None
) -> subprocess.Popen[bytes]:
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        flags = 0
    if log is None:
        return subprocess.Popen(arguments, cwd=ROOT, env=env, creationflags=flags)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as stream:
        return subprocess.Popen(
            arguments,
            cwd=ROOT,
            env=env,
            creationflags=flags,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )


def stop_owned(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGINT)
        process.wait(timeout=20)
        return
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def ensure_ollama(url: str, env: dict[str, str]) -> subprocess.Popen[bytes] | None:
    owned = None
    try:
        with httpx.Client(base_url=url, timeout=5, trust_env=False) as client:
            try:
                client.get("/api/tags").raise_for_status()
            except httpx.ConnectError:
                print("Starting the local Ollama server...", flush=True)
                owned = spawn(["ollama", "serve"], env, log=ROOT / "artifacts/launcher/ollama.log")
            deadline = time.monotonic() + 60
            while True:
                if owned is not None and owned.poll() is not None:
                    raise StartupError("Ollama exited; inspect artifacts/launcher/ollama.log.")
                try:
                    response = client.get("/api/tags")
                    response.raise_for_status()
                    tags = response.json()["models"]
                    break
                except httpx.TransportError:
                    if time.monotonic() >= deadline:
                        raise StartupError("Local Ollama startup timed out.") from None
                    time.sleep(0.5)
            if not any(item.get("name") == MODEL for item in tags):
                run(["ollama", "pull", MODEL], timeout=3600, env=env)
        model = OllamaModel(url, MODEL)
        try:
            model.identity()
        finally:
            model.close()
    except BaseException:
        stop_owned(owned)
        raise
    return owned


def wait_for_api(process: subprocess.Popen[bytes], timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=API_URL, timeout=5, trust_env=False) as client:
        while True:
            if process.poll() is not None:
                raise StartupError("The API exited during startup; inspect its console output.")
            try:
                health = client.get("/healthz")
                health.raise_for_status()
                if health.json().get("version") != SERVICE_VERSION:
                    raise StartupError("The API version differs from the launcher sources.")
                client.get("/readyz").raise_for_status()
                return
            except (httpx.TransportError, httpx.HTTPStatusError):
                if time.monotonic() >= deadline:
                    raise StartupError(
                        "API readiness timed out; inspect dependency errors."
                    ) from None
                time.sleep(0.5)


def verify_query(
    index: IndexManifest, profile_path: Path, url: str, environment: dict[str, str]
) -> Path:
    corpus = load_corpus(ROOT / "artifacts/corpora" / index.repo / index.corpus_version)
    cases, dataset_sha = load_repository_dataset(corpus, profile_path)
    directory = ROOT / "artifacts/launcher" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    directory.mkdir(parents=True)
    model = OllamaModel(url, MODEL)
    try:
        identity = model.identity()
        with httpx.Client(base_url=API_URL, timeout=210, trust_env=False) as api:
            response = api.post(
                "/query",
                json={"question": cases[0].question, "language": cases[0].language, "top_k": 3},
            )
            (directory / "response.json").write_bytes(response.content)
            response.raise_for_status()
            body = QueryResponse.model_validate_json(response.content)
            if (
                body.status != "answered"
                or not body.citations
                or body.index_version != index.index_version
                or body.corpus_version != corpus.version
                or body.commit_sha != index.commit_sha
                or body.repo != index.repo
                or body.model != identity.model
                or body.model_revision != identity.revision
                or body.model_backend_version != identity.backend_version
                or body.prompt_version != PROMPT_VERSION
                or body.prompt_sha256 != PROMPT_SHA256
                or response.headers.get("X-Request-ID") != str(body.request_id)
                or response.headers.get("X-Trace-ID") != body.trace_id
            ):
                raise StartupError(
                    "The startup query failed answer/version/request identity checks."
                )
            chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
            for citation in body.citations:
                chunk = chunks.get(citation.chunk_id)
                if chunk is None or any(
                    getattr(citation, key) != getattr(chunk, key)
                    for key in ("repo", "commit_sha", "path", "symbol", "start_line", "end_line")
                ):
                    raise StartupError("The startup citation differs from the pinned source.")
            phoenix = f"http://127.0.0.1:{environment['PHOENIX_PORT']}"
            with httpx.Client(base_url=phoenix, timeout=5, trust_env=False) as client:
                trace = fetch_trace(client, body.trace_id or "", str(body.request_id))
        (directory / "trace.json").write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        versions = manifest(index, body, dataset_sha, container_identities())
        (directory / "version-manifest.json").write_text(
            json.dumps(versions, indent=2) + "\n", encoding="utf-8"
        )
        return directory
    finally:
        model.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Stop owned API/Ollama processes after the live startup probe.",
    )
    args = parser.parse_args()
    profile_path = ROOT / "evals/datasets/kubesentiment/profile.json"
    profile = read_profile(profile_path)
    repository = (args.repository or ROOT / "artifacts/repositories/KubeSentiment").resolve()
    url = check_prerequisites()
    environment = start_infrastructure()
    prepare_source(repository, profile)
    child_env = {
        **os.environ,
        "COPILOT_OLLAMA_URL": url,
        "OLLAMA_HOST": url,
        "COPILOT_TRACING": "1",
    }
    owned_model = None
    api = None
    try:
        owned_model = ensure_ollama(url, child_env)
        run(
            [
                sys.executable,
                "-m",
                "scripts.prepare_repository",
                "--repository",
                str(repository),
                "--profile",
                str(profile_path),
                "--download-models",
                "--reuse-index",
            ],
            timeout=3600,
            env=child_env,
        )
        pointer = ROOT / "artifacts/repository-indexes" / f"{profile.name}.json"
        index_path = Path(json.loads(pointer.read_bytes())["index_manifest"])
        index = load_manifest(index_path)
        child_env["COPILOT_INDEX_MANIFEST"] = str(index_path)
        api = spawn(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            child_env,
        )
        wait_for_api(api)
        evidence = verify_query(index, profile_path, url, environment)
        print(f"Startup evidence: {evidence}", flush=True)
        print("ONE COMMAND ACCEPTANCE PASSED", flush=True)
        if not args.check_only:
            print(
                f"API documentation: {API_URL}/docs; press Ctrl+C to stop owned processes.",
                flush=True,
            )
            if api.wait() != 0:
                raise StartupError("The API process exited with an error.")
    finally:
        stop_owned(api)
        stop_owned(owned_model)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Launcher stopped; Docker data and external Ollama processes are preserved.")
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        httpx.HTTPError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Repository startup failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
