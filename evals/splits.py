"""Source-only dataset separation and an explicit procedural holdout guard."""

import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from evals.comparison import digest, read_json
from evals.comparison_models import Digest
from evals.datasets import DatasetProfile, load_repository_dataset, read_profile
from indexing.corpus import Corpus


class DatasetSplit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    name: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    dev_profile: str = Field(pattern=r"^[a-z][a-z0-9-]*\.json$")
    holdout_profile: str = Field(pattern=r"^[a-z][a-z0-9-]*\.json$")
    dev_profile_sha256: Digest
    holdout_profile_sha256: Digest
    dev_status: Literal["previously-inspected-development"]
    holdout_policy: Literal["release-only-no-tuning"]
    separation: Literal["evidence-file-disjoint"]
    annotation_status: Literal["assistant-authored-awaiting-maintainer-review"]


def split_profiles(path: Path) -> tuple[DatasetSplit, DatasetProfile, DatasetProfile]:
    split = DatasetSplit.model_validate(read_json(path.read_bytes()))
    dev_path, holdout_path = path.parent / split.dev_profile, path.parent / split.holdout_profile
    if digest(dev_path.read_bytes()) != split.dev_profile_sha256 or (
        digest(holdout_path.read_bytes()) != split.holdout_profile_sha256
    ):
        raise ValueError("Dataset profile bytes differ from the split registry.")
    dev, holdout = read_profile(dev_path), read_profile(holdout_path)
    if dev.name == holdout.name:
        raise ValueError("Development and holdout names must differ.")
    for key in ("repo", "source_url", "commit_sha", "ingestion", "source_layout_sha256"):
        if getattr(dev, key) != getattr(holdout, key):
            raise ValueError("Dataset profiles must bind the same pinned source layout.")
    return split, dev, holdout


def validate_split(corpus: Corpus, path: Path) -> dict[str, object]:
    split, dev, holdout = split_profiles(path)
    dev_cases, dev_sha = load_repository_dataset(corpus, path.parent / split.dev_profile)
    holdout_cases, holdout_sha = load_repository_dataset(corpus, path.parent / split.holdout_profile)
    if {c.id for c in dev_cases} & {c.id for c in holdout_cases}:
        raise ValueError("Development and holdout case IDs overlap.")
    def normalize(text: str) -> str:
        return re.sub(r"\W+", " ", text.casefold()).strip()
    dev_questions = {normalize(c.question) for c in dev_cases}
    holdout_questions = {normalize(c.question) for c in holdout_cases}
    if len(dev_questions) != len(dev_cases) or len(holdout_questions) != len(holdout_cases) or (
        dev_questions & holdout_questions
    ):
        raise ValueError("Normalized questions overlap or are duplicated.")
    dev_files = {e.path for c in dev_cases for e in c.evidence}
    holdout_files = {e.path for c in holdout_cases for e in c.evidence}
    if dev_files & holdout_files:
        raise ValueError("Development and holdout evidence files overlap.")
    categories = {"locating", "explanation", "dependency", "debugging", "change-impact"}
    for cases in (dev_cases, holdout_cases):
        counts = Counter(c.category for c in cases)
        if set(counts) != categories or len(set(counts.values())) != 1:
            raise ValueError("Each split must balance the five task categories.")
    return {
        "development_cases": len(dev_cases),
        "holdout_cases": len(holdout_cases),
        "development_sha256": dev_sha,
        "holdout_sha256": holdout_sha,
        "development_evidence_files": sorted(dev_files),
        "holdout_evidence_files": sorted(holdout_files),
        "source_commit_sha": corpus.commit_sha,
        "source_validation_only": True,
        "holdout_model_evaluation_performed": False,
        "human_annotation_status": split.annotation_status,
    }


def dataset_role(profile: DatasetProfile, registry: Path, purpose: str) -> str:
    _, dev, holdout = split_profiles(registry)
    if profile.name == holdout.name or profile.questions_sha256 == holdout.questions_sha256:
        if profile != holdout:
            raise ValueError("Registered holdout profile was modified.")
        if purpose != "release":
            raise ValueError("Holdout evaluation requires explicit --purpose release; never tune on it.")
        return "holdout"
    if profile.name == dev.name or profile.questions_sha256 == dev.questions_sha256:
        if profile != dev:
            raise ValueError("Registered development profile was modified.")
        return "development"
    return "custom"
