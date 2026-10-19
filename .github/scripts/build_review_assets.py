"""Validate the pinned source split and package source and review instructions."""

import json
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from evals.datasets import read_profile
from evals.human_review import write_json
from evals.splits import validate_split
from indexing.corpus import load_corpus
from ingestion.pipeline import ingest

ROOT = Path.cwd()


def main() -> None:
    profile_path = ROOT / "evals/datasets/kubesentiment/profile.json"
    profile = read_profile(profile_path)
    source = ROOT / "artifacts/repositories/KubeSentiment"
    actual = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    if actual != profile.commit_sha:
        raise ValueError("Upstream checkout is not the frozen dataset source.")
    prepared = ingest(
        source, ROOT / "artifacts/corpora", repo_id=profile.repo, config=profile.ingestion,
    )
    corpus = load_corpus(prepared.directory)
    report = validate_split(corpus, profile_path.parent / "split.json")
    output = ROOT / "delivery"
    output.mkdir()
    write_json(output / "split-validation.json", report)
    names = (
        "evals/review/rubric-v1.md", "evals/review/selection-v1.json",
        "docs/week2-dataset-review.md", "evals/datasets/kubesentiment/SOURCE-LICENSE.txt",
    )
    with ZipFile(output / "kubesentiment-review-tools.zip", "w", ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(ROOT / name, arcname=name)
        archive.writestr(
            "README.md",
            "# Review preparation tools\n\n"
            "This archive contains instructions, selection and rubric only.\n"
            "Historical results and a filled source-bound packet are not published.\n"
            "Use the full source checkout and your local historical baseline:\n\n"
            "powershell -NoProfile -ExecutionPolicy Bypass -File "
            ".\\scripts\\check-dataset-review.ps1 -Baseline "
            ".\\artifacts\\baselines\\20261015T103820.268147Z\n\n"
            "The printed human-review directory contains 20 null labels for a human to fill.\n"
            "No actual human scores or calibration results have been produced.\n",
        )
    subprocess.run([
        "git", "archive", "--format=zip",
        "--output=" + str(output / "codebase-copilot-week2-source.zip"), "HEAD",
    ], check=True, timeout=30)
    for name in ("kubesentiment-review-tools.zip", "codebase-copilot-week2-source.zip"):
        with ZipFile(output / name) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Archive integrity check failed: {name}")
    print(json.dumps(report, indent=2))
    print("SOURCE-ONLY SPLIT AND ARCHIVE ACCEPTANCE PASSED")


if __name__ == "__main__":
    main()
