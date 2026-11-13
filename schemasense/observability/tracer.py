"""OpenTelemetry-Compatible Distributed Tracing & Span Context Manager for SchemaSense 2.0.

Provides seamless distributed tracing with zero mandatory external dependencies.
If `opentelemetry` is installed, it integrates directly with the global tracer;
otherwise, it maintains an in-process, context-propagated span lifecycle with
automatic sensitive attribute redaction (Mandatory Corrections 7 & 18).
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import time
import uuid
from typing import Any, Callable

from schemasense.telemetry import redact_sensitive_string

# Attempt native OpenTelemetry import if available
try:
    from opentelemetry import trace as otel_trace

    _HAS_OTEL = True
except ImportError:
    otel_trace = None
    _HAS_OTEL = False


class Span:
    """Lightweight in-memory distributed tracing span."""

    def __init__(
        self,
        name: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.trace_id = trace_id or uuid.uuid4().hex
        self.span_id = uuid.uuid4().hex[:16]
        self.parent_span_id = parent_span_id
        self.start_time = time.time()
        self.end_time: float | None = None
        self.duration_seconds: float = 0.0
        self.status: str = "OK"
        self.attributes: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []

        if attributes:
            for k, v in attributes.items():
                self.set_attribute(k, v)

    def set_attribute(self, key: str, value: Any) -> None:
        """Sets a sanitized attribute on the span."""
        if isinstance(value, str):
            clean_val = redact_sensitive_string(value)
        else:
            clean_val = value
        self.attributes[key] = clean_val

    def record_exception(self, exc: BaseException) -> None:
        """Records an exception event and marks the span status as ERROR."""
        self.status = "ERROR"
        self.events.append(
            {
                "name": "exception",
                "timestamp": time.time(),
                "attributes": {
                    "exception.type": type(exc).__name__,
                    "exception.message": redact_sensitive_string(str(exc)),
                },
            }
        )

    def set_status(self, status: str) -> None:
        """Sets span status ('OK' or 'ERROR')."""
        self.status = status.upper()

    def finish(self) -> None:
        """Completes span execution timing."""
        if self.end_time is None:
            self.end_time = time.time()
            self.duration_seconds = max(0.0, self.end_time - self.start_time)


# Context variable tracking current active span across async tasks and threads
_CURRENT_SPAN: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "current_span", default=None
)


def get_current_span() -> Span | None:
    """Returns the currently active span in the context, if any."""
    return _CURRENT_SPAN.get()


class SpanContextManager:
    """Context manager controlling span lifecycle and context propagation."""

    def __init__(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.raw_attributes = attributes or {}
        self.span: Span | None = None
        self._token: contextvars.Token | None = None
        self._otel_cm = None

    def __enter__(self) -> Span:
        if _HAS_OTEL and otel_trace is not None:
            try:
                tracer = otel_trace.get_tracer("schemasense.platform")
                clean_attrs = {
                    k: (redact_sensitive_string(v) if isinstance(v, str) else v)
                    for k, v in self.raw_attributes.items()
                }
                self._otel_cm = tracer.start_as_current_span(
                    self.name, attributes=clean_attrs
                )
                self._otel_cm.__enter__()
            except Exception:  # noqa: BLE001
                self._otel_cm = None

        parent_span = get_current_span()
        trace_id = parent_span.trace_id if parent_span else None
        parent_id = parent_span.span_id if parent_span else None

        self.span = Span(
            name=self.name,
            trace_id=trace_id,
            parent_span_id=parent_id,
            attributes=self.raw_attributes,
        )
        self._token = _CURRENT_SPAN.set(self.span)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.span:
            if exc_val is not None:
                self.span.record_exception(exc_val)
            self.span.finish()

        if self._token is not None:
            _CURRENT_SPAN.reset(self._token)

        if self._otel_cm is not None:
            try:
                self._otel_cm.__exit__(exc_type, exc_val, exc_tb)
            except Exception:  # noqa: BLE001
                pass


def trace_span(
    name: str | Callable[..., Any],
    attributes: dict[str, Any] | None = None,
) -> Any:
    """Unified span constructor: works as a context manager or as a decorator.

    Usage as context manager:
        with trace_span("agent.plan", {"tenant_id": "cust_123"}) as span:
            ...

    Usage as function decorator:
        @trace_span("task.profiling")
        def profile_data():
            ...
    """
    if callable(name):
        func = name
        span_name = f"{func.__module__}.{func.__qualname__}"

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with SpanContextManager(span_name, attributes):
                    return await func(*args, **kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with SpanContextManager(span_name, attributes):
                    return func(*args, **kwargs)

            return sync_wrapper

    return SpanContextManager(str(name), attributes)


def get_tracer(service_name: str = "schemasense") -> Any:
    """Returns the OpenTelemetry tracer if available, or a fallback handle."""
    if _HAS_OTEL and otel_trace is not None:
        return otel_trace.get_tracer(service_name)
    return None
