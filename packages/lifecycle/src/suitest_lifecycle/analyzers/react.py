"""Deterministic React Router analyzer (ZERO tier).

Parses ``<Route path="…" element={<Component …/>}>`` declarations and marks a
route protected when it sits inside a ``<ProtectedRoute …>`` subtree. Also
harvests ``data-testid`` attributes per page so the frontend exporter can drive
the UI with stable selectors instead of brittle text matching.
"""

from __future__ import annotations

import re
from pathlib import Path

from suitest_lifecycle.models import CodeSummary, Mode, Page

_ROUTE_RE = re.compile(
    r"""<Route\s+[^>]*?path=["'](?P<path>[^"']+)["'][^>]*?element=\{<(?P<comp>\w+)""",
    re.DOTALL,
)
_PROTECTED_OPEN_RE = re.compile(r"element=\{<ProtectedRoute")
_TESTID_RE = re.compile(r"""data-testid=["'](?P<id>[^"']+)["']""")


def _find_app_file(src: Path) -> Path | None:
    for name in ("App.tsx", "App.jsx", "routes.tsx", "main.tsx"):
        cand = src / name
        if cand.is_file():
            return cand
    matches = [p for p in src.rglob("*.tsx") if "<Route" in p.read_text(encoding="utf-8", errors="replace")]
    return matches[0] if matches else None


def _collect_testids(src: Path) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {}
    for f in sorted((src / "pages").glob("*.tsx")) if (src / "pages").is_dir() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        found = sorted({m.group("id") for m in _TESTID_RE.finditer(text)})
        ids[f.stem] = found
    return ids


def analyze_react(project_path: Path, project_name: str) -> CodeSummary:
    src = project_path / "src"
    if not src.is_dir():
        src = project_path
    app = _find_app_file(src)
    pages: list[Page] = []

    if app is not None:
        text = app.read_text(encoding="utf-8", errors="replace")
        protected_idx = -1
        pm = _PROTECTED_OPEN_RE.search(text)
        if pm:
            protected_idx = pm.start()
        catchall_idx = text.find('path="*"')
        for m in _ROUTE_RE.finditer(text):
            route = m.group("path")
            comp = m.group("comp")
            if route == "*":
                continue
            pos = m.start()
            protected = protected_idx != -1 and pos > protected_idx
            if catchall_idx != -1 and pos > catchall_idx:
                protected = False
            if route in {"/login"}:
                protected = False
            pages.append(
                Page(
                    route=route,
                    name=comp,
                    protected=protected,
                    source_file=str(app.relative_to(project_path)),
                )
            )

    stack = ["TypeScript", "React", "Vite"]
    pkg = project_path / "package.json"
    if pkg.is_file():
        text = pkg.read_text(encoding="utf-8", errors="replace")
        if "react-router" in text:
            stack.append("React Router")
        if "axios" in text:
            stack.append("axios")

    return CodeSummary(
        project_name=project_name,
        mode=Mode.FRONTEND,
        tech_stack=stack,
        pages=pages,
        features=[p.name for p in pages],
        auth_flow="Form login at /login; protected routes redirect anonymous users to /login.",
    )


def collect_testids(project_path: Path) -> dict[str, list[str]]:
    src = project_path / "src"
    if not src.is_dir():
        src = project_path
    return _collect_testids(src)


__all__ = ["analyze_react", "collect_testids"]
