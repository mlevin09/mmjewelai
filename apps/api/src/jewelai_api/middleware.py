"""Pure ASGI request hardening applied before FastAPI body parsing."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

TRACE_CONTEXT = re.compile(rb"^([0-9a-f]{32})(?:/[0-9]+)?(?:;o=[01])?$")


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", ()))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared > self.max_bytes:
                await _send_too_large(send)
                return

        received = 0
        too_large = False
        response_started = False

        async def limited_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def tracked_send(message):
            nonlocal response_started
            if too_large:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, tracked_send)
        if too_large and not response_started:
            await _send_too_large(send)


class RequestObservabilityMiddleware:
    def __init__(
        self,
        app,
        *,
        logger: logging.Logger,
        service: str,
        environment: str,
        gcp_project_id: str | None,
    ) -> None:
        self.app = app
        self.logger = logger
        self.service = service
        self.environment = environment
        self.gcp_project_id = gcp_project_id

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        response_started = False
        started = time.perf_counter()

        async def observed_send(message):
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = list(message.get("headers", ()))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except Exception as exc:
            self.logger.error(
                "Unhandled application error",
                extra={
                    "jewelai_fields": {
                        "service": self.service,
                        "environment": self.environment,
                        "event": "application_error",
                        "request_id": request_id,
                        "error_code": type(exc).__name__,
                    }
                },
            )
            if response_started:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            else:
                await _send_internal_error(observed_send)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            fields: dict[str, Any] = {
                "service": self.service,
                "environment": self.environment,
                "event": "http_request_completed",
                "request_id": request_id,
                "method": scope.get("method", ""),
                "route": route_template,
                "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
            trace_id = _trace_id(scope.get("headers", ()))
            if trace_id and self.gcp_project_id:
                fields["logging.googleapis.com/trace"] = (
                    f"projects/{self.gcp_project_id}/traces/{trace_id}"
                )
            self.logger.info("HTTP request completed", extra={"jewelai_fields": fields})


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = dict(getattr(record, "jewelai_fields", {}))
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            **fields,
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_json_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "jewelai_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        handler.jewelai_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


async def _send_too_large(send: Callable[[dict], Awaitable[None]]) -> None:
    body = b'{"error":"request_too_large","detail":"Request body exceeds configured limit"}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-content-type-options", b"nosniff"),
                (b"referrer-policy", b"no-referrer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_internal_error(send: Callable[[dict], Awaitable[None]]) -> None:
    body = b'{"error":"internal_error","detail":"Internal server error"}'
    await send(
        {
            "type": "http.response.start",
            "status": 500,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _trace_id(headers: list[tuple[bytes, bytes]]) -> str | None:
    value = dict(headers).get(b"x-cloud-trace-context")
    if value is None:
        return None
    match = TRACE_CONTEXT.fullmatch(value)
    return match.group(1).decode("ascii") if match else None
