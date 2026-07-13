"""Render runnable backend ``TCxxx.py`` files (``requests``) from a test plan.

Output matches TestSprite's backend tests: plain ``requests``, real login →
bearer-token flow, real CRUD that seeds a record before hitting ``/:id`` routes,
and standalone execution at the bottom (guarded so pytest doesn't double-run).
Each file is fully runnable on its own — no Suitest import needed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from suitest_lifecycle.analyzers.zod_schema import ZodField, find_create_schema, sample_value

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config
    from suitest_lifecycle.models import CodeSummary, PlanCase
    from suitest_lifecycle.paths import Paths


def _archetype(title: str) -> str:
    suffix_map = {
        "_returns_service_status_without_authentication": "health",
        "_with_valid_credentials_returns_token": "login_valid",
        "_with_invalid_credentials_returns_401": "login_invalid",
        "_requires_authentication": "requires_auth",
        "_with_valid_token_returns_profile": "me",
        "_with_valid_token_returns_list": "list",
        "_with_valid_id_returns_resource": "get_by_id",
        "_with_valid_data_creates_resource": "create",
        "_with_valid_data_updates_resource": "update",
        "_with_valid_id_deletes_resource": "delete",
        "_with_missing_required_field_returns_validation_error": "validation",
        "_with_missing_credentials_returns_validation_error": "login_missing",
        "_with_invalid_token_returns_401": "invalid_token",
        "_with_unknown_id_returns_404": "not_found",
        "_with_duplicate_unique_field_returns_conflict": "duplicate",
    }
    for suffix, name in suffix_map.items():
        if title.endswith(suffix):
            return name
    return "unknown"


def _ref_parts(source_ref: str) -> tuple[str, str]:
    method, _, path = source_ref.partition(" ")
    return method.strip().upper(), path.strip()


def _rel(path: str, config: Config) -> str:
    """Path relative to the api base (strip the apiBasePath prefix)."""
    api_prefix = "/" + config.api_base_path.strip("/")
    if path.startswith(api_prefix):
        return path[len(api_prefix) :] or "/"
    return path


def _collection_for(resource: str, summary: CodeSummary, config: Config) -> tuple[str, str] | None:
    """Return (relative_collection_path, create_method) for seeding, if a POST exists."""
    for ep in summary.endpoints:
        if ep.method == "POST" and ":" not in ep.path and resource in ep.path:
            return _rel(ep.path, config), "POST"
    return None


def _example_literal(example: dict[str, object]) -> str:
    """Render a python dict-literal from an OpenAPI/Postman example body, making
    obviously-unique fields (sku/email) f-strings keyed on the test's ``token``."""
    items: list[str] = []
    for key, val in example.items():
        lk = str(key).lower()
        if isinstance(val, str):
            if lk == "sku":
                rendered = 'f"SKU-{token}"'
            elif lk == "email":
                rendered = 'f"user_{token}@example.com"'
            else:
                rendered = '"' + val.replace('"', '\\"') + '"'
        elif isinstance(val, bool):
            rendered = "True" if val else "False"
        elif isinstance(val, (int, float)):
            rendered = json.dumps(val)
        else:
            rendered = json.dumps(val)
        items.append(f'        "{key}": {rendered},')
    return "{\n" + "\n".join(items) + "\n    }"


def _resolve_payload(res_name: str, summary: CodeSummary, config: Config) -> str:
    """Prefer a spec/Postman example body (no-repo); fall back to the project's
    Zod create-schema (repo mode)."""
    for ep in summary.endpoints:
        if (
            ep.method == "POST"
            and ":" not in ep.path
            and "{" not in ep.path
            and res_name in ep.path
            and ep.request_example
        ):
            return _example_literal(ep.request_example)
    fields = find_create_schema(config.project_path, res_name)
    return _payload_literal(fields) if fields else "{}"


def _payload_literal(fields: list[ZodField]) -> str:
    """Build a python dict-literal string for a valid create payload."""
    items: list[str] = []
    for f in fields:
        if not f.required and f.base_type == "boolean":
            continue  # skip optionals to keep payload minimal
        val = sample_value(f, "{token}")
        if isinstance(val, str):
            rendered = '"' + val.replace('"', '\\"') + '"'
            if "{token}" in val:
                rendered = "f" + rendered
        elif isinstance(val, bool):
            rendered = "True" if val else "False"
        else:
            rendered = json.dumps(val)
        items.append(f'        "{f.name}": {rendered},')
    return "{\n" + "\n".join(items) + "\n    }"


_HEADER = """import os
import requests
import uuid

BASE_URL = os.environ.get("SUITEST_TARGET_API_URL", {api_url})
TIMEOUT = 30
USERNAME = os.environ.get("SUITEST_TEST_USERNAME", "")
PASSWORD = os.environ.get("SUITEST_TEST_PASSWORD", "")


def _login():
    resp = requests.post(
        f"{{BASE_URL}}{login_rel}",
        json={{"{ufield}": USERNAME, "{pfield}": PASSWORD}},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"login failed: {{resp.status_code}} {{resp.text}}"
    token = resp.json().get("{token_field}")
    assert token, "no token in login response"
    return token


def _auth_headers():
    return {{"Authorization": f"Bearer {{_login()}}"}}


def _extract_id(body):
    if isinstance(body, dict):
        if isinstance(body.get("data"), dict) and "id" in body["data"]:
            return body["data"]["id"]
        if "id" in body:
            return body["id"]
    return None
"""


def _render(case: PlanCase, config: Config, summary: CodeSummary) -> str:
    method, path = _ref_parts(case.source_ref)
    rel = _rel(path, config)
    arch = _archetype(case.title)
    fn = f"test_{case.title}"
    login_rel = _rel(config.auth.login_path, config)
    header = _HEADER.format(
        api_url=repr(config.api_url),
        login_rel=login_rel,
        ufield=config.auth.username_field,
        pfield=config.auth.password_field,
        token_field=config.auth.token_field,
    )

    body = ""
    if arch == "health":
        body = f"""
def {fn}():
    resp = requests.get(f"{{BASE_URL}}{rel}", timeout=TIMEOUT)
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
    assert isinstance(resp.json(), dict)
"""
    elif arch == "login_valid":
        body = f'''
def {fn}():
    resp = requests.post(
        f"{{BASE_URL}}{rel}",
        json={{"{config.auth.username_field}": USERNAME, "{config.auth.password_field}": PASSWORD}},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
    assert resp.json().get("{config.auth.token_field}"), "missing token"
'''
    elif arch == "login_invalid":
        body = f'''
def {fn}():
    resp = requests.post(
        f"{{BASE_URL}}{rel}",
        json={{"{config.auth.username_field}": USERNAME, "{config.auth.password_field}": "wrong-password-xyz"}},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 401, f"expected 401, got {{resp.status_code}}"
'''
    elif arch == "requires_auth":
        verb = method.lower()
        body = f"""
def {fn}():
    resp = requests.{verb}(f"{{BASE_URL}}{rel}", timeout=TIMEOUT)
    assert resp.status_code == 401, f"expected 401, got {{resp.status_code}}"
"""
    elif arch == "me":
        body = f"""
def {fn}():
    resp = requests.get(f"{{BASE_URL}}{rel}", headers=_auth_headers(), timeout=TIMEOUT)
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
    assert isinstance(resp.json(), dict)
"""
    elif arch == "list":
        body = f"""
def {fn}():
    resp = requests.get(f"{{BASE_URL}}{rel}", headers=_auth_headers(), timeout=TIMEOUT)
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
"""
    elif arch in {"get_by_id", "update", "delete"}:
        resource = [
            p for p in path.strip("/").split("/") if p and not p.startswith(":") and p != "api"
        ]
        res_name = resource[-1] if resource else "resource"
        coll = _collection_for(res_name, summary, config)
        payload = _resolve_payload(res_name, summary, config)
        coll_rel = coll[0] if coll else rel.rsplit("/", 1)[0] or "/"
        item_rel = rel.replace(":id", "{rid}").replace("{id}", "{rid}")
        seed = f"""
    headers = _auth_headers()
    token = uuid.uuid4().hex[:8]
    payload = {payload}
    created = requests.post(f"{{BASE_URL}}{coll_rel}", json=payload, headers=headers, timeout=TIMEOUT)
    assert created.status_code in (200, 201), f"seed failed: {{created.status_code}} {{created.text}}"
    rid = _extract_id(created.json())
    assert rid is not None, "could not extract id from created resource"
"""
        if arch == "get_by_id":
            action = f"""    resp = requests.get(f"{{BASE_URL}}{item_rel}", headers=headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
"""
        elif arch == "update":
            action = f"""    resp = requests.{method.lower()}(f"{{BASE_URL}}{item_rel}", json={{"name": "Suitest Updated"}}, headers=headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
"""
        else:  # delete
            action = f"""    resp = requests.delete(f"{{BASE_URL}}{item_rel}", headers=headers, timeout=TIMEOUT)
    assert resp.status_code == 200, f"expected 200, got {{resp.status_code}}"
"""
        body = f"\ndef {fn}():{seed}{action}"
    elif arch == "create":
        resource = [
            p for p in path.strip("/").split("/") if p and not p.startswith(":") and p != "api"
        ]
        res_name = resource[-1] if resource else "resource"
        payload = _resolve_payload(res_name, summary, config)
        body = f"""
def {fn}():
    headers = _auth_headers()
    token = uuid.uuid4().hex[:8]
    payload = {payload}
    resp = requests.post(f"{{BASE_URL}}{rel}", json=payload, headers=headers, timeout=TIMEOUT)
    assert resp.status_code in (200, 201), f"expected 2xx, got {{resp.status_code}} {{resp.text}}"
"""
    elif arch == "validation":
        body = f"""
def {fn}():
    headers = _auth_headers()
    resp = requests.post(f"{{BASE_URL}}{rel}", json={{}}, headers=headers, timeout=TIMEOUT)
    assert resp.status_code in (400, 422), f"expected validation 4xx, got {{resp.status_code}} {{resp.text}}"
"""
    elif arch == "login_missing":
        body = f"""
def {fn}():
    resp = requests.post(f"{{BASE_URL}}{rel}", json={{}}, timeout=TIMEOUT)
    assert resp.status_code in (400, 422), f"expected validation 4xx, got {{resp.status_code}} {{resp.text}}"
"""
    elif arch == "invalid_token":
        verb = method.lower()
        body = f"""
def {fn}():
    headers = {{"Authorization": "Bearer invalid-token-xyz"}}
    resp = requests.{verb}(f"{{BASE_URL}}{rel}", headers=headers, timeout=TIMEOUT)
    assert resp.status_code == 401, f"expected 401, got {{resp.status_code}}"
"""
    elif arch == "not_found":
        verb = method.lower()
        missing_rel = rel.replace(":id", "999999").replace("{id}", "999999")
        extra = ', json={"name": "Suitest Updated"}' if verb in ("put", "patch") else ""
        body = f"""
def {fn}():
    headers = _auth_headers()
    resp = requests.{verb}(f"{{BASE_URL}}{missing_rel}", headers=headers{extra}, timeout=TIMEOUT)
    assert resp.status_code == 404, f"expected 404, got {{resp.status_code}} {{resp.text}}"
"""
    elif arch == "duplicate":
        resource = [
            p for p in path.strip("/").split("/") if p and not p.startswith(":") and p != "api"
        ]
        res_name = resource[-1] if resource else "resource"
        payload = _resolve_payload(res_name, summary, config)
        body = f"""
def {fn}():
    headers = _auth_headers()
    token = uuid.uuid4().hex[:8]
    payload = {payload}
    first = requests.post(f"{{BASE_URL}}{rel}", json=payload, headers=headers, timeout=TIMEOUT)
    assert first.status_code in (200, 201), f"seed failed: {{first.status_code}} {{first.text}}"
    resp = requests.post(f"{{BASE_URL}}{rel}", json=payload, headers=headers, timeout=TIMEOUT)
    assert resp.status_code in (400, 409), f"expected conflict, got {{resp.status_code}} {{resp.text}}"
"""
    else:
        body = f"""
def {fn}():
    raise AssertionError("unsupported archetype for {case.id}")
"""

    footer = f"""

if __name__ == "__main__":
    {fn}()
    print("PASS {case.id}")
"""
    return header + body + footer


def export_backend_tests(
    cases: list[PlanCase], summary: CodeSummary, config: Config, paths: Paths
) -> list[PlanCase]:
    """Write one runnable .py per case; set ``automation_file`` on each case."""
    paths.ensure()
    for case in cases:
        filename = f"{case.id}_{case.title}.py"
        code = _render(case, config, summary)
        paths.test_file(filename).write_text(code, encoding="utf-8")
        case.automation_file = filename
    return cases


__all__ = ["export_backend_tests"]
