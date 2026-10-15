"""Corpus configuration and citation-ready source records."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LanguageName = Literal["python", "go", "cpp", "markdown", "text"]


class IngestionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal["symbol-boundaries-v1", "symbol-method-boundaries-v2"] = (
        "symbol-boundaries-v1"
    )
    max_chars: int = Field(default=4000, ge=128, le=64000)
    max_file_bytes: int = Field(default=1048576, ge=1, le=16777216)
    max_total_bytes: int = Field(default=33554432, ge=1, le=268435456)
    max_files: int = Field(default=1000, ge=1, le=10000)


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    repo: str
    commit_sha: str
    path: str
    language: LanguageName
    symbol: str | None
    kind: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    part: int = Field(ge=1)
    content_sha256: str
    text: str = Field(min_length=1)
