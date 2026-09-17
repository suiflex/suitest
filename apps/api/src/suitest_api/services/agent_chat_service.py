"""Agent conversation (chat) service (M3-12 / M3-13).

Streams the assistant reply token-by-token over SSE (``provider.stream_complete``)
and persists the turn as an ``AgentSession`` (kind CONVERSATION) + its user/agent
messages for replay. When the model emits a tool-request JSON instead of prose, a
``tool`` SSE frame is yielded AND mirrored on the WS gateway
(``agent.tool.call``) so the UI can surface a confirm (mutations always require an
explicit confirm — AUTONOMY.md §3 hard rail).

Tools (M3-12 extension): the panel model can call read-only tools
(``case.get``, ``cases.search``) immediately. Mutating tools
(``case.update_meta``, ``case.set_steps``) are NEVER executed from model output:
the request is recorded as a ``pending`` :class:`AgentToolCall` and surfaced as a
confirm card carrying an opaque ``call_id``. The panel approves by re-sending
that ``call_id`` alone; the server executes the stored arguments, so neither
model output nor natural-language text can authorize a write (AUTONOMY.md §3
``conversation_can_mutate`` hard rail). A write also requires ``QA``-or-higher
role and ``assist``-or-higher workspace autonomy, checked server-side here.

The router rejects a workspace without a validated LLM with 409 before streaming.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from pydantic import ValidationError
from suitest_agent.graphs._util import parse_json_object
from suitest_agent.providers.base import ChatMessage, ModelCall
from suitest_core.llm_credentials import ResolvedCredential
from suitest_db.repositories.agent_sessions import AgentSessionCreate, AgentSessionRepo
from suitest_db.repositories.projects import ProjectRepo
from suitest_db.repositories.suites import SuiteRepo
from suitest_db.repositories.test_cases import TestCaseRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AgentSessionKind, AutonomyLevel, MessageRole, Role
from suitest_shared.schemas.agent_chat import ChatRequest, ChatSseEvent

from suitest_api.deps.scope import TenantContext
from suitest_api.services.agent_tools import (
    TOOLS_PROMPT,
    WRITE_TOOLS,
    ToolDeniedError,
    ToolInputError,
    execute_tool,
)
from suitest_api.services.llm_credentials import provider_for_credential
from suitest_api.services.prompt_resolver import resolve_and_pin
from suitest_api.services.test_case_service import TestCaseService

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.agent import AgentToolCall

# Publishes a ``{"event", "data"}`` envelope to the workspace WS channel.
WsPublish = Callable[[dict[str, object]], Awaitable[None]]

# A chat-initiated mutation needs QA-or-higher role AND assist-or-higher autonomy
# (AUTONOMY.md: ``conversation_can_mutate`` is OFF at ``manual``).
_WRITER_ROLES = frozenset({Role.QA, Role.ADMIN, Role.OWNER})
_MUTATION_AUTONOMY = frozenset({AutonomyLevel.ASSIST, AutonomyLevel.SEMI_AUTO, AutonomyLevel.AUTO})


class AgentChatService:
    def __init__(self, session: AsyncSession, *, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx
        self._workspace_id = ctx.workspace_id
        self._user_id: str | None = ctx.user_id or None

    @staticmethod
    def _strip_tool_fences(raw: str) -> str:
        """Remove <tool_call> wrappers and json code fences from a model turn."""
        if "<tool_call>" not in raw and "```json" not in raw:
            return raw
        return (
            raw.replace("<tool_call>", "")
            .replace("</tool_call>", "")
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

    @staticmethod
    def _last_tool_envelope(raw: str) -> dict[str, object]:
        """Return the LAST ``{"tool": ...}`` object in a model turn.

        A round may carry SEVERAL envelopes (e.g. case.get then
        case.set_steps); the last one is the newest request.
        """
        tool_obj: dict[str, object] = {}
        scan = raw
        while True:
            start = scan.find("{")
            if start == -1:
                break
            candidate = parse_json_object(scan[start:])
            if "tool" not in candidate:
                break
            tool_obj = candidate
            end_idx = scan.rfind("}")
            scan = scan[end_idx + 1 :] if end_idx != -1 else ""
        return tool_obj

    async def _mutation_blocked_reason(self) -> str | None:
        """Return why a chat-initiated write is refused, or ``None`` when allowed.

        Model output and natural-language text carry NO authority here — a write
        needs the caller's real membership role (``QA`` or higher) and the
        workspace autonomy dial at ``assist`` or higher.
        """
        if self._ctx.role not in _WRITER_ROLES:
            return f"role '{self._ctx.role.value}' cannot edit test cases"
        capability = await WorkspaceCapabilityRepo(self._session).get(self._workspace_id)
        autonomy = capability.autonomy_level if capability is not None else AutonomyLevel.MANUAL
        if autonomy not in _MUTATION_AUTONOMY:
            return f"chat editing is disabled at '{autonomy.value}' autonomy"
        return None

    @staticmethod
    def _as_uuid(user_id: str | None) -> uuid.UUID | None:
        import uuid as _uuid

        try:
            return _uuid.UUID(user_id) if user_id else None
        except (ValueError, AttributeError):
            return None

    async def _approved_call_note(
        self,
        pending: AgentToolCall,
        *,
        repo: AgentSessionRepo,
        case_service: TestCaseService,
        agent_session_id: str,
    ) -> str:
        """Execute an already-approved pending call and settle its row.

        Runs the STORED ``tool_name`` / ``input`` — the request body carried only
        the opaque id. Returns the ``TOOL RESULT`` note to feed the next round.
        """
        blocked = await self._mutation_blocked_reason()
        if blocked is not None:
            await repo.settle_tool_call(pending.id, status="rejected", error_msg=blocked)
            return f"TOOL RESULT {pending.tool_name}: {json.dumps({'error': blocked})}"
        try:
            result = await execute_tool(
                pending.tool_name,
                dict(pending.input),
                session=self._session,
                ctx=self._ctx,
                case_service=case_service,
                confirmed=True,
            )
        except ToolInputError as exc:
            await repo.settle_tool_call(pending.id, status="error", error_msg=str(exc))
            return f"TOOL RESULT {pending.tool_name}: {json.dumps({'error': str(exc)})}"
        except ToolDeniedError:
            await repo.settle_tool_call(pending.id, status="error", error_msg="permission denied")
            return f"TOOL RESULT {pending.tool_name}: permission denied."
        result_json = json.dumps(result, default=str)
        await repo.settle_tool_call(pending.id, status="completed", output=result)
        await repo.add_message(
            agent_session_id,
            role=MessageRole.TOOL,
            content=f"{pending.tool_name} executed (user-approved): {result_json}",
        )
        return (
            f"TOOL RESULT (user-approved execution of {pending.tool_name}): "
            f"{result_json}\nReport the outcome to the user concisely."
        )

    async def _record_pending_write(
        self,
        tool: str,
        arguments: dict[str, object],
        round_accumulated: str,
        *,
        repo: AgentSessionRepo,
        agent_session_id: str,
    ) -> tuple[dict[str, object] | None, str]:
        """Gate + record a model-proposed write as a ``pending`` call.

        Never executes the write. Returns ``(payload, outcome)`` where outcome is
        ``"stop"`` (gate refused; payload is ``{"error": reason}``), ``"retry"``
        (bad arguments — let the model fix them) or ``"pending"`` (recorded; wait
        for approval; payload is the confirm-card tool frame).
        """
        blocked = await self._mutation_blocked_reason()
        if blocked is not None:
            return {"error": blocked}, "stop"
        try:
            WRITE_TOOLS[tool].model_validate(arguments)
        except ValidationError as exc:
            return {"error": exc.json(indent=None)}, "retry"
        turn_msg = await repo.add_message(
            agent_session_id, role=MessageRole.AGENT, content=round_accumulated
        )
        pending_call = await repo.add_tool_call(
            turn_msg.id, tool_name=tool, tool_input=arguments, status="pending"
        )
        return {
            "tool": tool,
            "arguments": arguments,
            "call_id": pending_call.id,
            "requires_approval": True,
            "agent_session_id": agent_session_id,
        }, "pending"

    async def stream(
        self,
        request: ChatRequest,
        *,
        credential: ResolvedCredential,
        model: str,
        publish: WsPublish | None = None,
    ) -> AsyncIterator[ChatSseEvent]:
        """Stream the assistant reply; persist the session + messages."""
        # M5-3: honour an active per-workspace prompt fork; falls back to the
        # file default when none exists. ``resolve_and_pin`` also records the
        # reproducibility row, replacing the direct read_prompt + ensure pair.
        prompt_content, prompt_row = await resolve_and_pin(
            self._session, workspace_id=self._workspace_id, prompt_name="converse"
        )
        repo = AgentSessionRepo(self._session)
        # Reuse an existing conversation when the panel supplies its id, so
        # approve/reject follow-ups land in the same replayable thread.
        agent_session = None
        if request.session_id:
            existing = await repo.get_by_id(request.session_id)
            if existing is not None and existing.workspace_id == self._workspace_id:
                agent_session = existing
        if agent_session is None:
            agent_session = await repo.create(
                AgentSessionCreate(
                    workspace_id=self._workspace_id,
                    kind=AgentSessionKind.CONVERSATION,
                    model_id=model,
                    provider=credential.provider,
                    user_id=self._as_uuid(self._user_id),
                    prompt_version_id=prompt_row.id,
                    seed=request.seed,
                    temperature=0.3,
                )
            )

        # Persist the latest user turn (the rest is prior context already stored).
        last_user = next((m for m in reversed(request.messages) if m.role == "user"), None)
        if last_user is not None:
            await repo.add_message(
                agent_session.id, role=MessageRole.USER, content=last_user.content
            )

        yield ChatSseEvent(kind="progress", data={"agent_session_id": agent_session.id})
        # Capture once — expire_all() inside the tool loop invalidates ORM
        # attributes, and a later ``agent_session.id`` access would lazy-load
        # outside greenlet context and crash the stream.
        agent_session_id = agent_session.id

        # The tool catalogue rides on the system prompt so the model knows the
        # request envelope and which tools are read-only vs mutating.
        messages = [ChatMessage(role="system", content=prompt_content + TOOLS_PROMPT)]
        messages.extend(ChatMessage(role=m.role, content=m.content) for m in request.messages)

        case_service = TestCaseService(
            self._ctx,
            TestCaseRepo(self._session),
            SuiteRepo(self._session),
            ProjectRepo(self._session),
        )
        # Set when the pending-write path already stored the model turn as an
        # AGENT message (the tool call hangs off it) — do not write it twice.
        agent_message_written = False

        # Approval path: the panel sends only the opaque ``call_id`` of a
        # server-recorded pending call. Look it up, re-check the mutation gate,
        # and execute the STORED arguments — model output never authorizes this.
        approved = request.approved_tool
        if approved is not None:
            pending = await repo.get_pending_tool_call(
                approved.call_id, session_id=agent_session_id
            )
            if pending is None:
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            "TOOL RESULT: the approval reference is invalid or was already "
                            "used. Do not retry automatically; ask the user to resubmit."
                        ),
                    )
                )
            else:
                tool_data: dict[str, object] = {
                    "tool": pending.tool_name,
                    "arguments": pending.input,
                    "call_id": pending.id,
                    "confirmed": True,
                    "agent_session_id": agent_session_id,
                }
                if publish is not None:
                    await publish({"event": "agent.tool.call", "data": tool_data})
                yield ChatSseEvent(kind="tool", data=tool_data)
                note = await self._approved_call_note(
                    pending,
                    repo=repo,
                    case_service=case_service,
                    agent_session_id=agent_session_id,
                )
                messages.append(ChatMessage(role="user", content=note))
            await self._session.commit()
            self._session.expire_all()

        max_tool_rounds = 4
        for _round in range(max_tool_rounds):
            call = ModelCall(model=model, messages=messages, seed=request.seed, temperature=0.3)
            provider = provider_for_credential(credential)
            round_accumulated = ""
            async for chunk in provider.stream_complete(call):
                if chunk.delta:
                    round_accumulated += chunk.delta
                    yield ChatSseEvent(kind="token", data={"delta": chunk.delta})
                if chunk.done:
                    tokens_out = chunk.tokens_out

            raw = self._strip_tool_fences(round_accumulated)
            tool_obj = self._last_tool_envelope(raw)

            tool = tool_obj.get("tool")
            if not (isinstance(tool, str) and tool.strip()):
                accumulated = round_accumulated
                break

            arguments = tool_obj.get("arguments", {})
            arguments = arguments if isinstance(arguments, dict) else {}

            if tool in WRITE_TOOLS:
                # A write is NEVER executed from model output. Gate it, record a
                # pending call, and stop the turn — the panel approves by id.
                frame_data, outcome = await self._record_pending_write(
                    tool,
                    arguments,
                    round_accumulated,
                    repo=repo,
                    agent_session_id=agent_session_id,
                )
                if outcome in ("stop", "retry"):
                    messages.append(
                        ChatMessage(
                            role="user",
                            content=f"TOOL RESULT {tool}: {json.dumps(frame_data)}",
                        )
                    )
                    if outcome == "stop":
                        accumulated = round_accumulated
                        break
                    await self._session.commit()
                    self._session.expire_all()
                    continue
                if publish is not None and frame_data is not None:
                    await publish({"event": "agent.tool.call", "data": frame_data})
                yield ChatSseEvent(kind="tool", data=frame_data or {})
                await self._session.commit()
                accumulated = round_accumulated
                agent_message_written = True
                break

            # Read-only tool — safe to run immediately and feed back to the model.
            tool_data = {
                "tool": tool,
                "arguments": arguments,
                "call_id": None,
                "requires_approval": False,
                "agent_session_id": agent_session_id,
            }
            if publish is not None:
                await publish({"event": "agent.tool.call", "data": tool_data})
            yield ChatSseEvent(kind="tool", data=tool_data)
            try:
                result = await execute_tool(
                    tool,
                    arguments,
                    session=self._session,
                    ctx=self._ctx,
                    case_service=case_service,
                    confirmed=False,
                )
                result_json = json.dumps(result, default=str)
            except ToolInputError as exc:
                result_json = json.dumps({"error": str(exc)})
            except ToolDeniedError:
                # Defensive: a write tool reached here without approval — stop.
                accumulated = round_accumulated
                break
            messages.append(ChatMessage(role="user", content=f"TOOL RESULT {tool}: {result_json}"))
            # Persist + drop stale identity-map state before the next round
            # reads rows the tool just wrote. Committing (not just expiring)
            # is required: expired ORM objects would lazy-load outside the
            # greenlet context when re-read later in this generator.
            await self._session.commit()
            self._session.expire_all()
        else:
            accumulated = round_accumulated

        if not agent_message_written:
            await repo.add_message(agent_session_id, role=MessageRole.AGENT, content=accumulated)
        await repo.complete(agent_session_id, tokens_out=tokens_out)
        await self._session.commit()

        yield ChatSseEvent(
            kind="done",
            data={
                "agent_session_id": agent_session_id,
                "content": accumulated,
                "tokens_out": tokens_out,
            },
        )
