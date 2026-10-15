"""CPU embeddings with explicit model asset identity and input limits."""

import hashlib
import importlib.metadata
from pathlib import Path
from typing import Protocol

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import models
from tokenizers import Tokenizer

from indexing.corpus import IndexingError

DENSE_MODEL = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"


class EmbeddingBackend(Protocol):
    dimension: int
    identity: dict[str, object]

    def documents(
        self, texts: list[str]
    ) -> tuple[list[list[float]], list[models.SparseVector]]: ...

    def query(self, text: str) -> tuple[list[float], models.SparseVector]: ...


def asset_hashes(model: object) -> dict[str, str]:
    directory = getattr(model, "_model_dir", None)
    if not isinstance(directory, Path) or not directory.is_dir():
        raise IndexingError("FastEmbed model asset path is unavailable; check its locked version.")
    result = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if not path.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1048576):
                digest.update(block)
        result[relative.as_posix()] = digest.hexdigest()
    if not result:
        raise IndexingError("Model assets cannot be fingerprinted.")
    return result


class CpuEmbeddings:
    def __init__(self, cache: Path, *, local_only: bool = False) -> None:
        cache.mkdir(parents=True, exist_ok=True)
        self.dense = TextEmbedding(
            model_name=DENSE_MODEL,
            cache_dir=str(cache),
            threads=2,
            providers=["CPUExecutionProvider"],
            local_files_only=local_only,
        )
        self.sparse = SparseTextEmbedding(
            model_name=SPARSE_MODEL,
            cache_dir=str(cache),
            language="english",
            k=1.2,
            b=0.75,
            avg_len=256.0,
            token_max_length=40,
            local_files_only=local_only,
        )
        self.dimension = self.dense.embedding_size
        tokenizer = getattr(self.dense.model, "tokenizer", None)
        if not isinstance(tokenizer, Tokenizer):
            raise IndexingError(
                "Dense tokenizer is unavailable; check the locked FastEmbed version."
            )
        self.tokenizer = Tokenizer.from_str(tokenizer.to_str())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.identity: dict[str, object] = {
            "dense_model": DENSE_MODEL,
            "dense_dimension": self.dimension,
            "dense_assets": asset_hashes(self.dense.model),
            "sparse_model": SPARSE_MODEL,
            "sparse_assets": asset_hashes(self.sparse.model),
            "sparse_parameters": {
                "language": "english",
                "k": 1.2,
                "b": 0.75,
                "avg_len": 256.0,
                "token_max_length": 40,
                "disable_stemmer": False,
            },
            "provider": "CPUExecutionProvider",
            "threads": 2,
            "max_input_tokens": 512,
            "packages": {
                name: importlib.metadata.version(name)
                for name in (
                    "fastembed",
                    "onnxruntime",
                    "tokenizers",
                    "numpy",
                    "mmh3",
                    "py-rust-stemmers",
                )
            },
        }

    def check_input(self, text: str) -> None:
        if len(self.tokenizer.encode(text).ids) > 512:
            raise IndexingError(
                "Embedding input exceeds 512 tokens. "
                "Use smaller ingestion chunks or a shorter query."
            )

    def documents(self, texts: list[str]) -> tuple[list[list[float]], list[models.SparseVector]]:
        for text in texts:
            self.check_input(text)
        dense = [[float(value) for value in vector] for vector in self.dense.passage_embed(texts)]
        sparse = [
            models.SparseVector(
                indices=[int(value) for value in vector.indices],
                values=[float(value) for value in vector.values],
            )
            for vector in self.sparse.passage_embed(texts)
        ]
        return dense, sparse

    def query(self, text: str) -> tuple[list[float], models.SparseVector]:
        self.check_input(text)
        dense = next(iter(self.dense.query_embed(text)))
        sparse = next(iter(self.sparse.query_embed(text)))
        return (
            [float(value) for value in dense],
            models.SparseVector(
                indices=[int(value) for value in sparse.indices],
                values=[float(value) for value in sparse.values],
            ),
        )
