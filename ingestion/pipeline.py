"""Build and atomically publish a versioned JSONL corpus."""

import hashlib
import importlib.metadata
import json
import platform
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ingestion.chunking import chunk_source
from ingestion.git_source import IngestionError, git, list_files, read_blob, resolve_commit
from ingestion.models import Chunk, IngestionConfig, LanguageName

EXTENSIONS: dict[str, LanguageName] = {
    ".py": "python",
    ".go": "go",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
    ".md": "markdown",
    ".rst": "text",
    ".txt": "text",
}
EXCLUDED_DIRECTORIES = {"node_modules", "vendor", "artifacts", "data", "build", "dist"}


@dataclass(frozen=True)
class CorpusResult:
    directory: Path
    commit_sha: str
    corpus_version: str
    file_count: int
    chunk_count: int


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def publish(directory: Path, chunks: bytes, manifest: bytes) -> None:
    def verify_existing() -> None:
        if (directory / "chunks.jsonl").read_bytes() != chunks:
            raise IngestionError("An existing versioned corpus has different or corrupted chunks.")
        if (directory / "manifest.json").read_bytes() != manifest:
            raise IngestionError(
                "An existing versioned corpus has a different or corrupted manifest."
            )

    if directory.exists():
        verify_existing()
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".corpus-", dir=directory.parent) as temporary:
        staging = Path(temporary) / "complete"
        staging.mkdir()
        (staging / "chunks.jsonl").write_bytes(chunks)
        (staging / "manifest.json").write_bytes(manifest)
        try:
            staging.rename(directory)
        except OSError:
            if not directory.exists():
                raise
            verify_existing()


def ingest(
    repository: Path,
    output: Path,
    *,
    revision: str = "HEAD",
    repo_id: str | None = None,
    config: IngestionConfig | None = None,
) -> CorpusResult:
    config = config or IngestionConfig()
    repository = repository.resolve()
    commit = resolve_commit(repository, revision)
    root = Path(git(repository, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    repo = repo_id or root.name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", repo):
        raise IngestionError(
            "Supply --repo-id with 1 to 80 ASCII letters, digits, dots, or dashes."
        )

    versions = {
        "python": platform.python_version(),
        "tree-sitter": importlib.metadata.version("tree-sitter"),
        "tree-sitter-go": importlib.metadata.version("tree-sitter-go"),
        "tree-sitter-cpp": importlib.metadata.version("tree-sitter-cpp"),
    }
    identity = {
        "schema_version": 1,
        "repo": repo,
        "commit_sha": commit,
        "config": config.model_dump(),
        "parser_versions": versions,
        "extensions": EXTENSIONS,
        "excluded_directories": sorted(EXCLUDED_DIRECTORIES),
        "normalization": "utf-8-sig-to-utf-8-and-crlf-to-lf",
    }
    corpus_version = fingerprint(identity)
    skipped = []
    sources = []
    chunks: list[Chunk] = []
    total_bytes = 0
    selected_count = 0
    for source in list_files(root, commit):
        path = PurePosixPath(source.path)
        language = EXTENSIONS.get(path.suffix.lower())
        reason = None
        if source.mode not in ("100644", "100755"):
            reason = "non_regular_file"
        elif any(part.startswith(".") or part in EXCLUDED_DIRECTORIES for part in path.parts):
            reason = "excluded_path"
        elif language is None:
            reason = "unsupported_extension"
        elif source.size > config.max_file_bytes:
            reason = "file_size_limit"
        if reason is not None:
            skipped.append({"path": source.path, "reason": reason})
            continue
        if language is None:
            raise IngestionError("A selected source has no language.")
        selected_count += 1
        total_bytes += source.size
        if selected_count > config.max_files or total_bytes > config.max_total_bytes:
            raise IngestionError("Snapshot exceeds the configured file count or total byte budget.")
        data = read_blob(root, source)
        try:
            text = data.decode("utf-8-sig").replace("\r\n", "\n")
        except UnicodeDecodeError:
            skipped.append({"path": source.path, "reason": "non_utf8"})
            continue
        if "\0" in text:
            skipped.append({"path": source.path, "reason": "binary_content"})
            continue
        file_chunks, fallback = chunk_source(
            text=text,
            repo=repo,
            commit=commit,
            path=source.path,
            language=language,
            max_chars=config.max_chars,
            method_boundaries=config.algorithm == "symbol-method-boundaries-v2",
        )
        sources.append(
            {
                "path": source.path,
                "blob_oid": source.oid,
                "language": language,
                "normalized_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "chunk_count": len(file_chunks),
                "syntax_fallback": fallback,
            }
        )
        chunks.extend(file_chunks)
    if not chunks:
        raise IngestionError(
            "The snapshot contains no supported, non-empty source or document chunks."
        )

    chunk_bytes = "".join(canonical(chunk.model_dump()) + "\n" for chunk in chunks).encode("utf-8")
    manifest = {
        **identity,
        "corpus_version": corpus_version,
        "corpus_sha256": hashlib.sha256(chunk_bytes).hexdigest(),
        "source_file_count": len(sources),
        "chunk_count": len(chunks),
        "sources": sources,
        "skipped": skipped,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    destination = output.resolve() / repo / corpus_version
    publish(destination, chunk_bytes, manifest_bytes)
    return CorpusResult(destination, commit, corpus_version, len(sources), len(chunks))
