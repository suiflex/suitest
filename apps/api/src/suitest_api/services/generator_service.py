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
from typing import TYPE_CHECKING

from opentelemetry import trace
from suitest_agent.generators.openapi_generator import OpenApiGenerator, OpenApiSpecError
from suitest_agent.generators.url_crawler import UrlCrawler
from suitest_db.audit import write_audit
from suitest_db.models.case import CaseTag, TestCase, TestStep
from suitest_db.models.generator_run import GeneratorRun
from suitest_db.public_id import set_workspace_id
from suitest_shared.domain.enums import CaseStatus
from suitest_shared.schemas.generator_input import (
    CrawlerGenerateRequest,
    GeneratorSseEvent,
    OpenApiGenerateRequest,
    TestCaseDraft,
)

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
        self, workspace_id: str, user_id: str, request: OpenApiGenerateRequest
    ) -> AsyncIterator[GeneratorSseEvent]:
        """Stream the OpenAPI generation lifecycle as SSE events.

        Validates the suite is in-scope FIRST (raising
        :class:`SuiteNotInWorkspaceError` for the router to map to 404 *before*
        any stream byte is sent). After that the generator drives the body; a
        spec error becomes an ``error`` event rather than an exception.
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
