"""cuid2-based ID generator helper."""

from cuid2 import Cuid

_cuid = Cuid(length=24)


def new_id() -> str:
    """Return a new 24-char cuid2 string."""
    return str(_cuid.generate())
