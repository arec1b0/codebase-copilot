# Architecture v1

Container view of the implemented demo. Host ports bind to loopback. The API uses
one worker and one nonblocking generation slot. Ollama runs natively; the storage
and tracing services use the accepted Compose stack.

```mermaid
C4Container
    Person(developer, "Developer", "Queries code and inspects evaluations")
    System_Boundary(host, "Windows host") {
        Container(api, "Query API", "FastAPI / Python", "Pinned retrieval, prompt, citations")
        Container(model, "Model server", "Native Ollama", "qwen2.5-coder:3b")
        Container(evaluation, "Evaluation runner", "Python / JSONL", "Labels and baseline artifacts")
    }
    System_Boundary(stack, "Docker Compose") {
        ContainerDb(qdrant, "Qdrant", "Dense + BM25", "Versioned source vectors")
        Container(phoenix, "Phoenix", "OTLP / HTTP", "Query traces")
        ContainerDb(postgres, "PostgreSQL", "PostgreSQL 17", "Phoenix metadata")
    }
    Rel(developer, api, "Question", "HTTP")
    Rel(developer, evaluation, "Run acceptance", "PowerShell")
    Rel(api, qdrant, "Hybrid retrieval", "HTTP")
    Rel(api, model, "Structured generation", "HTTP")
    Rel(api, phoenix, "Metadata-only spans", "OTLP / HTTP")
    Rel(phoenix, postgres, "Persist traces", "SQL")
    Rel(evaluation, api, "Measure answers", "HTTP")
    Rel(evaluation, model, "Uncalibrated judging", "HTTP")
    Rel(evaluation, phoenix, "Export five traces", "REST")
```

Git ingestion publishes immutable corpus JSONL and hash-checked manifests.
CPU embeddings publish dense/BM25 vectors and a versioned index manifest. The API
verifies chunks against the corpus, selects whole chunks in RRF order, requests
sourced statements, validates labels, and renders citations.

The `rerank` span records `enabled=false` and `preserve_rrf_order`, describing the
pass-through/context-budget stage. No learned reranker is deployed. PostgreSQL's
`copilot` database is reserved for later application metadata; current application
versions are kept in manifests, not claimed to be in SQL.

Trace attributes include versions, chunk IDs/locations, timings, and token counts.
Raw questions, source text, model output, and exception stacks are omitted.
Phoenix outages do not fail queries. The exporter has bounded buffers and can
drop spans; acceptance separately checks collector ingestion and readback.

Authentication/rate limiting, LiteLLM, vLLM, GPU capacity tests, Kubernetes,
canary delivery, and production SLOs remain later-week work.
