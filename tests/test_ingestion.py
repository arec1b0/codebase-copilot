"""Test snapshot isolation, source positions, bounded chunks, and publication."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ingestion.chunking import chunk_source
from ingestion.git_source import IngestionError
from ingestion.models import Chunk, IngestionConfig, LanguageName
from ingestion.pipeline import ingest


def git_command(repository: Path, *arguments: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Ingestion Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *arguments,
        ],
        input=data,
        capture_output=True,
        timeout=30,
        check=True,
    ).stdout


def create_repository(directory: Path, files: dict[str, bytes]) -> Path:
    directory.mkdir()
    git_command(directory, "init", "--initial-branch=main")
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    git_command(directory, "add", ".")
    git_command(directory, "commit", "-m", "Create test snapshot")
    return directory


def read_chunks(directory: Path) -> list[Chunk]:
    return [
        Chunk.model_validate_json(line)
        for line in (directory / "chunks.jsonl").read_bytes().splitlines()
    ]


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        ("python", "def add(a, b):\n    return a + b\n", "add"),
        ("go", "package main\nfunc Add(a int, b int) int { return a + b }\n", "Add"),
        ("cpp", "int add(int a, int b) { return a + b; }\n", "add"),
    ],
)
def test_syntax_symbols(language: LanguageName, source: str, expected: str) -> None:
    chunks, fallback = chunk_source(
        text=source, repo="demo", commit="a" * 40, path="source", language=language, max_chars=4000
    )
    assert not fallback
    assert any(chunk.symbol == expected and chunk.kind == "function" for chunk in chunks)
    for chunk in chunks:
        assert chunk.text == source[chunk.start_char : chunk.end_char]
        assert chunk.start_line == source.count("\n", 0, chunk.start_char) + 1
        assert chunk.end_line == source.count("\n", 0, chunk.end_char - 1) + 1


def test_python_decorators_and_unicode_positions() -> None:
    source = '@decorate("é")\ndef café():\n    return "你好"\n'
    chunks, fallback = chunk_source(
        text=source, repo="demo", commit="a" * 40, path="a.py", language="python", max_chars=4000
    )
    assert not fallback
    assert len(chunks) == 1
    assert chunks[0].symbol == "café"
    assert chunks[0].text.startswith("@decorate")
    assert chunks[0].end_line == 3
    assert chunks[0].text == source[chunks[0].start_char : chunks[0].end_char]


def test_long_lines_are_bounded_without_losing_text() -> None:
    source = "x" * 700
    chunks, _ = chunk_source(
        text=source, repo="demo", commit="a" * 40, path="a.txt", language="text", max_chars=128
    )
    assert all(len(chunk.text) <= 128 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == source
    assert all(chunk.start_line == chunk.end_line == 1 for chunk in chunks)


def test_python_method_boundaries_preserve_qualified_symbols_and_source() -> None:
    source = (
        '# module\nclass Café:\n    value = "你好"\n\n'
        '    @decorate("é")\n    async def run(self):\n        return self.value\n\n'
        "    # between methods\n    def stop(self):\n        return False\n"
    )
    arguments = dict(
        text=source, repo="demo", commit="a" * 40, path="a.py", language="python", max_chars=4000
    )
    # The accepted v1 default retains the original class-sized chunk.
    old, _ = chunk_source(**arguments)  # type: ignore[arg-type]
    new, fallback = chunk_source(**arguments, method_boundaries=True)  # type: ignore[arg-type]
    assert not fallback and [c.symbol for c in old if c.symbol] == ["Café"]
    assert {c.symbol for c in new if c.kind == "method"} == {"Café.run", "Café.stop"}
    decorated = next(c for c in new if c.symbol == "Café.run")
    assert decorated.text.startswith('    @decorate("é")') and decorated.start_line == 5
    assert "between methods" in "".join(c.text for c in new)
    for chunk in new:
        assert chunk.text == source[chunk.start_char : chunk.end_char]
        assert len(chunk.text) <= 4000


def test_method_algorithm_changes_manifest_and_default_stays_reproducible(tmp_path: Path) -> None:
    repository = create_repository(
        tmp_path / "repo", {"a.py": b"class Example:\n    def run(self):\n        return 1\n"}
    )
    old = ingest(repository, tmp_path / "out")
    new = ingest(
        repository,
        tmp_path / "out",
        config=IngestionConfig(algorithm="symbol-method-boundaries-v2"),
    )
    assert old.corpus_version != new.corpus_version
    assert any(c.symbol == "Example.run" for c in read_chunks(new.directory))
    assert ingest(repository, tmp_path / "out").directory == old.directory


def test_syntax_errors_are_explicit_fallbacks() -> None:
    source = "def broken(:\n    return 1\n"
    chunks, fallback = chunk_source(
        text=source, repo="demo", commit="a" * 40, path="a.py", language="python", max_chars=4000
    )
    assert fallback
    assert chunks[0].kind == "syntax_fallback"
    assert chunks[0].symbol is None
    assert chunks[0].text == source


def test_markdown_code_fence_does_not_create_a_document_heading() -> None:
    source = "# Overview\n```python\n# this is code\nx = 1\n```\n## Usage\nRun it.\n"
    chunks, fallback = chunk_source(
        text=source, repo="demo", commit="a" * 40, path="a.md", language="markdown", max_chars=4000
    )
    assert not fallback
    assert [chunk.symbol for chunk in chunks] == ["Overview", "Usage"]
    assert "# this is code" in chunks[0].text


def test_grouped_go_types_do_not_claim_a_single_symbol() -> None:
    source = "package demo\ntype (\n First struct{}\n Second struct{}\n)\n"
    chunks, fallback = chunk_source(
        text=source, repo="demo", commit="a" * 40, path="a.go", language="go", max_chars=4000
    )
    assert not fallback
    types = [chunk for chunk in chunks if chunk.kind == "type"]
    assert len(types) == 1
    assert types[0].symbol is None
    assert "First" in types[0].text and "Second" in types[0].text


def test_committed_snapshot_ignores_working_tree_and_untracked_files(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.py": b"def original():\n    return 1\n"})
    result = ingest(repository, tmp_path / "out")
    before = (result.directory / "chunks.jsonl").read_bytes()
    (repository / "a.py").write_text("def dirty():\n    return 2\n", encoding="utf-8")
    (repository / "untracked.py").write_text("x = 1\n", encoding="utf-8")
    repeated = ingest(repository, tmp_path / "out")
    assert repeated.directory == result.directory
    assert (repeated.directory / "chunks.jsonl").read_bytes() == before
    assert b"original" in before and b"dirty" not in before
    assert {chunk.path for chunk in read_chunks(repeated.directory)} == {"a.py"}


def test_new_commit_changes_version_and_old_revision_is_reproducible(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.py": b"x = 1\n"})
    first = ingest(repository, tmp_path / "out")
    (repository / "a.py").write_text("x = 2\n", encoding="utf-8")
    git_command(repository, "add", ".")
    git_command(repository, "commit", "-m", "Change value")
    second = ingest(repository, tmp_path / "out")
    assert first.commit_sha != second.commit_sha
    assert first.corpus_version != second.corpus_version
    original = ingest(repository, tmp_path / "out", revision=first.commit_sha)
    assert original.directory == first.directory


def test_chunk_configuration_changes_version(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.txt": b"a" * 600})
    first = ingest(repository, tmp_path / "out", config=IngestionConfig(max_chars=128))
    second = ingest(repository, tmp_path / "out", config=IngestionConfig(max_chars=256))
    assert first.corpus_version != second.corpus_version
    assert first.chunk_count > second.chunk_count


def test_skipped_files_and_normalization_are_recorded(tmp_path: Path) -> None:
    repository = create_repository(
        tmp_path / "repo",
        {
            "a.py": b"x = 1\r\n",
            ".env.txt": b"example configuration",
            "binary.txt": b"a\0b",
            "legacy.txt": b"\xff",
            "large.txt": b"x" * 30,
            "image.png": b"not a supported file",
        },
    )
    result = ingest(repository, tmp_path / "out", config=IngestionConfig(max_file_bytes=25))
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    reasons = {item["reason"] for item in manifest["skipped"]}
    assert reasons == {
        "excluded_path",
        "binary_content",
        "non_utf8",
        "file_size_limit",
        "unsupported_extension",
    }
    assert read_chunks(result.directory)[0].text == "x = 1\n"
    content = (result.directory / "chunks.jsonl").read_bytes()
    assert manifest["corpus_sha256"] == hashlib.sha256(content).hexdigest()


def test_symlink_blob_is_not_followed(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.py": b"x = 1\n"})
    oid = (
        git_command(repository, "hash-object", "-w", "--stdin", data=b"/outside/file")
        .decode()
        .strip()
    )
    git_command(repository, "update-index", "--add", "--cacheinfo", f"120000,{oid},link.py")
    git_command(repository, "commit", "-m", "Track symlink")
    result = ingest(repository, tmp_path / "out")
    assert {chunk.path for chunk in read_chunks(result.directory)} == {"a.py"}
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert {"path": "link.py", "reason": "non_regular_file"} in manifest["skipped"]


def test_budget_failure_does_not_publish_a_partial_corpus(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.py": b"x = 1\n", "b.py": b"x = 2\n"})
    output = tmp_path / "out"
    with pytest.raises(IngestionError, match="budget"):
        ingest(repository, output, config=IngestionConfig(max_files=1))
    assert not output.exists()


def test_corrupted_existing_version_is_not_overwritten(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.py": b"x = 1\n"})
    result = ingest(repository, tmp_path / "out")
    target = result.directory / "chunks.jsonl"
    target.write_bytes(b"corrupted\n")
    with pytest.raises(IngestionError, match="corrupted"):
        ingest(repository, tmp_path / "out")
    assert target.read_bytes() == b"corrupted\n"


def test_missing_revision_fails(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.py": b"x = 1\n"})
    with pytest.raises(IngestionError, match="revision"):
        ingest(repository, tmp_path / "out", revision="missing-commit")


def test_no_supported_files_fails(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "repo", {"a.png": b"unsupported"})
    with pytest.raises(IngestionError, match="no supported"):
        ingest(repository, tmp_path / "out")
