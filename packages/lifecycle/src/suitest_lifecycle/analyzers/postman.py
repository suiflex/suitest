"""No-repo backend discovery from a Postman v2 collection (deterministic).

Walks the collection (folders nested), extracting method + path + an example
request body per request. Auth is inferred from an Authorization header or an
auth block. Path is taken from ``url.path`` (or parsed from ``url.raw``), with
``{{baseUrl}}`` and host stripped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from suitest_lifecycle.models import CodeSummary, Endpoint, Mode

_PARAM = re.compile(r"\{\{[^}]+\}\}")


def load_collection(file: str) -> dict[str, object]:
    data = json.loads(Path(file).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Postman collection must be a JSON object")
    return data


def _path_from_url(url: object) -> str:
    if isinstance(url, dict):
        segs = url.get("path")
        if isinstance(segs, list):
            parts = [str(s) for s in segs]
            return "/" + "/".join(p.strip("/") for p in parts if p)
        raw = str(url.get("raw", ""))
    else:
        raw = str(url)
    raw = _PARAM.sub("", raw)  # drop {{baseUrl}} etc.
    raw = re.sub(r"^https?://[^/]+", "", raw)  # drop scheme+host
    raw = raw.split("?", 1)[0]  # drop query
    return "/" + raw.strip("/")


def _example_body(request: dict[str, object]) -> dict[str, object] | None:
    body = request.get("body")
    if not isinstance(body, dict):
        return None
    if body.get("mode") == "raw":
        raw = body.get("raw")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
    return None


def _auth_required(request: dict[str, object]) -> bool:
    auth = request.get("auth")
    if isinstance(auth, dict) and auth.get("type") not in (None, "noauth"):
        return True
    headers = request.get("header")
    if isinstance(headers, list):
        for h in headers:
            if isinstance(h, dict) and str(h.get("key", "")).lower() == "authorization":
                return True
    return False


def _walk(items: list[object], out: list[Endpoint]) -> None:
    for it in items:
        if not isinstance(it, dict):
            continue
        sub = it.get("item")
        if isinstance(sub, list):  # folder
            _walk(sub, out)
            continue
        request = it.get("request")
        if not isinstance(request, dict):
            continue
        method = str(request.get("method", "GET")).upper()
        path = _path_from_url(request.get("url", ""))
        out.append(
            Endpoint(
                method=method,
                path=path,
                auth_required=_auth_required(request),
                source_file="postman",
                handler=str(it.get("name", "")),
                request_example=_example_body(request),
            )
        )


def analyze_postman(collection: dict[str, object], project_name: str) -> CodeSummary:
    endpoints: list[Endpoint] = []
    items = collection.get("item")
    if isinstance(items, list):
        _walk(items, endpoints)

    # de-dup (method, path)
    seen: set[tuple[str, str]] = set()
    unique: list[Endpoint] = []
    for ep in endpoints:
        key = (ep.method, ep.path)
        if key not in seen:
            seen.add(key)
            unique.append(ep)
    unique.sort(key=lambda e: (e.path, e.method))

    info = collection.get("info", {})
    name = info.get("name", project_name) if isinstance(info, dict) else project_name
    groups: dict[str, int] = {}
    for ep in unique:
        parts = [
            p for p in ep.path.strip("/").split("/") if p and not p.startswith(":") and p != "api"
        ]
        key = parts[0] if parts else "root"
        groups[key] = groups.get(key, 0) + 1

    return CodeSummary(
        project_name=str(name) or project_name,
        mode=Mode.BACKEND,
        tech_stack=["Postman", "HTTP API"],
        endpoints=unique,
        features=[k for k, _ in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))],
        auth_flow="Auth inferred from Authorization header / auth block."
        if any(e.auth_required for e in unique)
        else "",
    )


__all__ = ["analyze_postman", "load_collection"]
