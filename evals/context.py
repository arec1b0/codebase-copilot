"""Validate recorded generator context without substituting independent retrieval."""

from app.contracts import QueryRequest, QueryResponse
from app.prompt import PROMPT_SHA256, build_prompt, input_sha256
from indexing.store import RetrievalHit
from ingestion.models import Chunk, LanguageName


def context_issues(
    body: QueryResponse,
    chunks: dict[str, Chunk],
    question: str,
    language: LanguageName | None,
    top_k: int = 3,
) -> list[str]:
    sources = body.context_sources
    if sources is None:
        return ["context_hash_without_context"] if body.generation_input_sha256 else []
    problems = []
    if len(sources) > top_k or [c.source_id for c in sources] != [
        f"S{i}" for i in range(1, len(sources) + 1)
    ]:
        problems.append("invalid_context_labels")
    if len({c.chunk_id for c in sources}) != len(sources):
        problems.append("duplicate_context_chunk")
    fields = ("repo", "commit_sha", "path", "symbol", "start_line", "end_line")
    for source in sources:
        chunk = chunks.get(source.chunk_id)
        if chunk is None or any(getattr(source, f) != getattr(chunk, f) for f in fields):
            problems.append("context_source_mismatch")
        elif (
            chunk.repo != body.repo
            or chunk.commit_sha != body.commit_sha
            or (language is not None and chunk.language != language)
        ):
            problems.append("context_source_mismatch")
    available = {c.source_id: c for c in sources}
    if any(c != available.get(c.source_id) for c in body.citations):
        problems.append("citation_context_mismatch")
    if not sources:
        if body.generation_input_sha256 is not None or body.status == "answered":
            problems.append("invalid_empty_context")
    elif body.generation_input_sha256 is None:
        problems.append("missing_context_hash")
    # Historical prompts with another declared hash cannot be reconstructed here.
    if not problems and sources and body.prompt_sha256 == PROMPT_SHA256:
        hits = [
            RetrievalHit(
                index_version=body.index_version,
                corpus_version=body.corpus_version,
                score=0.0,
                chunk=chunks[c.chunk_id],
            )
            for c in sources
        ]
        messages, rebuilt = build_prompt(
            QueryRequest(question=question, language=language, top_k=top_k), hits
        )
        if (
            list(rebuilt.values()) != sources
            or input_sha256(messages) != body.generation_input_sha256
        ):
            problems.append("context_input_hash_mismatch")
    return sorted(set(problems))
