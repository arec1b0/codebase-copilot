"""Retrieve complete query traces from the pinned Phoenix REST API."""

import time
from typing import Any

import httpx

from observability.tracing import PROJECT, valid_trace_id

REQUIRED = {"POST /query", "retrieval", "rerank", "generation", "citation_validation"}


def fetch_trace(client: httpx.Client, trace_id: str, request_id: str) -> dict[str, Any]:
    if not valid_trace_id(trace_id):
        raise ValueError("API did not return a valid trace ID. Enable tracing and restart it.")
    deadline = time.monotonic() + 20
    while True:
        response = client.get(
            f"/v1/projects/{PROJECT}/spans", params={"trace_id": trace_id, "limit": 100}
        )
        if response.status_code == 404:
            spans: list[dict[str, Any]] = []
        else:
            response.raise_for_status()
            data = response.json()
            if data.get("next_cursor"):
                raise ValueError("Unexpectedly large query trace; refusing a partial export.")
            spans = data["data"]
        roots = [span for span in spans if span["name"] == "POST /query"]
        if roots and REQUIRED.issubset({span["name"] for span in spans}):
            if len(roots) != 1:
                raise ValueError("Phoenix returned multiple API roots for one query.")
            span_ids = [span["context"]["span_id"] for span in spans]
            if len(set(span_ids)) != len(span_ids):
                raise ValueError("Phoenix returned duplicate span IDs.")
            root = roots[0]
            if root["attributes"].get("copilot.request_id") != request_id:
                raise ValueError("Phoenix root request ID differs from the API response.")
            if any(span["context"]["trace_id"] != trace_id for span in spans):
                raise ValueError("Phoenix returned a span from a different trace.")
            root_id = root["context"]["span_id"]
            for span in spans:
                if span["name"] in REQUIRED - {"POST /query"} and span["parent_id"] != root_id:
                    raise ValueError("Query stages are not children of the API span.")
            return {"trace_id": trace_id, "request_id": request_id, "spans": spans}
        if time.monotonic() >= deadline:
            raise ValueError("Complete query trace did not arrive in Phoenix within 20 seconds.")
        time.sleep(0.5)
