"""Read committed blobs without depending on working-tree contents or filters."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class IngestionError(RuntimeError):
    """A source snapshot or corpus cannot be produced safely."""


@dataclass(frozen=True)
class GitFile:
    path: str
    oid: str
    mode: str
    size: int


def git(repository: Path, *arguments: str) -> bytes:
    environment = {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            timeout=30,
            env=environment,
            check=False,
        )
    except FileNotFoundError as error:
        raise IngestionError("Git is required and must be available on PATH.") from error
    except subprocess.TimeoutExpired as error:
        raise IngestionError("Git operation exceeded its 30 second timeout.") from error
    if result.returncode:
        raise IngestionError(f"Git {arguments[0]} failed. Check the repository and revision.")
    return result.stdout


def resolve_commit(repository: Path, revision: str) -> str:
    if not repository.is_dir():
        raise IngestionError("The repository directory does not exist.")
    commit = git(repository, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
    value = commit.decode("ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", value):
        raise IngestionError("Git did not return a full commit object identifier.")
    return value


def list_files(repository: Path, commit: str) -> list[GitFile]:
    listing = git(repository, "ls-tree", "-r", "-l", "-z", "--full-tree", commit)
    files = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        mode, kind, oid, size = header.decode("ascii").split()
        if kind != "blob":
            continue
        try:
            path = path_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise IngestionError("Git paths must use UTF-8 for this corpus format.") from error
        files.append(GitFile(path=path, oid=oid, mode=mode, size=int(size)))
    return sorted(files, key=lambda item: item.path)


def read_blob(repository: Path, source: GitFile) -> bytes:
    data = git(repository, "cat-file", "blob", source.oid)
    if len(data) != source.size:
        raise IngestionError(f"Blob size mismatch for {source.path}.")
    return data
