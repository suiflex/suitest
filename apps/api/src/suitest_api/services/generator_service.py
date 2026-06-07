"""GeneratorService — orchestrates deterministic generation + persistence (M2).

``run_openapi`` drives the deterministic :class:`OpenApiGenerator`: it creates a
:class:`GeneratorRun` row (``source="openapi"``), iterates the generated
:class:`TestCaseDraft`s, persists each as a ``DRAFT`` :class:`TestCase` (+ its
steps + tags) linked to ``target_suite_id``, and streams one
:class:`GeneratorSseEvent` per phase (``progress`` → ``case`` → ``complete``).

A spec/parse failure yields a single structured ``error`` event and stops — the
HTTP layer keeps the 200 SSE stream open and lets the client read the error
frame (the request itself was well-formed; the *spec* was not).

Tier: deterministic, NO LLM → runs in every tier (the endpoint stamps
``TierFlag.ANY``). All MCP wiring is deferred to run time via the rendered
``mcp.api.request`` step code; this service never invokes an MCP server.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import TYPE_CHECKING

from opentelemetry import trace
from suitest_agent.generators.mcp_discovery import McpDiscoveryGenerator
from suitest_agent.generators.openapi_enrich import OpenApiEnricher
from suitest_agent.generators.openapi_generator import OpenApiGenerator, OpenApiSpecError
from suitest_agent.generators.prd import PrdGenerator
from suitest_agent.generators.url_crawler import UrlCrawler
from suitest_agent.generators.url_semantic import UrlSemanticGenerator
from suitest_agent.providers.litellm_router import get_provider
from suitest_db.audit import write_audit
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.public_id import set_workspace_id
from suitest_db.repositories.agent_sessions import AgentSessionCreate, AgentSessionRepo
from suitest_shared.domain.enums import AgentSessionKind, CaseStatus, TargetKind
from suitest_shared.schemas.generator_input import (
    CrawlerGenerateRequest,
    GeneratorSseEvent,
    McpDiscoveryGenerateRequest,
    OpenApiGenerateRequest,
    PrdGenerateRequest,
    TestCaseDraft,
    UrlSemanticGenerateRequest,
)

from suitest_api.services.prompt_resolver import resolve_and_pin

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.repositories.generator_runs import GeneratorRunRepo
    from suitest_db.repositories.projects import ProjectRepo
    from suitest_db.repositories.suites import SuiteRepo
    from suitest_mcp.invoker import McpInvoker

tracer = trace.get_tracer("suitest.generators")


class SuiteNotInWorkspaceError(Exception):
    """``target_suite_id`` does not resolve to a live suite in the workspace.

    The router maps this to ``404`` (NEVER 403) so a caller cannot probe the
    existence of suites in other workspaces.
    """

    def __init__(self, suite_id: str) -> None:
        super().__init__(f"suite {suite_id} not found in workspace")
        self.suite_id = suite_id


class GeneratorService:
    """Deterministic-generator orchestrator. One instance per request."""

    def __init__(
        self,
        db_session: AsyncSession,
        generator_run_repo: GeneratorRunRepo,
        suite_repo: SuiteRepo,
        project_repo: ProjectRepo,
        http_client: httpx.AsyncClient,
        mcp_invoker: McpInvoker | None = None,
    ) -> None:
        self._session = db_session
        self._run_repo = generator_run_repo
        self._suite_repo = suite_repo
        self._project_repo = project_repo
        self._http = http_client
        # Injected so the crawler is mockable in tests; the router wires the real
        # invoker (registry + pool + redis + audit) for production crawls.
        self._mcp_invoker = mcp_invoker

    # ------------------------------------------------------------------

    async def suite_in_scope(self, suite_id: str, workspace_id: str) -> bool:
        """Return whether ``suite_id`` is a live suite owned by ``workspace_id``."""
        suite = await self._suite_repo.get_active_by_id(suite_id)
        if suite is None:
            return False
        project = await self._project_repo.get_by_id(suite.project_id)
        return project is not None and project.workspace_id == workspace_id

    @staticmethod
    def _as_user_uuid(user_id: str) -> uuid.UUID | None:
        try:
            return uuid.UUID(user_id)
        except (ValueError, AttributeError):
            return None

    # ------------------------------------------------------------------

    async def run_openapi(
        self,
        workspace_id: str,
        user_id: str,
        request: OpenApiGenerateRequest,
        *,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Stream the OpenAPI generation lifecycle as SSE events.

        Validates the suite is in-scope FIRST (raising
        :class:`SuiteNotInWorkspaceError` for the router to map to 404 *before*
        any stream byte is sent). After that the generator drives the body; a
        spec error becomes an ``error`` event rather than an exception.

        When ``request.options.include_llm_edge_cases`` is set AND the caller
        passes a resolved LLM (``llm_provider``/``llm_model``), a second pass adds
        boundary/fuzz/negative edge cases (M3-8). The deterministic core always
        runs first; the LLM pass is pure enrichment and is skipped gracefully
        (``llm_enrich_skipped`` progress frame) when no LLM is configured.
        """
        if not await self.suite_in_scope(request.target_suite_id, workspace_id):
            raise SuiteNotInWorkspaceError(request.target_suite_id)

        with tracer.start_as_current_span("generator.openapi") as span:
            span.set_attribute("generator.source", "openapi")
            span.set_attribute("workspace.id", workspace_id)
            start = time.perf_counter()

            run = GeneratorRun(
                workspace_id=workspace_id,
                source="openapi",
                input_meta_json={
                    "target_suite_id": request.target_suite_id,
                    "spec_url": request.spec_url,
                    "has_inline_content": request.spec_content is not None,
                    "options": request.options.model_dump(),
                },
                output_case_ids_json=[],
                created_by_user_id=self._as_user_uuid(user_id),
            )
            self._session.add(run)
            await self._session.flush()
            run_id = run.id

            generator = OpenApiGenerator(self._http, request.options)
            try:
                await generator.fetch_spec(request.spec_url, request.spec_content)
            except OpenApiSpecError as exc:
                span.set_attribute("generator.error", str(exc))
                # Keep the (empty) run row for traceability; commit so the error
                # is auditable even though no cases were produced.
                await self._finalize(run, workspace_id, user_id, public_ids=[], duration_ms=0)
                await self._session.commit()
                yield GeneratorSseEvent(
                    kind="error",
                    data={"code": "INVALID_SPEC", "message": str(exc)},
                )
                return

            yield GeneratorSseEvent(
                kind="progress",
                data={"phase": "parsed", "generator_run_id": run_id},
            )

            public_ids: list[str] = []
            async for draft in generator.generate():
                public_id = await self._persist_case(
                    draft, suite_id=request.target_suite_id, workspace_id=workspace_id
                )
                public_ids.append(public_id)
                yield GeneratorSseEvent(
                    kind="case",
                    data={
                        "public_id": public_id,
                        "name": draft.name,
                        "case_kind": draft.generated_from.get("case_kind"),
                        "tags": draft.tags,
                    },
                )

            # M3-8: optional LLM edge-case enrichment on top of the contract suite.
            if request.options.include_llm_edge_cases:
                async for event in self._enrich_openapi(
                    generator,
                    workspace_id,
                    user_id,
                    request,
                    public_ids=public_ids,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    llm_api_key=llm_api_key,
                    llm_base_url=llm_base_url,
                ):
                    yield event

            duration_ms = int((time.perf_counter() - start) * 1000)
            span.set_attribute("generator.cases_created", len(public_ids))
            await self._finalize(
                run, workspace_id, user_id, public_ids=public_ids, duration_ms=duration_ms
            )
            await self._session.commit()

            yield GeneratorSseEvent(
                kind="complete",
                data={
                    "generator_run_id": run_id,
                    "target_suite_id": request.target_suite_id,
                    "cases_created": len(public_ids),
                    "public_ids": public_ids,
                    "duration_ms": duration_ms,
                },
            )

    async def _enrich_openapi(
        self,
        generator: OpenApiGenerator,
        workspace_id: str,
        user_id: str,
        request: OpenApiGenerateRequest,
        *,
        public_ids: list[str],
        llm_provider: str | None,
        llm_model: str | None,
        llm_api_key: str | None,
        llm_base_url: str | None,
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Append LLM edge cases (M3-8). Yields ``progress`` + per-edge ``case``.

        Mutates ``public_ids`` in place so the caller's ``complete`` frame counts
        the edge cases. No LLM configured → a single ``llm_enrich_skipped`` frame
        (graceful ZERO degrade); the deterministic suite already persisted.
        """
        if not (llm_provider and llm_model):
            yield GeneratorSseEvent(
                kind="progress",
                data={"phase": "llm_enrich_skipped", "reason": "no active LLM"},
            )
            return

        yield GeneratorSseEvent(kind="progress", data={"phase": "llm_enrich"})

        prompt_content, prompt_row = await resolve_and_pin(
            self._session, workspace_id=workspace_id, prompt_name="enrich-openapi-edges"
        )
        agent_repo = AgentSessionRepo(self._session)
        agent_session = await agent_repo.create(
            AgentSessionCreate(
                workspace_id=workspace_id,
                kind=AgentSessionKind.GENERATION,
                model_id=llm_model,
                provider=llm_provider,
                user_id=self._as_user_uuid(user_id),
                prompt_version_id=prompt_row.id,
                temperature=0.2,
                metadata_json={"source": "openapi-enrich"},
            )
        )

        provider = get_provider(llm_provider, api_key=llm_api_key, base_url=llm_base_url)
        enricher = OpenApiEnricher(provider, model=llm_model, prompt_override=prompt_content)
        result = await enricher.enrich(generator.op_summaries())

        if result.error:
            await agent_repo.complete(agent_session.id, status="error")
            yield GeneratorSseEvent(
                kind="progress",
                data={"phase": "llm_enrich_failed", "reason": result.error},
            )
            return

        for draft in result.drafts:
            public_id = await self._persist_case(
                draft,
                suite_id=request.target_suite_id,
                workspace_id=workspace_id,
                generated_by="openapi-enricher",
            )
            public_ids.append(public_id)
            yield GeneratorSseEvent(
                kind="case",
                data={
                    "public_id": public_id,
                    "name": draft.name,
                    "case_kind": draft.generated_from.get("case_kind"),
                    "tags": draft.tags,
                    "llm_edge": True,
                },
            )

        usage = result.usage
        await agent_repo.complete(
            agent_session.id,
            cost_usd=Decimal(str(usage.cost_usd)) if usage else None,
            tokens_in=usage.tokens_in if usage else 0,
            tokens_out=usage.tokens_out if usage else 0,
        )

    # ------------------------------------------------------------------

    async def run_crawler(
        self, workspace_id: str, user_id: str, request: CrawlerGenerateRequest
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Stream the heuristic-crawler generation lifecycle as SSE events.

        Validates the suite is in-scope FIRST (raising
        :class:`SuiteNotInWorkspaceError` for the router to map to 404 *before*
        any stream byte is sent), then drives :class:`UrlCrawler` over
        ``playwright-mcp``: a smoke (+ optional form) DRAFT case per visited page.
        Requires an injected :class:`McpInvoker`; absence is a wiring bug, not a
        user error, so it raises rather than emitting an SSE ``error`` frame.
        """
        if not await self.suite_in_scope(request.target_suite_id, workspace_id):
            raise SuiteNotInWorkspaceError(request.target_suite_id)
        if self._mcp_invoker is None:  # pragma: no cover - wiring guard
            raise RuntimeError("GeneratorService.run_crawler requires an McpInvoker")

        with tracer.start_as_current_span("generator.crawler") as span:
            span.set_attribute("generator.source", "crawler")
            span.set_attribute("workspace.id", workspace_id)
            start = time.perf_counter()

            run = GeneratorRun(
                workspace_id=workspace_id,
                source="crawler",
                input_meta_json={
                    "target_suite_id": request.target_suite_id,
                    "start_url": request.start_url,
                    "auth_kind": request.auth.kind,
                    "options": request.options.model_dump(),
                },
                output_case_ids_json=[],
                created_by_user_id=self._as_user_uuid(user_id),
            )
            self._session.add(run)
            await self._session.flush()
            run_id = run.id

            yield GeneratorSseEvent(
                kind="progress",
                data={"phase": "crawling", "generator_run_id": run_id},
            )

            crawler = UrlCrawler(self._mcp_invoker, request.options, request.auth)
            public_ids: list[str] = []
            async for draft in crawler.crawl(request.start_url, workspace_id):
                public_id = await self._persist_case(
                    draft,
                    suite_id=request.target_suite_id,
                    workspace_id=workspace_id,
                    generated_by="url-crawler",
                )
                public_ids.append(public_id)
                yield GeneratorSseEvent(
                    kind="case",
                    data={
                        "public_id": public_id,
                        "name": draft.name,
                        "case_kind": draft.generated_from.get("case_kind"),
                        "tags": draft.tags,
                    },
                )

            duration_ms = int((time.perf_counter() - start) * 1000)
            span.set_attribute("generator.cases_created", len(public_ids))
            await self._finalize(
                run,
                workspace_id,
                user_id,
                public_ids=public_ids,
                duration_ms=duration_ms,
                action="generator.crawler.completed",
            )
            await self._session.commit()

            yield GeneratorSseEvent(
                kind="complete",
                data={
                    "generator_run_id": run_id,
                    "target_suite_id": request.target_suite_id,
                    "cases_created": len(public_ids),
                    "public_ids": public_ids,
                    "duration_ms": duration_ms,
                },
            )

    # ------------------------------------------------------------------

    async def run_prd(
        self,
        workspace_id: str,
        user_id: str,
        request: PrdGenerateRequest,
        *,
        provider_name: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Stream LLM-driven PRD generation as SSE (M3-6) — CLOUD/LOCAL only.

        Validates the suite is in-scope FIRST (404 before any stream byte), then
        drives the GENERATION graph through :class:`PrdGenerator`. Persists an
        :class:`AgentSession` (reproducibility + cost rollup, M3-5/M3-14) and a
        ``GeneratorRun`` (provenance), one DRAFT case per draft, and streams
        ``progress`` → ``case`` → ``complete`` (or a single ``error``).

        The caller resolves ``provider_name`` / ``model`` / key / base_url from the
        workspace's active ``LLMConfig``; absence of an active config is the real
        tier gate and is rejected by the router (409) before this runs.
        """
        if not await self.suite_in_scope(request.target_suite_id, workspace_id):
            raise SuiteNotInWorkspaceError(request.target_suite_id)

        with tracer.start_as_current_span("generator.prd") as span:
            span.set_attribute("generator.source", "prd")
            span.set_attribute("workspace.id", workspace_id)
            span.set_attribute("llm.provider", provider_name)
            span.set_attribute("llm.model", model)
            start = time.perf_counter()

            # Reproducibility: pin the exact prompt content hash (M3-5). ``ensure``
            # is idempotent — the first PRD run per (name, version) inserts the row.
            prompt_content, prompt_row = await resolve_and_pin(
                self._session, workspace_id=workspace_id, prompt_name="generate-from-prd"
            )

            agent_repo = AgentSessionRepo(self._session)
            agent_session = await agent_repo.create(
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    kind=AgentSessionKind.GENERATION,
                    model_id=model,
                    provider=provider_name,
                    user_id=self._as_user_uuid(user_id),
                    prompt_version_id=prompt_row.id,
                    seed=request.seed,
                    temperature=0.2,
                    metadata_json={
                        "source": "prd",
                        "target_suite_id": request.target_suite_id,
                        "default_target_kind": request.default_target_kind.value,
                    },
                )
            )

            run = GeneratorRun(
                workspace_id=workspace_id,
                source="prd",
                input_meta_json={
                    "target_suite_id": request.target_suite_id,
                    "prd_chars": len(request.prd_text),
                    "default_target_kind": request.default_target_kind.value,
                    "seed": request.seed,
                    "agent_session_id": agent_session.id,
                },
                output_case_ids_json=[],
                created_by_user_id=self._as_user_uuid(user_id),
            )
            self._session.add(run)
            await self._session.flush()
            run_id = run.id

            yield GeneratorSseEvent(
                kind="progress",
                data={
                    "phase": "drafting",
                    "generator_run_id": run_id,
                    "agent_session_id": agent_session.id,
                },
            )

            provider = get_provider(provider_name, api_key=api_key, base_url=base_url)
            generator = PrdGenerator(
                provider,
                model=model,
                default_target_kind=request.default_target_kind,
                prompt_override=prompt_content,
            )
            result = await generator.run(
                request.prd_text, seed=request.seed, max_cases=request.max_cases
            )

            if result.error:
                span.set_attribute("generator.error", result.error)
                await agent_repo.complete(agent_session.id, status="error")
                await self._finalize(
                    run,
                    workspace_id,
                    user_id,
                    public_ids=[],
                    duration_ms=0,
                    action="generator.prd.completed",
                )
                await self._session.commit()
                yield GeneratorSseEvent(
                    kind="error",
                    data={"code": "GENERATION_FAILED", "message": result.error},
                )
                return

            public_ids: list[str] = []
            for draft in result.drafts:
                public_id = await self._persist_case(
                    draft,
                    suite_id=request.target_suite_id,
                    workspace_id=workspace_id,
                    generated_by="prd-generator",
                )
                public_ids.append(public_id)
                yield GeneratorSseEvent(
                    kind="case",
                    data={
                        "public_id": public_id,
                        "name": draft.name,
                        "case_kind": draft.generated_from.get("case_kind"),
                        "tags": draft.tags,
                    },
                )

            usage = result.usage
            duration_ms = int((time.perf_counter() - start) * 1000)
            span.set_attribute("generator.cases_created", len(public_ids))
            await agent_repo.complete(
                agent_session.id,
                cost_usd=Decimal(str(usage.cost_usd)) if usage else None,
                tokens_in=usage.tokens_in if usage else 0,
                tokens_out=usage.tokens_out if usage else 0,
            )
            await self._finalize(
                run,
                workspace_id,
                user_id,
                public_ids=public_ids,
                duration_ms=duration_ms,
                action="generator.prd.completed",
            )
            await self._session.commit()

            yield GeneratorSseEvent(
                kind="complete",
                data={
                    "generator_run_id": run_id,
                    "agent_session_id": agent_session.id,
                    "target_suite_id": request.target_suite_id,
                    "cases_created": len(public_ids),
                    "public_ids": public_ids,
                    "duration_ms": duration_ms,
                    "tokens_in": usage.tokens_in if usage else 0,
                    "tokens_out": usage.tokens_out if usage else 0,
                    "cost_usd": float(usage.cost_usd) if usage else 0.0,
                },
            )

    # ------------------------------------------------------------------

    async def run_url_semantic(
        self,
        workspace_id: str,
        user_id: str,
        request: UrlSemanticGenerateRequest,
        *,
        provider_name: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Stream LLM semantic URL generation as SSE (M3-7) — CLOUD/LOCAL only.

        Decomposes ``request.intent`` into FE_WEB journey cases on ``request.url``
        (playwright-mcp, agentic). Persists an ``AgentSession`` (repro+cost) and a
        ``GeneratorRun`` (source=url_semantic); one DRAFT case per journey.
        """
        if not await self.suite_in_scope(request.target_suite_id, workspace_id):
            raise SuiteNotInWorkspaceError(request.target_suite_id)

        with tracer.start_as_current_span("generator.url_semantic") as span:
            span.set_attribute("generator.source", "url_semantic")
            span.set_attribute("workspace.id", workspace_id)
            start = time.perf_counter()

            prompt_content, prompt_row = await resolve_and_pin(
                self._session, workspace_id=workspace_id, prompt_name="generate-url-semantic"
            )
            agent_repo = AgentSessionRepo(self._session)
            agent_session = await agent_repo.create(
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    kind=AgentSessionKind.GENERATION,
                    model_id=model,
                    provider=provider_name,
                    user_id=self._as_user_uuid(user_id),
                    prompt_version_id=prompt_row.id,
                    seed=request.seed,
                    temperature=0.2,
                    metadata_json={
                        "source": "url-semantic",
                        "url": request.url,
                        "intent": request.intent,
                        "target_suite_id": request.target_suite_id,
                    },
                )
            )

            run = GeneratorRun(
                workspace_id=workspace_id,
                source="url_semantic",
                input_meta_json={
                    "target_suite_id": request.target_suite_id,
                    "url": request.url,
                    "intent": request.intent,
                    "seed": request.seed,
                    "agent_session_id": agent_session.id,
                },
                output_case_ids_json=[],
                created_by_user_id=self._as_user_uuid(user_id),
            )
            self._session.add(run)
            await self._session.flush()
            run_id = run.id

            yield GeneratorSseEvent(
                kind="progress",
                data={
                    "phase": "interpreting",
                    "generator_run_id": run_id,
                    "agent_session_id": agent_session.id,
                },
            )

            provider = get_provider(provider_name, api_key=api_key, base_url=base_url)
            generator = UrlSemanticGenerator(provider, model=model, prompt_override=prompt_content)
            result = await generator.run(
                request.url, request.intent, seed=request.seed, max_cases=request.max_cases
            )

            if result.error:
                span.set_attribute("generator.error", result.error)
                await agent_repo.complete(agent_session.id, status="error")
                await self._finalize(
                    run,
                    workspace_id,
                    user_id,
                    public_ids=[],
                    duration_ms=0,
                    action="generator.url_semantic.completed",
                )
                await self._session.commit()
                yield GeneratorSseEvent(
                    kind="error",
                    data={"code": result.error, "message": "could not interpret intent"},
                )
                return

            public_ids: list[str] = []
            for draft in result.drafts:
                public_id = await self._persist_case(
                    draft,
                    suite_id=request.target_suite_id,
                    workspace_id=workspace_id,
                    generated_by="url-semantic-generator",
                )
                public_ids.append(public_id)
                yield GeneratorSseEvent(
                    kind="case",
                    data={
                        "public_id": public_id,
                        "name": draft.name,
                        "case_kind": draft.generated_from.get("case_kind"),
                        "tags": draft.tags,
                    },
                )

            usage = result.usage
            duration_ms = int((time.perf_counter() - start) * 1000)
            span.set_attribute("generator.cases_created", len(public_ids))
            await agent_repo.complete(
                agent_session.id,
                cost_usd=Decimal(str(usage.cost_usd)) if usage else None,
                tokens_in=usage.tokens_in if usage else 0,
                tokens_out=usage.tokens_out if usage else 0,
            )
            await self._finalize(
                run,
                workspace_id,
                user_id,
                public_ids=public_ids,
                duration_ms=duration_ms,
                action="generator.url_semantic.completed",
            )
            await self._session.commit()

            yield GeneratorSseEvent(
                kind="complete",
                data={
                    "generator_run_id": run_id,
                    "agent_session_id": agent_session.id,
                    "target_suite_id": request.target_suite_id,
                    "cases_created": len(public_ids),
                    "public_ids": public_ids,
                    "duration_ms": duration_ms,
                },
            )

    # ------------------------------------------------------------------

    async def run_mcp_discovery(
        self,
        workspace_id: str,
        user_id: str,
        request: McpDiscoveryGenerateRequest,
        *,
        provider_name: str,
        model: str,
        api_key: str | None,
        base_url: str | None,
        mcp_provider_name: str,
        mcp_target_kind: TargetKind,
        mcp_tools: list[dict[str, object]],
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Stream LLM MCP tool-discovery generation as SSE (M3-9) — CLOUD/LOCAL.

        The router resolves the LLM (``provider_name``/``model``/key) AND the
        target MCP provider (its name, ``target_kind``, and persisted tool
        catalog). An empty catalog yields an ``error`` frame (re-run discover
        first); otherwise one DRAFT case per proposed contract is persisted.
        """
        if not await self.suite_in_scope(request.target_suite_id, workspace_id):
            raise SuiteNotInWorkspaceError(request.target_suite_id)

        with tracer.start_as_current_span("generator.mcp_discovery") as span:
            span.set_attribute("generator.source", "mcp_discovery")
            span.set_attribute("workspace.id", workspace_id)
            span.set_attribute("mcp.provider", mcp_provider_name)
            start = time.perf_counter()

            prompt_content, prompt_row = await resolve_and_pin(
                self._session, workspace_id=workspace_id, prompt_name="discover-mcp-cases"
            )
            agent_repo = AgentSessionRepo(self._session)
            agent_session = await agent_repo.create(
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    kind=AgentSessionKind.GENERATION,
                    model_id=model,
                    provider=provider_name,
                    user_id=self._as_user_uuid(user_id),
                    prompt_version_id=prompt_row.id,
                    seed=request.seed,
                    temperature=0.2,
                    metadata_json={
                        "source": "mcp-discovery",
                        "mcp_provider": mcp_provider_name,
                        "target_suite_id": request.target_suite_id,
                    },
                )
            )

            run = GeneratorRun(
                workspace_id=workspace_id,
                source="mcp_discovery",
                input_meta_json={
                    "target_suite_id": request.target_suite_id,
                    "mcp_provider_id": request.mcp_provider_id,
                    "mcp_provider": mcp_provider_name,
                    "tool_count": len(mcp_tools),
                    "agent_session_id": agent_session.id,
                },
                output_case_ids_json=[],
                created_by_user_id=self._as_user_uuid(user_id),
            )
            self._session.add(run)
            await self._session.flush()
            run_id = run.id

            yield GeneratorSseEvent(
                kind="progress",
                data={
                    "phase": "exploring",
                    "generator_run_id": run_id,
                    "agent_session_id": agent_session.id,
                    "tool_count": len(mcp_tools),
                },
            )

            provider = get_provider(provider_name, api_key=api_key, base_url=base_url)
            generator = McpDiscoveryGenerator(provider, model=model, prompt_override=prompt_content)
            result = await generator.run(
                mcp_tools,
                target_kind=mcp_target_kind,
                mcp_provider_name=mcp_provider_name,
                seed=request.seed,
                max_cases=request.max_cases,
            )

            if result.error:
                span.set_attribute("generator.error", result.error)
                await agent_repo.complete(agent_session.id, status="error")
                await self._finalize(
                    run,
                    workspace_id,
                    user_id,
                    public_ids=[],
                    duration_ms=0,
                    action="generator.mcp_discovery.completed",
                )
                await self._session.commit()
                yield GeneratorSseEvent(
                    kind="error",
                    data={"code": result.error, "message": "no testable tools in catalog"},
                )
                return

            public_ids: list[str] = []
            for draft in result.drafts:
                public_id = await self._persist_case(
                    draft,
                    suite_id=request.target_suite_id,
                    workspace_id=workspace_id,
                    generated_by="mcp-discovery-generator",
                )
                public_ids.append(public_id)
                yield GeneratorSseEvent(
                    kind="case",
                    data={
                        "public_id": public_id,
                        "name": draft.name,
                        "case_kind": draft.generated_from.get("case_kind"),
                        "tags": draft.tags,
                    },
                )

            usage = result.usage
            duration_ms = int((time.perf_counter() - start) * 1000)
            span.set_attribute("generator.cases_created", len(public_ids))
            await agent_repo.complete(
                agent_session.id,
                cost_usd=Decimal(str(usage.cost_usd)) if usage else None,
                tokens_in=usage.tokens_in if usage else 0,
                tokens_out=usage.tokens_out if usage else 0,
            )
            await self._finalize(
                run,
                workspace_id,
                user_id,
                public_ids=public_ids,
                duration_ms=duration_ms,
                action="generator.mcp_discovery.completed",
            )
            await self._session.commit()

            yield GeneratorSseEvent(
                kind="complete",
                data={
                    "generator_run_id": run_id,
                    "agent_session_id": agent_session.id,
                    "target_suite_id": request.target_suite_id,
                    "cases_created": len(public_ids),
                    "public_ids": public_ids,
                    "duration_ms": duration_ms,
                },
            )

    # ------------------------------------------------------------------

    async def persist_recorder_case(
        self, draft: TestCaseDraft, *, suite_id: str, workspace_id: str
    ) -> str:
        """Persist a recorder-produced draft and return its internal case id.

        Used by the recorder finalize endpoint: it needs the internal id (not the
        public id) to stamp ``recorder_sessions.finalized_case_id`` (an FK to
        ``test_cases.id``). Mirrors :meth:`_persist_case` but returns ``case.id``.
        """
        case = TestCase(
            suite_id=suite_id,
            name=draft.name,
            description=draft.description,
            status=CaseStatus.DRAFT,
            priority=draft.priority,
            source=draft.source,
            generated_by="recorder",
            generated_from=draft.generated_from,
        )
        set_workspace_id(case, workspace_id)
        self._session.add(case)
        await self._session.flush()

        for step in draft.steps:
            self._session.add(
                TestStep(
                    case_id=case.id,
                    order=step.order,
                    action=step.action,
                    expected=step.expected,
                    code=step.code,
                    data=step.data,
                    mcp_provider=step.mcp_provider,
                    target_kind=step.target_kind,
                )
            )

        seen: set[str] = set()
        for tag in draft.tags:
            if tag in seen:
                continue
            seen.add(tag)
            self._session.add(CaseTag(case_id=case.id, tag=tag))

        await self._session.flush()
        return case.id

    async def _persist_case(
        self,
        draft: TestCaseDraft,
        *,
        suite_id: str,
        workspace_id: str,
        generated_by: str = "openapi-generator",
    ) -> str:
        """Persist one draft as a DRAFT :class:`TestCase` + steps + tags.

        Mirrors :class:`TestCaseService.create`'s write path (public_id via the
        ``before_insert`` listener, steps in declared order, tag rows) so a
        generated case is indistinguishable from a manually authored one apart
        from ``source=MCP`` + the ``generated_from`` provenance.
        """
        case = TestCase(
            suite_id=suite_id,
            name=draft.name,
            description=draft.description,
            status=CaseStatus.DRAFT,
            priority=draft.priority,
            source=draft.source,
            generated_by=generated_by,
            generated_from=draft.generated_from,
        )
        set_workspace_id(case, workspace_id)
        self._session.add(case)
        await self._session.flush()

        for step in draft.steps:
            self._session.add(
                TestStep(
                    case_id=case.id,
                    order=step.order,
                    action=step.action,
                    expected=step.expected,
                    code=step.code,
                    data=step.data,
                    mcp_provider=step.mcp_provider,
                    target_kind=step.target_kind,
                )
            )

        seen: set[str] = set()
        for tag in draft.tags:
            if tag in seen:
                continue
            seen.add(tag)
            self._session.add(CaseTag(case_id=case.id, tag=tag))

        await self._session.flush()
        return case.public_id

    async def _finalize(
        self,
        run: GeneratorRun,
        workspace_id: str,
        user_id: str,
        *,
        public_ids: list[str],
        duration_ms: int,
        action: str = "generator.openapi.completed",
    ) -> None:
        run.output_case_ids_json = public_ids
        run.duration_ms = duration_ms
        await self._session.flush()
        await write_audit(
            self._session,
            workspace_id=workspace_id,
            user_id=user_id,
            action=action,
            resource_type="generator_run",
            resource_id=run.id,
            metadata={
                "casesCreated": len(public_ids),
                "publicIds": public_ids,
                "durationMs": duration_ms,
            },
        )
