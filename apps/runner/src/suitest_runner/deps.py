"""Runner-side dependency-injection helpers.

The runner avoids a heavy DI container — every collaborator is built lazily
inside :func:`suitest_runner.worker.startup` and stashed on the ARQ ``ctx``
dict the job receives. This module exposes pure constructors for the
collaborators the orchestrator + handler hooks reach for. Tests can build
the same collaborators in isolation by importing the factories below; the
ARQ ``startup`` hook calls them with real settings + redis + engine.

Today the only DI-exposed surface is the M1d-10
:func:`build_defect_auto_filer` factory — every other collaborator
(``McpInvoker``, ``McpRegistry``, ``McpPool``) is still built inline in
``worker.py``. M2 will fold those into this module too so the worker file
stays a thin wiring layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_api.services.defect_auto_filer import DefectAutoFiler, DefectCategorizer

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_api.services.defect_auto_filer import _ArqEnqueueCapable, _PublishCapable


def build_defect_auto_filer(
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    publisher: _PublishCapable | None,
    arq_pool: _ArqEnqueueCapable | None,
    categorizer: DefectCategorizer | None = None,
) -> DefectAutoFiler:
    """Construct a :class:`DefectAutoFiler` ready to serve the runner hook.

    ``categorizer`` defaults to a fresh :class:`DefectCategorizer` instance —
    the regex tables are module-level constants so multiple instances share
    the underlying patterns and the construction cost is essentially zero.

    The factory takes ``arq_pool`` + ``publisher`` as :class:`Protocol`
    surfaces (no concrete redis / arq type) so unit tests can pass recorder
    stubs without instantiating the real clients.
    """
    return DefectAutoFiler(
        session_factory=session_factory,
        publisher=publisher,
        arq_pool=arq_pool,
        categorizer=categorizer or DefectCategorizer(),
    )
