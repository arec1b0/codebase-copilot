"""HTTP and grounding contracts with explicit test-only service dependencies."""

import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import StatusCode

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
from app.prompt import SYSTEM_PROMPT, build_prompt
from app.service import GroundedService
from indexing.store import IndexManifest, RetrievalHit
from ingestion.chunking import chunk_source
from ingestion.models import LanguageName
from observability.tracing import Telemetry


class StubRetriever:
    def __init__(self) -> None:
        self.manifest = IndexManifest(
            repo="demo",
            commit_sha="a" * 40,
            corpus_version="b" * 64,
            corpus_sha256="c" * 64,
            chunk_count=1,
            embeddings={"test_only": True},
            dimension=3,
            index_version="d" * 64,
            collection="test-only",
        )
        chunk = chunk_source(
            text=(
                "class Counter:\n    def increment(self, amount):\n"
                "        self.value += amount\n        return self.value\n"
            ),
            repo="demo",
            commit="a" * 40,
            path="calculator.py",
            language="python",
            max_chars=4000,
        )[0][0]
        self.hits = [
            RetrievalHit(
                index_version=self.manifest.index_version,
                corpus_version=self.manifest.corpus_version,
                score=1.0,
                chunk=chunk,
            )
        ]
        self.closed = False

    def check(self) -> None:
        return None

    def retrieve(self, query: str, top_k: int, language: LanguageName | None) -> list[RetrievalHit]:
        return [] if language == "text" else self.hits[:top_k]

    def close(self) -> None:
        self.closed = True


class StubModel:
    def __init__(self, content: ModelAnswer | None = None) -> None:
        self.current = ModelIdentity(
            model="qwen2.5-coder:3b", revision="sha256:" + "e" * 64, backend_version="ollama:test"
        )
        self.content = content or ModelAnswer(
            statements=[
                SourceClaim(
                    text="The value increases by amount and is returned.", source_ids=["S1"]
                )
            ],
            abstain=False,
            reason="",
        )
        self.calls = 0
        self.closed = False
        self.change_on_generate = False

    def identity(self) -> ModelIdentity:
        return self.current

    def generate(self, messages: list[dict[str, str]], source_ids: list[str]) -> Generation:
        self.calls += 1
        assert source_ids == ["S1"]
        assert messages[0]["role"] == "system"
        if self.change_on_generate:
            self.current = self.current.model_copy(update={"revision": "sha256:" + "f" * 64})
        return Generation(
            content=self.content,
            usage=TokenUsage(input_tokens=100, output_tokens=30),
            ttft_ms=2.0,
            latency_ms=5.0,
        )

    def close(self) -> None:
        self.closed = True


def test_query_http_returns_citations_versions_and_request_id() -> None:
    retriever, model = StubRetriever(), StubModel()
    with TestClient(create_app(GroundedService(retriever, model))) as client:
        assert client.get("/readyz").status_code == 200
        response = client.post(
            "/query", json={"question": "How does Counter increment?", "language": "python"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["request_id"] == response.headers["X-Request-ID"]
        assert body["status"] == "answered"
        assert body["answer"] == "The value increases by amount and is returned. [S1]"
        assert body["prompt_version"] == "grounded-codebase-v2"
        assert body["citations"][0]["path"] == "calculator.py"
        assert body["citations"][0]["symbol"] == "Counter"
        assert body["index_version"] == retriever.manifest.index_version
        assert body["model_revision"] == model.current.revision
        assert len(body["prompt_sha256"]) == 64
        assert body["usage"]["output_tokens"] == 30
        assert body["model_ttft_ms"] == 2.0
    assert retriever.closed and model.closed


def test_empty_retrieval_abstains_without_calling_model() -> None:
    model = StubModel()
    with TestClient(create_app(GroundedService(StubRetriever(), model))) as client:
        response = client.post("/query", json={"question": "Where is Counter?", "language": "text"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_context" and body["citations"] == []
    assert body["usage"]["output_tokens"] == 0 and body["model_ttft_ms"] is None
    assert model.calls == 0


@pytest.mark.parametrize(
    "body",
    [
        {"question": " "},
        {"question": "x", "top_k": True},
        {"question": "x", "language": "java"},
        {"question": "x", "model": "other"},
    ],
)
def test_invalid_http_inputs_have_correlated_safe_errors(body: dict[str, object]) -> None:
    with TestClient(create_app(initialize=False)) as client:
        response = client.post("/query", json=body)
    assert response.status_code == 422
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.json()["error"] == "invalid_request"


def test_liveness_does_not_claim_readiness() -> None:
    with TestClient(create_app(initialize=False)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 503
        assert client.post("/query", json={"question": "Counter?"}).status_code == 503


@pytest.mark.parametrize(
    "text,ids,abstain",
    [
        ("Invented. [S999]", ["S999"], False),
        ("Undeclared citation. [S2]", ["S1"], False),
        ("Combined undeclared citation. [S1, S999]", ["S1"], False),
        ("Duplicate. [S1]", ["S1", "S1"], False),
        ("No evidence. [S1]", ["S1"], True),
        ("No statements.", None, False),
    ],
)
def test_invalid_model_citations_fail_closed(
    text: str, ids: list[str] | None, abstain: bool
) -> None:
    service = GroundedService(
        StubRetriever(),
        StubModel(
            ModelAnswer(
                statements=[SourceClaim(text=text, source_ids=ids)] if ids is not None else [],
                abstain=abstain,
                reason="Missing evidence." if abstain else "",
            )
        ),
    )
    with TestClient(create_app(service)) as client:
        response = client.post("/query", json={"question": "Counter?"})
    assert response.status_code == 502
    assert response.json()["error"] == "invalid_citations"


def test_model_can_abstain_when_context_is_insufficient() -> None:
    service = GroundedService(
        StubRetriever(),
        StubModel(
            ModelAnswer(
                statements=[], abstain=True, reason="The sources do not describe persistence."
            )
        ),
    )
    result = service.answer(QueryRequest(question="Is Counter persisted?"), uuid4())
    assert result.status == "insufficient_context" and not result.citations
    assert result.usage.output_tokens == 30


def test_statement_citations_render_without_model_inline_markers() -> None:
    content = ModelAnswer(
        statements=[
            SourceClaim(text="It adds amount to value.", source_ids=["S1"]),
            SourceClaim(text="It returns the updated value.", source_ids=["S1"]),
        ],
        abstain=False,
        reason="",
    )
    with TestClient(create_app(GroundedService(StubRetriever(), StubModel(content)))) as client:
        response = client.post("/query", json={"question": "Counter?"})
    assert response.status_code == 200
    assert response.json()["answer"] == (
        "It adds amount to value. [S1]\n\nIt returns the updated value. [S1]"
    )
    assert [item["source_id"] for item in response.json()["citations"]] == ["S1"]


def test_native_claim_response_renders_through_query_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5-coder:3b", "digest": "a" * 64}]}
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        definition = payload["format"]["$defs"]["SourceClaim"]["properties"]["source_ids"]
        assert definition["items"]["enum"] == ["S1"]
        content = json.dumps(
            {
                "statements": [
                    {"text": "It increases value by amount.", "source_ids": ["S1"]},
                    {"text": "It returns the updated value.", "source_ids": ["S1"]},
                ],
                "abstain": False,
                "reason": "",
            }
        )
        event = {
            "model": "qwen2.5-coder:3b",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 120,
            "eval_count": 70,
        }
        return httpx.Response(200, content=(json.dumps(event) + "\n").encode())

    model = OllamaModel(
        "http://ollama",
        "qwen2.5-coder:3b",
        httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler)),
    )
    with TestClient(create_app(GroundedService(StubRetriever(), model))) as client:
        response = client.post("/query", json={"question": "Counter?"})
    assert response.status_code == 200
    assert response.json()["answer"] == (
        "It increases value by amount. [S1]\n\nIt returns the updated value. [S1]"
    )
    assert len(response.json()["citations"]) == 1
    assert response.json()["usage"] == {"input_tokens": 120, "output_tokens": 70}


def test_redundant_declared_markers_are_canonicalized() -> None:
    content = ModelAnswer(
        statements=[SourceClaim(text="Value increases. [S1] [S1]", source_ids=["S1"])],
        abstain=False,
        reason="",
    )
    service = GroundedService(StubRetriever(), StubModel(content))
    result = service.answer(QueryRequest(question="Counter?"), uuid4())
    assert result.answer == "Value increases. [S1]"


@pytest.mark.parametrize("reason", [" ", "Missing evidence. [S1]"])
def test_abstention_requires_uncited_nonblank_reason(reason: str) -> None:
    content = ModelAnswer(statements=[], abstain=True, reason=reason)
    with TestClient(create_app(GroundedService(StubRetriever(), StubModel(content)))) as client:
        response = client.post("/query", json={"question": "Counter?"})
    assert response.status_code == 502


def test_changed_model_digest_is_rejected_after_generation() -> None:
    model = StubModel()
    model.change_on_generate = True
    with TestClient(create_app(GroundedService(StubRetriever(), model))) as client:
        response = client.post("/query", json={"question": "Counter?"})
    assert response.status_code == 503
    assert response.json()["error"] == "model_revision_changed"


def test_busy_slot_returns_503_instead_of_queueing() -> None:
    service = GroundedService(StubRetriever(), StubModel())
    service.lock.acquire()
    try:
        with TestClient(create_app(service)) as client:
            response = client.post("/query", json={"question": "Counter?"})
        assert response.status_code == 503 and response.json()["error"] == "service_busy"
    finally:
        service.lock.release()


def test_prompt_budget_preserves_whole_source_ranges() -> None:
    retriever = StubRetriever()
    original = retriever.hits[0]
    oversized = original.model_copy(
        update={"chunk": original.chunk.model_copy(update={"text": "x" * 12000})}
    )
    messages, citations = build_prompt(QueryRequest(question="Counter?"), [oversized, original])
    assert list(citations) == ["S1"]
    assert len(SYSTEM_PROMPT.encode()) + len(messages[1]["content"].encode()) <= 6000
    assert citations["S1"].start_line == original.chunk.start_line


def test_trace_parentage_correlation_versions_and_metadata_only() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False, sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = Telemetry(provider)
    service = GroundedService(StubRetriever(), StubModel(), telemetry.tracer)
    with TestClient(create_app(service, telemetry=telemetry)) as client:
        response = client.post("/query", json={"question": "PRIVATE_QUESTION_MARKER Counter?"})
    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    root = next(span for span in spans if span.name == "POST /query")
    assert response.headers["X-Trace-ID"] == f"{root.context.trace_id:032x}"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]
    assert root.attributes is not None
    assert root.attributes["copilot.request_id"] == response.json()["request_id"]
    assert root.attributes["copilot.index_version"] == service.retriever.manifest.index_version
    for name in ("retrieval", "rerank", "generation", "citation_validation"):
        child = next(span for span in spans if span.name == name)
        assert child.parent and child.parent.span_id == root.context.span_id
    generation = next(span for span in spans if span.name == "generation")
    assert generation.attributes is not None
    assert generation.attributes["llm.token_count.completion"] == 30
    assert "PRIVATE_QUESTION_MARKER" not in "".join(span.to_json() for span in spans)
    assert "self.value += amount" not in "".join(span.to_json() for span in spans)


def test_error_and_validation_traces_keep_error_status_without_raw_output() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False, sampler=ALWAYS_ON)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    telemetry = Telemetry(provider)
    model = StubModel(
        ModelAnswer(
            statements=[SourceClaim(text="PRIVATE_MODEL_MARKER", source_ids=["S999"])],
            abstain=False,
            reason="",
        )
    )
    with TestClient(
        create_app(GroundedService(StubRetriever(), model, telemetry.tracer), telemetry=telemetry)
    ) as client:
        failed = client.post("/query", json={"question": "Counter?"})
        invalid = client.post("/query", json={"question": " "})
    assert failed.status_code == 502 and invalid.status_code == 422
    assert failed.headers["X-Trace-ID"] != invalid.headers["X-Trace-ID"]
    spans = exporter.get_finished_spans()
    roots = [span for span in spans if span.name == "POST /query"]
    assert len(roots) == 2 and all(span.status.status_code == StatusCode.ERROR for span in roots)
    validation = next(span for span in spans if span.name == "citation_validation")
    assert validation.status.status_code == StatusCode.ERROR
    assert "PRIVATE_MODEL_MARKER" not in "".join(span.to_json() for span in spans)
