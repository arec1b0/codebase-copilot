"""Verify source-only splits and prepare a reproducible, unlabelled review packet."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from evals.comparison import digest, load_run
from evals.human_review import agreement_audit, create_packet, validate_packet, write_json
from evals.splits import dataset_role, split_profiles, validate_split
from indexing.config import ROOT
from indexing.corpus import load_corpus


def check(
    baseline: Path, corpora_root: Path, output: Path, *,
    split_path: Path = ROOT / "evals/datasets/kubesentiment/split.json",
    selection: Path = ROOT / "evals/review/selection-v1.json",
) -> None:
    run = load_run(baseline, corpora_root)
    if run.issues:
        raise ValueError("Baseline contains technical issues; review preparation is blocked.")
    corpus = load_corpus(corpora_root / run.versions.index.repo / run.versions.index.corpus_version)
    report = validate_split(corpus, split_path)
    split, _, holdout = split_profiles(split_path)
    try:
        dataset_role(holdout, split_path, "development")
    except ValueError:
        pass
    else:
        raise ValueError("Holdout development guard did not reject the run.")
    if dataset_role(holdout, split_path, "release") != "holdout":
        raise ValueError("Explicit holdout release classification failed.")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "split-validation.json", report)
    for name in ("human-review", "reproducibility-copy"):
        create_packet(
            baseline / "results.jsonl", corpus, split_path.parent / split.dev_profile,
            selection, ROOT / "evals/review/rubric-v1.md", output / name,
            run_manifest=baseline / "version-manifest.json",
        )
    packet, copy = output / "human-review", output / "reproducibility-copy"
    if {p.name: p.read_bytes() for p in packet.iterdir()} != {
        p.name: p.read_bytes() for p in copy.iterdir()
    }:
        raise ValueError("Review packet is not byte reproducible.")
    labels, state = validate_packet(packet)
    if state["completed"] != 0 or state["pending"] != 20 or any(
        item.faithfulness is not None or item.relevance is not None for item in labels.labels
    ):
        raise ValueError("Human scores must remain unfilled during preparation.")
    try:
        agreement_audit(packet, baseline / "results.jsonl")
    except ValueError:
        pass
    else:
        raise ValueError("Agreement audit accepted incomplete human labels.")
    write_json(output / "review-status.json", state)
    if any(digest((baseline / name).read_bytes()) != value for name, value in run.file_hashes.items()):
        raise ValueError("Historical baseline was modified.")
    print("Development/holdout: 30/30; source validation only; no holdout model evaluation.")
    print(f"Review packet: {packet}")
    print("HUMAN LABELS PENDING: 20")
    print("WEEK 2 STEP 2 PREPARATION ACCEPTANCE PASSED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--corpora-root", type=Path, default=ROOT / "artifacts/corpora")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "artifacts/acceptance/week2-step2" / datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    check(args.baseline, args.corpora_root, output)


if __name__ == "__main__":
    main()
