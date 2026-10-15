"""Verify real OTLP HTTP serialization without claiming a live Phoenix test."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from observability.tracing import Telemetry, stage


def test_otlp_exporter_sends_protobuf_to_local_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[bytes] = []
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append(self.rfile.read(int(self.headers["Content-Length"])))
            paths.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    monkeypatch.setattr(
        "observability.tracing.phoenix_url", lambda: f"http://127.0.0.1:{server.server_port}"
    )
    monkeypatch.setenv("COPILOT_TRACING", "1")
    telemetry = Telemetry.configured("test")
    try:
        with stage(telemetry.tracer, "test-root", "CHAIN", {"copilot.request_id": "wire-test"}):
            pass
        assert telemetry.provider is not None
        assert telemetry.provider.force_flush(timeout_millis=3000)
        message = ExportTraceServiceRequest()
        message.ParseFromString(received[0])
        assert paths == ["/v1/traces"]
        resource = message.resource_spans[0]
        attributes = {item.key: item.value.string_value for item in resource.resource.attributes}
        assert attributes["openinference.project.name"] == "codebase-copilot-week1"
        assert resource.scope_spans[0].spans[0].name == "test-root"
    finally:
        telemetry.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
