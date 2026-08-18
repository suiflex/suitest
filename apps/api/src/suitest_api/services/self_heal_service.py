"""AI selector repair with explicit autonomy and optimistic-lock gates."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from suitest_agent.generators.selector_repair import (
    SelectorRepairError,
    apply_selector_repair,
    propose_selector_repair,
    selector_code_sha256,
)
from suitest_agent.providers.base import ProviderError
from suitest_db.audit import write_audit
from suitest_db.models.case import TestCase, TestStep
from suitest_db.repositories.agent_sessions import AgentSessionCreate, AgentSessionRepo
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AgentSessionKind, AutonomyLevel, Tier

from suitest_api.schemas.self_heal import (
    SelectorRepairApplied,
    SelectorRepairApplyRequest,
    SelectorRepairPublic,
)
from suitest_api.services.llm_credentials import provider_for_config
from suitest_api.services.prompt_resolver import resolve_and_pin

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SelfHealError(Exception):
    """Stable service error mapped by the API and runner."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SelfHealService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str | None,
    ) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._user_id = user_id

    async def _require_human_repair_policy(self) -> None:
        capability = await WorkspaceCapabilityRepo(self._session).get(self._workspace_id)
        if (
            capability is None
            or capability.tier is Tier.ZERO
            or capability.autonomy_level is AutonomyLevel.MANUAL
        ):
            raise SelfHealError(
                "SELF_HEAL_REQUIRES_ASSIST",
                "selector repair requires assist, semi_auto, or auto autonomy",
            )

    async def _step(
        self,
        case_id: str,
        step_id: str,
        *,
        for_update: bool = False,
    ) -> TestStep:
        statement = (
            select(TestStep)
            .join(TestCase, TestCase.id == TestStep.case_id)
            .where(
                TestStep.id == step_id,
                TestCase.workspace_id == self._workspace_id,
                (TestCase.id == case_id) | (TestCase.public_id == case_id),
                TestCase.deleted_at.is_(None),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        step = await self._session.scalar(statement)
        if step is None:
            raise SelfHealError("STEP_NOT_FOUND", "test step not found")
        return step

    @staticmethod
    def _user_uuid(user_id: str | None) -> uuid.UUID | None:
        if not user_id:
            return None
        try:
            return uuid.UUID(user_id)
        except ValueError:
            return None

    async def propose(
        self,
        case_id: str,
        *,
        step_id: str,
        error: str,
        dom_snapshot: str | None,
    ) -> SelectorRepairPublic:
        await self._require_human_repair_policy()
        step = await self._step(case_id, step_id)
        if not step.code:
            raise SelfHealError("STEP_CODE_REQUIRED", "selector repair requires step code")
        config = await LLMConfigRepo(self._session).get_active(self._workspace_id)
        if config is None:
            raise SelfHealError("LLM_REQUIRED", "no active LLM configured for this workspace")
        prompt, prompt_row = await resolve_and_pin(
            self._session,
            workspace_id=self._workspace_id,
            prompt_name="repair-selector",
        )
        sessions = AgentSessionRepo(self._session)
        agent_session = await sessions.create(
            AgentSessionCreate(
                workspace_id=self._workspace_id,
                kind=AgentSessionKind.EXECUTION,
                model_id=config.model,
                provider=config.provider,
                user_id=self._user_uuid(self._user_id),
                prompt_version_id=prompt_row.id,
                temperature=0.0,
                metadata_json={"caseId": case_id, "stepId": step.id, "operation": "self_heal"},
            )
        )
        provider = await provider_for_config(self._session, config)
        try:
            proposal, completion = await propose_selector_repair(
                provider,
                model=config.model,
                system_prompt=prompt,
                code=step.code,
                error=error,
                action=step.action,
                expected=step.expected,
                dom_snapshot=dom_snapshot,
            )
        except (ProviderError, SelectorRepairError, ValueError) as exc:
            await sessions.complete(agent_session.id, status="failed")
            raise SelfHealError("REPAIR_PROPOSAL_FAILED", str(exc)) from exc
        await sessions.complete(
            agent_session.id,
            cost_usd=Decimal(str(completion.cost_usd)),
            tokens_in=completion.tokens_in,
            tokens_out=completion.tokens_out,
        )
        await write_audit(
            self._session,
            workspace_id=self._workspace_id,
            user_id=self._user_id,
            action="test_step.self_heal.proposed",
            resource_type="test_step",
            resource_id=step.id,
            metadata={
                "agentSessionId": agent_session.id,
                "oldSelector": proposal.old_selector,
                "newSelector": proposal.new_selector,
                "confidence": proposal.confidence,
            },
        )
        return SelectorRepairPublic(step_id=step.id, **proposal.model_dump())

    async def apply(
        self,
        case_id: str,
        request: SelectorRepairApplyRequest,
        *,
        actor_type: str = "user",
    ) -> SelectorRepairApplied:
        await self._require_human_repair_policy()
        step = await self._step(case_id, request.step_id, for_update=True)
        current_code = step.code or ""
        if selector_code_sha256(current_code) != request.code_sha256:
            raise SelfHealError(
                "REPAIR_STALE",
                "step code changed after this repair was proposed",
            )
        try:
            updated_code = apply_selector_repair(
                current_code,
                request.old_selector,
                request.new_selector,
            )
        except SelectorRepairError as exc:
            raise SelfHealError("REPAIR_INVALID", str(exc)) from exc
        step.code = updated_code
        case = await self._session.get(TestCase, step.case_id)
        if case is not None:
            case.order_in_suite = case.order_in_suite
        await self._session.flush()
        await write_audit(
            self._session,
            workspace_id=self._workspace_id,
            user_id=self._user_id,
            action="test_step.self_heal.applied",
            resource_type="test_step",
            resource_id=step.id,
            metadata={
                "actor_type": actor_type,
                "oldSelector": request.old_selector,
                "newSelector": request.new_selector,
                "rationale": request.rationale,
            },
        )
        return SelectorRepairApplied(
            step_id=step.id,
            code=updated_code,
            old_selector=request.old_selector,
            new_selector=request.new_selector,
        )


__all__ = ["SelfHealError", "SelfHealService"]
