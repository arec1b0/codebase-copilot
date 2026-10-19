"""Capture real code hashes, runtime versions, and running container identities."""

import hashlib
import json
import platform
import subprocess
from pathlib import Path

from app.contracts import QueryResponse
from app.main import SERVICE_VERSION
from indexing.config import ROOT
from indexing.store import IndexManifest

SOURCE_DIRS = (
    "app",
    "ingestion",
    "indexing",
    "observability",
    "evals",
    "scripts",
    "tests",
    "deploy",
    "docs",
    "examples",
)
ROOT_FILES = ("pyproject.toml", "uv.lock", "README.md", ".gitignore", ".gitattributes", ".python-version")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    files = [ROOT / name for name in ROOT_FILES]
    for directory in SOURCE_DIRS:
        files.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in sorted(set(files))}


def container_identities() -> dict[str, object]:
    result: dict[str, object] = {}
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "deploy/compose.yaml"),
    ]
    for service in ("postgres", "qdrant", "phoenix"):
        container = subprocess.run(
            [*compose, "ps", "-q", service], capture_output=True, text=True, check=True, timeout=15
        ).stdout.strip()
        if not container or "\n" in container:
            raise ValueError(f"One running {service} container is required.")
        inspected = json.loads(
            subprocess.run(
                ["docker", "inspect", container],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            ).stdout
        )[0]
        image_id = inspected["Image"]
        image = json.loads(
            subprocess.run(
                ["docker", "image", "inspect", image_id],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            ).stdout
        )[0]
        if not image.get("RepoDigests") or not inspected["State"]["Running"]:
            raise ValueError(f"Running image digest is unavailable for {service}.")
        result[service] = {
            "configured_image": inspected["Config"]["Image"],
            "image_id": image_id,
            "repo_digests": image["RepoDigests"],
        }
    return result


def manifest(
    index: IndexManifest, response: QueryResponse, dataset_sha: str, containers: dict[str, object]
) -> dict[str, object]:
    git_sha = None
    dirty = None
    try:
        git_sha = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(ROOT), "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
        )
    except (subprocess.SubprocessError, OSError):
        pass
    hashes = source_hashes()
    return {
        "application_version": SERVICE_VERSION,
        "application_git_sha": git_sha,
        "application_git_dirty": dirty,
        "source_files": hashes,
        "source_tree_sha256": hashlib.sha256(
            json.dumps(hashes, sort_keys=True).encode()
        ).hexdigest(),
        "python": platform.python_version(),
        "uv_lock_sha256": sha256(ROOT / "uv.lock"),
        "source_commit_sha": index.commit_sha,
        "corpus_version": index.corpus_version,
        "index": index.model_dump(),
        "dataset_sha256": dataset_sha,
        "model": response.model,
        "model_revision": response.model_revision,
        "model_backend_version": response.model_backend_version,
        "prompt_version": response.prompt_version,
        "prompt_sha256": response.prompt_sha256,
        "containers": containers,
        "serving_image_digest": None,
        "serving_mode": "native_windows_ollama",
    }
