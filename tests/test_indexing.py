"""Exercise Qdrant operations offline with an explicit test-only embedding backend."""

import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

from app.service import QdrantRetriever
from indexing.corpus import Corpus, IndexingError, load_corpus
from indexing.store import create_manifest, index_corpus, load_manifest, search, validate_vectors
from ingestion.chunking import chunk_source
from ingestion.pipeline import canonical, fingerprint


class TestEmbeddings:
    __test__ = False
    dimension = 3

    def __init__(self, version: str = "A") -> None:
        self.identity: dict[str, object] = {"test_only_backend": version}

    def vector(self, text: str) -> tuple[list[float], models.SparseVector]:
        tokens = set(re.findall(r"\w+", text.lower()))
        vocabulary = {"counter": 1, "increment": 2, "add": 3, "python": 4, "go": 5, "cpp": 6}
        dense = (
            [1.0, 0.0, 0.0]
            if {"counter", "increment"} & tokens
            else [0.0, 1.0, 0.0]
            if "add" in tokens
            else [0.0, 0.0, 1.0]
        )
        indices = sorted(value for token, value in vocabulary.items() if token in tokens)
        return dense, models.SparseVector(indices=indices, values=[1.0] * len(indices))

    def documents(self, texts: list[str]) -> tuple[list[list[float]], list[models.SparseVector]]:
        vectors = [self.vector(text) for text in texts]
        return [value[0] for value in vectors], [value[1] for value in vectors]

    def query(self, text: str) -> tuple[list[float], models.SparseVector]:
        return self.vector(text)


def make_corpus(*, many: bool = False) -> Corpus:
    source = (
        "".join(f"def f{number}():\n    return {number}\n\n" for number in range(40))
        if many
        else "class Counter:\n    def increment(self): return 1\n\ndef add(a, b): return a + b\n"
    )
    chunks, _ = chunk_source(
        text=source,
        repo="unit-test",
        commit="a" * 40,
        path="calculator.py",
        language="python",
        max_chars=4000,
    )
    raw = "".join(canonical(chunk.model_dump()) + "\n" for chunk in chunks).encode()
    return Corpus("unit-test", "a" * 40, "b" * 64, hashlib.sha256(raw).hexdigest(), chunks)


def test_hybrid_index_source_metadata_and_language_filter(tmp_path: Path) -> None:
    corpus = make_corpus()
    backend = TestEmbeddings()
    progress = []
    with closing(QdrantClient(":memory:")) as client:
        manifest, path = index_corpus(
            client,
            corpus,
            backend,
            tmp_path,
            progress=lambda completed, total: progress.append((completed, total)),
        )
        assert progress == [(len(corpus.chunks), len(corpus.chunks))]
        assert client.count(manifest.collection, exact=True).count == len(corpus.chunks)
        assert load_manifest(path) == manifest
        hits = search(client, manifest, backend, "Counter increment", top_k=1, language="python")
        assert hits[0].chunk.symbol == "Counter"
        assert hits[0].chunk.commit_sha == corpus.commit_sha
        assert hits[0].index_version == manifest.index_version
        assert search(client, manifest, backend, "Counter", language="go") == []


def test_reindexing_reuses_version_and_does_not_duplicate_points(tmp_path: Path) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        manifest, path = index_corpus(client, corpus, backend, tmp_path)
        original = path.read_bytes()
        repeated, repeated_path = index_corpus(client, corpus, backend, tmp_path)
        assert repeated == manifest and repeated_path.read_bytes() == original
        assert client.count(manifest.collection, exact=True).count == len(corpus.chunks)


def test_complete_index_reuse_skips_embeddings_and_recovers_manifest(tmp_path: Path) -> None:
    class NoEmbeddingCalls(TestEmbeddings):
        def documents(
            self, texts: list[str]
        ) -> tuple[list[list[float]], list[models.SparseVector]]:
            raise AssertionError("A complete verified index must not be re-embedded.")

    corpus = make_corpus()
    with closing(QdrantClient(":memory:")) as client:
        original, _ = index_corpus(client, corpus, TestEmbeddings(), tmp_path / "first")
        reused, path = index_corpus(
            client, corpus, NoEmbeddingCalls(), tmp_path / "recovered", reuse_complete=True
        )
        assert reused == original and load_manifest(path) == original
        assert search(client, reused, NoEmbeddingCalls(), "Counter", top_k=1)


def test_index_reuse_repairs_missing_points_but_rejects_changed_source(tmp_path: Path) -> None:
    corpus = make_corpus()
    with closing(QdrantClient(":memory:")) as client:
        original, _ = index_corpus(client, corpus, TestEmbeddings(), tmp_path)
        first = corpus.chunks[0]
        client.delete(original.collection, points_selector=[first.chunk_id], wait=True)
        restored, _ = index_corpus(client, corpus, TestEmbeddings(), tmp_path, reuse_complete=True)
        assert restored == original
        assert client.count(original.collection, exact=True).count == len(corpus.chunks)
        client.set_payload(
            original.collection,
            payload={"chunk": {"text": "tampered"}},
            points=[first.chunk_id],
            wait=True,
        )
        with pytest.raises(IndexingError, match="inconsistent"):
            index_corpus(client, corpus, TestEmbeddings(), tmp_path, reuse_complete=True)


def test_changed_embedding_identity_creates_another_index(tmp_path: Path) -> None:
    corpus = make_corpus()
    with closing(QdrantClient(":memory:")) as client:
        first, _ = index_corpus(client, corpus, TestEmbeddings("A"), tmp_path)
        second, _ = index_corpus(client, corpus, TestEmbeddings("B"), tmp_path)
        assert first.collection != second.collection
        with pytest.raises(IndexingError, match="differ"):
            search(client, first, TestEmbeddings("B"), "Counter")


def test_incomplete_index_is_not_served(tmp_path: Path) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        manifest, _ = index_corpus(client, corpus, backend, tmp_path)
        client.delete(manifest.collection, points_selector=[corpus.chunks[0].chunk_id], wait=True)
        with pytest.raises(IndexingError, match="incomplete"):
            search(client, manifest, backend, "Counter")


def test_wrong_collection_schema_is_not_overwritten(tmp_path: Path) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        manifest = create_manifest(corpus, backend)
        client.create_collection(
            manifest.collection,
            vectors_config={"dense": models.VectorParams(size=5, distance=models.Distance.COSINE)},
        )
        with pytest.raises(IndexingError, match="schema"):
            index_corpus(client, corpus, backend, tmp_path)
        assert client.get_collection(manifest.collection).config.params.vectors is not None


def test_inconsistent_existing_payload_is_not_overwritten(tmp_path: Path) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        manifest, _ = index_corpus(client, corpus, backend, tmp_path)
        client.set_payload(
            manifest.collection,
            payload={"index_version": "wrong"},
            points=[corpus.chunks[0].chunk_id],
            wait=True,
        )
        with pytest.raises(IndexingError, match="inconsistent"):
            index_corpus(client, corpus, backend, tmp_path)
        with pytest.raises(IndexingError, match="another index"):
            search(client, manifest, backend, "Counter", top_k=1)


@pytest.mark.parametrize("query,top_k", [("", 5), (" ", 5), ("a" * 4001, 5), ("x", 0), ("x", 21)])
def test_invalid_queries_fail_before_embedding(tmp_path: Path, query: str, top_k: int) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        manifest = create_manifest(corpus, backend)
        with pytest.raises(IndexingError, match="Query"):
            search(client, manifest, backend, query, top_k=top_k)


def test_invalid_vectors_are_rejected() -> None:
    sparse = models.SparseVector(indices=[1], values=[1.0])
    with pytest.raises(IndexingError, match="dimensions"):
        validate_vectors([float("nan"), 0.0, 1.0], sparse, 3)
    with pytest.raises(IndexingError, match="zero"):
        validate_vectors([0.0, 0.0, 0.0], sparse, 3)


def test_partial_index_can_resume_without_publishing_early(tmp_path: Path) -> None:
    class FailSecondBatch(TestEmbeddings):
        calls = 0

        def documents(
            self, texts: list[str]
        ) -> tuple[list[list[float]], list[models.SparseVector]]:
            self.calls += 1
            if self.calls == 2:
                raise IndexingError("Simulated embedding failure.")
            return super().documents(texts)

    corpus = make_corpus(many=True)
    backend = FailSecondBatch()
    with closing(QdrantClient(":memory:")) as client:
        manifest = create_manifest(corpus, backend)
        with pytest.raises(IndexingError, match="Simulated"):
            index_corpus(client, corpus, backend, tmp_path)
        assert client.count(manifest.collection, exact=True).count == 32
        assert not list(tmp_path.rglob("manifest.json"))
        resumed, path = index_corpus(client, corpus, TestEmbeddings(), tmp_path)
        assert resumed == manifest and path.is_file()
        assert client.count(manifest.collection, exact=True).count == 40


def test_modified_manifest_fails_integrity_check(tmp_path: Path) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        _, path = index_corpus(client, corpus, backend, tmp_path)
    value = json.loads(path.read_bytes())
    value["corpus_sha256"] = "c" * 64
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(IndexingError, match="integrity"):
        load_manifest(path)


def test_corrupted_corpus_bytes_are_rejected(tmp_path: Path) -> None:
    corpus = make_corpus()
    content = "".join(canonical(chunk.model_dump()) + "\n" for chunk in corpus.chunks).encode()
    identity = {
        "schema_version": 1,
        "repo": corpus.repo,
        "commit_sha": corpus.commit_sha,
        "config": {},
        "parser_versions": {},
        "extensions": {},
        "excluded_directories": [],
        "normalization": "test",
    }
    manifest = {
        **identity,
        "corpus_version": fingerprint(identity),
        "corpus_sha256": hashlib.sha256(content).hexdigest(),
        "chunk_count": len(corpus.chunks),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "chunks.jsonl").write_bytes(content)
    assert len(load_corpus(tmp_path).chunks) == len(corpus.chunks)
    (tmp_path / "chunks.jsonl").write_bytes(content + b" ")
    with pytest.raises(IndexingError, match="integrity"):
        load_corpus(tmp_path)


def test_api_retriever_rejects_payload_text_changed_after_indexing(tmp_path: Path) -> None:
    corpus, backend = make_corpus(), TestEmbeddings()
    with closing(QdrantClient(":memory:")) as client:
        manifest, _ = index_corpus(client, corpus, backend, tmp_path)
        retriever = QdrantRetriever(client, manifest, backend, corpus.chunks)
        assert retriever.retrieve("Counter", 1, "python")[0].chunk.symbol == "Counter"
        altered = corpus.chunks[0].model_dump()
        altered["text"] = "This source was changed after publication."
        client.set_payload(
            manifest.collection,
            payload={"chunk": altered},
            points=[corpus.chunks[0].chunk_id],
            wait=True,
        )
        with pytest.raises(IndexingError, match="saved source corpus"):
            retriever.retrieve("Counter", 1, "python")
