"""Verify corpus integrity before indexing its source records."""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from ingestion.models import Chunk
from ingestion.pipeline import fingerprint


class IndexingError(RuntimeError):
    """An index or retrieval contract cannot be satisfied."""


@dataclass(frozen=True)
class Corpus:
    repo: str
    commit_sha: str
    version: str
    sha256: str
    chunks: list[Chunk]


def load_corpus(directory: Path) -> Corpus:
    content = (directory / "chunks.jsonl").read_bytes()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise IndexingError("Corpus manifest must be a JSON object.")
    identity_fields = (
        "schema_version",
        "repo",
        "commit_sha",
        "config",
        "parser_versions",
        "extensions",
        "excluded_directories",
        "normalization",
    )
    if manifest.get("schema_version") != 1:
        raise IndexingError("Unsupported corpus schema version.")
    identity = {field: manifest[field] for field in identity_fields}
    version = fingerprint(identity)
    digest = hashlib.sha256(content).hexdigest()
    if manifest.get("corpus_version") != version or manifest.get("corpus_sha256") != digest:
        raise IndexingError("Corpus or manifest integrity check failed.")
    repo, commit = manifest["repo"], manifest["commit_sha"]
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", repo):
        raise IndexingError("Invalid repository namespace.")
    if not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit):
        raise IndexingError("Invalid corpus commit SHA.")
    chunks = [Chunk.model_validate_json(line) for line in content.splitlines()]
    if not chunks or len(chunks) != manifest.get("chunk_count"):
        raise IndexingError("Corpus chunk count is inconsistent.")
    ids = set()
    for chunk in chunks:
        if chunk.repo != repo or chunk.commit_sha != commit:
            raise IndexingError("A chunk belongs to another repository or commit.")
        if chunk.end_line < chunk.start_line or chunk.end_char - chunk.start_char != len(
            chunk.text
        ):
            raise IndexingError("A chunk has inconsistent source coordinates.")
        actual_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        if actual_hash != chunk.content_sha256:
            raise IndexingError("A chunk content hash is inconsistent.")
        source_identity = (
            f"{repo}\0{commit}\0{chunk.path}\0{chunk.start_char}\0{chunk.end_char}\0{actual_hash}"
        )
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, source_identity))
        if chunk.chunk_id != expected or chunk.chunk_id in ids:
            raise IndexingError("A chunk identifier is invalid or duplicated.")
        ids.add(chunk.chunk_id)
    return Corpus(repo, commit, version, digest, chunks)
