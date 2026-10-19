"""Build source-bound review packets and audit explicitly entered human labels."""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from evals.comparison import digest, read_json, response_issues
from evals.comparison_models import Digest, RunManifest, SavedRow
from evals.contracts import EvalCase
from evals.datasets import load_repository_dataset, read_profile
from indexing.config import ROOT
from indexing.corpus import Corpus, IndexingError, load_corpus
from ingestion.models import Chunk
from ingestion.pipeline import fingerprint

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Score = Annotated[int, Field(strict=True, ge=0, le=2)]
IMMUTABLE_FILES = {
    "items.jsonl",
    "rubric.md",
    "faithfulness.md",
    "relevance.md",
    "SOURCE-LICENSE.txt",
    "README.md",
}
PROVENANCE_FIELDS = (
    "source_results_raw_sha256",
    "source_corpus_version",
    "declared_judge_identity",
    "runtime_manifest_sha256",
)


class ReviewSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    name: Text
    sampling: Literal["purposive-development-sample"]
    results_canonical_sha256: Digest
    dataset_sha256: Digest
    case_ids: list[str] = Field(min_length=20, max_length=20)


class ReviewSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(pattern=r"^S[1-3]$")
    chunk: Chunk


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case: EvalCase
    answer: str
    request_id: str
    sources: list[ReviewSource] = Field(min_length=1)


class HumanLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str
    item_sha256: Digest
    faithfulness: Score | None = None
    faithfulness_reason: Text | None = None
    relevance: Score | None = None
    relevance_reason: Text | None = None
    reference_issue: bool = False
    notes: Text | None = None


class HumanLabels(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    packet_id: Digest
    label_origin: Literal["human"] | None = None
    annotator: Text | None = None
    reviewed_at: AwareDatetime | None = None
    labels: list[HumanLabel] = Field(min_length=20, max_length=20)


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )


def review_rows(results: Path, corpus: Corpus, profile: Path) -> tuple[dict[str, SavedRow], str]:
    cases, _ = load_repository_dataset(corpus, profile)
    values = [read_json(line) for line in results.read_bytes().splitlines()]
    rows = [SavedRow.model_validate_json(json.dumps(value, allow_nan=False)) for value in values]
    by_id = {row.case_id: row for row in rows}
    expected = {case.id: case for case in cases}
    if len(by_id) != len(rows) or set(by_id) != set(expected):
        raise ValueError("Review results must contain the exact complete development dataset.")
    chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
    for row in rows:
        body = row.response
        if row.case != expected[row.case_id] or row.case.id != row.case_id:
            raise ValueError("Question, reference or evidence changed in saved review results.")
        if row.error is not None or row.judge is None or body is None:
            raise ValueError("Review requires successful responses and saved judge assessments.")
        if body.status != "answered" or response_issues(row, chunks):
            raise ValueError("Answer citations or response metadata are invalid.")
        if body.repo != corpus.repo or body.commit_sha != corpus.commit_sha:
            raise ValueError("Review response belongs to another pinned source.")
        if row.retrieved_chunks is None or any(
            hit.chunk != chunks.get(hit.chunk.chunk_id) for hit in row.retrieved_chunks
        ):
            raise ValueError("Saved retrieval text differs from the pinned source.")
    return by_id, fingerprint(values)


def fenced(value: str) -> str:
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{value}\n{fence}\n"


def review_view(items: list[ReviewItem], dimension: str) -> str:
    sections = [f"# {dimension.title()} review\n", "Read rubric.md before assigning scores.\n"]
    for item in items:
        sections.append(f"## {item.case.id}\n")
        if dimension == "relevance":
            sections.extend(
                [
                    "Question:\n" + fenced(item.case.question),
                    "Reference:\n" + fenced(item.case.reference),
                ]
            )
        sections.append("Answer:\n" + fenced(item.answer))
        if dimension == "faithfulness":
            for source in item.sources:
                chunk = source.chunk
                sections.append(
                    f"[{source.source_id}] {chunk.path}:{chunk.start_line}-{chunk.end_line} "
                    f"({chunk.symbol})\n" + fenced(chunk.text)
                )
    return "\n".join(sections)


def create_packet(
    results: Path,
    corpus: Corpus,
    profile_path: Path,
    selection_path: Path,
    rubric_path: Path,
    output: Path,
    *,
    run_manifest: Path | None = None,
) -> dict[str, Any]:
    rows, canonical_sha = review_rows(results, corpus, profile_path)
    selection = ReviewSelection.model_validate(read_json(selection_path.read_bytes()))
    profile = read_profile(profile_path)
    if canonical_sha != selection.results_canonical_sha256 or (
        profile.questions_sha256 != selection.dataset_sha256
    ):
        raise ValueError("Selection does not bind these saved results and development dataset.")
    if len(set(selection.case_ids)) != 20 or not set(selection.case_ids) <= rows.keys():
        raise ValueError("Review selection requires 20 unique existing cases.")
    if Counter(rows[key].case.category for key in selection.case_ids) != {
        name: 4 for name in ("locating", "explanation", "dependency", "debugging", "change-impact")
    }:
        raise ValueError("Review selection requires four cases in each task category.")
    declared_judge: dict[str, Any] | None = None
    if run_manifest is not None:
        versions = RunManifest.model_validate(read_json(run_manifest.read_bytes()))
        if versions.dataset_sha256 != profile.questions_sha256 or (
            versions.source_commit_sha != corpus.commit_sha
        ):
            raise ValueError("Runtime manifest differs from the review dataset or source.")
        for row in rows.values():
            assert row.response is not None
            for key in (
                "model",
                "model_revision",
                "model_backend_version",
                "prompt_version",
                "prompt_sha256",
            ):
                if getattr(row.response, key) != getattr(versions, key):
                    raise ValueError("Saved response differs from the declared runtime manifest.")
            if row.response.index_version != versions.index.index_version:
                raise ValueError("Saved response differs from the declared index.")
        declared_judge = versions.judge.model_dump(mode="json")
    chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
    items: list[ReviewItem] = []
    for key in selection.case_ids:
        row = rows[key]
        assert row.response is not None
        items.append(
            ReviewItem(
                case=row.case,
                answer=row.response.answer,
                request_id=str(row.response.request_id),
                sources=[
                    ReviewSource(source_id=c.source_id, chunk=chunks[c.chunk_id])
                    for c in row.response.citations
                ],
            )
        )
    raw_items = ("\n".join(item.model_dump_json() for item in items) + "\n").encode("utf-8")
    identity = {
        "results_canonical_sha256": canonical_sha,
        "dev_dataset_sha256": profile.questions_sha256,
        "source_commit_sha": corpus.commit_sha,
        "source_layout_sha256": profile.source_layout_sha256,
        "selection_sha256": digest(selection_path.read_bytes()),
        "rubric_sha256": digest(rubric_path.read_bytes()),
        "items_sha256": digest(raw_items),
    }
    packet_id = fingerprint(identity)
    item_hashes = {item.case.id: fingerprint(item.model_dump(mode="json")) for item in items}
    labels = HumanLabels(
        packet_id=packet_id,
        labels=[
            HumanLabel(case_id=item.case.id, item_sha256=item_hashes[item.case.id])
            for item in items
        ],
    )
    # Refuse an existing directory so a rerun cannot overwrite human annotations.
    output.mkdir(parents=True, exist_ok=False)
    (output / "items.jsonl").write_bytes(raw_items)
    (output / "rubric.md").write_bytes(rubric_path.read_bytes())
    (output / "SOURCE-LICENSE.txt").write_bytes(
        (profile_path.parent / "SOURCE-LICENSE.txt").read_bytes()
    )
    (output / "faithfulness.md").write_bytes(review_view(items, "faithfulness").encode("utf-8"))
    (output / "relevance.md").write_bytes(review_view(items, "relevance").encode("utf-8"))
    (output / "README.md").write_bytes(
        b"# Development human review packet\n\n"
        b"Read rubric.md, then faithfulness.md, then relevance.md. Edit labels.json only.\n"
        b"All scores and reviewer fields start null; a human must supply all 20 labels.\n"
        b"This is a purposive development sample, not a holdout or a population estimate.\n"
        b"Question/reference and judge ratings are omitted from the faithfulness view.\n"
        b"Judge ratings are omitted from both views. Prior exposure can still bias review.\n"
        b"The source is pinned and checked; historical runtime provenance is declared only.\n"
        b"Without the optional original manifest, judge identity is unavailable.\n"
        b"Run evals.human_review validate --require-complete before audit.\n"
        b"Agreement alone never sets calibrated=true or approves release thresholds.\n"
    )
    provenance = {
        "source_results_raw_sha256": digest(results.read_bytes()),
        "source_corpus_version": corpus.version,
        "declared_judge_identity": declared_judge,
        "runtime_manifest_sha256": digest(run_manifest.read_bytes()) if run_manifest else None,
    }
    metadata = {
        "schema_version": 1,
        "packet_id": packet_id,
        "identity": identity,
        **provenance,
        "provenance_sha256": fingerprint(provenance),
        "sampling": selection.sampling,
        "item_sha256": item_hashes,
        "immutable_files": {
            name: digest((output / name).read_bytes()) for name in sorted(IMMUTABLE_FILES)
        },
        "provenance_scope": "saved-results-and-pinned-source",
        "calibrated": False,
    }
    write_json(output / "packet.json", metadata)
    write_json(output / "labels.json", labels.model_dump(mode="json"))
    return metadata


def validate_packet(
    packet: Path,
    labels_path: Path | None = None,
) -> tuple[HumanLabels, dict[str, Any]]:
    metadata = read_json((packet / "packet.json").read_bytes())
    if (
        metadata["schema_version"] != 1
        or fingerprint(metadata["identity"]) != metadata["packet_id"]
    ):
        raise ValueError("Review packet identity changed.")
    provenance = {key: metadata[key] for key in PROVENANCE_FIELDS}
    if fingerprint(provenance) != metadata["provenance_sha256"]:
        raise ValueError("Review packet provenance changed.")
    immutable = metadata["immutable_files"]
    if set(immutable) != IMMUTABLE_FILES:
        raise ValueError("Review packet has an invalid immutable file set.")
    for name, expected in immutable.items():
        if digest((packet / name).read_bytes()) != expected:
            raise ValueError(f"Review packet content changed: {name}")
    for field, name in (("items_sha256", "items.jsonl"), ("rubric_sha256", "rubric.md")):
        if metadata["identity"][field] != immutable[name]:
            raise ValueError("Review packet identity and file checksums disagree.")
    items = [
        ReviewItem.model_validate_json(line)
        for line in (packet / "items.jsonl").read_bytes().splitlines()
    ]
    item_hashes = {item.case.id: fingerprint(item.model_dump(mode="json")) for item in items}
    if len(items) != 20 or len(item_hashes) != 20 or item_hashes != metadata["item_sha256"]:
        raise ValueError("Review items changed or are duplicated.")
    labels = HumanLabels.model_validate_json((labels_path or packet / "labels.json").read_bytes())
    if labels.packet_id != metadata["packet_id"] or len({x.case_id for x in labels.labels}) != 20:
        raise ValueError("Labels do not bind the exact review packet.")
    if {x.case_id: x.item_sha256 for x in labels.labels} != item_hashes:
        raise ValueError("Labels do not bind the exact review items.")
    for label in labels.labels:
        if label.reference_issue and label.notes is None:
            raise ValueError("A reference issue requires adjudication notes.")
    completed = sum(
        label.faithfulness is not None
        and label.relevance is not None
        and label.faithfulness_reason is not None
        and label.relevance_reason is not None
        and not label.reference_issue
        for label in labels.labels
    )
    attested = (
        labels.annotator is not None
        and labels.reviewed_at is not None
        and labels.label_origin == "human"
    )
    return labels, {
        "packet_id": labels.packet_id,
        "completed": completed,
        "pending": 20 - completed,
        "human_attestation_present": attested,
        "ready_for_agreement_audit": completed == 20 and attested,
        "calibrated": False,
    }


def agreement_audit(
    packet: Path,
    results: Path,
    labels_path: Path | None = None,
) -> dict[str, Any]:
    labels, state = validate_packet(packet, labels_path)
    if not state["ready_for_agreement_audit"]:
        raise ValueError("Human labels are pending or reviewer attestation is missing.")
    metadata = read_json((packet / "packet.json").read_bytes())
    values = [read_json(line) for line in results.read_bytes().splitlines()]
    if fingerprint(values) != metadata["identity"]["results_canonical_sha256"]:
        raise ValueError("Audit results differ from the reviewed historical results.")
    rows = {
        row.case_id: row
        for row in (
            SavedRow.model_validate_json(json.dumps(value, allow_nan=False)) for value in values
        )
    }
    differences: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for dimension in ("faithfulness", "relevance"):
        distances: list[int] = []
        for label in labels.labels:
            judge = rows[label.case_id].judge
            if judge is None:
                raise ValueError("Saved judge assessment is missing.")
            human_score = getattr(label, dimension)
            judge_score = getattr(judge, dimension)
            distance = abs(human_score - judge_score)
            distances.append(distance)
            differences.append(
                {
                    "case_id": label.case_id,
                    "dimension": dimension,
                    "human": human_score,
                    "judge": judge_score,
                    "absolute_difference": distance,
                }
            )
        summary[dimension] = {
            "n": 20,
            "exact_agreement": distances.count(0) / 20,
            "mean_absolute_error": sum(distances) / 20,
        }
    return {
        "schema_version": 1,
        "packet_id": labels.packet_id,
        "sampling": metadata["sampling"],
        "labels_sha256": digest((labels_path or packet / "labels.json").read_bytes()),
        "declared_judge_identity": metadata["declared_judge_identity"],
        "runtime_manifest_sha256": metadata["runtime_manifest_sha256"],
        "summary": summary,
        "differences": differences,
        "calibrated": False,
        "release_threshold_approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--results", type=Path, required=True)
    create.add_argument("--corpus", type=Path, required=True)
    create.add_argument(
        "--profile", type=Path, default=ROOT / "evals/datasets/kubesentiment/profile.json"
    )
    create.add_argument("--selection", type=Path, default=ROOT / "evals/review/selection-v1.json")
    create.add_argument("--rubric", type=Path, default=ROOT / "evals/review/rubric-v1.md")
    create.add_argument("--run-manifest", type=Path)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--packet", type=Path, required=True)
    validate.add_argument("--labels", type=Path)
    validate.add_argument("--require-complete", action="store_true")
    audit = commands.add_parser("audit")
    audit.add_argument("--packet", type=Path, required=True)
    audit.add_argument("--labels", type=Path)
    audit.add_argument("--results", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_packet(
                args.results,
                load_corpus(args.corpus),
                args.profile,
                args.selection,
                args.rubric,
                args.output,
                run_manifest=args.run_manifest,
            )
        elif args.command == "validate":
            _, result = validate_packet(args.packet, args.labels)
            print(json.dumps(result, indent=2))
            return 3 if args.require_complete and not result["ready_for_agreement_audit"] else 0
        else:
            result = agreement_audit(args.packet, args.results, args.labels)
            with args.output.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(result, handle, indent=2, allow_nan=False)
                handle.write("\n")
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, IndexingError, KeyError, TypeError) as exc:
        print(f"Human review failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
