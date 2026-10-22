"""Re-score frozen development answers against completed human labels; never regenerate."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.model import OllamaModel, QueryError
from evals.comparison import digest, load_run, read_json
from evals.comparison_models import JudgeIdentity
from evals.contracts import JudgeAssessment
from evals.human_review import (
    HumanLabels,
    ReviewItem,
    agreement_audit,
    validate_packet,
    write_json,
)
from evals.judge import DIMENSIONS, RUBRIC_HASHES, RUBRIC_SHA256, RUBRIC_VERSION, assess
from evals.versions import source_hashes
from indexing.config import ROOT
from indexing.corpus import IndexingError, load_corpus


def agreement(labels: HumanLabels, scores: dict[str, JudgeAssessment]) -> dict[str, Any]:
    if set(scores) != {label.case_id for label in labels.labels}:
        raise ValueError("Agreement requires the exact complete set of reviewed cases.")
    summary: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        pairs = []
        for label in labels.labels:
            human = getattr(label, dimension)
            if human is None:
                raise ValueError("Human score is missing.")
            pairs.append((human, getattr(scores[label.case_id], dimension)))
        summary[dimension] = {
            "n": len(pairs),
            "exact_agreement": sum(h == j for h, j in pairs) / len(pairs),
            "mean_absolute_error": sum(abs(h - j) for h, j in pairs) / len(pairs),
            "human_zero_cases": sum(h == 0 for h, j in pairs),
            "human_zero_judge_nonzero": sum(h == 0 and j != 0 for h, j in pairs),
        }
    return summary


def rejudge(
    baseline: Path,
    packet: Path,
    corpora_root: Path,
    output: Path,
    model: OllamaModel,
    labels_path: Path | None = None,
    *,
    allow_backend_change: bool = False,
) -> dict[str, Any]:
    # All local integrity and completeness checks precede model identity/network calls.
    run = load_run(baseline, corpora_root)
    if run.issues:
        raise ValueError("Historical baseline contains technical issues.")
    labels, state = validate_packet(packet, labels_path)
    old_audit = agreement_audit(packet, baseline / "results.jsonl", labels_path)
    if not state["ready_for_agreement_audit"]:
        raise ValueError("Human review is incomplete.")
    metadata = read_json((packet / "packet.json").read_bytes())
    if metadata["identity"]["dev_dataset_sha256"] != run.versions.dataset_sha256 or (
        metadata["identity"]["source_commit_sha"] != run.versions.source_commit_sha
    ):
        raise ValueError("Packet belongs to another dataset or source commit.")
    if (
        metadata["declared_judge_identity"] is not None
        and JudgeIdentity.model_validate(metadata["declared_judge_identity"]) != run.versions.judge
    ):
        raise ValueError("Packet declares a different historical judge.")
    corpus_dir = corpora_root / run.versions.index.repo / run.versions.index.corpus_version
    corpus = load_corpus(corpus_dir)
    chunks = {chunk.chunk_id: chunk for chunk in corpus.chunks}
    items = [
        ReviewItem.model_validate_json(line)
        for line in (packet / "items.jsonl").read_bytes().splitlines()
    ]
    for item in items:
        row = run.rows[item.case.id]
        body = row.response
        if (
            body is None
            or item.case != row.case
            or item.answer != body.answer
            or (item.request_id != str(body.request_id))
        ):
            raise ValueError("Review item differs from its frozen historical answer.")
        if [(s.source_id, s.chunk.chunk_id) for s in item.sources] != [
            (c.source_id, c.chunk_id) for c in body.citations
        ] or any(source.chunk != chunks.get(source.chunk.chunk_id) for source in item.sources):
            raise ValueError("Review item differs from its frozen cited sources.")
    protected = {
        **{baseline / name: sha for name, sha in run.file_hashes.items()},
        **{path: digest(path.read_bytes()) for path in packet.iterdir() if path.is_file()},
        **{
            corpus_dir / name: digest((corpus_dir / name).read_bytes())
            for name in ("chunks.jsonl", "manifest.json")
        },
    }
    if labels_path is not None:
        protected[labels_path] = digest(labels_path.read_bytes())
    # Never overwrite a previous experiment or human annotations.
    output.mkdir(parents=True, exist_ok=False)
    identity = model.identity()
    expected_identity = {
        "model": run.versions.judge.model,
        "revision": run.versions.judge.revision,
        "backend_version": run.versions.model_backend_version,
    }
    observed_identity = identity.model_dump()
    differences = {
        key: {"expected": expected, "observed": observed_identity[key]}
        for key, expected in expected_identity.items()
        if expected != observed_identity[key]
    }
    accepted = not differences or (allow_backend_change and set(differences) == {"backend_version"})
    backend_changed = identity.backend_version != run.versions.model_backend_version
    comparison = {
        "backend_change_allowed": allow_backend_change,
        "backend_changed": backend_changed,
        "historical_backend_version": run.versions.model_backend_version,
        "candidate_backend_version": identity.backend_version,
        "rubric_only_comparison": accepted and not backend_changed,
    }
    identity_report = output / "identity-check.json"
    write_json(
        identity_report,
        {
            "schema_version": 1,
            "phase": "preflight",
            "matched": not differences,
            "accepted": accepted,
            **comparison,
            "expected": expected_identity,
            "observed": observed_identity,
            "differences": differences,
            "baseline_manifest_sha256": run.file_hashes["version-manifest.json"],
            "packet_id": labels.packet_id,
            "scoring_calls_started": False,
        },
    )
    if not accepted:
        detail = "; ".join(
            f"{key}: expected {values['expected']!r}, observed {values['observed']!r}"
            for key, values in differences.items()
        )
        hint = (
            " A backend-only change can be recorded with --allow-backend-change."
            if set(differences) == {"backend_version"}
            else ""
        )
        raise ValueError(
            f"Judge identity mismatch ({detail}). No answers were re-scored. "
            f"Inspect {identity_report.resolve()}.{hint}"
        )
    if backend_changed:
        print(
            f"Backend change recorded: {run.versions.model_backend_version} -> "
            f"{identity.backend_version}. Rubric-only attribution is disabled.",
            flush=True,
        )
    write_json(
        output / "version-manifest.json",
        {
            "schema_version": 1,
            "evaluation_kind": "frozen-answer-judge-rescore",
            **comparison,
            "created_at": datetime.now(UTC).isoformat(),
            "baseline_files": run.file_hashes,
            "baseline_versions": run.versions.model_dump(mode="json"),
            "packet_id": labels.packet_id,
            "labels_sha256": old_audit["labels_sha256"],
            "judge": {
                **identity.model_dump(),
                "rubric_version": RUBRIC_VERSION,
                "rubric_sha256": RUBRIC_SHA256,
                "dimension_rubrics": RUBRIC_HASHES,
                "calibrated": False,
            },
            "source_files": source_hashes(),
            "generator_called": False,
            "retrieval_called": False,
            "historical_context_inferred": False,
            "legacy_context_unknown_cases": sum(
                (recorded := run.rows[item.case.id].response) is not None
                and recorded.context_sources is None
                for item in items
            ),
        },
    )
    scores: dict[str, JudgeAssessment] = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    errors = []
    for number, item in enumerate(items, 1):
        body = run.rows[item.case.id].response
        assert body is not None
        result: dict[str, Any] = {
            "case_id": item.case.id,
            "request_id": str(body.request_id),
            "answer_sha256": digest(body.answer.encode("utf-8")),
        }
        try:
            judged = assess(model, identity, item.case, body, chunks)
            scores[item.case.id] = judged.assessment
            result.update(
                judge=judged.assessment.model_dump(),
                judge_usage=judged.usage.model_dump(),
                judge_calls=[call.model_dump() for call in judged.calls],
            )
            for key in usage:
                usage[key] += getattr(judged.usage, key)
        except (ValueError, QueryError, httpx.HTTPError) as error:
            result["error"] = {"type": type(error).__name__, "detail": str(error)[:500]}
            errors.append(item.case.id)
        with (output / "results.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + "\n")
        print(
            f"[{number}/{len(items)}] {item.case.id}: {'ERROR' if 'error' in result else 'scored'}",
            flush=True,
        )
    if any(digest(path.read_bytes()) != sha for path, sha in protected.items()):
        raise ValueError("Protected baseline, corpus or human review files changed during scoring.")
    old_scores = {item.case.id: run.rows[item.case.id].judge for item in items}
    if any(value is None for value in old_scores.values()):
        raise ValueError("Historical judge scores are missing.")
    historical = agreement(
        labels, {key: value for key, value in old_scores.items() if value is not None}
    )
    candidate = agreement(labels, scores) if not errors else None
    summary = {
        "evaluation_kind": "frozen-answer-judge-rescore",
        **comparison,
        "packet_id": labels.packet_id,
        "sampling": "purposive-development-sample",
        "cases": len(items),
        "errors": errors,
        "complete": not errors,
        "historical": historical,
        "candidate": candidate,
        "judge_usage": usage,
        "usage_scope": "validated_complete_call_pairs_only",
        "calibrated": False,
        "release_threshold_approved": False,
        "generator_called": False,
        "retrieval_called": False,
    }
    write_json(output / "agreement.json", summary)
    lines = ["# Frozen-answer judge comparison", "", f"Complete: {not errors}.", ""]
    lines += [
        f"Historical backend: {run.versions.model_backend_version}.",
        f"Candidate backend: {identity.backend_version}.",
        f"Rubric-only comparison: {comparison['rubric_only_comparison']}.",
        "",
    ]
    if backend_changed:
        lines += [
            "The backend also changed. Score differences cannot be attributed to the rubric alone.",
            "",
        ]
    if candidate is not None:
        lines += [
            "| Dimension | Old exact agreement | New exact agreement | Old MAE | New MAE |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for dim in DIMENSIONS:
            old, new = historical[dim], candidate[dim]
            lines.append(
                f"| {dim} | {old['exact_agreement']:.2%} | {new['exact_agreement']:.2%} | "
                f"{old['mean_absolute_error']:.2f} | {new['mean_absolute_error']:.2f} |"
            )
    lines += [
        "",
        "Frozen answers and human labels were reused. No generation or retrieval was run.",
        "Legacy context stays unknown; faithfulness uses cited source text.",
        "This is development agreement, not unseen-data accuracy or a causal proof of improvement.",
        "Usage covers validated complete call pairs; failed pairs may consume unreported tokens.",
        "Calibration and release approval remain false. This is not a pipeline baseline.",
    ]
    (output / "report.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--corpora-root", type=Path, default=ROOT / "artifacts/corpora")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ollama-port", type=int, default=11434, metavar="PORT")
    parser.add_argument(
        "--allow-backend-change",
        action="store_true",
        help="Record a backend-change experiment; the model name and revision must still match.",
    )
    args = parser.parse_args()
    if not 1 <= args.ollama_port <= 65535:
        parser.error("Ollama port must be between 1 and 65535.")
    try:
        declared = read_json((args.baseline / "version-manifest.json").read_bytes())["judge"][
            "model"
        ]
        output = args.output or ROOT / "artifacts/judge-rescores" / datetime.now(UTC).strftime(
            "%Y%m%dT%H%M%S.%fZ"
        )
        model = OllamaModel(f"http://127.0.0.1:{args.ollama_port}", declared)
        try:
            summary = rejudge(
                args.baseline,
                args.packet,
                args.corpora_root,
                output,
                model,
                args.labels,
                allow_backend_change=args.allow_backend_change,
            )
        finally:
            model.close()
        print(json.dumps(summary, indent=2))
        print(f"Judge rescore evidence: {output.resolve()}")
        if not summary["complete"]:
            print("Judge scoring incomplete; no agreement acceptance claimed.", file=sys.stderr)
            return 1
        print("WEEK 2 STEP 3 JUDGE RESCORING ACCEPTANCE PASSED")
        return 0
    except (
        OSError,
        ValueError,
        IndexingError,
        KeyError,
        TypeError,
        QueryError,
        httpx.HTTPError,
    ) as error:
        print(f"Judge rescore input/runtime error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
