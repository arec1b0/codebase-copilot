"""Ingest committed source only; do not import, install, or execute repository code."""

import argparse
import json
from pathlib import Path

from evals.datasets import load_repository_dataset, read_profile
from indexing.config import ROOT, connect
from indexing.corpus import IndexingError, load_corpus
from indexing.embeddings import CpuEmbeddings
from indexing.store import document_text, index_corpus
from ingestion.pipeline import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument(
        "--profile", type=Path, default=ROOT / "evals/datasets/kubesentiment/profile.json"
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--download-models",
        action="store_true",
        help="Allow public embedding asset downloads on first use.",
    )
    parser.add_argument(
        "--reuse-index",
        action="store_true",
        help="Reuse a complete index after schema/count/source-payload checks.",
    )
    parser.add_argument(
        "--local", action="store_true", help="SDK local store for development checks."
    )
    args = parser.parse_args()
    profile = read_profile(args.profile)
    result = ingest(
        args.repository,
        ROOT / "artifacts/corpora",
        revision=profile.commit_sha,
        repo_id=profile.repo,
        config=profile.ingestion,
    )
    corpus = load_corpus(result.directory)
    cases, dataset_sha = load_repository_dataset(corpus, args.profile)
    print(f"Source commit: {result.commit_sha}")
    print(f"Corpus: {result.directory}; files: {result.file_count}; chunks: {result.chunk_count}")
    print(f"Bound questions: {len(cases)}; dataset: {dataset_sha}", flush=True)
    if args.validate_only:
        print("DATASET SOURCE VALIDATION PASSED; no embedding/index acceptance claimed.")
        return
    backend = CpuEmbeddings(ROOT / "artifacts/models", local_only=not args.download_models)
    for chunk in corpus.chunks:
        try:
            backend.check_input(document_text(chunk))
        except IndexingError:
            raise ValueError(
                f"Embedding token budget exceeded at {chunk.path}:{chunk.start_line}."
            ) from None
    client = connect(local=args.local)
    wrote_batches = False

    def progress(completed: int, total: int) -> None:
        nonlocal wrote_batches
        wrote_batches = True
        if completed % 320 == 0 or completed == total:
            print(f"Embedded and indexed: {completed}/{total}", flush=True)

    try:
        print("Verifying the index or embedding and indexing source chunks...", flush=True)
        _, path = index_corpus(
            client,
            corpus,
            backend,
            ROOT / "artifacts/indexes",
            progress=progress,
            reuse_complete=args.reuse_index,
        )
        if args.reuse_index and not wrote_batches:
            print("Complete index verified; existing embeddings reused.", flush=True)
    finally:
        client.close()
    pointer = ROOT / "artifacts/repository-indexes" / f"{profile.name}.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(
        json.dumps(
            {
                "index_manifest": str(path),
                "profile": str(args.profile.resolve()),
                "commit_sha": profile.commit_sha,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Index manifest: {path}")
    print("REPOSITORY LOCAL CHECK PASSED" if args.local else "REPOSITORY PREPARATION PASSED")


if __name__ == "__main__":
    main()
