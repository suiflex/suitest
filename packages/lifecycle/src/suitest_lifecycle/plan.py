"""Deterministic backend test-plan generator (ZERO tier, no LLM).

Turns discovered endpoints into real, source-traceable test cases following the
same archetypes TestSprite emits: public probes, auth happy/invalid paths,
"protected endpoint rejects anonymous" 401s, and authenticated CRUD. Every case
carries a ``source_ref`` ("POST /api/products") so it can be traced back to the
endpoint that justified it — no dummy tests.
"""

from __future__ import annotations

from suitest_lifecycle.models import CodeSummary, Endpoint, PlanCase, PlanStep, Priority


def _slug(method: str, path: str) -> str:
    cleaned = (
        path.strip("/")
        .replace("/", "_")
        .replace(":", "")
        .replace("{", "")
        .replace("}", "")
        .replace("-", "_")
    )
    return f"{method.lower()}_{cleaned}".strip("_")


def _is_login(ep: Endpoint) -> bool:
    return ep.method == "POST" and ep.path.rstrip("/").endswith("login")


def _has_id_param(ep: Endpoint) -> bool:
    return ":" in ep.path or "{" in ep.path


def _resource(ep: Endpoint) -> str:
    parts = [p for p in ep.path.strip("/").split("/") if p and not p.startswith(":") and p != "api"]
    return parts[-1] if parts else "resource"


def _case(
    cid: str,
    title: str,
    description: str,
    category: str,
    priority: Priority,
    source_ref: str,
    steps: list[tuple[str, str]],
) -> PlanCase:
    return PlanCase(
        id=cid,
        title=title,
        description=description,
        category=category,
        priority=priority,
        source_ref=source_ref,
        steps=[PlanStep(type=t, description=d) for t, d in steps],
    )


def generate_backend_plan(summary: CodeSummary) -> list[PlanCase]:
    cases: list[PlanCase] = []
    counter = 0
    seen_unauth_resource: set[str] = set()

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"TC{counter:03d}"

    for ep in summary.endpoints:
        ref = f"{ep.method} {ep.path}"

        # Public probe (health / any public GET)
        if ep.method == "GET" and not ep.auth_required and "health" in ep.path:
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('get', ep.path)}_returns_service_status_without_authentication",
                    f"GET {ep.path} returns 200 with a JSON status body and requires no auth.",
                    "Health",
                    Priority.HIGH,
                    ref,
                    [
                        ("action", f"Send GET {ep.path} with no Authorization header"),
                        ("assertion", "Expect HTTP 200 and a JSON object"),
                    ],
                )
            )
            continue

        # Auth: login
        if _is_login(ep):
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('post', ep.path)}_with_valid_credentials_returns_token",
                    f"POST {ep.path} with valid credentials returns 200 and a bearer token.",
                    "Auth",
                    Priority.HIGH,
                    ref,
                    [
                        ("action", f"Send POST {ep.path} with valid username/password"),
                        ("assertion", "Expect HTTP 200 and a token field in the response"),
                    ],
                )
            )
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('post', ep.path)}_with_invalid_credentials_returns_401",
                    f"POST {ep.path} with wrong credentials returns 401.",
                    "Auth",
                    Priority.HIGH,
                    ref,
                    [
                        ("action", f"Send POST {ep.path} with an invalid password"),
                        ("assertion", "Expect HTTP 401"),
                    ],
                )
            )
            continue

        # Protected endpoint: emit a single anonymous-rejection case per resource
        if ep.auth_required:
            res = _resource(ep)
            if res not in seen_unauth_resource:
                seen_unauth_resource.add(res)
                anon_ep = ep
                cases.append(
                    _case(
                        next_id(),
                        f"{_slug(anon_ep.method.lower(), anon_ep.path)}_requires_authentication",
                        f"{anon_ep.method} {anon_ep.path} without a token returns 401.",
                        res.title(),
                        Priority.HIGH,
                        f"{anon_ep.method} {anon_ep.path}",
                        [
                            ("action", f"Send {anon_ep.method} {anon_ep.path} with no Authorization header"),
                            ("assertion", "Expect HTTP 401"),
                        ],
                    )
                )

        # Authenticated happy paths by method
        res = _resource(ep)
        category = res.title()
        if ep.method == "GET" and ep.path.rstrip("/").endswith("me"):
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('get', ep.path)}_with_valid_token_returns_profile",
                    f"GET {ep.path} with a valid token returns the current user profile.",
                    "Auth",
                    Priority.HIGH,
                    ref,
                    [
                        ("action", "Log in to obtain a token"),
                        ("action", f"Send GET {ep.path} with Authorization: Bearer <token>"),
                        ("assertion", "Expect HTTP 200 and a user object"),
                    ],
                )
            )
        elif ep.method == "GET" and _has_id_param(ep):
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('get', ep.path)}_with_valid_id_returns_resource",
                    f"GET {ep.path} with a valid id returns 200 and the {res} record.",
                    category,
                    Priority.MEDIUM,
                    ref,
                    [
                        ("action", "Log in and create a record to read"),
                        ("action", f"Send authenticated GET {ep.path}"),
                        ("assertion", "Expect HTTP 200 and the record body"),
                    ],
                )
            )
        elif ep.method == "GET":
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('get', ep.path)}_with_valid_token_returns_list",
                    f"GET {ep.path} with a valid token returns 200 and a collection.",
                    category,
                    Priority.MEDIUM,
                    ref,
                    [
                        ("action", "Log in to obtain a token"),
                        ("action", f"Send authenticated GET {ep.path}"),
                        ("assertion", "Expect HTTP 200 and a JSON array/list"),
                    ],
                )
            )
        elif ep.method == "POST":
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('post', ep.path)}_with_valid_data_creates_resource",
                    f"POST {ep.path} with valid data creates a {res} and returns 2xx.",
                    category,
                    Priority.HIGH,
                    ref,
                    [
                        ("action", "Log in to obtain a token"),
                        ("action", f"Send authenticated POST {ep.path} with a valid payload"),
                        ("assertion", "Expect HTTP 200/201 and the created record"),
                    ],
                )
            )
        elif ep.method == "PUT" or ep.method == "PATCH":
            cases.append(
                _case(
                    next_id(),
                    f"{_slug(ep.method.lower(), ep.path)}_with_valid_data_updates_resource",
                    f"{ep.method} {ep.path} updates an existing {res} and returns 200.",
                    category,
                    Priority.MEDIUM,
                    ref,
                    [
                        ("action", "Log in and create a record to update"),
                        ("action", f"Send authenticated {ep.method} {ep.path} with updated fields"),
                        ("assertion", "Expect HTTP 200 and the updated record"),
                    ],
                )
            )
        elif ep.method == "DELETE":
            cases.append(
                _case(
                    next_id(),
                    f"{_slug('delete', ep.path)}_with_valid_id_deletes_resource",
                    f"DELETE {ep.path} removes an existing {res} and returns 200.",
                    category,
                    Priority.MEDIUM,
                    ref,
                    [
                        ("action", "Log in and create a record to delete"),
                        ("action", f"Send authenticated DELETE {ep.path}"),
                        ("assertion", "Expect HTTP 200"),
                    ],
                )
            )

    return cases


__all__ = ["generate_backend_plan"]
