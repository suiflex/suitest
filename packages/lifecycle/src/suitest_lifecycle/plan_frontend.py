"""Deterministic frontend test-plan generator (ZERO tier).

Builds UI test cases from discovered pages: login happy/invalid, protected-route
redirect, dashboard/list render, create-via-form, search empty state, logout.
Each case's ``source_ref`` is ``fe:<archetype> <route>`` so the playwright
exporter can render the right script, and is traceable to a real page route.
"""

from __future__ import annotations

from suitest_lifecycle.config import Config
from suitest_lifecycle.models import CodeSummary, PlanCase, PlanStep, Priority


def _routes(summary: CodeSummary) -> dict[str, bool]:
    return {p.route: p.protected for p in summary.pages}


def _case(
    cid: str, title: str, desc: str, category: str, prio: Priority, ref: str, steps: list[tuple[str, str]]
) -> PlanCase:
    return PlanCase(
        id=cid,
        title=title,
        description=desc,
        category=category,
        priority=prio,
        source_ref=ref,
        steps=[PlanStep(type=t, description=d) for t, d in steps],
    )


def generate_frontend_plan(summary: CodeSummary, config: Config) -> list[PlanCase]:
    routes = _routes(summary)
    has_login = "/login" in routes
    protected = [r for r, prot in routes.items() if prot]
    cases: list[PlanCase] = []
    n = 0

    def nid() -> str:
        nonlocal n
        n += 1
        return f"TC{n:03d}"

    if has_login:
        cases.append(
            _case(
                nid(),
                "successful_login_opens_the_dashboard",
                "Valid credentials log in and land on the dashboard.",
                "Auth",
                Priority.HIGH,
                "fe:login_success /login",
                [
                    ("action", "Navigate to /login"),
                    ("action", "Fill email and password and submit"),
                    ("assertion", "Dashboard page is visible"),
                ],
            )
        )
        cases.append(
            _case(
                nid(),
                "invalid_login_shows_an_error",
                "Wrong credentials keep the user on login with an error.",
                "Auth",
                Priority.MEDIUM,
                "fe:invalid_login /login",
                [
                    ("action", "Navigate to /login"),
                    ("action", "Submit an invalid password"),
                    ("assertion", "An error message is shown and URL stays /login"),
                ],
            )
        )

    if protected:
        target = "/products" if "/products" in routes else protected[0]
        cases.append(
            _case(
                nid(),
                "protected_route_redirects_anonymous_to_login",
                f"Visiting {target} unauthenticated redirects to /login.",
                "Auth",
                Priority.HIGH,
                f"fe:protected_redirect {target}",
                [
                    ("action", f"Navigate directly to {target} with no session"),
                    ("assertion", "Login page is shown"),
                ],
            )
        )

    if "/dashboard" in routes:
        cases.append(
            _case(
                nid(),
                "dashboard_shows_summary_after_login",
                "After login the dashboard renders its summary cards.",
                "Dashboard",
                Priority.MEDIUM,
                "fe:dashboard_loads /dashboard",
                [
                    ("action", "Log in"),
                    ("assertion", "Dashboard summary is visible"),
                ],
            )
        )

    if "/products" in routes:
        cases.append(
            _case(
                nid(),
                "products_list_loads_after_login",
                "Authenticated user can open the products list.",
                "Products",
                Priority.MEDIUM,
                "fe:products_list /products",
                [
                    ("action", "Log in and go to /products"),
                    ("assertion", "Products page is visible"),
                ],
            )
        )
        cases.append(
            _case(
                nid(),
                "search_with_no_match_shows_empty_state",
                "Searching for a non-existent product shows an empty state.",
                "Products",
                Priority.LOW,
                "fe:search_empty /products",
                [
                    ("action", "Log in, open /products, type an unlikely query"),
                    ("assertion", "Empty state is visible"),
                ],
            )
        )

    if "/products/new" in routes:
        cases.append(
            _case(
                nid(),
                "create_product_via_form_returns_to_list",
                "Filling the product form creates a product and returns to the list.",
                "Products",
                Priority.HIGH,
                "fe:create_product /products/new",
                [
                    ("action", "Log in and open /products/new"),
                    ("action", "Fill required fields and submit"),
                    ("assertion", "Returns to the products list"),
                ],
            )
        )

    return cases


__all__ = ["generate_frontend_plan"]
