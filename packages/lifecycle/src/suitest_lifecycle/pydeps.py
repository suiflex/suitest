"""On-demand pip provisioning for the packages generated tests import.

Suitest owns its test runtime: the person testing their app runs their app, not
``pip install``. The generated backend tests import ``requests`` and the frontend
ones drive ``playwright``, so both are installed into the interpreter that will
execute them — the same one running this module, since ``runner.run_tests``
shells out to ``sys.executable``.

Everything here is idempotent and cheap when the package is already importable.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import site
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class DepStatus:
    ready: bool
    detail: str


def importable(module: str) -> bool:
    try:
        importlib.import_module(module)
    except ImportError:
        return False
    return True


def pip_install_variants(pkg: str) -> list[list[str]]:
    """pip argv variants to try in order, adapting to the interpreter.

    - Inside a venv (``sys.prefix != sys.base_prefix``): install into the venv
      site — no ``--user`` (disallowed in venvs), no PEP-668 marker to fight.
    - System/Homebrew/distro interpreter: prefer ``--user`` (contained to the
      user site, importable by this interpreter AND the subprocesses that run
      the generated tests), with a ``--break-system-packages`` fallback for
      PEP-668 "externally-managed" environments (Homebrew, Debian).
    """
    base = [sys.executable, "-m", "pip", "install", "--upgrade", pkg]
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        return [base]
    return [[*base, "--user"], [*base, "--user", "--break-system-packages"]]


def ensure_pip() -> None:
    """Best-effort: bootstrap pip via ensurepip when the interpreter lacks it
    (minimal venvs / stripped pythons ship without pip)."""
    if importlib.util.find_spec("pip") is not None:
        return
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            [sys.executable, "-m", "ensurepip", "--upgrade"],
            capture_output=True,
            text=True,
            timeout=180,
        )


def make_importable_in_process() -> None:
    """Surface a just-installed package to the RUNNING interpreter without a
    restart. A server started before the user-site dir existed never got it on
    ``sys.path`` (``site`` only adds user-site at startup, and only if it
    exists) — add it now and drop import caches."""
    usersite = site.getusersitepackages()
    if isinstance(usersite, str):
        site.addsitedir(usersite)
    importlib.invalidate_caches()


def install(pkg: str, module: str, timeout_sec: int) -> DepStatus:
    """Install ``pkg`` and report whether ``module`` became importable."""
    ensure_pip()
    detail = "pip unavailable"
    for argv in pip_install_variants(pkg):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_sec)
        except (subprocess.TimeoutExpired, OSError) as exc:
            detail = str(exc)
            continue
        if proc.returncode == 0:
            make_importable_in_process()
            if importable(module):
                return DepStatus(True, f"{pkg} installed on demand")
            detail = f"pip reported success but {module} is still not importable"
            continue
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        detail = " | ".join(tail) if tail else f"pip exited {proc.returncode}"
    return DepStatus(
        False,
        f"could not auto-install {pkg} (interpreter: {sys.executable}): {detail}. "
        f"Install it manually: '{sys.executable} -m pip install {pkg}'",
    )


def ensure(
    pkg: str, module: str | None = None, *, auto_install: bool = True, timeout_sec: int = 300
) -> DepStatus:
    """Make ``module`` importable, installing ``pkg`` on demand when it is not."""
    module = module or pkg
    if importable(module):
        return DepStatus(True, "ready")
    if not auto_install:
        return DepStatus(False, f"{pkg} not installed (auto-install disabled)")
    return install(pkg, module, timeout_sec)


_VENV_BIN = ("bin/python", "Scripts/python.exe")
_PROJECT_VENV_DIRS = (".venv", "venv", ".venv-suitest", "env")


def project_interpreter(project_path: Path) -> str | None:
    """The interpreter belonging to the project under test, if it ships one.

    A project's own tests import the project's own dependencies, which Suitest's
    interpreter knows nothing about. Prefer the venv sitting in the repo — the
    Python equivalent of what ``npm exec`` already does for the Node adapters.
    """
    for name in _PROJECT_VENV_DIRS:
        for rel in _VENV_BIN:
            candidate = project_path / name / rel
            if candidate.is_file():
                return str(candidate)
    return None


__all__ = [
    "DepStatus",
    "ensure",
    "ensure_pip",
    "importable",
    "install",
    "make_importable_in_process",
    "pip_install_variants",
    "project_interpreter",
]
