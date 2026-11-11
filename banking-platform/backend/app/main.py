import base64
import hmac
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import Histogram, generate_latest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException

from . import (
    analytics,
    api,
    assistant,
    clearing,
    db,
    exceptions,
    knowledge,
    mcp_server,
    reconciliation,
    settlement,
)
from .common import actor_context, request_context
from .errors import DomainError

REQUEST_LATENCY = Histogram(
    "banking_http_request_seconds", "HTTP response latency", ["method", "route", "status"]
)
log = logging.getLogger("banking.http")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        output = {
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "requestId",
            "method",
            "route",
            "status",
            "durationMs",
            "transaction_id",
            "attempt",
            "category",
        ):
            if hasattr(record, key):
                output[key] = getattr(record, key)
        return json.dumps(output)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logging.getLogger("httpx").setLevel(logging.WARNING)


def flag(name, default=False):
    return os.getenv(name, str(default)).lower() in {"true", "1", "yes"}


def validate_security():
    enabled = flag("APP_AUTH_ENABLED", True)
    if not enabled and not flag("APP_DEMO"):
        raise RuntimeError(
            "Authentication can only be disabled with APP_DEMO=true on a loopback demo server."
        )
    if enabled and (not os.getenv("APP_API_USERNAME") or not os.getenv("APP_API_PASSWORD")):
        raise RuntimeError(
            "Configure APP_API_USERNAME and APP_API_PASSWORD before starting the secured server."
        )
    reader_name, reader_pass = os.getenv("APP_READONLY_USERNAME"), os.getenv("APP_READONLY_PASSWORD")
    if bool(reader_name) != bool(reader_pass) or (
        reader_name and reader_name == os.getenv("APP_API_USERNAME")
    ):
        raise RuntimeError("Configure a distinct complete read-only credential pair.")


def problem(status, detail, request_id):
    return JSONResponse(
        {
            "type": "about:blank",
            "title": __import__("http").HTTPStatus(status).phrase,
            "status": status,
            "detail": detail,
            "requestId": request_id,
        },
        status_code=status,
        media_type="application/problem+json",
    )


@asynccontextmanager
async def lifespan(app):
    validate_security()
    async with app.state.mcp.session_manager.run():
        yield


async def request_controls(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else str(uuid4())
    token = request_context.set(request_id)
    actor_token = actor_context.set("anonymous")
    started = time.perf_counter()
    response = None
    try:
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 2_097_152):
            response = problem(413, "Request body must be at most 2 MiB.", request_id)
        elif flag("APP_AUTH_ENABLED", True) and not (
            request.url.path == "/health" or request.url.path.startswith("/health/")
        ):
            role = None
            try:
                scheme, value = request.headers.get("Authorization", "").split(" ", 1)
                if scheme.lower() == "basic" and len(value) <= 2048:
                    username, password = base64.b64decode(value, validate=True).decode().split(":", 1)
                    for kind, name_key, pass_key in (
                        ("operator", "APP_API_USERNAME", "APP_API_PASSWORD"),
                        ("reader", "APP_READONLY_USERNAME", "APP_READONLY_PASSWORD"),
                    ):
                        configured = os.getenv(name_key, "")
                        if (
                            configured
                            and hmac.compare_digest(username.encode("utf-8"), configured.encode("utf-8"))
                            and hmac.compare_digest(
                                password.encode("utf-8"), os.getenv(pass_key, "").encode("utf-8")
                            )
                        ):
                            role = kind
            except (ValueError, UnicodeError):
                pass
            if role is None:
                response = problem(401, "Valid API credentials are required.", request_id)
                response.headers["WWW-Authenticate"] = 'Basic realm="banking"'
            elif role == "reader" and (
                request.url.path == "/metrics"
                or (
                    request.method not in {"GET", "HEAD", "OPTIONS"}
                    and not (request.url.path == "/mcp" or request.url.path.startswith("/mcp/"))
                    and request.url.path != "/api/knowledge/search"
                )
            ):
                response = problem(403, "This read-only account cannot perform that operation.", request_id)
            else:
                actor_context.set(role)
        else:
            actor_context.set("demo")
        if response is None:
            if request.method in {"POST", "PUT", "PATCH"}:
                chunks = []
                received = 0
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > 2_097_152:
                        response = problem(413, "Request body must be at most 2 MiB.", request_id)
                        break
                    chunks.append(chunk)
                if response is None:
                    request._body = b"".join(chunks)
        if response is None:
            response = await call_next(request)
    except Exception:
        log.error("Unhandled request failure", extra={"requestId": request_id})
        response = problem(500, "Unexpected server error. Use the request ID for investigation.", request_id)
    finally:
        route = getattr(request.scope.get("route"), "path", "unmatched")
        status = response.status_code if response else 500
        REQUEST_LATENCY.labels(request.method, route, str(status)).observe(time.perf_counter() - started)
        log.info(
            "HTTP request completed",
            extra={
                "requestId": request_id,
                "method": request.method,
                "route": route,
                "status": status,
                "durationMs": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        actor_context.reset(actor_token)
        request_context.reset(token)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


operations = APIRouter()


async def domain_error(request, exc):
    return problem(exc.status, exc.detail, request_context.get())


async def database_conflict(request, exc):
    return problem(
        409, "Request conflicts with an existing or concurrently changed resource.", request_context.get()
    )


async def database_unavailable(request, exc):
    return problem(503, "Database temporarily unavailable.", request_context.get())


async def validation_error(request, exc):
    return problem(
        422,
        "Request validation failed. Check documented field types, limits and required values.",
        request_context.get(),
    )


async def http_error(request, exc):
    return problem(
        exc.status_code, "The requested route or HTTP method is unavailable.", request_context.get()
    )


@operations.get("/health/liveness", tags=["Operations"])
def liveness():
    return {"status": "UP"}


@operations.get("/health", tags=["Operations"])
@operations.get("/health/readiness", tags=["Operations"])
def readiness():
    with db.SessionLocal() as session:
        session.execute(text("SELECT 1"))
    return {"status": "UP", "database": "ready", "eventsEnabled": flag("EVENTS_ENABLED")}


@operations.get("/metrics", tags=["Operations"])
def metrics():
    from .events import metrics_text

    return Response(
        metrics_text(db.SessionLocal) + generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def create_app():
    application = FastAPI(
        title="Enterprise Banking Transaction & Reconciliation Platform",
        version="1.0.0",
        description="Independent educational project. Synthetic data only. No employer affiliation.",
        lifespan=lifespan,
    )
    application.middleware("http")(request_controls)
    for exception, handler in (
        (DomainError, domain_error),
        (IntegrityError, database_conflict),
        (OperationalError, database_unavailable),
        (RequestValidationError, validation_error),
        (ValidationError, validation_error),
        (HTTPException, http_error),
    ):
        application.add_exception_handler(exception, handler)
    for router in (
        operations,
        api.router,
        clearing.router,
        settlement.router,
        reconciliation.router,
        exceptions.router,
        analytics.router,
        knowledge.router,
        assistant.router,
    ):
        application.include_router(router)
    server = mcp_server.create_mcp_server()
    application.state.mcp = server
    application.mount("/mcp", server.streamable_http_app())
    return application


app = create_app()
