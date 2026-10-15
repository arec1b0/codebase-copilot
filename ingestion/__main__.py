"""Command line entry point for snapshot ingestion."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from ingestion.git_source import IngestionError
from ingestion.models import IngestionConfig
from ingestion.pipeline import ingest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a citation-ready corpus from a Git commit."
    )
    parser.add_argument(
        "--repo", type=Path, required=True, help="Path to an existing local Git repo."
    )
    parser.add_argument(
        "--revision", default="HEAD", help="Locally available commit, tag, or branch."
    )
    parser.add_argument(
        "--repo-id", help="Stable corpus namespace, defaulting to the repo folder name."
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/corpora"))
    parser.add_argument("--max-chars", type=int, default=4000)
    parser.add_argument("--max-file-bytes", type=int, default=1048576)
    parser.add_argument("--max-total-bytes", type=int, default=33554432)
    parser.add_argument("--max-files", type=int, default=1000)
    arguments = parser.parse_args()
    try:
        config = IngestionConfig(
            max_chars=arguments.max_chars,
            max_file_bytes=arguments.max_file_bytes,
            max_total_bytes=arguments.max_total_bytes,
            max_files=arguments.max_files,
        )
        result = ingest(
            arguments.repo,
            arguments.output,
            revision=arguments.revision,
            repo_id=arguments.repo_id,
            config=config,
        )
    except (IngestionError, ValidationError, OSError, UnicodeError) as error:
        print(f"Ingestion failed: {error}", file=sys.stderr)
        return 1
    print(f"Commit: {result.commit_sha}")
    print(f"Corpus version: {result.corpus_version}")
    print(f"Files: {result.file_count}; chunks: {result.chunk_count}")
    print(f"Output: {result.directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
