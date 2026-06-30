"""Deterministic Express/Node route analyzer (ZERO tier — no LLM).

Handles the canonical modular Express layout used by real TS backends:

    // app.ts
    app.get("/api/health", ...)                 // direct route
    app.use("/api/auth", authRoutes)            // mounted router
    app.use("/api/products", productRoutes)

    // auth.routes.ts
    router.post("/login", loginController)
    router.get("/me", authMiddleware, meController)

    // product.routes.ts
    router.use(authMiddleware)                  // router-level auth
    router.get("/", listController)

Output: a :class:`CodeSummary` with fully-qualified, auth-aware endpoints. It is
heuristic (regex over source) but traceable: every endpoint records the file it
came from. Anything it cannot resolve is simply omitted rather than guessed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from suitest_lifecycle.models import CodeSummary, Endpoint, Mode

_METHODS = ("get", "post", "put", "delete", "patch")
# app.use("/prefix", routerVar)
_MOUNT_RE = re.compile(r"""\.use\(\s*['"](?P<prefix>/[^'"]*)['"]\s*,\s*(?P<var>\w+)\s*\)""")
# import authRoutes from "./modules/auth/auth.routes"
_IMPORT_RE = re.compile(r"""import\s+(?P<var>\w+)\s+from\s+['"](?P<spec>[^'"]+)['"]""")
# app.get("/api/health", ...)  /  router.post("/login", authMiddleware, ctrl)
_ROUTE_RE = re.compile(
    r"""\b(?P<obj>app|router)\s*\.\s*(?P<method>get|post|put|delete|patch)\s*\(\s*"""
    r"""['"](?P<path>[^'"]*)['"](?P<rest>[^)]*)\)""",
    re.IGNORECASE,
)
_ROUTER_USE_AUTH_RE = re.compile(r"""\brouter\s*\.\s*use\(\s*(?P<mw>\w+)\s*\)""")


def _ts_files(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*.ts") if ".d.ts" not in p.name and "node_modules" not in p.parts)


def _join(prefix: str, sub: str) -> str:
    prefix = "/" + prefix.strip("/")
    sub = sub.strip("/")
    return prefix if not sub else f"{prefix.rstrip('/')}/{sub}"


def _resolve_import(from_file: Path, spec: str, src: Path) -> Path | None:
    if not spec.startswith("."):
        return None
    base = (from_file.parent / spec).resolve()
    for cand in (base.with_suffix(".ts"), base / "index.ts", Path(str(base) + ".ts")):
        if cand.is_file():
            return cand
    return None


def _auth_markers(text: str) -> tuple[bool, set[str]]:
    """Return (router_level_auth, set of auth middleware identifiers seen)."""
    auth_ids: set[str] = set()
    for m in _ROUTER_USE_AUTH_RE.finditer(text):
        mw = m.group("mw")
        if "auth" in mw.lower():
            auth_ids.add(mw)
    router_level = bool(auth_ids)
    # also collect any identifier that looks like auth middleware referenced inline
    for ident in re.findall(r"\b(\w*[Aa]uth\w*)\b", text):
        if "middleware" in ident.lower() or ident.lower() in {"authmiddleware", "requireauth", "protect"}:
            auth_ids.add(ident)
    return router_level, auth_ids


def _routes_in_file(path: Path, src: Path) -> tuple[list[tuple[str, str, bool, str]], bool]:
    """Parse one router/app file.

    Returns (routes, router_level_auth) where each route is
    (method, sub_path, inline_auth, handler).
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    router_level, auth_ids = _auth_markers(text)
    routes: list[tuple[str, str, bool, str]] = []
    for m in _ROUTE_RE.finditer(text):
        method = m.group("method").upper()
        sub = m.group("path")
        rest = m.group("rest")
        inline_auth = any(aid in rest for aid in auth_ids)
        handler = ""
        ids = re.findall(r"\b(\w+)\b", rest)
        if ids:
            handler = ids[-1]
        routes.append((method, sub, inline_auth, handler))
    return routes, router_level


def _tech_stack(project_path: Path) -> tuple[list[str], str]:
    stack: list[str] = ["TypeScript", "Node.js"]
    auth_flow = ""
    pkg = project_path / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        known = {
            "express": "Express",
            "@prisma/client": "Prisma",
            "prisma": "Prisma",
            "jsonwebtoken": "JWT",
            "zod": "Zod",
            "bcryptjs": "bcrypt",
            "cors": "CORS",
        }
        for dep, label in known.items():
            if dep in deps and label not in stack:
                stack.append(label)
        if "jsonwebtoken" in deps:
            auth_flow = "JWT bearer: POST login returns a token used as 'Authorization: Bearer <token>'."
    return stack, auth_flow


def analyze_express(project_path: Path, project_name: str) -> CodeSummary:
    src = project_path / "src"
    if not src.is_dir():
        src = project_path
    files = _ts_files(src)

    # 1) imports per file (var -> resolved file)
    # 2) mounts (prefix -> var) across all files (app entry)
    mounts: list[tuple[str, str, Path]] = []  # (prefix, var, file)
    imports_by_file: dict[Path, dict[str, Path]] = {}
    direct_routes: list[Endpoint] = []

    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        imap: dict[str, Path] = {}
        for im in _IMPORT_RE.finditer(text):
            resolved = _resolve_import(f, im.group("spec"), src)
            if resolved is not None:
                imap[im.group("var")] = resolved
        imports_by_file[f] = imap
        for mm in _MOUNT_RE.finditer(text):
            mounts.append((mm.group("prefix"), mm.group("var"), f))
        # direct app.<method> routes (e.g. health)
        for m in _ROUTE_RE.finditer(text):
            if m.group("obj").lower() == "app":
                method = m.group("method").upper()
                path = m.group("path")
                rest = m.group("rest")
                _, auth_ids = _auth_markers(text)
                inline_auth = any(aid in rest for aid in auth_ids)
                direct_routes.append(
                    Endpoint(
                        method=method,
                        path="/" + path.strip("/"),
                        auth_required=inline_auth,
                        source_file=str(f.relative_to(project_path)),
                    )
                )

    endpoints: list[Endpoint] = list(direct_routes)

    # 3) expand each mount into its router file's routes
    for prefix, var, mount_file in mounts:
        router_file = imports_by_file.get(mount_file, {}).get(var)
        if router_file is None or not router_file.is_file():
            continue
        routes, router_level_auth = _routes_in_file(router_file, src)
        for method, sub, inline_auth, handler in routes:
            endpoints.append(
                Endpoint(
                    method=method,
                    path=_join(prefix, sub),
                    auth_required=router_level_auth or inline_auth,
                    source_file=str(router_file.relative_to(project_path)),
                    handler=handler,
                )
            )

    # de-dup (method, path), keep first
    seen: set[tuple[str, str]] = set()
    unique: list[Endpoint] = []
    for ep in endpoints:
        key = (ep.method, ep.path)
        if key not in seen:
            seen.add(key)
            unique.append(ep)
    unique.sort(key=lambda e: (e.path, e.method))

    stack, auth_flow = _tech_stack(project_path)
    features = _infer_features(unique)

    return CodeSummary(
        project_name=project_name,
        mode=Mode.BACKEND,
        tech_stack=stack,
        endpoints=unique,
        features=features,
        auth_flow=auth_flow,
    )


def _infer_features(endpoints: list[Endpoint]) -> list[str]:
    groups: dict[str, int] = {}
    for ep in endpoints:
        parts = [p for p in ep.path.strip("/").split("/") if p and not p.startswith(":")]
        # drop leading 'api'
        parts = [p for p in parts if p != "api"]
        key = parts[0] if parts else "root"
        groups[key] = groups.get(key, 0) + 1
    return [k for k, _ in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))]
