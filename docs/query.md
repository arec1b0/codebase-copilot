# Grounded query contract

Step 5 serves one source snapshot and one local model through a single-worker
FastAPI process. It uses native Ollama HTTP, not the OpenAI-compatible API or the
vLLM serving planned for a later deployment step.

## Startup

`COPILOT_INDEX_MANIFEST` selects an existing index manifest. The startup script
sets it before launching Uvicorn. The matching source corpus must remain under
`artifacts/corpora/<repo>/<corpus_version>/`; its hash and commit must match the
index. Cached embedding assets must match the recorded identity. Qdrant connection
details come from the preserved root `.env`.

`COPILOT_OLLAMA_URL` defaults to `http://127.0.0.1:11434`; only a loopback server
root is accepted. The selected model is `qwen2.5-coder:3b`. Startup reads its actual
digest from `/api/tags` and backend version from `/api/version`. Identity is pinned
and checked before queries and after generation. Model or backend changes require
an API restart. The model loads in Ollama; embeddings load during API startup.

## HTTP behavior

`GET /healthz` reports process liveness. `GET /readyz` checks the pinned Qdrant
schema, exact point count, loaded embedding identity, and live model identity.
Readiness is independent of Phoenix. Failed initialization requires a restart
after fixing the dependency.

Example `POST /query` body:

```json
{
  "question": "How does Counter.increment change value and what does it return?",
  "language": "python",
  "top_k": 3
}
```

The stripped question must contain 1–1024 characters. Optional `language` accepts
`python`, `go`, `cpp`, `markdown`, or `text`. `top_k` is an integer from 1 to 5, default 3.
Unknown fields are rejected. Every request receives a generated UUID in
`X-Request-ID`; query responses and handled errors include the same ID.

Step 6 adds an optional `trace_id` to successful query responses and `X-Trace-ID`
on traced query HTTP responses, including validation errors. It correlates with
Phoenix's API root and child stages. Tracing is enabled by default for normal
startup and samples all local queries; `COPILOT_TRACING=0` disables it.
Readiness still checks retrieval/model dependencies independently of Phoenix.

A successful response contains `status`, `answer`, `citations`, model name/digest/
backend version, prompt version/hash, corpus/index versions, repository, commit,
token usage, and timings. Status is `answered` or `insufficient_context`.
Citations map labels such as `S1` to chunk ID, repository, commit, path, symbol,
and inclusive source line range. Responses omit retrieved source text. Inspect
the cited commit to read the original file.

## Context and citations

Hybrid retrieval uses the accepted dense/BM25 RRF index. Returned chunks must
equal saved corpus records. Up to five whole chunks are considered in rank order.
Combined system/user content is limited to 6,000 UTF-8 bytes. Oversized chunks
are skipped; source text and line ranges are never truncated. This byte bound
is not an exact preflight token count for the generation model.

Prompt v2 receives a schema with `statements`, `abstain`, and `reason`. Each of
one to three statements contains `text` and one to five `source_ids` selected from
the supplied label enum. The service validates each statement's labels; unknown
or duplicate labels fail. It appends canonical inline markers to every statement
and deduplicates the public citation list in first-use order. Repeated valid
markers already present in statement text are removed before rendering; any
undeclared marker fails. The public `answer` and `citations` contract is unchanged.

Abstentions must contain no statements and a nonblank explanation without source
markers. Empty retrieval or no chunks fitting the budget produces an abstention
without generation and reports zero generation tokens. The previous v1 contract
required the model to maintain both inline citations and a separate label list;
a live Windows request failed because those two representations disagreed.

Label validation establishes provenance, not semantic support or source relevance.
A labeled evaluation and faithfulness checks remain a later checkpoint. The prompt
treats sources and questions as untrusted data, but this does not prove resistance
to prompt injection. No tools or code execution are exposed.

## Generation and timings

Native `/api/chat` streams internally with JSON-schema formatting, temperature 0,
seed 42, context setting 8,192, and output limit 512 tokens. Returned prompt and
generation counts are checked against these settings. Incomplete streams and
token-limit stops fail instead of returning partial JSON. Identical output across
hardware or backend versions is not guaranteed.

`model_ttft_ms` measures client-observed time from the Ollama request to its first
nonempty content fragment, including loading and transport. It is not an exact
server token timestamp or API streaming metric: `POST /query` returns a completed
response. `generation_ms` covers streaming/parsing; `retrieval_ms` covers embedding/
search; `total_ms` also includes readiness and identity checks. Without generation,
TTFT is null.

Connect timeout is five seconds; stream read inactivity timeout is 180 seconds.
Elapsed time is checked on received events. This is not a hard wall-clock deadline
when a stream stalls between events. One nonblocking query slot is available;
another concurrent query gets 503. Disconnecting the API client does not guarantee
cancellation of a running model request.

| HTTP status | Behavior |
| --- | --- |
| 422 | Invalid query fields |
| 503 | Unavailable service/retrieval/model, changed identity, or occupied slot |
| 502 | Invalid JSON, token usage, incomplete output, or citations |
| 504 | Model connection/read timeout or elapsed-time check |

Handled errors give a short code and explanation without source/model output.
This local development API has no application authentication or production rate
limiting. Keep its bind address on loopback.
