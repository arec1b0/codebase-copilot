# Git source ingestion contract

Ingestion reads one immutable commit from a local Git repository and produces
`chunks.jsonl` and `manifest.json` in a versioned corpus directory. Every snippet
can be traced to a committed source path and source range. It does not execute
repository code, change the repository, generate embeddings, or call a model.

## Snapshot and source selection

`--revision` defaults to `HEAD` and resolves once to a full commit SHA. All file
listings and content reads use that commit or its blob object IDs. Working-tree
edits, staged changes, untracked files, and checkout line-ending conversions do
not affect the snapshot. Git replacement objects are disabled for these reads.
The CLI does not fetch missing revisions from a remote.

Supported extensions are `.py`, `.go`, `.cpp`, `.cc`, `.cxx`, `.h`, `.hpp`, `.md`,
`.rst`, and `.txt`. Header files are parsed as C++. All supported text must use
UTF-8; an initial UTF-8 BOM is removed and CRLF is normalized to LF. Non-UTF-8
files and content containing a NUL byte are skipped with a reason.

Only regular tracked files are read. Symlink blobs are skipped and are never
followed. Submodules are not traversed. Hidden path components and directories
named `node_modules`, `vendor`, `artifacts`, `data`, `build`, or `dist` are excluded.
Unsupported files and size exclusions appear in the manifest. A tracked secret
inside an allowed source file is not detected by these path rules; ingestion is
not a secret scanner.

## Chunk boundaries

Python uses the standard library AST. Top-level functions, asynchronous functions,
and classes get symbol boundaries, including decorators. Nested functions and
class methods remain inside their containing top-level definition.

Go and C++ use pinned Tree-sitter grammars. Go functions, methods, and type
declarations and C++ functions, classes, and structs get syntax boundaries.
A grouped Go type declaration has a null symbol when it contains multiple types.
This is syntactic chunking; it does not resolve imports, overloads, inherited
methods, or fully qualified names through a compiler symbol table.

Markdown is split at ATX headings outside backtick or tilde fences. RST and plain
text use bounded text chunks. Text outside selected definitions is retained as
module or document chunks. Whitespace-only chunks are omitted.

Large definitions are split at the last available newline within the character
limit. A line longer than the limit is split by Unicode character count.
Each part keeps its original symbol and source positions. These are character
limits, not model-token limits. There is no chunk overlap in this implementation.

If a code file cannot be parsed, the complete normalized text is still chunked,
`kind` is `syntax_fallback`, `symbol` is null, and the source entry reports
`syntax_fallback: true`. Code with macros or unsupported syntax can therefore
remain available for retrieval without fabricated symbol metadata.

## Limits and CLI

| Option | Default | Meaning |
| --- | --- | --- |
| `--max-chars` | 4000 | Maximum Unicode characters per chunk |
| `--max-file-bytes` | 1048576 | Maximum raw bytes in one eligible file |
| `--max-total-bytes` | 33554432 | Maximum raw bytes across eligible files |
| `--max-files` | 1000 | Maximum eligible file count |
| `--output` | `artifacts/corpora` | Parent for versioned corpus directories |

Oversized individual files are skipped. Exceeding the file-count or total-byte
budget fails ingestion and publishes no corpus. Eligible files later skipped for
encoding or binary content still consume the total-byte and file-count budgets.
An empty or unsupported-only snapshot also fails. Git commands have a 30-second
timeout each; large repositories may need a later batch-reader implementation.

## Output records

| Chunk field | Meaning |
| --- | --- |
| `chunk_id` | Deterministic UUID from source identity, range, and content hash |
| `repo` | Stable repository namespace supplied by `--repo-id` or root folder name |
| `commit_sha` | Full immutable Git commit SHA |
| `path` | Repository-relative source path using Git path separators |
| `language` | Python, Go, C++, Markdown, or plain text |
| `symbol` | Syntactic symbol or heading name, or null |
| `kind` | Function, method, class, struct, type, section, module, document, or fallback |
| `start_line`, `end_line` | One-based inclusive source line range |
| `start_char`, `end_char` | Zero-based half-open offsets in normalized source text |
| `part` | One-based part within the same selected region |
| `content_sha256` | SHA-256 of the snippet encoded as UTF-8 |
| `text` | Exact slice of normalized source text |

The manifest records the source commit, schema and chunking configuration,
normalization policy, parser versions, source blob IDs, per-file normalized
hashes, skipped-file reasons, file and chunk counts, and corpus SHA-256.
Its corpus version is derived from the source identity and processing contract.
The Python patch version is part of this contract, so Python 3.12.13 and 3.12.14
produce different corpus versions even when their snippets are identical.

Output is stored at `OUTPUT/REPO/CORPUS_VERSION/`. The CLI writes a staging
directory and publishes it by renaming the complete directory. Repeating the
same snapshot and configuration verifies existing bytes and reuses that directory.
It does not silently overwrite changed or corrupted artifacts. This publication
method does not claim power-loss durability or backup coverage.

## Acceptance and recovery

The demo check exercises all four source languages, symbol extraction, manifest
hashes, snapshot isolation, repeated-run equality, and a missing-revision failure.
The test suite additionally checks Unicode positions, bounded long lines,
syntax fallback, symlink exclusion, skipped-file reasons, configuration and commit
version changes, budget failure, and rejection of corrupted output.

If publication rejects an existing corpus, retain it for inspection and rerun
with a separate `--output` directory. Rebuild the corpus from its exact commit and
processing configuration before replacing or removing an artifact. This step
does not modify Qdrant, PostgreSQL, or Docker volumes.

## References

- Python Tree-sitter API: https://github.com/tree-sitter/py-tree-sitter
- Git tree listing: https://git-scm.com/docs/git-ls-tree
- Git object reads: https://git-scm.com/docs/git-cat-file
