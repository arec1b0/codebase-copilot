"""Metadata-only OpenInference spans exported to the local Phoenix collector."""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

import requests
from openinference.semconv.trace import SpanAttributes
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer
from opentelemetry.util.types import Attributes

from indexing.config import ROOT

PROJECT = "codebase-copilot-week1"


def phoenix_url() -> str:
    port = "6006"
    file = ROOT / ".env"
    if file.exists():
        for line in file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "PHOENIX_PORT":
                port = value.strip()
    port = os.environ.get("PHOENIX_PORT", port)
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("PHOENIX_PORT must be a valid TCP port.")
    return f"http://127.0.0.1:{port}"


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    return f"{context.trace_id:032x}" if context.is_valid else None


@contextmanager
def stage(
    tracer: Tracer,
    name: str,
    kind: str,
    attributes: Attributes = None,
    *,
    server: bool = False,
) -> Iterator[Span]:
    with tracer.start_as_current_span(
        name,
        kind=SpanKind.SERVER if server else SpanKind.INTERNAL,
        attributes={SpanAttributes.OPENINFERENCE_SPAN_KIND: kind, **(attributes or {})},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as error:
            code = getattr(error, "code", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR, str(code)))
            span.set_attribute("error.type", type(error).__name__)
            raise


class Telemetry:
    def __init__(self, provider: TracerProvider | None = None) -> None:
        self.provider = provider
        self.tracer = provider.get_tracer("codebase-copilot") if provider else trace.NoOpTracer()

    @classmethod
    def configured(cls, version: str) -> "Telemetry":
        if os.environ.get("COPILOT_TRACING", "1") == "0":
            return cls()
        session = requests.Session()
        session.trust_env = False
        exporter = OTLPSpanExporter(
            endpoint=phoenix_url() + "/v1/traces", timeout=2, session=session, headers={}
        )
        provider = TracerProvider(
            sampler=ALWAYS_ON,
            resource=Resource.create(
                {
                    "service.name": "codebase-copilot",
                    "service.version": version,
                    "deployment.environment.name": "local",
                    "openinference.project.name": PROJECT,
                }
            ),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_queue_size=512,
                max_export_batch_size=64,
                schedule_delay_millis=1000,
                export_timeout_millis=3000,
            )
        )
        return cls(provider)

    def close(self) -> None:
        if self.provider:
            self.provider.force_flush(timeout_millis=3000)
            self.provider.shutdown()


def valid_trace_id(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[a-f0-9]{32}", value) and int(value, 16))
