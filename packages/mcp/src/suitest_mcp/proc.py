"""Cross-OS resolution for stdio MCP command executables.

Bundled providers spawn bare names like ``npx`` / ``node`` (see
``bundled/playwright.py``). On Windows those live as ``npx.cmd`` / ``node.exe``,
so passing the bare name straight to the stdio transport fails to launch. This
resolves the command to an absolute path before spawn.

``shutil.which`` already honors Windows ``PATHEXT`` and absolute/relative paths,
so this is a thin wrapper: resolve when possible, otherwise return the original
string unchanged so the transport still surfaces a helpful "not found" error.
"""

from __future__ import annotations

import shutil


def resolve_command(command: str) -> str:
    """Return an absolute path for ``command`` on PATH, else ``command`` as-is.

    ``# ponytail: shutil.which covers PATHEXT + absolute paths; thin wrapper only``
    """
    return shutil.which(command) or command
