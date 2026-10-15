"""Accept ingestion using a temporary Git repository and a persistent corpus."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ingestion.git_source import IngestionError
from ingestion.models import Chunk
from ingestion.pipeline import ingest

ROOT = Path(__file__).resolve().parents[1]


def git_command(repository: Path, *arguments: str) -> None:
    environment = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
    }
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=LLMOps Training",
            "-c",
            "user.email=training@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *arguments,
        ],
        env=environment,
        check=True,
        capture_output=True,
        timeout=30,
    )


def main() -> None:
    artifact_root = ROOT / "artifacts"
    artifact_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ingestion-demo-", dir=artifact_root) as temporary:
        repository = Path(temporary)
        for source in (ROOT / "examples" / "demo-repo").iterdir():
            shutil.copyfile(source, repository / source.name)
        git_command(repository, "init", "--initial-branch=main")
        git_command(repository, "add", ".")
        git_command(repository, "commit", "-m", "Create ingestion acceptance source")
        result = ingest(repository, artifact_root / "corpora", repo_id="training-demo")
        content = (result.directory / "chunks.jsonl").read_bytes()
        manifest_content = (result.directory / "manifest.json").read_bytes()
        manifest = json.loads(manifest_content)
        chunks = [Chunk.model_validate_json(line) for line in content.splitlines()]
        assert {chunk.language for chunk in chunks} == {"python", "go", "cpp", "markdown"}
        assert result.file_count == 4
        assert manifest["chunk_count"] == len(chunks)
        assert manifest["corpus_sha256"] == hashlib.sha256(content).hexdigest()
        assert all(chunk.commit_sha == result.commit_sha for chunk in chunks)
        for language in ("python", "cpp"):
            assert any(chunk.language == language and chunk.symbol == "Counter" for chunk in chunks)
        assert any(chunk.language == "go" and chunk.symbol == "Increment" for chunk in chunks)

        (repository / "calculator.py").write_text("UNCOMMITTED_MARKER = True\n", encoding="utf-8")
        (repository / "untracked.py").write_text("UNTRACKED_MARKER = True\n", encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "ingestion",
                "--repo",
                str(repository),
                "--repo-id",
                "training-demo",
                "--output",
                str(artifact_root / "corpora"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        assert result.corpus_version in completed.stdout
        assert (result.directory / "chunks.jsonl").read_bytes() == content
        assert (result.directory / "manifest.json").read_bytes() == manifest_content
        assert b"UNCOMMITTED_MARKER" not in content
        assert not any(chunk.path == "untracked.py" for chunk in chunks)
        try:
            ingest(repository, artifact_root / "corpora", revision="missing-revision")
        except IngestionError:
            pass
        else:
            raise AssertionError("Missing revision must fail.")
        print(f"Commit: {result.commit_sha}")
        print(f"Source files: {result.file_count}; chunks: {result.chunk_count}")
        print(f"Corpus: {result.directory}")
        print("Reproducibility, source metadata, and failure checks passed.")
        print("STEP 3 ACCEPTANCE PASSED")


if __name__ == "__main__":
    main()
