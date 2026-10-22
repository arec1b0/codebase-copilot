"""HTTP liveness, dependency readiness, and grounded query API."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse, Response

from app.contracts import QueryRequest, QueryResponse
from app.model import QueryError
from app.service import QueryService, build_service
from observability.tracing import Telemetry, current_trace_id, stage

SERVICE_NAME = "codebase-copilot"
SERVICE_VERSION = "0.5.0"
LOGGER = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Report process liveness without claiming dependency readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"]
    service: str
    version: str


def create_app(
    service: QueryService | None = None,
    *,
    initialize: bool = True,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Build an application; initialize resources during lifespan, not import."""
    active = service
    tracing = telemetry or Telemetry()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal active, tracing
        if telemetry is None and initialize and service is None:
            tracing = Telemetry.configured(SERVICE_VERSION)
        if active is None and initialize:
            try:
                active = build_service(tracing.tracer)
            except Exception as error:
                LOGGER.warning("Query startup unavailable (%s).", type(error).__name__)
        try:
            yield
        finally:
            if active is not None:
                active.close()
            active = None
            tracing.close()

    application = FastAPI(
        title="Codebase Copilot",
        description="An internal assistant for versioned source code and documentation.",
        version=SERVICE_VERSION,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4()
        if request.url.path == "/query":
            with stage(
                tracing.tracer,
                "POST /query",
                "CHAIN",
                {
                    "copilot.request_id": str(request.state.request_id),
                    "http.request.method": request.method,
                    "http.route": "/query",
                },
                server=True,
            ) as span:
                response = await call_next(request)
                span.set_attribute("http.response.status_code", response.status_code)
                if response.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
                identifier = current_trace_id()
                if identifier:
                    response.headers["X-Trace-ID"] = identifier
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    def error_body(request: Request, code: str, detail: str) -> dict[str, str]:
        return {"request_id": str(request.state.request_id), "error": code, "detail": detail}

    @application.exception_handler(QueryError)
    async def query_error(request: Request, error: QueryError) -> JSONResponse:
        return JSONResponse(error_body(request, error.code, str(error)), status_code=error.status)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            error_body(request, "invalid_request", "Request fields do not match the query schema."),
            status_code=422,
        )

    def require_service() -> QueryService:
        if active is None:
            raise QueryError(
                "not_ready",
                "Query service is unavailable. Check its configuration and dependencies.",
                503,
            )
        return active

    @application.get("/healthz", response_model=HealthResponse, tags=["operations"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service=SERVICE_NAME, version=SERVICE_VERSION)

    @application.get("/readyz", tags=["operations"])
    def ready(request: Request) -> dict[str, str]:
        try:
            require_service().check_ready()
        except QueryError:
            raise
        except Exception:
            raise QueryError("not_ready", "A query dependency is unavailable.", 503) from None
        return {"status": "ready", "request_id": str(request.state.request_id)}

    @application.post("/query", response_model=QueryResponse, tags=["query"])
    def query(body: QueryRequest, request: Request) -> QueryResponse:
        correlation: UUID = request.state.request_id
        return require_service().answer(body, correlation)

    return application


app = create_app()
