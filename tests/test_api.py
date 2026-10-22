"""Exercise HTTP behavior through the application boundary."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_liveness_contract() -> None:
    with TestClient(create_app(initialize=False)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "status": "ok",
        "service": "codebase-copilot",
        "version": "0.5.0",
    }


def test_liveness_rejects_unsupported_method() -> None:
    with TestClient(create_app(initialize=False)) as client:
        response = client.post("/healthz")

    assert response.status_code == 405


def test_unknown_endpoint_is_not_a_success() -> None:
    with TestClient(create_app(initialize=False)) as client:
        response = client.get("/missing")

    assert response.status_code == 404


def test_openapi_exposes_typed_health_response() -> None:
    with TestClient(create_app(initialize=False)) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    health_schema = schema["components"]["schemas"]["HealthResponse"]
    assert set(health_schema["required"]) == {"status", "service", "version"}
    assert health_schema["properties"]["status"]["const"] == "ok"
    assert "/healthz" in schema["paths"]
