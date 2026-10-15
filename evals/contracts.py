"""Evaluation labels refer to source ranges, independent of chunk UUIDs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from indexing.store import RetrievalHit
from ingestion.models import LanguageName


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str | None = Field(default=None, min_length=1, max_length=1000)

    def matches(self, hit: RetrievalHit) -> bool:
        chunk = hit.chunk
        return (
            chunk.path == self.path
            and chunk.start_line <= self.start_line
            and chunk.end_line >= self.end_line
            and (
                self.quote is None
                or self.quote
                in "\n".join(
                    chunk.text.split("\n")[
                        self.start_line - chunk.start_line : self.end_line - chunk.start_line + 1
                    ]
                )
            )
        )


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z]+-[0-9]{2}$")
    category: Literal["locating", "explanation", "dependency", "debugging", "change-impact"]
    question: str = Field(min_length=1, max_length=1024)
    language: LanguageName
    reference: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(min_length=1)


class JudgeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    faithfulness: int = Field(ge=0, le=2)
    relevance: int = Field(ge=0, le=2)
    faithfulness_reason: str = Field(min_length=1, max_length=500)
    relevance_reason: str = Field(min_length=1, max_length=500)


def retrieval_metrics(case: EvalCase, hits: list[RetrievalHit]) -> dict[str, float]:
    covered = [any(target.matches(hit) for hit in hits) for target in case.evidence]
    rank = next(
        (
            index
            for index, hit in enumerate(hits, 1)
            if any(target.matches(hit) for target in case.evidence)
        ),
        None,
    )
    return {
        "hit": float(any(covered)),
        "recall": sum(covered) / len(covered),
        "reciprocal_rank": 1 / rank if rank else 0.0,
    }
