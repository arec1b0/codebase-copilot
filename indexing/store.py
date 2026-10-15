"""Index and retrieve explicit vectors through Qdrant's named-vector API."""

import json
import math
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict
from qdrant_client import QdrantClient, models

from indexing.corpus import Corpus, IndexingError
from indexing.embeddings import EmbeddingBackend
from ingestion.models import Chunk, LanguageName
from ingestion.pipeline import fingerprint


class IndexManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    algorithm: Literal["dense-bm25-v1"] = "dense-bm25-v1"
    repo: str
    commit_sha: str
    corpus_version: str
    corpus_sha256: str
    chunk_count: int
    embeddings: dict[str, object]
    dimension: int
    document_format: Literal["source-header-v1"] = "source-header-v1"
    distance: Literal["Cosine"] = "Cosine"
    sparse_modifier: Literal["idf"] = "idf"
    index_version: str
    collection: str


class RetrievalHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_version: str
    corpus_version: str
    score: float
    chunk: Chunk


def document_text(chunk: Chunk) -> str:
    return f"{chunk.language} {chunk.path} {chunk.symbol or ''}\n{chunk.text}"


def create_manifest(corpus: Corpus, backend: EmbeddingBackend) -> IndexManifest:
    identity = {
        "schema_version": 1,
        "algorithm": "dense-bm25-v1",
        "repo": corpus.repo,
        "commit_sha": corpus.commit_sha,
        "corpus_version": corpus.version,
        "corpus_sha256": corpus.sha256,
        "chunk_count": len(corpus.chunks),
        "embeddings": backend.identity,
        "dimension": backend.dimension,
        "document_format": "source-header-v1",
        "distance": "Cosine",
        "sparse_modifier": "idf",
    }
    version = fingerprint(identity)
    return IndexManifest.model_validate(
        {
            **identity,
            "index_version": version,
            "collection": f"copilot_{corpus.repo}_{version[:24]}",
        }
    )


def load_manifest(path: Path) -> IndexManifest:
    manifest = IndexManifest.model_validate_json(path.read_bytes())
    identity = manifest.model_dump(exclude={"index_version", "collection"})
    expected_version = fingerprint(identity)
    expected_collection = f"copilot_{manifest.repo}_{expected_version[:24]}"
    if manifest.index_version != expected_version or manifest.collection != expected_collection:
        raise IndexingError("Index manifest integrity check failed.")
    return manifest


def validate_vectors(dense: list[float], sparse: models.SparseVector, dimension: int) -> None:
    if len(dense) != dimension or not all(math.isfinite(value) for value in dense):
        raise IndexingError("Dense embedding has invalid dimensions or non-finite values.")
    if not any(value != 0.0 for value in dense):
        raise IndexingError("Dense embedding cannot be the zero vector.")
    if len(sparse.indices) != len(sparse.values) or len(set(sparse.indices)) != len(sparse.indices):
        raise IndexingError("Sparse embedding has inconsistent or duplicate indices.")
    if any(index < 0 for index in sparse.indices) or not all(
        math.isfinite(v) for v in sparse.values
    ):
        raise IndexingError("Sparse embedding contains invalid values.")


def validate_schema(client: QdrantClient, manifest: IndexManifest) -> None:
    parameters = client.get_collection(manifest.collection).config.params
    vectors = parameters.vectors
    sparse = parameters.sparse_vectors
    if (
        not isinstance(vectors, dict)
        or set(vectors) != {"dense"}
        or vectors["dense"].size != manifest.dimension
        or vectors["dense"].distance != models.Distance.COSINE
        or sparse is None
        or set(sparse) != {"bm25"}
        or sparse["bm25"].modifier != models.Modifier.IDF
    ):
        raise IndexingError("Qdrant collection schema does not match the index manifest.")


def publish_manifest(directory: Path, content: bytes) -> None:
    def verify_existing() -> None:
        if (directory / "manifest.json").read_bytes() != content:
            raise IndexingError("Existing index manifest has different or corrupted content.")

    if directory.exists():
        verify_existing()
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".index-", dir=directory.parent) as temporary:
        staging = Path(temporary) / "complete"
        staging.mkdir()
        (staging / "manifest.json").write_bytes(content)
        try:
            staging.rename(directory)
        except OSError:
            if not directory.exists():
                raise
            verify_existing()


def index_corpus(
    client: QdrantClient,
    corpus: Corpus,
    backend: EmbeddingBackend,
    output: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    reuse_complete: bool = False,
) -> tuple[IndexManifest, Path]:
    manifest = create_manifest(corpus, backend)
    expected = {chunk.chunk_id: chunk for chunk in corpus.chunks}
    if not client.collection_exists(manifest.collection):
        client.create_collection(
            collection_name=manifest.collection,
            vectors_config={
                "dense": models.VectorParams(
                    size=backend.dimension, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
    validate_schema(client, manifest)
    offset: models.ExtendedPointId | None = None
    while True:
        records, offset = client.scroll(
            manifest.collection, limit=128, offset=offset, with_payload=True, with_vectors=False
        )
        for record in records:
            payload = record.payload or {}
            chunk = expected.get(str(record.id))
            if (
                chunk is None
                or payload.get("index_version") != manifest.index_version
                or payload.get("corpus_version") != manifest.corpus_version
                or payload.get("chunk") != chunk.model_dump()
            ):
                raise IndexingError(
                    "Existing collection contains foreign or inconsistent source records."
                )
        if offset is None:
            break

    if reuse_complete and client.count(manifest.collection, exact=True).count == len(expected):
        return manifest, save_manifest(output, manifest)

    for start in range(0, len(corpus.chunks), 32):
        batch = corpus.chunks[start : start + 32]
        dense, sparse = backend.documents([document_text(chunk) for chunk in batch])
        if len(dense) != len(batch) or len(sparse) != len(batch):
            raise IndexingError("Embedding backend returned an inconsistent batch size.")
        points = []
        for chunk, dense_vector, sparse_vector in zip(batch, dense, sparse, strict=True):
            validate_vectors(dense_vector, sparse_vector, backend.dimension)
            points.append(
                models.PointStruct(
                    id=chunk.chunk_id,
                    vector={"dense": dense_vector, "bm25": sparse_vector},
                    payload={
                        "chunk": chunk.model_dump(),
                        "index_version": manifest.index_version,
                        "corpus_version": manifest.corpus_version,
                    },
                )
            )
        client.upsert(manifest.collection, points=points, wait=True)
        if progress is not None:
            progress(start + len(batch), len(corpus.chunks))
    if client.count(manifest.collection, exact=True).count != manifest.chunk_count:
        raise IndexingError("Qdrant point count does not match the complete corpus.")

    return manifest, save_manifest(output, manifest)


def save_manifest(output: Path, manifest: IndexManifest) -> Path:
    directory = output.resolve() / manifest.repo / manifest.index_version
    serialized = (json.dumps(manifest.model_dump(), sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    publish_manifest(directory, serialized)
    return directory / "manifest.json"


def search(
    client: QdrantClient,
    manifest: IndexManifest,
    backend: EmbeddingBackend,
    query: str,
    *,
    top_k: int = 5,
    language: LanguageName | None = None,
) -> list[RetrievalHit]:
    query = query.strip()
    if not query or len(query) > 4000 or not 1 <= top_k <= 20:
        raise IndexingError("Query must contain 1 to 4000 characters and top_k must be 1 to 20.")
    if backend.identity != manifest.embeddings or backend.dimension != manifest.dimension:
        raise IndexingError("Query embeddings differ from the indexed model assets or runtime.")
    validate_schema(client, manifest)
    if client.count(manifest.collection, exact=True).count != manifest.chunk_count:
        raise IndexingError("Qdrant index is incomplete or has an unexpected point count.")
    dense, sparse = backend.query(query)
    validate_vectors(dense, sparse, manifest.dimension)
    query_filter = None
    if language is not None:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(key="chunk.language", match=models.MatchValue(value=language))
            ]
        )
    response = client.query_points(
        collection_name=manifest.collection,
        prefetch=[
            models.Prefetch(
                query=dense, using="dense", limit=max(20, top_k * 4), filter=query_filter
            ),
            models.Prefetch(
                query=sparse, using="bm25", limit=max(20, top_k * 4), filter=query_filter
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )
    hits = []
    for point in response.points:
        payload = point.payload or {}
        if (
            payload.get("index_version") != manifest.index_version
            or payload.get("corpus_version") != manifest.corpus_version
        ):
            raise IndexingError("A retrieved point belongs to another index version.")
        chunk = Chunk.model_validate(payload.get("chunk"))
        if chunk.repo != manifest.repo or chunk.commit_sha != manifest.commit_sha:
            raise IndexingError("A retrieved point belongs to another source snapshot.")
        hits.append(
            RetrievalHit(
                index_version=manifest.index_version,
                corpus_version=manifest.corpus_version,
                score=point.score,
                chunk=chunk,
            )
        )
    return hits
