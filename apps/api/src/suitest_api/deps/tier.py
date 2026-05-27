"""``@require_tier`` — capability gate for service methods.

M1a contract (NO-OP enforcement)
--------------------------------
Every service method MUST be decorated with ``@require_tier(...)``. In M1a the
decorator does **not** block: it only *records* the required :class:`TierFlag` on
the wrapped function via the ``__suitest_required_tier__`` attribute and then
calls through unchanged. This guarantees that when M3 flips on enforcement, the
gate is already present on every method and only the decorator body changes —
no service code has to be touched, and nothing silently ships ungated.

When enforcement lands (M3) the decorator will resolve the deployment tier (and
optional workspace overlay) and raise ``403`` via :func:`suitest_core.capabilities.tier_in`
when the resolved tier is not permitted by the recorded flag.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import TypeVar

from suitest_core.capabilities import TierFlag

P = TypeVar("P")
R = TypeVar("R")

# Attribute name under which the required tier flag is stamped on a wrapped fn.
REQUIRED_TIER_ATTR = "__suitest_required_tier__"


def require_tier(
    flag: TierFlag = TierFlag.ANY,
) -> Callable[[Callable[..., Awaitable[R]]], Callable[..., Awaitable[R]]]:
    """Record ``flag`` as the method's tier requirement (no-op enforcement in M1a).

    Usage on a service method::

        @require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
        async def generate(self, ...) -> ...:
            ...

    The wrapped coroutine is returned unchanged behaviourally; the requirement is
    discoverable via ``getattr(fn, REQUIRED_TIER_ATTR)``.
    """

    def decorator(fn: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> R:
            # M1a: no gate. M3 resolves tier here and raises 403 when not permitted.
            return await fn(*args, **kwargs)

        setattr(wrapper, REQUIRED_TIER_ATTR, flag)
        return wrapper

    return decorator
