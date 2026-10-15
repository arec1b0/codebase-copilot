"""Build a Qdrant index or search one pinned source snapshot."""

import argparse
import json
import sys
from contextlib import closing
from pathlib import Path
from typing import cast

from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from indexing.config import ROOT, connect
from indexing.corpus import load_corpus
from indexing.embeddings import CpuEmbeddings
from indexing.store import index_corpus, load_manifest, search
from ingestion.models import LanguageName


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Versioned CPU embeddings and Qdrant hybrid search."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    build = subcommands.add_parser("build")
    build.add_argument("--corpus", type=Path, required=True)
    build.add_argument("--output", type=Path, default=ROOT / "artifacts" / "indexes")
    build.add_argument(
        "--offline-models", action="store_true", help="Load only cached model assets."
    )
    build.add_argument(
        "--local", action="store_true", help="Use the embedded SDK store, not Docker."
    )
    query = subcommands.add_parser("search")
    query.add_argument("--manifest", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--top-k", type=int, default=5)
    query.add_argument(
        "--offline-models", action="store_true", help="Load only cached model assets."
    )
    query.add_argument("--language", choices=["python", "go", "cpp", "markdown", "text"])
    query.add_argument(
        "--local", action="store_true", help="Use the embedded SDK store, not Docker."
    )
    arguments = parser.parse_args()
    try:
        if arguments.command == "build":
            corpus = load_corpus(arguments.corpus)
            with closing(connect(local=arguments.local)) as client:
                client.get_collections()
                embeddings = CpuEmbeddings(
                    ROOT / "artifacts" / "models", local_only=arguments.offline_models
                )
                manifest, path = index_corpus(client, corpus, embeddings, arguments.output)
            print(f"Index version: {manifest.index_version}")
            print(f"Collection: {manifest.collection}; points: {manifest.chunk_count}")
            print(f"Manifest: {path}")
        else:
            manifest = load_manifest(arguments.manifest)
            with closing(connect(local=arguments.local)) as client:
                client.get_collection(manifest.collection)
                embeddings = CpuEmbeddings(
                    ROOT / "artifacts" / "models", local_only=arguments.offline_models
                )
                hits = search(
                    client,
                    manifest,
                    embeddings,
                    arguments.query,
                    top_k=arguments.top_k,
                    language=cast(LanguageName | None, arguments.language),
                )
            print(json.dumps([hit.model_dump() for hit in hits], ensure_ascii=False, indent=2))
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        UnexpectedResponse,
        ResponseHandlingException,
    ) as error:
        print(f"Indexing failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
