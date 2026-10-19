"""Saved-run contracts and an explicit, provisional regression policy."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import QueryResponse, TokenUsage
from evals.contracts import EvalCase, JudgeAssessment
from indexing.store import IndexManifest, RetrievalHit

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class JudgeIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    rubric_sha256: Digest
    calibrated: bool
    same_model_as_generator: bool


class RunManifest(BaseModel):
    # Retain historical runtime fields without requiring the current API version.
    model_config = ConfigDict(extra="allow", strict=True)
    dataset_sha256: Digest
    dataset_name: str = Field(min_length=1)
    source_commit_sha: str = Field(pattern=r"^[a-f0-9]{40}(?:[a-f0-9]{24})?$")
    corpus_version: Digest
    index: IndexManifest
    model: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    model_backend_version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: Digest
    judge: JudgeIdentity


class SavedRetrieval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hit: Unit
    recall: Unit
    reciprocal_rank: Unit


class SavedError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: str = Field(min_length=1)
    detail: str


class SavedRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case: EvalCase
    case_id: str
    retrieval: SavedRetrieval | None = None
    retrieved_chunks: list[RetrievalHit] | None = None
    response: QueryResponse | None = None
    client_ms: Nonnegative | None = None
    model_ttft_ms: Nonnegative | None = None
    judge: JudgeAssessment | None = None
    judge_usage: TokenUsage | None = None
    error: SavedError | None = None


class RetrievalTolerances(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    hit_rate_at_3: Unit = 0.0
    recall_at_3: Unit = 0.0
    mrr_at_3: Unit = 0.0


class RegressionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    stage: Literal["provisional-development"] = "provisional-development"
    max_retrieval_drop: RetrievalTolerances = Field(default_factory=RetrievalTolerances)
    gate_judge_scores: bool = False
    max_judge_drop: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] = 0.0
