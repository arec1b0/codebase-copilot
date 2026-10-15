"""Bind repository-specific questions to a pinned, portable source layout."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.contracts import EvalCase
from indexing.corpus import Corpus
from indexing.store import RetrievalHit
from ingestion.models import Chunk, IngestionConfig
from ingestion.pipeline import fingerprint


class DatasetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,79}$")
    repo: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    source_url: str = Field(pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    ingestion: IngestionConfig
    questions_file: str = Field(pattern=r"^[A-Za-z0-9_-]+\.jsonl$")
    questions_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_layout_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_count: int = Field(ge=30, le=50)
    annotation_origin: Literal["assistant-authored-from-source"]


def source_layout(chunks: list[Chunk]) -> str:
    """Exclude namespace/UUID/Python patch version; preserve text and source coordinates."""
    fields = {
        "path",
        "language",
        "symbol",
        "kind",
        "start_line",
        "end_line",
        "start_char",
        "end_char",
        "part",
        "content_sha256",
    }
    return fingerprint([chunk.model_dump(include=fields) for chunk in chunks])


def read_profile(path: Path) -> DatasetProfile:
    return DatasetProfile.model_validate_json(path.read_bytes())


def load_repository_dataset(corpus: Corpus, path: Path) -> tuple[list[EvalCase], str]:
    profile = read_profile(path)
    if corpus.repo != profile.repo or corpus.commit_sha != profile.commit_sha:
        raise ValueError("Corpus namespace or source commit differs from the dataset profile.")
    if source_layout(corpus.chunks) != profile.source_layout_sha256:
        raise ValueError("Corpus content or chunk layout differs from the dataset profile.")
    raw = (path.parent / profile.questions_file).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != profile.questions_sha256:
        raise ValueError("Question bytes differ from the dataset profile.")
    cases = [EvalCase.model_validate_json(line) for line in raw.splitlines()]
    if len(cases) != profile.case_count or len({case.id for case in cases}) != len(cases):
        raise ValueError("Question count or unique case IDs differ from the dataset contract.")
    hits = [
        RetrievalHit(
            index_version="validation", corpus_version=corpus.version, score=0, chunk=chunk
        )
        for chunk in corpus.chunks
    ]
    for case in cases:
        for target in case.evidence:
            if target.quote is None or target.end_line < target.start_line:
                raise ValueError(f"A repository evidence range/quote is missing for {case.id}.")
            if not any(hit.chunk.language == case.language and target.matches(hit) for hit in hits):
                raise ValueError(f"Source evidence is not contained in one chunk for {case.id}.")
    return cases, digest
