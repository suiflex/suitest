"""OpenTelemetry + structlog wiring for the ARQ worker.

Mirrors :mod:`suitest_api.observability` in spirit (one stdout JSON stream, OTLP
traces to ``OTEL_EXPORTER_OTLP_ENDPOINT``) but skips the FastAPI / Prometheus /
SQLAlchemy bits — the worker doesn't serve HTTP and we instrument SQLAlchemy
where the engine is created (in :mod:`suitest_runner.worker`'s startup hook)
rather than at process init.

Idempotency:
  Repeated :func:`setup_observability` calls are no-ops via a module-level
  ``_setup_done`` flag — same guard pattern as the API side, so test suites
  that re-import the worker module don't leak BatchSpanProcessor threads.

Opt-out:
  ``SUITEST_OTEL_DISABLED=true`` (or ``1`` / ``yes``) skips OTel TracerProvider
  installation. JSON logging is still configured.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from suitest_runner import __version__

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_setup_done = False


def _is_disabled() -> bool:
    """Return True when ``SUITEST_OTEL_DISABLED`` is set to a truthy value."""
    return os.getenv("SUITEST_OTEL_DISABLED", "").strip().lower() in _TRUTHY


def _configure_structlog() -> None:
    """Configure :mod:`structlog` for JSON-on-stdout logging.

    Pipeline mirrors the API side (``level`` / ``time`` / ``event`` keys) so log
    shippers can fan-out worker + API logs to the same aggregator without
    per-service schema branching.
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

    # Funnel stdlib root logger through the same stdout stream so ARQ / SQLAlchemy
    # log lines land next to structlog's output (one stream for the container
    # log collector).
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

    Repeated calls would leak a BatchSpanProcessor thread per call — the
    module-level ``_setup_done`` flag in :func:`setup_observability` guards
    against that, so we don't add a second guard here.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318").rstrip("/")
    traces_endpoint = endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"
    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "suitest-runner"),
            "service.version": __version__,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=traces_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def setup_observability() -> None:
    """Wire structlog JSON + (optionally) OpenTelemetry tracing for the worker.

    Always-on:
      * structlog JSON renderer is configured on every call (cheap, idempotent).

    OTel (skipped when ``SUITEST_OTEL_DISABLED`` is truthy):
      * Global TracerProvider + OTLP/HTTP exporter.

    Repeated calls are no-ops via a module-level ``_setup_done`` flag.
    """
    global _setup_done
    if _setup_done:
        return

    _configure_structlog()
    if not _is_disabled():
        _configure_tracing()

    _setup_done = True


def get_tracer() -> trace.Tracer:
    """Return a tracer bound to the worker's instrumentation scope.

    Job handlers use this to open spans annotated with ``job.id`` / ``job.queue``
    / ``run.id`` so the same trace links into the API span that enqueued the run.
    """
    return trace.get_tracer("suitest_runner", __version__)
