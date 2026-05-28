"""OpenTelemetry + Prometheus + structlog wiring.

Single :func:`setup_observability` entrypoint that:

* configures a global :class:`TracerProvider` exporting OTLP/HTTP spans to
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` (default ``http://localhost:4318``);
* auto-instruments FastAPI, SQLAlchemy (via the engine's ``sync_engine``), httpx,
  and asyncpg;
* mounts a Prometheus ``/metrics`` route (default registry, auth-free) via
  ``prometheus_fastapi_instrumentator``;
* configures :mod:`structlog` to emit JSON lines on stdout with ``time`` /
  ``level`` / ``event`` keys (so log shippers can fan-out to any aggregator).

Idempotency:
  The function early-returns when ``app.state.otel_setup`` is truthy. This guards
  against double-instrumentation when the FastAPI app is re-created within the
  same process (test suites, hot-reload), which would otherwise raise from the
  OTel instrumentors and double-register Prometheus collectors.

Opt-out:
  Setting ``SUITEST_OTEL_DISABLED=true`` (or ``1`` / ``yes``) skips ALL OTel
  instrumentation but still mounts ``/metrics`` and configures JSON logging — keeps
  tests fast and avoids the BatchSpanProcessor trying to flush to an unreachable
  collector during shutdown.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_fastapi_instrumentator import Instrumentator

from suitest_api import __version__

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncEngine


_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _is_disabled() -> bool:
    """Return True when ``SUITEST_OTEL_DISABLED`` is set to a truthy value."""
    return os.getenv("SUITEST_OTEL_DISABLED", "").strip().lower() in _TRUTHY


def _configure_structlog() -> None:
    """Configure :mod:`structlog` for JSON-on-stdout logging.

    Pipeline:
      * ``add_log_level`` → injects ``level`` (``info`` / ``error`` / ...);
      * ``TimeStamper(fmt="iso", utc=True, key="time")`` → ISO-8601 ``time``;
      * ``JSONRenderer()`` → final ``str`` line.

    The stdlib ``logging`` root is also wired to a plain ``StreamHandler`` on
    stdout so any non-structlog logger (uvicorn / sqlalchemy / fastapi) still flows
    to the same sink and gets captured by the platform log collector.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )

    # Funnel the stdlib root logger through the same stdout stream so anything
    # uvicorn / sqlalchemy logs lands next to structlog's output (one log stream
    # for container log shippers).
    root = logging.getLogger()
    if not any(
        isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout
        for h in root.handlers
    ):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setLevel(logging.INFO)
        root.addHandler(handler)


def _configure_tracing() -> None:
    """Install the global :class:`TracerProvider` + OTLP exporter once.

    Re-installing a TracerProvider in the same process is harmless (OTel just
    swaps the global), but the BatchSpanProcessor leaks a thread per call —
    :func:`setup_observability` already guards against repeated invocation, so we
    don't add a second guard here.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")
    traces_endpoint = endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "suitest-api"),
            "service.version": __version__,
        }
    )
    provider = TracerProvider(resource=resource)
    # HTTP/protobuf — works with localhost:4318 (OTel Collector default).
    exporter = OTLPSpanExporter(endpoint=traces_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def setup_observability(app: FastAPI, *, engine: AsyncEngine | None = None) -> None:
    """Wire OpenTelemetry traces + Prometheus metrics + structlog onto ``app``.

    Always-on:
      * structlog JSON renderer is configured on every call (cheap, idempotent);
      * Prometheus ``/metrics`` is exposed (default registry, ``include_in_schema=False``
        so it stays out of the public OpenAPI doc).

    OTel (skipped when ``SUITEST_OTEL_DISABLED`` is truthy):
      * Global TracerProvider + OTLP/HTTP exporter;
      * FastAPI / SQLAlchemy (``engine.sync_engine``) / httpx / asyncpg
        instrumentors.

    The function early-returns when ``app.state.otel_setup`` is truthy — repeated
    calls (e.g. test re-creating the app) are no-ops.
    """
    if getattr(app.state, "otel_setup", False):
        return

    _configure_structlog()

    if not _is_disabled():
        _configure_tracing()
        FastAPIInstrumentor.instrument_app(app)
        if engine is not None:
            # OTel's SQLAlchemy instrumentor binds to the *sync* engine; async
            # engines expose it via ``.sync_engine``.
            SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        HTTPXClientInstrumentor().instrument()
        # AsyncPGInstrumentor.__init__ is untyped in opentelemetry-instrumentation-asyncpg;
        # the call is safe at runtime — silence mypy's untyped-call here so the rest of
        # the codebase keeps strict typing intact.
        AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]

    # Prometheus default metrics (http_requests_total, http_request_duration_seconds, …).
    # Kept outside the OTel-disabled branch so /metrics is always scrapable, even
    # in tests where OTel is off.
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    app.state.otel_setup = True
