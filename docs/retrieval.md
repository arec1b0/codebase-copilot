# Versioned hybrid retrieval contract

Step 4 turns one verified Git-source corpus into a dense and sparse Qdrant index.
It provides source retrieval through a CLI. Answer generation, reranking, tracing,
and a statistically meaningful quality baseline are separate remaining tasks.

## Models and input limits

Dense embeddings use `BAAI/bge-small-en-v1.5` with 384 dimensions and the ONNX
Runtime CPU provider with two threads. BM25 uses FastEmbed's `Qdrant/bm25` with
English stemming, k 1.2, b 0.75, average document length 256, and maximum token
length 40. Qdrant applies IDF through the named sparse-vector configuration.

The document embedding input contains language, source path, symbol, and snippet
text. Query and passage embedding methods are used separately. The dense model
supports 512 input tokens, including special tokens. A cloned tokenizer with
truncation and padding disabled checks the complete input before inference.
Overlong chunks or queries fail instead of silently losing source text.

For an overlong corpus, re-ingest the exact same source commit with a smaller
`--max-chars`, inspect the output, then build the new corpus version. Character
counts are not token counts, so the tokenizer remains the final limit check.
Input limits include the source header; unusually long paths also consume tokens.

The English demo checks do not establish performance on Russian queries, other
languages, or a large production repository. Select another embedding model only
after comparing labeled retrieval results; this implementation intentionally has
one model contract rather than untested model selection switches.

## Artifact identity

Before indexing, the corpus loader verifies the manifest fingerprint, full corpus
hash, per-chunk text hashes, deterministic UUIDs, counts, repository and commit
identities, and source-range consistency. This is an integrity check of the
artifact, not a signature or a fresh comparison with a remote Git repository.

The index manifest records the corpus version and hash, source commit, document
format, vector dimension, distance metric, sparse modifier, dense and sparse
model names, SHA-256 hashes of non-hidden model asset files, model parameters,
and relevant embedding runtime package versions. Its fingerprint determines
`index_version` and the versioned Qdrant collection name.

FastEmbed's locked implementation exposes loaded assets through `_model_dir`.
The adapter validates that this is a directory and fails if the dependency
changes that interface. Do not update this dependency without rerunning real
embedding acceptance and inspecting the model asset contract.

The loader caches public files in `artifacts/models/`. Keep that cache with an
index if reproducible queries are required. `--offline-models` uses only cached
assets. Newly downloaded model files or changed runtime versions produce another
identity; queries reject an embedding backend that differs from the manifest.
The hash record does not itself back up or redistribute the model files.

## Index publication and recovery

Each point has named vectors `dense` and `bm25` and a payload containing its full
source chunk, corpus version, and index version. Points use the deterministic
chunk UUIDs. Batches of up to 32 are upserted with `wait=True`.

An existing collection must have the exact named-vector schema. Its current
payloads must belong to the expected version and expected source chunks. Foreign
points, altered payloads, or incompatible schemas fail before overwriting them.
After upload, an exact point count must match the complete corpus. Only then is
the local index manifest published through a staging-directory rename.

An interrupted build can leave a partial Qdrant collection. The same build can
resume it after validating its existing points. The absence of a completed local
manifest prevents the CLI from selecting that partial build. Search additionally
rejects a collection whose point count differs from the manifest.

Changing the corpus or model identity creates another collection. Old collections
are retained; this step does not delete them or switch an active-index alias.
Repeated indexing is idempotent for point identities and manifests, but it still
recomputes and upserts the vectors. Model embeddings and server payloads are not
cryptographically immutable after publication; authorization and release policy
must protect them in later stages.

## Query behavior

Search sends one dense prefetch and one BM25 prefetch to Qdrant, then uses RRF to
combine the rankings. Each prefetch takes `max(20, top_k * 4)` candidates. The
optional language filter applies to both prefetches and the final query.
Queries accept 1 to 4000 characters and top_k from 1 to 20, subject to the dense
tokenizer limit. Whitespace-only queries fail.

Results include source chunks, scores, and pinned corpus and index versions.
Returned payloads must match the selected repository, source commit, and index
version. A filter with no matching sources returns an empty list. Search can
return irrelevant results for unknown questions; no calibrated relevance
threshold or answer-abstention policy is claimed at this stage.

RRF scores are not probabilities. The three demo locating checks are smoke tests
over thirteen chunks, not the thirty to fifty real questions required for the
Week 1 quality and latency baseline.

## Execution modes and validation

The default client reads the Step 2 `.env` and connects to authenticated Qdrant
on loopback. System proxy variables are ignored for that loopback connection.
No source text is sent to an external embedding service.

The `--local` option uses Qdrant SDK's embedded persistent store at
`artifacts/qdrant-local/`. This exercises real vectors and retrieval without a
Docker daemon. It does not prove server API compatibility, network authentication,
server persistence, or server performance. The acceptance script prints a distinct
local-check result instead of `STEP 4 ACCEPTANCE PASSED` in this mode.

Offline unit tests inject an explicitly test-only embedding backend to check
store operations and failure behavior. Real CPU models are used by the separate
retrieval acceptance script. Preserve both types of evidence when assessing the
change.

## References

- Qdrant hybrid retrieval: https://qdrant.tech/documentation/search-tuning/hybrid-search/
- FastEmbed CPU embeddings: https://qdrant.tech/documentation/tutorials-basics/generate-embeddings-fastembed/
- Selected model source: https://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q
- BM25 implementation: https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py
