"""PromptVersion repository (M3-5).

Backs the prompt-drift guard: :meth:`get_hash` returns the stored content hash so
the agent ``prompts.loader`` can reject an in-place edit, and :meth:`ensure`
registers a ``(name, version)`` exactly once (it never overwrites an existing
row's content — bumping the version is the contract for changing a prompt).
"""

from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.prompt_version import PromptVersion
from suitest_db.repositories.base import AsyncRepository


class PromptVersionCreate(BaseModel):
    name: str
    version: str
    content: str
    hash: str


class PromptVersionUpdate(BaseModel):
    content: str | None = None
    hash: str | None = None


class PromptVersionRepo(AsyncRepository[PromptVersion, PromptVersionCreate, PromptVersionUpdate]):
    model = PromptVersion

    async def get(self, name: str, version: str) -> PromptVersion | None:
        stmt = select(PromptVersion).where(
            PromptVersion.name == name, PromptVersion.version == version
        )
        row: PromptVersion | None = await self.session.scalar(stmt)
        return row

    async def get_hash(self, name: str, version: str) -> str | None:
        row = await self.get(name, version)
        return row.hash if row is not None else None

    async def ensure(
        self, name: str, version: str, content: str, content_hash: str
    ) -> PromptVersion:
        """Return the existing ``(name, version)`` row, or insert it if absent.

        Does not mutate an existing row — drift between disk and DB is surfaced by
        the loader, not silently healed here.
        """
        existing = await self.get(name, version)
        if existing is not None:
            return existing
        row = PromptVersion(name=name, version=version, content=content, hash=content_hash)
        self.session.add(row)
        await self.session.flush()
        return row
