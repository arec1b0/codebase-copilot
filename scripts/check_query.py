"""Live HTTP acceptance for the pinned local RAG pipeline."""

import json
import re
from pathlib import Path

import httpx

from app.contracts import QueryResponse
from app.main import SERVICE_VERSION
from app.prompt import PROMPT_VERSION
from indexing.config import ROOT


def require_success(response: httpx.Response) -> None:
    """Report the API's structured error without echoing arbitrary response text."""
    if response.is_success:
        return
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    report = {
        "endpoint": response.request.url.path,
        "http_status": response.status_code,
        "request_id": response.headers.get("X-Request-ID", ""),
        "error": "unexpected_http_status",
        "detail": "The response did not contain a structured API error.",
    }
    for key in ("request_id", "error", "detail"):
        value = body.get(key)
        if isinstance(value, str) and value:
            report[key] = value[:500]
    directory = ROOT / "artifacts" / "acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, indent=2, ensure_ascii=True)
    (directory / "step5-query-error.json").write_text(rendered + "\n", encoding="utf-8")
    print(rendered, flush=True)
    raise SystemExit("STEP 5 ACCEPTANCE FAILED: see artifacts/acceptance/step5-query-error.json")


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=210, trust_env=False) as client:
        health = client.get("/healthz")
        require_success(health)
        assert health.json()["version"] == SERVICE_VERSION, "Restart the API with updated sources."
        ready = client.get("/readyz")
        require_success(ready)
        result = client.post(
            "/query",
            json={
                "question": "How does Counter.increment change value and what does it return?",
                "language": "python",
                "top_k": 3,
            },
        )
        require_success(result)
        body = QueryResponse.model_validate_json(result.content)
        assert body.status == "answered"
        assert body.prompt_version == PROMPT_VERSION, "The API is running an older prompt."
        assert set(re.findall(r"\[(S\d+)\]", body.answer)) == {
            citation.source_id for citation in body.citations
        }
        assert str(body.request_id) == result.headers["X-Request-ID"]
        assert body.citations and any(
            citation.path == "calculator.py" and citation.symbol == "Counter"
            for citation in body.citations
        )
        assert body.model == "qwen2.5-coder:3b" and body.model_revision.startswith("sha256:")
        assert body.usage.input_tokens > 0 and body.usage.output_tokens > 0
        assert body.model_ttft_ms is not None and body.model_ttft_ms >= 0
        empty = client.post(
            "/query",
            json={
                "question": "Where is Counter defined?",
                "language": "text",
                "top_k": 3,
            },
        )
        require_success(empty)
        abstention = QueryResponse.model_validate_json(empty.content)
        assert abstention.status == "insufficient_context"
        assert not abstention.citations and abstention.usage.output_tokens == 0
        invalid = client.post("/query", json={"question": " "})
        assert invalid.status_code == 422
        assert invalid.json()["request_id"] == invalid.headers["X-Request-ID"]
    directory: Path = ROOT / "artifacts" / "acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "step5-query.json").write_text(body.model_dump_json(indent=2), encoding="utf-8")
    print(body.answer)
    print(
        json.dumps(
            {
                "request_id": str(body.request_id),
                "model_revision": body.model_revision,
                "index_version": body.index_version,
                "model_ttft_ms": body.model_ttft_ms,
                "total_ms": body.total_ms,
            },
            indent=2,
        )
    )
    print("Grounded answer, citations, versions, abstention, and HTTP validation passed.")
    print("STEP 5 ACCEPTANCE PASSED")


if __name__ == "__main__":
    main()
