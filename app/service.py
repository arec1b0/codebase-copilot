"""One pinned source snapshot, bounded context, and validated citations."""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from openinference.semconv.trace import SpanAttributes
from opentelemetry import trace
from opentelemetry.trace import Tracer
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.contracts import (
    Citation,
    ModelAnswer,
    ModelIdentity,
    QueryRequest,
    QueryResponse,
    TokenUsage,
)
from app.model import ModelBackend, OllamaModel, QueryError
from app.prompt import PROMPT_SHA256, PROMPT_VERSION, build_prompt
from indexing.config import ROOT, connect
from indexing.corpus import IndexingError, load_corpus
from indexing.embeddings import CpuEmbeddings, EmbeddingBackend
from indexing.store import IndexManifest, RetrievalHit, load_manifest, search, validate_schema
from ingestion.models import Chunk, LanguageName
from observability.tracing import current_trace_id, stage


class Retriever(Protocol):
    manifest: IndexManifest

    def check(self) -> None: ...
    def retrieve(
        self, query: str, top_k: int, language: LanguageName | None
    ) -> list[RetrievalHit]: ...
    def close(self) -> None: ...


class QueryService(Protocol):
    def check_ready(self) -> None: ...
    def answer(self, request: QueryRequest, request_id: UUID) -> QueryResponse: ...
    def close(self) -> None: ...


def render_answer(
    content: ModelAnswer, available: dict[str, Citation]
) -> tuple[str, list[Citation]]:
    """Validate claim provenance and render all displayed citation markers here."""
    labels = re.compile(r"\[\s*S[^\]]*\]")
    if content.abstain:
        if content.statements or labels.search(content.reason):
            raise QueryError("invalid_citations", "An abstention cannot claim cited evidence.")
        reason = content.reason.strip()
        if not reason:
            raise QueryError("invalid_model_output", "An abstention must explain missing evidence.")
        return reason, []
    if not content.statements:
        raise QueryError("invalid_citations", "An answer must contain sourced statements.")
    parts: list[str] = []
    used: dict[str, Citation] = {}
    for statement in content.statements:
        ids = statement.source_ids
        if len(set(ids)) != len(ids) or any(label not in available for label in ids):
            raise QueryError("invalid_citations", "Model cited unknown or duplicate source labels.")
        inline = {match[1:-1] for match in labels.findall(statement.text)}
        if not inline.issubset(ids):
            raise QueryError("invalid_citations", "Statement contains an undeclared source label.")
        # Redundant valid markers are removed before adding the canonical markers.
        text = labels.sub("", statement.text).strip()
        if not text:
            raise QueryError("invalid_model_output", "A sourced statement cannot be blank.")
        parts.append(text + " " + " ".join(f"[{label}]" for label in ids))
        for label in ids:
            used.setdefault(label, available[label])
    return "\n\n".join(parts), list(used.values())


class QdrantRetriever:
    def __init__(
        self,
        client: QdrantClient,
        manifest: IndexManifest,
        backend: EmbeddingBackend,
        expected_chunks: list[Chunk],
    ) -> None:
        self.client, self.manifest, self.backend = client, manifest, backend
        self.expected = {chunk.chunk_id: chunk for chunk in expected_chunks}

    def check(self) -> None:
        validate_schema(self.client, self.manifest)
        if (
            self.client.count(self.manifest.collection, exact=True).count
            != self.manifest.chunk_count
        ):
            raise IndexingError("Index point count differs from its pinned manifest.")
        if self.backend.identity != self.manifest.embeddings:
            raise IndexingError("Embedding assets differ from the pinned index.")

    def retrieve(self, query: str, top_k: int, language: LanguageName | None) -> list[RetrievalHit]:
        hits = search(
            self.client, self.manifest, self.backend, query, top_k=top_k, language=language
        )
        for hit in hits:
            if hit.chunk != self.expected.get(hit.chunk.chunk_id):
                raise IndexingError("Retrieved content differs from the saved source corpus.")
        return hits

    def close(self) -> None:
        self.client.close()


class GroundedService:
    def __init__(
        self, retriever: Retriever, model: ModelBackend, tracer: Tracer | None = None
    ) -> None:
        self.retriever, self.model = retriever, model
        self.tracer = tracer or trace.NoOpTracer()
        self.identity: ModelIdentity = model.identity()
        self.lock = threading.Lock()

    def check_ready(self) -> None:
        self.retriever.check()
        if self.model.identity() != self.identity:
            raise QueryError(
                "model_revision_changed", "Pinned model identity changed. Restart the API.", 503
            )

    def answer(self, request: QueryRequest, request_id: UUID) -> QueryResponse:
        if not self.lock.acquire(blocking=False):
            raise QueryError("service_busy", "The local generation slot is busy.", 503)
        try:
            start = time.perf_counter()
            root = trace.get_current_span()
            root.set_attributes(
                {
                    "copilot.index_version": self.retriever.manifest.index_version,
                    "copilot.corpus_version": self.retriever.manifest.corpus_version,
                    "copilot.commit_sha": self.retriever.manifest.commit_sha,
                    "copilot.model_revision": self.identity.revision,
                    "copilot.model_backend_version": self.identity.backend_version,
                    "copilot.prompt_version": PROMPT_VERSION,
                    "copilot.prompt_sha256": PROMPT_SHA256,
                }
            )
            with stage(self.tracer, "readiness", "CHAIN"):
                self.check_ready()
            retrieval_start = time.perf_counter()
            with stage(self.tracer, "retrieval", "RETRIEVER") as span:
                hits = self.retriever.retrieve(request.question, request.top_k, request.language)
                span.set_attributes(
                    {
                        "copilot.retrieval.top_k": request.top_k,
                        "copilot.retrieval.language": request.language or "all",
                        "copilot.retrieval.hit_count": len(hits),
                        "copilot.retrieval.chunk_ids": [hit.chunk.chunk_id for hit in hits],
                    }
                )
                for index, hit in enumerate(hits):
                    prefix = f"retrieval.documents.{index}.document"
                    span.set_attributes(
                        {
                            prefix + ".id": hit.chunk.chunk_id,
                            prefix + ".score": hit.score,
                            prefix + ".metadata": json.dumps(
                                {
                                    "path": hit.chunk.path,
                                    "symbol": hit.chunk.symbol,
                                    "start_line": hit.chunk.start_line,
                                    "end_line": hit.chunk.end_line,
                                }
                            ),
                        }
                    )
            retrieval_ms = (time.perf_counter() - retrieval_start) * 1000
            with stage(
                self.tracer,
                "rerank",
                "RERANKER",
                {
                    "copilot.rerank.enabled": False,
                    "copilot.rerank.strategy": "preserve_rrf_order",
                },
            ) as span:
                messages, available = build_prompt(request, hits)
                span.set_attribute("copilot.context.source_count", len(available))
                span.set_attribute(
                    "copilot.context.chunk_ids", [c.chunk_id for c in available.values()]
                )
            citations: list[Citation] = []
            usage = TokenUsage(input_tokens=0, output_tokens=0)
            ttft = None
            generation_ms = 0.0
            status = "insufficient_context"
            answer = "No retrieved sources fit the query and context budget."
            if available:
                with stage(
                    self.tracer,
                    "generation",
                    "LLM",
                    {
                        SpanAttributes.LLM_MODEL_NAME: self.identity.model,
                        "copilot.model_revision": self.identity.revision,
                        "copilot.prompt_version": PROMPT_VERSION,
                    },
                ) as span:
                    generation = self.model.generate(messages, list(available))
                    span.set_attributes(
                        {
                            SpanAttributes.LLM_TOKEN_COUNT_PROMPT: generation.usage.input_tokens,
                            SpanAttributes.LLM_TOKEN_COUNT_COMPLETION: (
                                generation.usage.output_tokens
                            ),
                            "copilot.model_ttft_ms": generation.ttft_ms,
                            "copilot.generation_ms": generation.latency_ms,
                        }
                    )
                if self.model.identity() != self.identity:
                    raise QueryError(
                        "model_revision_changed", "Model identity changed during generation.", 503
                    )
                content = generation.content
                with stage(self.tracer, "citation_validation", "GUARDRAIL"):
                    answer, citations = render_answer(content, available)
                if not content.abstain:
                    status = "answered"
                usage, ttft, generation_ms = (
                    generation.usage,
                    generation.ttft_ms,
                    generation.latency_ms,
                )
            manifest = self.retriever.manifest
            root.set_attributes(
                {
                    "copilot.answer_status": status,
                    "copilot.citation_count": len(citations),
                    "copilot.retrieval_ms": retrieval_ms,
                    "copilot.generation_ms": generation_ms,
                }
            )
            return QueryResponse.model_validate(
                {
                    "request_id": request_id,
                    "trace_id": current_trace_id(),
                    "status": status,
                    "answer": answer,
                    "citations": citations,
                    "model": self.identity.model,
                    "model_revision": self.identity.revision,
                    "model_backend_version": self.identity.backend_version,
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": PROMPT_SHA256,
                    "index_version": manifest.index_version,
                    "corpus_version": manifest.corpus_version,
                    "repo": manifest.repo,
                    "commit_sha": manifest.commit_sha,
                    "usage": usage,
                    "retrieval_ms": retrieval_ms,
                    "generation_ms": generation_ms,
                    "model_ttft_ms": ttft,
                    "total_ms": (time.perf_counter() - start) * 1000,
                }
            )
        except (IndexingError, UnexpectedResponse, ResponseHandlingException):
            raise QueryError(
                "retrieval_unavailable",
                "Pinned retrieval index is unavailable or incompatible.",
                503,
            ) from None
        finally:
            self.lock.release()

    def close(self) -> None:
        self.model.close()
        self.retriever.close()


def build_service(tracer: Tracer | None = None) -> GroundedService:
    selected = os.environ.get("COPILOT_INDEX_MANIFEST")
    if not selected:
        raise QueryError(
            "index_not_configured", "Set COPILOT_INDEX_MANIFEST before starting the API.", 503
        )
    manifest = load_manifest(Path(selected))
    corpus = load_corpus(ROOT / "artifacts" / "corpora" / manifest.repo / manifest.corpus_version)
    if corpus.sha256 != manifest.corpus_sha256 or corpus.commit_sha != manifest.commit_sha:
        raise IndexingError("Local source corpus differs from the pinned index manifest.")
    base_url = os.environ.get("COPILOT_OLLAMA_URL", "http://127.0.0.1:11434")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise QueryError(
            "invalid_model_endpoint", "Ollama URL must point to the local server root.", 503
        )
    client = connect()
    model: OllamaModel | None = None
    try:
        validate_schema(client, manifest)
        backend = CpuEmbeddings(ROOT / "artifacts" / "models", local_only=True)
        retriever = QdrantRetriever(client, manifest, backend, corpus.chunks)
        retriever.check()
        model = OllamaModel(base_url, "qwen2.5-coder:3b")
        return GroundedService(retriever, model, tracer)
    except Exception:
        client.close()
        if model is not None:
            model.close()
        raise
