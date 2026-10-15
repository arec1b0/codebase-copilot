"""Prepare a pinned demo corpus and index, returning only its manifest path."""

import json
import shutil
import tempfile
from pathlib import Path

from indexing.config import ROOT, connect
from indexing.corpus import load_corpus
from indexing.embeddings import CpuEmbeddings
from indexing.store import index_corpus
from ingestion.pipeline import ingest
from scripts.check_ingestion import git_command


def main() -> None:
    directory = ROOT / "artifacts"
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prepare-demo-", dir=directory) as temporary:
        repository = Path(temporary)
        for source in (ROOT / "examples/demo-repo").iterdir():
            shutil.copyfile(source, repository / source.name)
        git_command(repository, "init", "--initial-branch=main")
        git_command(repository, "add", ".")
        git_command(repository, "commit", "-m", "Create ingestion acceptance source")
        result = ingest(repository, directory / "corpora", repo_id="training-demo")
    client = connect()
    try:
        backend = CpuEmbeddings(directory / "models")
        _, manifest = index_corpus(
            client, load_corpus(result.directory), backend, directory / "indexes"
        )
    finally:
        client.close()
    (directory / "demo-index.json").write_text(
        json.dumps({"index_manifest": str(manifest)}, indent=2) + "\n", encoding="utf-8"
    )
    print(manifest)


if __name__ == "__main__":
    main()
