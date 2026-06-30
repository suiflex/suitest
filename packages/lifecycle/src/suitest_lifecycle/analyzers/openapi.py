"""No-repo backend discovery from an OpenAPI spec (deterministic, ZERO tier).

When QA has no source checkout, the API contract is the discovery source. Reads
an OpenAPI 3.x document (local file or fetched URL), and emits endpoints with
auth flags + an example request body (so the backend exporter can build a valid
create payload without the project's Zod schema).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from suitest_lifecycle.models import CodeSummary, Endpoint, Mode

_METHODS = ("get", "post", "put", "delete", "patch")


def load_spec(*, url: str, file: str, base_url: str) -> dict[str, object]:
    """Load an OpenAPI doc from a local file or a URL (absolute, or relative to base_url)."""
    if file:
        text = Path(file).read_text(encoding="utf-8")
        return _as_dict(json.loads(text))
    if url:
        full = url if url.startswith("http") else base_url.rstrip("/") + "/" + url.lstrip("/")
        with urllib.request.urlopen(full, timeout=15) as resp:  # noqa: S310 - user-provided spec URL
            return _as_dict(json.loads(resp.read().decode("utf-8")))
    raise ValueError("no openapi url or file provided")


def _as_dict(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ValueError("OpenAPI spec must be a JSON object")
    return data


def _resolve_ref(ref: str, spec: dict[str, object]) -> dict[str, object]:
    # only local refs: #/components/schemas/Name
    node: object = spec
    for part in ref.lstrip("#/").split("/"):
        if isinstance(node, dict):
            node = node.get(part, {})
    return node if isinstance(node, dict) else {}


def _example_from_schema(schema: dict[str, object], spec: dict[str, object], depth: int = 0) -> object:
    if depth > 5 or not isinstance(schema, dict):
        return None
    if "$ref" in schema and isinstance(schema["$ref"], str):
        schema = _resolve_ref(schema["$ref"], spec)
    if "example" in schema:
        return schema["example"]
    stype = schema.get("type")
    if stype == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required = schema.get("required", [])
        out: dict[str, object] = {}
        if isinstance(props, dict):
            for name, sub in props.items():
                # include required fields (+ a couple optionals are fine)
                if isinstance(required, list) and name not in required:
                    continue
                out[str(name)] = _example_from_schema(sub if isinstance(sub, dict) else {}, spec, depth + 1)
        return out
    if stype == "string":
        fmt = schema.get("format")
        if fmt == "email":
            return "user@example.com"
        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]
        return "sutest-sample"
    if stype == "integer":
        return 1
    if stype == "number":
        return 9.99
    if stype == "boolean":
        return True
    if stype == "array":
        return []
    return None


def _request_example(op: dict[str, object], spec: dict[str, object]) -> dict[str, object] | None:
    body = op.get("requestBody")
    if not isinstance(body, dict):
        return None
    content = body.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    schema = media.get("schema")
    example = _example_from_schema(schema if isinstance(schema, dict) else {}, spec)
    return example if isinstance(example, dict) else None


def _auth_required(op: dict[str, object], spec: dict[str, object]) -> bool:
    if "security" in op:
        sec = op.get("security")
        return bool(sec)  # [] means explicitly public
    return bool(spec.get("security"))


def analyze_openapi(spec: dict[str, object], project_name: str) -> CodeSummary:
    paths = spec.get("paths", {})
    endpoints: list[Endpoint] = []
    if isinstance(paths, dict):
        for raw_path, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method in _METHODS:
                op = item.get(method)
                if not isinstance(op, dict):
                    continue
                endpoints.append(
                    Endpoint(
                        method=method.upper(),
                        path=str(raw_path),
                        auth_required=_auth_required(op, spec),
                        source_file="openapi",
                        handler=str(op.get("operationId", "")),
                        summary=str(op.get("summary", "")),
                        request_example=_request_example(op, spec),
                    )
                )
    endpoints.sort(key=lambda e: (e.path, e.method))

    info = spec.get("info", {})
    title = info.get("title", project_name) if isinstance(info, dict) else project_name
    stack = ["OpenAPI", "HTTP API"]
    groups: dict[str, int] = {}
    for ep in endpoints:
        parts = [p for p in ep.path.strip("/").split("/") if p and not _is_param(p) and p != "api"]
        key = parts[0] if parts else "root"
        groups[key] = groups.get(key, 0) + 1
    auth_flow = "Auth required on secured operations (per OpenAPI security)." if any(
        e.auth_required for e in endpoints
    ) else ""

    return CodeSummary(
        project_name=str(title) or project_name,
        mode=Mode.BACKEND,
        tech_stack=stack,
        endpoints=endpoints,
        features=[k for k, _ in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))],
        auth_flow=auth_flow,
    )


def _is_param(seg: str) -> bool:
    return seg.startswith(":") or (seg.startswith("{") and seg.endswith("}"))


__all__ = ["load_spec", "analyze_openapi"]
