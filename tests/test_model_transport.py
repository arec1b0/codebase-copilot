"""Native Ollama protocol tests; these do not substitute for live model acceptance."""

import json

import httpx
import pytest

from app.model import OllamaModel, QueryError

MODEL = "qwen2.5-coder:3b"


def stream_bytes(
    *, content: str, done: bool = True, reason: str = "stop", input_tokens: int = 100
) -> bytes:
    middle = len(content) // 2
    events = [
        {"model": MODEL, "message": {"role": "assistant", "content": piece}, "done": False}
        for piece in (content[:middle], content[middle:])
    ]
    if done:
        events.append(
            {
                "model": MODEL,
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": reason,
                "prompt_eval_count": input_tokens,
                "eval_count": 30,
            }
        )
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode()


def test_native_identity_and_stream_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL, "digest": "a" * 64}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "test"})
        assert request.url.path == "/api/chat"
        payload = json.loads(request.content)
        assert payload["stream"] is True and payload["options"]["num_ctx"] == 8192
        claim_schema = payload["format"]["$defs"]["SourceClaim"]["properties"]
        assert claim_schema["source_ids"]["items"]["enum"] == ["S1"]
        content = json.dumps(
            {
                "statements": [{"text": "Value increases.", "source_ids": ["S1"]}],
                "abstain": False,
                "reason": "",
            }
        )
        return httpx.Response(200, content=stream_bytes(content=content))

    model = OllamaModel(
        "http://ollama",
        MODEL,
        httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler)),
    )
    try:
        identity = model.identity()
        assert identity.revision == "sha256:" + "a" * 64
        result = model.generate([{"role": "user", "content": "Counter?"}], ["S1"])
        assert result.content.statements[0].source_ids == ["S1"]
        assert result.usage.input_tokens == 100
        assert 0 <= result.ttft_ms <= result.latency_ms
    finally:
        model.close()


@pytest.mark.parametrize(
    "variant",
    ["malformed", "incomplete", "length", "string_bool", "context_overflow", "uncited_claim"],
)
def test_bad_native_outputs_fail_without_echoing_model_text(variant: str) -> None:
    content = json.dumps(
        {
            "statements": [{"text": "RESPONSE_SECRET_MARKER", "source_ids": ["S1"]}],
            "abstain": False,
            "reason": "",
        }
    )
    if variant == "malformed":
        content = "RESPONSE_SECRET_MARKER"
    if variant == "string_bool":
        content = content.replace('"abstain": false', '"abstain": "false"')
    if variant == "uncited_claim":
        content = content.replace('"source_ids": ["S1"]', '"source_ids": []')
    body = stream_bytes(
        content=content,
        done=variant != "incomplete",
        reason="length" if variant == "length" else "stop",
        input_tokens=8000 if variant == "context_overflow" else 100,
    )
    model = OllamaModel(
        "http://ollama",
        MODEL,
        httpx.Client(
            base_url="http://ollama",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
        ),
    )
    try:
        with pytest.raises(QueryError) as caught:
            model.generate([{"role": "user", "content": "Counter?"}], ["S1"])
        assert caught.value.code == "invalid_model_output"
        assert "RESPONSE_SECRET_MARKER" not in str(caught.value)
    finally:
        model.close()


def test_native_timeout_is_distinct_from_invalid_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("test timeout")

    model = OllamaModel(
        "http://ollama",
        MODEL,
        httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(QueryError) as caught:
            model.generate([{"role": "user", "content": "Counter?"}], ["S1"])
        assert caught.value.status == 504
    finally:
        model.close()
