"""Request, response, and structured generation contracts."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ingestion.models import LanguageName


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)
    ]
    language: LanguageName | None = None
    top_k: int = Field(default=3, ge=1, le=5, strict=True)


class SourceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    source_ids: list[str] = Field(min_length=1, max_length=5)


class ModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    statements: list[SourceClaim] = Field(max_length=3)
    abstain: bool
    reason: str = Field(max_length=1000)


class ModelIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model: str
    revision: str
    backend_version: str


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)


class Generation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    content: ModelAnswer
    usage: TokenUsage
    ttft_ms: float = Field(ge=0)
    latency_ms: float = Field(ge=0)


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: str
    chunk_id: str
    repo: str
    commit_sha: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int


class QueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    trace_id: str | None = None
    status: Literal["answered", "insufficient_context"]
    answer: str
    citations: list[Citation]
    # None means a historical response did not record its actual context.
    context_sources: list[Citation] | None = Field(default=None, max_length=5)
    generation_input_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model: str
    model_revision: str
    model_backend_version: str
    prompt_version: str
    prompt_sha256: str
    index_version: str
    corpus_version: str
    repo: str
    commit_sha: str
    usage: TokenUsage
    retrieval_ms: float
    generation_ms: float
    model_ttft_ms: float | None
    total_ms: float
