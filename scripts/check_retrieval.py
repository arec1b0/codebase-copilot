"""Accept real CPU embeddings and hybrid retrieval against a selected corpus."""

import argparse
from contextlib import closing
from pathlib import Path

from indexing.config import ROOT, connect
from indexing.corpus import IndexingError, load_corpus
from indexing.embeddings import CpuEmbeddings
from indexing.store import index_corpus, load_manifest, search
from ingestion.models import LanguageName


def main() -> None:
    parser = argparse.ArgumentParser(description="Check real-model hybrid retrieval.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--local", action="store_true", help="Use SDK local mode instead of Docker."
    )
    arguments = parser.parse_args()
    corpus = load_corpus(arguments.corpus)
    if corpus.repo != "training-demo" or len(corpus.chunks) != 13:
        raise IndexingError("This acceptance scenario requires the Step 3 training-demo corpus.")
    with closing(connect(local=arguments.local)) as client:
        client.get_collections()
        print("Loading CPU embedding models; first use downloads public model files.", flush=True)
        embeddings = CpuEmbeddings(ROOT / "artifacts" / "models")
        manifest, path = index_corpus(client, corpus, embeddings, ROOT / "artifacts" / "indexes")
        before = path.read_bytes()
        repeated, repeated_path = index_corpus(
            client, corpus, embeddings, ROOT / "artifacts" / "indexes"
        )
        assert repeated.index_version == manifest.index_version
        assert repeated_path.read_bytes() == before
    checks: list[tuple[str, LanguageName, str]] = [
        ("Counter increment amount", "python", "Counter"),
        ("Increment amount", "go", "Increment"),
        ("add left right integers", "cpp", "add"),
    ]
    with closing(connect(local=arguments.local)) as client:
        restored = load_manifest(path)
        for query, language, symbol in checks:
            hits = search(client, restored, embeddings, query, top_k=3, language=language)
            assert hits and all(hit.chunk.language == language for hit in hits)
            assert any(hit.chunk.symbol == symbol for hit in hits)
            assert all(hit.chunk.commit_sha == corpus.commit_sha for hit in hits)
            print(f"Retrieval smoke passed: {language} {symbol}", flush=True)
        try:
            search(client, restored, embeddings, " ")
        except IndexingError:
            pass
        else:
            raise AssertionError("Blank queries must fail.")
    print(f"Collection: {manifest.collection}; points: {manifest.chunk_count}")
    print(f"Index manifest: {path}")
    if arguments.local:
        print("STEP 4 LOCAL CHECK PASSED; Docker server acceptance remains pending.")
    else:
        print("STEP 4 ACCEPTANCE PASSED")


if __name__ == "__main__":
    main()
