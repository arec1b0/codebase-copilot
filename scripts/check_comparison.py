"""Exercise the actual comparison CLI against a baseline and explicitly edited copies."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.comparison import digest, load_run
from indexing.config import ROOT


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check(baseline: Path, corpora_root: Path, output: Path) -> None:
    baseline = baseline.resolve()
    original = load_run(baseline, corpora_root)
    if original.issues:
        raise ValueError("Acceptance needs a technically complete baseline without case errors.")
    output.mkdir(parents=True, exist_ok=False)

    def run(candidate: Path, name: str, expected: int) -> dict[str, Any] | None:
        directory = output / name
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "evals.compare",
                "--baseline",
                str(baseline),
                "--candidate",
                str(candidate),
                "--corpora-root",
                str(corpora_root.resolve()),
                "--output",
                str(directory),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        (output / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (output / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode != expected:
            raise ValueError(
                f"{name}: expected exit {expected}, got {result.returncode}; inspect {output}."
            )
        print(f"{name}: expected exit {expected} observed", flush=True)
        return (
            json.loads((directory / "comparison.json").read_text(encoding="utf-8"))
            if (directory / "comparison.json").exists()
            else None
        )

    run(baseline, "self-comparison", 0)
    for mode in ("retrieval-drop", "citation-failure", "judge-drop-report-only", "missing-case"):
        fixture = output / "synthetic-fixtures" / mode
        fixture.mkdir(parents=True)
        raw = (baseline / "results.jsonl").read_bytes()
        rows = [json.loads(line) for line in raw.splitlines()]
        versions = json.loads((baseline / "version-manifest.json").read_bytes())
        versions["comparison_fixture"] = {
            "kind": mode,
            "not_a_pipeline_measurement": True,
            "parent_results_sha256": digest(raw),
        }
        write_json(fixture / "version-manifest.json", versions)
        (fixture / "dataset.jsonl").write_bytes((baseline / "dataset.jsonl").read_bytes())
        if mode == "retrieval-drop":
            for row in rows:
                row["retrieved_chunks"] = []
                row["retrieval"] = {"hit": 0.0, "recall": 0.0, "reciprocal_rank": 0.0}
        elif mode == "citation-failure":
            answered = next((row for row in rows if row["response"]["citations"]), None)
            if answered is None:
                raise ValueError("Acceptance needs at least one cited baseline answer.")
            answered["response"]["citations"][0]["chunk_id"] = "synthetic-missing-chunk"
        elif mode == "judge-drop-report-only":
            for row in rows:
                row["judge"].update(faithfulness=0, relevance=0)
        else:
            rows.pop()
        (fixture / "results.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        expected = 0 if mode == "judge-drop-report-only" else (2 if mode == "missing-case" else 1)
        report = run(fixture, mode, expected)
        if mode == "retrieval-drop" and (
            report is None
            or not report["regressions"]
            or not any(metric["failed"] for metric in report["metrics"])
        ):
            raise ValueError(
                "Retrieval fixture did not expose a per-case and aggregate regression."
            )
    if original.file_hashes != load_run(baseline, corpora_root).file_hashes:
        raise ValueError("Acceptance changed the supplied baseline.")
    print(f"Comparison evidence: {output.resolve()}")
    print("WEEK 2 STEP 1 ACCEPTANCE PASSED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--corpora-root", type=Path, default=ROOT / "artifacts/corpora")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        ROOT / "artifacts/acceptance/week2-step1" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    check(args.baseline, args.corpora_root, output)


if __name__ == "__main__":
    main()
