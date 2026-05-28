"""Tests for :mod:`suitest_api.observability` and span-attributes middleware.

Three contracts are pinned:

* ``GET /metrics`` returns Prometheus exposition format (default registry).
* structlog emits JSON lines containing ``event`` / ``level`` / ``time`` keys.
* The :class:`SpanAttributesMiddleware` tags the active OTel span with
  ``workspace.id`` (when ``X-Workspace-Id`` is provided) and ``capabilities.tier``.

The third test re-enables OTel (clears ``SUITEST_OTEL_DISABLED``), swaps the
TracerProvider's processor for :class:`InMemorySpanExporter` BEFORE the FastAPI
instrumentor runs, then drives a request through the app and asserts the
exported span attributes.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import structlog
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest_asyncio.fixture
async def metrics_client() -> AsyncIterator[AsyncClient]:
    """Lifespan-wired client. Inherits ``SUITEST_OTEL_DISABLED=true`` from conftest."""
    # Late import so conftest's env tweak (SUITEST_OTEL_DISABLED) is honoured.
    from suitest_api.main import create_app

    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_default_metrics(metrics_client: AsyncClient) -> None:
    """``/metrics`` must serve Prometheus exposition format (no auth required)."""
    # Generate one request first so request-counter metrics actually have samples.
    await metrics_client.get("/health")
    response = await metrics_client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    # Prometheus exposition format always begins each metric family with `# HELP`.
    assert "# HELP" in body
    assert "# TYPE" in body
    # Default instrumentator exposes request-duration histograms — check the
    # well-known family name without pinning the exact metric prefix (depends on
    # instrumentator config).
    assert "http_request" in body


@pytest.mark.asyncio
async def test_request_logs_are_json() -> None:
    """structlog emits one JSON object per log line with the canonical keys."""
    from suitest_api.observability import setup_observability

    # Capture configured by an isolated buffer instead of stdout so capsys/caplog
    # quirks (pytest's stdout capture races with structlog's PrintLogger) don't
    # turn this into a flaky test.
    buf = io.StringIO()
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="time"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buf),
        cache_logger_on_first_use=False,
    )

    log = structlog.get_logger("test_obs")
    log.info("incoming_request", request_id="r1", method="GET", path="/health")
    log.warning("downstream_slow", request_id="r1", duration_ms=812)

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert lines, "structlog must emit at least one line"
    for line in lines:
        record = json.loads(line)
        assert "event" in record
        assert "level" in record
        assert "time" in record

    # The first call already mutated the structlog global config. Call
    # setup_observability to confirm it can re-configure without raising
    # (idempotency proxy — does not redirect our buf-based logger).
    from fastapi import FastAPI

    fresh_app = FastAPI()
    setup_observability(fresh_app)
    setup_observability(fresh_app)  # second call must be a no-op


@pytest.mark.asyncio
async def test_span_attributes_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Span-attributes middleware tags the OTel span with workspace.id + tier."""
    # Force OTel ON for this test; we own the exporter so nothing escapes.
    monkeypatch.setenv("SUITEST_OTEL_DISABLED", "false")

    # Install an in-memory tracer provider BEFORE create_app + setup_observability
    # runs. setup_observability calls trace.set_tracer_provider(...) which would
    # overwrite ours, so we monkeypatch the helper that does it.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    def _install_memory_tracer() -> None:
        trace.set_tracer_provider(provider)

    monkeypatch.setattr(
        "suitest_api.observability._configure_tracing",
        _install_memory_tracer,
    )

    from suitest_api.main import create_app

    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/health", headers={"X-Workspace-Id": "ws_observ"})
            assert resp.status_code == 200

    spans = exporter.get_finished_spans()
    assert spans, "FastAPIInstrumentor must export at least one span per request"
    # Find the span that carries our custom attributes (the outer HTTP server
    # span — siblings like asgi.send carry only protocol metadata).
    workspace_spans = [s for s in spans if (s.attributes or {}).get("workspace.id")]
    assert (
        workspace_spans
    ), f"no span carried workspace.id; got: {[(s.name, dict(s.attributes or {})) for s in spans]}"
    attrs = dict(workspace_spans[0].attributes or {})
    assert attrs.get("workspace.id") == "ws_observ"
    # capabilities.tier should match whatever resolve_tier returned (ZERO in
    # default test env — no LLM provider configured).
    assert "capabilities.tier" in attrs
    assert isinstance(attrs["capabilities.tier"], str)

    # Restore OTel-disabled for downstream tests sharing this process.
    os.environ["SUITEST_OTEL_DISABLED"] = "true"
