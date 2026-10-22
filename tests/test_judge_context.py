"""Actual model inputs, legacy context and isolated judge calls with synthetic models."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.contracts import (
    Generation,
    ModelAnswer,
    ModelIdentity,
    QueryRequest,
    SourceClaim,
    TokenUsage,
)
from app.main import create_app
from app.model import OllamaModel
from app.prompt import input_sha256
from app.service import GroundedService
from evals.context import context_issues
from evals.contracts import EvalCase, Evidence
from evals.judge import RUBRIC_HASHES, assess
from indexing.store import IndexManifest, RetrievalHit
from ingestion.chunking import chunk_source
from ingestion.models import LanguageName


class ContextRetriever:
    def __init__(self) -> None:
        self.manifest = IndexManifest(
            repo="synthetic",
            commit_sha="a" * 40,
            corpus_version="b" * 64,
            corpus_sha256="c" * 64,
            chunk_count=2,
            embeddings={"synthetic": True},
            dimension=3,
            index_version="d" * 64,
            collection="synthetic",
        )
        self.hits = [
            RetrievalHit(
                index_version=self.manifest.index_version,
                corpus_version=self.manifest.corpus_version,
                score=1.0,
                chunk=chunk_source(
                    text=f"def function_{i}():\n    return {i}\n",
                    repo="synthetic",
                    commit="a" * 40,
                    path=f"file{i}.py",
                    language="python",
                    max_chars=600,
                )[0][0],
            )
            for i in range(2)
        ]

    def check(self) -> None:
        pass

    def retrieve(
        self, question: str, top_k: int, language: LanguageName | None
    ) -> list[RetrievalHit]:
        return self.hits[:top_k]

    def close(self) -> None:
        pass


class ContextModel:
    def __init__(self, abstain: bool = False) -> None:
        self.abstain = abstain
        self.messages: list[dict[str, str]] = []
        self.labels: list[str] = []
        self.calls = 0

    def identity(self) -> ModelIdentity:
        return ModelIdentity(
            model="synthetic", revision="sha256:" + "e" * 64, backend_version="ollama:test"
        )

    def generate(self, messages: list[dict[str, str]], source_ids: list[str]) -> Generation:
        self.messages, self.labels = messages, source_ids
        self.calls += 1
        return Generation(
            content=ModelAnswer(
                statements=[]
                if self.abstain
                else [SourceClaim(text="Synthetic supported fact.", source_ids=["S1"])],
                abstain=self.abstain,
                reason="Missing evidence." if self.abstain else "",
            ),
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            ttft_ms=1.0,
            latency_ms=2.0,
        )

    def close(self) -> None:
        pass


def test_api_records_uncited_context_order_and_exact_messages_hash() -> None:
    retriever, model = ContextRetriever(), ContextModel()
    with TestClient(create_app(GroundedService(retriever, model))) as api:
        body = api.post(
            "/query", json={"question": "Synthetic question?", "language": "python"}
        ).json()
    assert len(body["citations"]) == 1 and len(body["context_sources"]) == 2
    assert [c["chunk_id"] for c in body["context_sources"]] == [
        h.chunk.chunk_id for h in retriever.hits
    ]
    assert [c["source_id"] for c in body["context_sources"]] == model.labels == ["S1", "S2"]
    assert body["generation_input_sha256"] == input_sha256(model.messages)


def test_budget_skips_oversized_hit_and_renumbers_actual_context() -> None:
    retriever, model = ContextRetriever(), ContextModel()
    original = retriever.hits[0]
    retriever.hits.insert(
        0,
        original.model_copy(
            update={
                "chunk": original.chunk.model_copy(
                    update={"text": "OVERSIZED_PRIVATE_TEXT" * 1000}
                ),
            }
        ),
    )
    request = QueryRequest(question="Budget test?", language="python")
    body = GroundedService(retriever, model).answer(request, uuid4())
    assert body.context_sources is not None
    assert body.context_sources[0].source_id == "S1"
    assert body.context_sources[0].chunk_id == original.chunk.chunk_id
    assert "OVERSIZED_PRIVATE_TEXT" not in json.dumps(model.messages)
    assert len(body.context_sources) == 2
    chunks = {h.chunk.chunk_id: h.chunk for h in retriever.hits}
    assert context_issues(body, chunks, request.question, request.language) == []


@pytest.mark.parametrize("abstain,empty", [(True, False), (False, True)])
def test_abstention_distinguishes_used_context_from_no_model_call(
    abstain: bool, empty: bool
) -> None:
    retriever, model = ContextRetriever(), ContextModel(abstain)
    if empty:
        retriever.hits = []
    body = GroundedService(retriever, model).answer(QueryRequest(question="Missing fact?"), uuid4())
    assert body.status == "insufficient_context" and body.citations == []
    assert body.context_sources is not None and len(body.context_sources) == (0 if empty else 2)
    assert model.calls == (0 if empty else 1)
    assert (body.generation_input_sha256 is None) == empty


@pytest.mark.parametrize(
    "damage", ["labels", "duplicate", "metadata", "hash", "missing-hash", "citation", "count"]
)
def test_context_tampering_is_rejected(damage: str) -> None:
    retriever, model = ContextRetriever(), ContextModel()
    body = GroundedService(retriever, model).answer(QueryRequest(question="Context?"), uuid4())
    assert body.context_sources is not None
    sources = body.context_sources.copy()
    if damage == "labels":
        sources.reverse()
    elif damage == "duplicate":
        sources[1] = sources[0].model_copy(update={"source_id": "S2"})
    elif damage == "metadata":
        sources[0] = sources[0].model_copy(update={"path": "forged.py"})
    elif damage in ("hash", "missing-hash"):
        body = body.model_copy(
            update={"generation_input_sha256": "f" * 64 if damage == "hash" else None}
        )
    elif damage == "citation":
        body = body.model_copy(
            update={"citations": [body.citations[0].model_copy(update={"source_id": "S2"})]}
        )
    else:
        sources.append(sources[0].model_copy(update={"source_id": "S3"}))
        sources.append(sources[0].model_copy(update={"source_id": "S4"}))
    body = body.model_copy(update={"context_sources": sources})
    assert context_issues(
        body, {h.chunk.chunk_id: h.chunk for h in retriever.hits}, "Context?", None
    )


def test_legacy_context_stays_unknown_and_is_not_reconstructed() -> None:
    retriever, model = ContextRetriever(), ContextModel()
    body = GroundedService(retriever, model).answer(QueryRequest(question="Context?"), uuid4())
    legacy = body.model_copy(update={"context_sources": None, "generation_input_sha256": None})
    assert context_issues(legacy, {}, "Context?", None) == []
    assert legacy.context_sources is None
    damaged = legacy.model_copy(update={"generation_input_sha256": "f" * 64})
    assert context_issues(damaged, {}, "Context?", None) == ["context_hash_without_context"]


@pytest.mark.parametrize(
    "damage", [None, "score", "extra", "truncated", "tools", "tokens", "http", "revision"]
)
def test_judge_inputs_are_isolated_and_protocol_failures_close(damage: str | None) -> None:
    retriever, generator = ContextRetriever(), ContextModel()
    body = GroundedService(retriever, generator).answer(
        QueryRequest(question="PRIVATE_QUESTION?"), uuid4()
    )
    case = EvalCase(
        id="synthetic-01",
        category="explanation",
        question="PRIVATE_QUESTION?",
        language="python",
        reference="PRIVATE_REFERENCE",
        evidence=[Evidence(path="file0.py", start_line=1, end_line=2)],
    )
    calls = []
    chat_done = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal chat_done
        if request.url.path == "/api/tags":
            revision = "f" if damage == "revision" and chat_done else "e"
            return httpx.Response(
                200, json={"models": [{"name": "synthetic", "digest": revision * 64}]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        payload = json.loads(request.content)
        calls.append(payload)
        chat_done = True
        content: dict[str, object] = {
            "score": 1 if len(calls) == 1 else 0,
            "reason": "Synthetic test reason.",
        }
        if damage == "score":
            content["score"] = True
        if damage == "extra":
            content["other_dimension"] = 2
        event = {
            "model": "synthetic",
            "done": True,
            "done_reason": "length" if damage == "truncated" else "stop",
            "message": {
                "content": json.dumps(content),
                **({"tool_calls": [{}]} if damage == "tools" else {}),
            },
            "prompt_eval_count": 8000 if damage == "tokens" else 100,
            "eval_count": 20,
        }
        return httpx.Response(503 if damage == "http" else 200, json=event)

    client = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    model = OllamaModel("http://ollama", "synthetic", client)
    try:
        identity = model.identity()
        chunks = {hit.chunk.chunk_id: hit.chunk for hit in retriever.hits}
        if damage:
            with pytest.raises(ValueError):
                assess(model, identity, case, body, chunks)
            return
        result = assess(model, identity, case, body, chunks)
        assert len(calls) == 2
        faith = json.loads(calls[0]["messages"][1]["content"])
        rel = json.loads(calls[1]["messages"][1]["content"])
        assert set(faith) == {"answer", "sources"}
        assert "PRIVATE_QUESTION" not in json.dumps(
            faith
        ) and "PRIVATE_REFERENCE" not in json.dumps(faith)
        assert set(rel) == {"question", "reference", "answer"} and "sources" not in rel
        assert result.assessment.faithfulness == 1 and result.assessment.relevance == 0
        assert result.usage == TokenUsage(input_tokens=200, output_tokens=40)
        assert {c.dimension: c.rubric_sha256 for c in result.calls} == RUBRIC_HASHES
        assert result.calls[0].input_sha256 != result.calls[1].input_sha256
    finally:
        model.close()
