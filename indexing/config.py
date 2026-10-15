"""Qdrant connection configuration for local development."""

import os
import re
from pathlib import Path

from qdrant_client import QdrantClient

from indexing.corpus import IndexingError

ROOT = Path(__file__).resolve().parents[1]


def connect(*, local: bool = False) -> QdrantClient:
    if local:
        return QdrantClient(path=str(ROOT / "artifacts" / "qdrant-local"))
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        key, separator, value = line.strip().partition("=")
        if not separator:
            raise IndexingError(".env must contain KEY=value lines.")
        values[key] = os.environ.get(key, value)
    key = values.get("QDRANT_API_KEY", "")
    port = values.get("QDRANT_PORT", "")
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise IndexingError("QDRANT_API_KEY must match the credentials generated in Step 2.")
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise IndexingError("QDRANT_PORT must be a valid TCP port.")
    return QdrantClient(url=f"http://127.0.0.1:{port}", api_key=key, timeout=30, trust_env=False)
