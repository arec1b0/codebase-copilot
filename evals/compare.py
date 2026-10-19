"""Offline comparison of saved evaluation directories, with nonzero regression exit."""

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from evals.comparison import compare_runs, digest, load_run, read_json, render_report
from evals.comparison_models import RegressionPolicy
from evals.versions import source_hashes
from indexing.config import ROOT
from indexing.corpus import IndexingError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Saved evaluation directory.")
    parser.add_argument("--candidate", type=Path, required=True, help="Saved evaluation directory.")
    parser.add_argument("--policy", type=Path, default=ROOT / "evals/policies/development-v1.json")
    parser.add_argument("--corpora-root", type=Path, default=ROOT / "artifacts/corpora")
    parser.add_argument(
        "--output", type=Path, help="New directory; existing paths are never replaced."
    )
    args = parser.parse_args()
    try:
        policy_raw = args.policy.read_bytes()
        policy = RegressionPolicy.model_validate(read_json(policy_raw))
        report = compare_runs(
            load_run(args.baseline, args.corpora_root),
            load_run(args.candidate, args.corpora_root),
            policy,
        )
        report["policy_file_sha256"] = digest(policy_raw)
        report["created_at"] = datetime.now(UTC).isoformat()
        report["comparison_python"] = platform.python_version()
        hashes = source_hashes()
        report["comparison_source_files"] = hashes
        report["comparison_source_tree_sha256"] = digest(
            json.dumps(hashes, sort_keys=True).encode()
        )
        output = args.output or (
            ROOT / "artifacts/comparisons" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        )
        output.mkdir(parents=True, exist_ok=False)
        (output / "comparison.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (output / "report.md").write_text(render_report(report), encoding="utf-8")
    except (OSError, ValueError, IndexingError, KeyError, TypeError) as error:
        print(f"COMPARISON INPUT ERROR: {error}", file=sys.stderr)
        return 2
    print(f"Comparison: {output.resolve()}")
    print(f"Per-case metric decreases: {len(report['regressions'])}")
    if report["status"] != "passed":
        print("REGRESSION GATE FAILED")
        return 1
    print("REGRESSION GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
