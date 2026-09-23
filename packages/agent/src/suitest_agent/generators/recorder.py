"""Live browser-recorder session manager (M2 Task 4).

Pure deterministic event→step mapping, NO LLM — runs in every tier. The manager
owns the lifecycle of a :class:`~suitest_db.models.recorder_session.RecorderSession`:

* :meth:`start` — create the row (``status=active``, ``ws_room=recorder:<id>``,
  TTL = ``now + ttl_minutes``) and *best-effort* ask ``playwright-mcp`` to begin
  recording. The bundled provider advertises ``browser.start_recording`` /
  ``browser.stop_recording`` (see :mod:`suitest_mcp.bundled.playwright`
  ``DECLARED_TOOLS``) but the runner has never driven them, so we treat the call
  as advisory: a failure (tool absent / not implemented) is swallowed and the
  session still records via client-pushed events through :meth:`append_event`.
* :meth:`append_event` — persist one :class:`RecorderEvent` to
  ``captured_events_json`` and publish it on the Redis ``recorder:<id>`` channel
  so the WS gateway fans it out to live subscribers.
* :meth:`finalize` — best-effort ``browser.stop_recording`` (its returned trace,
  if any, is merged), then convert the captured events into one DRAFT
  :class:`TestCaseDraft` (``source=RECORDER``) and mark the session finalized.
* :meth:`expire_idle_sessions` — sweep ``active`` sessions past their TTL, stop
  recording, and mark them ``expired`` (driven on an interval by the API).

Conversion rules (:meth:`_convert_events_to_case`):

* One step per ``navigate`` / ``click`` / ``type`` / ``assert`` event.
* A ``type`` event flagged ``masked=True`` (password fields) renders its value
  as the ``{{password}}`` placeholder — the raw secret never reaches the case.
* A ``network`` event whose ``status`` is 4xx/5xx becomes an auto-assertion step
  (``assert response.status == <observed>``).
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from suitest_shared.domain.enums import CaseSource, Priority, TargetKind
from suitest_shared.schemas.generator_input import (
    RecorderEvent,
    RecorderEventKind,
    RecorderFinalizeRequest,
    RecorderSessionStartRequest,
    TestCaseDraft,
    TestStepDraft,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from redis.asyncio import Redis as AsyncRedis
    from suitest_db.models.recorder_session import RecorderSession
    from suitest_db.repositories.recorder_sessions import RecorderSessionRepo
    from suitest_mcp.invoker import McpInvoker

#: Provider every recorder step routes through (playwright-mcp, FE_WEB).
_PROVIDER = "playwright-mcp"

#: Placeholder substituted for masked (secret) ``type`` values.
_PASSWORD_PLACEHOLDER = "{{password}}"


class RecorderSessionNotFound(Exception):
    """No live session matched the id (or it belongs to another workspace).

    The router maps this to ``404`` (NEVER 403) so a caller cannot probe the
    existence of sessions in other workspaces.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(f"recorder session {session_id} not found")
        self.session_id = session_id


class RecorderSessionExpired(Exception):
    """The session is no longer ``active`` (expired, finalized, or cancelled).

    The router maps this to ``410 Gone`` — the resource existed but its window
    has closed, so the operation is permanently unavailable.
    """

    def __init__(self, session_id: str, status: str) -> None:
        super().__init__(f"recorder session {session_id} is {status}, not active")
        self.session_id = session_id
        self.status = status


class RecorderSessionManager:
    """Orchestrates one workspace's recorder sessions. One instance per request."""

    def __init__(
        self,
        mcp_invoker: McpInvoker,
        recorder_repo: RecorderSessionRepo,
        redis: AsyncRedis | object | None = None,
        ttl_minutes: int = 30,
        api_base_url: str = "",
    ) -> None:
        self._mcp = mcp_invoker
        self._repo = recorder_repo
        self._redis = redis
        self._ttl = timedelta(minutes=ttl_minutes)
        self._api_base_url = api_base_url

    # ------------------------------------------------------------------

    async def start(
        self,
        workspace_id: str,
        user_id: str | None,
        request: RecorderSessionStartRequest,
    ) -> tuple[RecorderSession, str | None]:
        """Create a session row and best-effort begin recording.

        Returns the persisted session plus an optional ``browser_url`` (a
        DevTools preview link the provider may surface). The ``ws_room`` is
        derived from the freshly assigned id, so we create the row first (with a
        placeholder) and stamp the canonical ``recorder:<id>`` room before flush.
        """
        from suitest_db.repositories.recorder_sessions import RecorderSessionCreate

        from suitest_agent.generators.browser_launcher import (
            is_display_available,
            launch_headed_browser,
        )

        expires_at = datetime.now(tz=UTC) + self._ttl
        row = await self._repo.create(
            RecorderSessionCreate(
                workspace_id=workspace_id,
                user_id=user_id,
                project_id=request.project_id,
                start_url=request.start_url,
                mcp_provider=request.mcp_provider,
                ws_room="recorder:pending",
                expires_at=expires_at,
            )
        )
        row.ws_room = f"recorder:{row.id}"

        # If native headed mode is requested or in desktop environments, launch a real browser window
        should_headed = (
            request.mcp_provider in ("playwright-headed", "headed", "playwright-mcp", "")
            and request.mcp_provider != "playwright-proxy"
            and is_display_available()
        )
        if should_headed:
            api_url = self._api_base_url or "http://localhost:8000/api/v1"
            spawned = await launch_headed_browser(
                session_id=row.id,
                start_url=request.start_url,
                api_url=api_url,
                workspace_id=workspace_id,
            )
            if spawned:
                log.info("Launched native headed browser session for %s", row.id)

        browser_url = await self._begin_recording(workspace_id, user_id, row.id, request)
        return row, browser_url

    async def _begin_recording(
        self,
        workspace_id: str,
        user_id: str | None,
        session_id: str,
        request: RecorderSessionStartRequest,
    ) -> str | None:
        """Advisory ``browser.start_recording`` — tolerate an unimplemented tool.

        The bundled provider lists the tool but does not implement it today, so
        any failure is logged-and-ignored: recording proceeds via client-pushed
        events. Returns the provider-reported ``browser_url`` when present.
        """
        from suitest_mcp.invoker import InvokeContext

        ctx = InvokeContext(
            workspace_id=workspace_id,
            target_kind=TargetKind.FE_WEB,
            actor_user_id=user_id,
        )
        try:
            result = await self._mcp.invoke(
                explicit_provider=request.mcp_provider,
                tool="browser.start_recording",
                arguments={"session_id": session_id, "start_url": request.start_url},
                ctx=ctx,
            )
        except Exception as exc:
            log.warning("Advisory browser.start_recording failed (tolerated): %s", exc)
            return None
        browser_url = result.output.get("browser_url")
        return browser_url if isinstance(browser_url, str) else None

    # ------------------------------------------------------------------

    async def append_event(self, session_id: str, workspace_id: str, event: RecorderEvent) -> None:
        """Persist one captured event + publish it to the WS room.

        Raises :class:`RecorderSessionNotFound` for an unknown / cross-workspace
        id and :class:`RecorderSessionExpired` if the session is not ``active``.
        """
        session = await self._repo.get_by_id(session_id, workspace_id=workspace_id)
        if session is None:
            raise RecorderSessionNotFound(session_id)
        if session.status != "active":
            raise RecorderSessionExpired(session_id, session.status)

        payload = event.model_dump(mode="json")
        await self._repo.append_event(session_id, payload, workspace_id=workspace_id)
        await self._publish(session.ws_room, payload)

    async def _publish(self, ws_room: str, event: dict[str, Any]) -> None:
        """Publish one event on the ``recorder:<id>`` channel for WS fan-out.

        Uses the ``{"event": ..., "data": ...}`` envelope the WS manager's
        ``_build_envelope`` expects, so the client receives a
        ``{"type": "event", "event": "generator.recorder.step", ...}`` frame.
        """
        if self._redis is None or not hasattr(self._redis, "publish"):
            return
        message = json.dumps({"event": "generator.recorder.step", "data": event}, default=str)
        with contextlib.suppress(Exception):
            await self._redis.publish(ws_room, message)

    # ------------------------------------------------------------------

    async def finalize(
        self,
        session_id: str,
        workspace_id: str,
        user_id: str | None,
        request: RecorderFinalizeRequest,
    ) -> tuple[RecorderSession, TestCaseDraft]:
        """Stop recording + convert the captured log into a DRAFT case.

        Raises :class:`RecorderSessionNotFound` / :class:`RecorderSessionExpired`
        as :meth:`append_event` does. The session is NOT marked finalized here —
        the caller persists the produced :class:`TestCaseDraft`, then calls
        :meth:`mark_finalized` with the new case id so the FK is satisfiable.
        """
        session = await self._repo.get_by_id(session_id, workspace_id=workspace_id)
        if session is None:
            raise RecorderSessionNotFound(session_id)
        if session.status != "active":
            raise RecorderSessionExpired(session_id, session.status)

        from suitest_agent.generators.browser_launcher import close_headed_browser

        await close_headed_browser(session_id)
        if request.events is not None:
            events = request.events
        else:
            trace_events = await self._stop_recording(
                workspace_id, user_id, session_id, session.mcp_provider
            )
            events = [*session.captured_events_json, *trace_events]
        draft = self._convert_events_to_case(events, session.start_url, session_id, request)
        return session, draft

    async def mark_finalized(self, session_id: str, workspace_id: str, case_id: str) -> None:
        """Transition the session to ``finalized`` + stamp the produced case id."""
        await self._repo.mark_finalized(
            session_id,
            finalized_case_id=case_id,
            finalized_at=datetime.now(tz=UTC),
            workspace_id=workspace_id,
        )

    async def cancel(self, session_id: str, workspace_id: str) -> RecorderSession:
        """Mark an active session ``cancelled`` (best-effort stop recording)."""
        session = await self._repo.get_by_id(session_id, workspace_id=workspace_id)
        if session is None:
            raise RecorderSessionNotFound(session_id)
        if session.status != "active":
            raise RecorderSessionExpired(session_id, session.status)
        from suitest_agent.generators.browser_launcher import close_headed_browser

        await close_headed_browser(session_id)
        await self._stop_recording(workspace_id, None, session_id, session.mcp_provider)
        updated = await self._repo.update_status(session_id, "cancelled", workspace_id=workspace_id)
        return updated if updated is not None else session

    async def _stop_recording(
        self,
        workspace_id: str,
        user_id: str | None,
        session_id: str,
        provider: str,
    ) -> list[dict[str, Any]]:
        """Advisory ``browser.stop_recording`` — return any trace events it yields.

        Tolerates an unimplemented tool (returns ``[]``). When the provider does
        return a trace, its ``events`` list (already in :class:`RecorderEvent`
        shape) is merged with the client-pushed log at finalize time.
        """
        from suitest_mcp.invoker import InvokeContext

        ctx = InvokeContext(
            workspace_id=workspace_id,
            target_kind=TargetKind.FE_WEB,
            actor_user_id=user_id,
        )
        try:
            result = await self._mcp.invoke(
                explicit_provider=provider,
                tool="browser.stop_recording",
                arguments={"session_id": session_id},
                ctx=ctx,
            )
        except Exception as exc:
            log.warning("Advisory browser.stop_recording failed (tolerated): %s", exc)
            return []
        events = result.output.get("events")
        if not isinstance(events, list):
            return []
        return [e for e in events if isinstance(e, dict)]

    # ------------------------------------------------------------------

    async def expire_idle_sessions(self) -> int:
        """Stop + expire every ``active`` session past its TTL. Returns the count."""
        now = datetime.now(tz=UTC)
        stale = await self._repo.list_active_expired(now)
        from suitest_agent.generators.browser_launcher import close_headed_browser

        for session in stale:
            await close_headed_browser(session.id)
            await self._stop_recording(session.workspace_id, None, session.id, session.mcp_provider)
            await self._repo.update_status(session.id, "expired", workspace_id=session.workspace_id)
        return len(stale)

    # ------------------------------------------------------------------

    def _convert_events_to_case(
        self,
        events: Iterable[dict[str, Any]],
        start_url: str,
        session_id: str,
        request: RecorderFinalizeRequest,
    ) -> TestCaseDraft:
        """Map captured events to a DRAFT :class:`TestCaseDraft` (one step / event)."""
        coalesced_events: list[dict[str, Any]] = []
        for raw in events:
            if not isinstance(raw, dict):
                continue
            if not coalesced_events:
                coalesced_events.append(raw)
                continue
            prev = coalesced_events[-1]
            # Coalesce consecutive type events on the same selector (intermediate debounce typing)
            if (
                prev.get("kind") == "type"
                and raw.get("kind") == "type"
                and prev.get("selector") == raw.get("selector")
            ):
                coalesced_events[-1] = raw
                continue
            # Coalesce click on input immediately preceding typing into the same selector
            if (
                prev.get("kind") == "click"
                and raw.get("kind") == "type"
                and prev.get("selector") == raw.get("selector")
            ):
                coalesced_events[-1] = raw
                continue
            coalesced_events.append(raw)

        steps: list[TestStepDraft] = []
        order = 1
        for raw in coalesced_events:
            step = self._event_to_step(raw, order)
            if step is not None:
                steps.append(step)
                order += 1

        # Guarantee that a recorded test case starts with navigation to the target site
        if start_url and not (steps and steps[0].action.startswith("Navigate to")):
            nav_step = TestStepDraft(
                order=1,
                action=f"Navigate to {start_url}",
                expected="Page loads",
                code=json.dumps({"tool": "browser_navigate", "arguments": {"url": start_url}}),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"url": start_url},
            )
            steps.insert(0, nav_step)
            for idx, s in enumerate(steps, start=1):
                s.order = idx

        return TestCaseDraft(
            name=request.name,
            description=request.description
            or f"Recorded session from {start_url} ({len(steps)} steps).",
            priority=Priority(request.priority),
            source=CaseSource.RECORDER,
            target_kind=TargetKind.FE_WEB,
            tags=["recorder"],
            generated_from={
                "source": "RECORDER",
                "session_id": session_id,
                "start_url": start_url,
            },
            steps=steps,
        )

    def _event_to_step(self, raw: dict[str, Any], order: int) -> TestStepDraft | None:
        """Render one captured event as a step, or ``None`` to drop it.

        Validates via :class:`RecorderEvent` so a malformed entry (e.g. partial
        provider trace) is skipped rather than crashing finalize.
        """
        try:
            event = RecorderEvent.model_validate(raw)
        except ValueError:
            return None

        if event.kind is RecorderEventKind.NAVIGATE:
            url = event.url or ""
            if url.startswith("about:") or url.startswith("chrome:"):
                return None
            return TestStepDraft(
                order=order,
                action=f"Navigate to {url}",
                expected="Page loads",
                code=json.dumps({"tool": "browser_navigate", "arguments": {"url": url}}),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"url": url},
            )
        if event.kind is RecorderEventKind.CLICK:
            selector = event.selector or ""
            return TestStepDraft(
                order=order,
                action=f"Click {selector}",
                expected="Element responds to click",
                code=json.dumps(
                    {
                        "tool": "browser_click",
                        "arguments": {"target": selector, "selector": selector},
                    }
                ),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"selector": selector},
            )
        if event.kind is RecorderEventKind.TYPE:
            return self._type_step(event, order)
        if event.kind is RecorderEventKind.ASSERT:
            assertion = event.assertion or {}
            return TestStepDraft(
                order=order,
                action="Assert condition",
                expected=str(assertion.get("expected", "condition holds")),
                code=json.dumps(
                    {
                        "tool": "browser_evaluate",
                        "arguments": {"function": str(assertion.get("code", "() => true"))},
                    }
                ),
                mcp_provider=_PROVIDER,
                target_kind=TargetKind.FE_WEB,
                data={"assertion": assertion},
            )
        if event.kind is RecorderEventKind.NETWORK:
            return self._network_step(event, order)
        return None

    def _type_step(self, event: RecorderEvent, order: int) -> TestStepDraft:
        """Render a ``type`` event; masked (secret) values use the placeholder."""
        selector = event.selector or ""
        value = _PASSWORD_PLACEHOLDER if event.masked else (event.text or "")
        step_data: dict[str, Any] = {"selector": selector, "masked": event.masked}
        if event.text and not event.masked:
            step_data["raw_value"] = event.text
        return TestStepDraft(
            order=order,
            action=f"Type into {selector}",
            expected="Field accepts input",
            code=json.dumps(
                {
                    "tool": "browser_type",
                    "arguments": {
                        "target": selector,
                        "selector": selector,
                        "text": value,
                    },
                }
            ),
            mcp_provider=_PROVIDER,
            target_kind=TargetKind.FE_WEB,
            data=step_data,
        )

    def _network_step(self, event: RecorderEvent, order: int) -> TestStepDraft | None:
        """Render a 4xx/5xx ``network`` event as an auto-assertion step (else drop)."""
        network = event.network or {}
        status = network.get("status")
        if not isinstance(status, int) or status < 400:
            return None
        url = network.get("url", event.url or "")
        return TestStepDraft(
            order=order,
            action=f"Assert response status for {url}",
            expected=f"Observed HTTP {status}",
            code=json.dumps(
                {
                    "tool": "browser_evaluate",
                    "arguments": {"function": f"() => window.__last_status === {status}"},
                }
            ),
            mcp_provider=_PROVIDER,
            target_kind=TargetKind.FE_WEB,
            data={"network": network},
        )
