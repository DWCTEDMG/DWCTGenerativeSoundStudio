from __future__ import annotations

import os
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<parent_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_TRUTHY = {"1", "true", "yes", "on"}

correlation_context: ContextVar[dict[str, str] | None] = ContextVar(
    "request_correlation", default=None
)


@dataclass(frozen=True)
class Correlation:
    request_id: str
    trace_id: str
    span_id: str
    trace_flags: str
    traceparent: str
    tracestate: str | None = None


def correlation_enabled() -> bool:
    return os.getenv("EDMG_TRACE_CORRELATION_ENABLED", "").strip().lower() in _TRUTHY


def current_correlation() -> dict[str, str]:
    return dict(correlation_context.get() or {})


def _header(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for raw_name, raw_value in headers:
        if raw_name.lower() == name:
            return raw_value.decode("latin-1").strip()
    return ""


def parse_traceparent(value: str) -> tuple[str, str] | None:
    match = _TRACEPARENT_RE.fullmatch(value.strip().lower())
    if match is None or match["version"] == "ff":
        return None
    if match["version"] == "00" and len(value.strip()) != 55:
        return None
    trace_id = match["trace_id"]
    parent_id = match["parent_id"]
    if trace_id == "0" * 32 or parent_id == "0" * 16:
        return None
    return trace_id, match["flags"]


class CorrelationMiddleware:
    """Provide local W3C trace and request correlation without an exporter."""

    def __init__(self, app: Any, *, enabled: bool = False) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not self.enabled or scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers") or [])
        incoming = parse_traceparent(_header(headers, b"traceparent"))
        trace_id, flags = incoming or (secrets.token_hex(16), "01")
        span_id = secrets.token_hex(8)
        traceparent = f"00-{trace_id}-{span_id}-{flags}"
        supplied_request_id = _header(headers, b"x-request-id")
        request_id = (
            supplied_request_id
            if _REQUEST_ID_RE.fullmatch(supplied_request_id)
            else secrets.token_hex(16)
        )
        tracestate = _header(headers, b"tracestate") if incoming else ""
        correlation = Correlation(
            request_id=request_id,
            trace_id=trace_id,
            span_id=span_id,
            trace_flags=flags,
            traceparent=traceparent,
            tracestate=tracestate or None,
        )
        scope.setdefault("state", {})["correlation"] = correlation
        token = correlation_context.set(
            {
                "request_id": request_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "traceparent": traceparent,
            }
        )

        async def send_with_correlation(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers") or [])
                names = {name.lower() for name, _value in response_headers}
                additions = [
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"traceparent", traceparent.encode("ascii")),
                ]
                if correlation.tracestate:
                    additions.append((b"tracestate", correlation.tracestate.encode("latin-1")))
                response_headers.extend(item for item in additions if item[0] not in names)
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            correlation_context.reset(token)
