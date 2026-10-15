"""Local Ollama streaming transport and immutable model identity checks."""

import json
import re
import time
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.contracts import Generation, ModelAnswer, ModelIdentity, TokenUsage


class QueryError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.code, self.status = code, status


class ModelBackend(Protocol):
    def identity(self) -> ModelIdentity: ...
    def generate(self, messages: list[dict[str, str]], source_ids: list[str]) -> Generation: ...
    def close(self) -> None: ...


class OllamaModel:
    def __init__(self, base_url: str, model: str, client: httpx.Client | None = None) -> None:
        self.model = model
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=httpx.Timeout(180, connect=5), trust_env=False
        )

    def identity(self) -> ModelIdentity:
        try:
            tags = self.client.get("/api/tags", timeout=5)
            version = self.client.get("/api/version", timeout=5)
            tags.raise_for_status()
            version.raise_for_status()
            models = tags.json().get("models", [])
            backend_version = version.json().get("version")
            for item in models:
                if item.get("name") == self.model or item.get("model") == self.model:
                    digest = item.get("digest", "")
                    if not isinstance(digest, str) or not re.fullmatch(
                        r"(?:sha256:)?[a-f0-9]{64}", digest
                    ):
                        break
                    if not isinstance(backend_version, str) or not backend_version:
                        break
                    return ModelIdentity(
                        model=self.model,
                        revision="sha256:" + digest.removeprefix("sha256:"),
                        backend_version=f"ollama:{backend_version}",
                    )
        except (httpx.HTTPError, ValueError, AttributeError, TypeError):
            raise QueryError(
                "model_unavailable", "Cannot inspect the local Ollama model.", 503
            ) from None
        raise QueryError(
            "model_unavailable", "The selected local model is missing or has no valid digest.", 503
        )

    def generate(self, messages: list[dict[str, str]], source_ids: list[str]) -> Generation:
        schema = ModelAnswer.model_json_schema()
        schema["$defs"]["SourceClaim"]["properties"]["source_ids"]["items"]["enum"] = source_ids
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "format": schema,
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 512},
            "keep_alive": "5m",
        }
        start = time.perf_counter()
        ttft: float | None = None
        pieces = []
        byte_count = 0
        final: dict[str, object] | None = None
        try:
            with self.client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if time.perf_counter() - start > 180:
                        raise QueryError(
                            "model_timeout", "Generation exceeded the total time limit.", 504
                        )
                    if not line:
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get("error"):
                        raise QueryError(
                            "invalid_model_output", "Model stream returned an invalid event."
                        )
                    if event.get("model") != self.model:
                        raise QueryError(
                            "invalid_model_output", "Model stream used an unexpected model name."
                        )
                    message = event.get("message", {})
                    if not isinstance(message, dict) or message.get("tool_calls"):
                        raise QueryError(
                            "invalid_model_output", "Model stream returned unsupported tool calls."
                        )
                    fragment = message.get("content", "")
                    if not isinstance(fragment, str):
                        raise QueryError("invalid_model_output", "Model content must be text.")
                    if fragment:
                        if ttft is None:
                            ttft = (time.perf_counter() - start) * 1000
                        pieces.append(fragment)
                        byte_count += len(fragment.encode("utf-8"))
                        if byte_count > 16000:
                            raise QueryError(
                                "invalid_model_output", "Model output exceeded its byte limit."
                            )
                    if event.get("done") is True:
                        final = event
                        break
            if final is None or final.get("done_reason") != "stop" or ttft is None:
                raise QueryError(
                    "invalid_model_output", "Model stream was incomplete or reached a token limit."
                )
            content = ModelAnswer.model_validate_json("".join(pieces))
            usage = TokenUsage.model_validate(
                {
                    "input_tokens": final.get("prompt_eval_count"),
                    "output_tokens": final.get("eval_count"),
                }
            )
            if usage.input_tokens + 512 > 8192 or usage.output_tokens > 512:
                raise QueryError(
                    "invalid_model_output", "Model token counts violate the context contract."
                )
        except httpx.TimeoutException:
            raise QueryError("model_timeout", "Local model request timed out.", 504) from None
        except httpx.HTTPError:
            raise QueryError(
                "model_unavailable", "Local model generation request failed.", 503
            ) from None
        except (ValueError, ValidationError, TypeError):
            raise QueryError(
                "invalid_model_output", "Model output failed the JSON or usage contract."
            ) from None
        return Generation(
            content=content,
            usage=usage,
            ttft_ms=ttft,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    def close(self) -> None:
        self.client.close()
