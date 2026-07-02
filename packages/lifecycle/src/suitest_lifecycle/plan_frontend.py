"""Deterministic frontend test-plan generator (ZERO tier).

Builds UI test cases from discovered pages: login happy/invalid, protected-route
redirect, dashboard/list render, create-via-form, search empty state, logout.
Each case's ``source_ref`` is ``fe:<archetype> <route>`` so the playwright
exporter can render the right script, and is traceable to a real page route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_lifecycle.models import CodeSummary, PlanCase, PlanStep, Priority

if TYPE_CHECKING:
    from suitest_lifecycle.config import Config


def _routes(summary: CodeSummary) -> dict[str, bool]:
    return {p.route: p.protected for p in summary.pages}


def _case(
    cid: str,
    title: str,
    desc: str,
    category: str,
    prio: Priority,
    ref: str,
    steps: list[tuple[str, str]],
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
        cases.append(
            _case(
                nid(),
                "login_with_empty_fields_shows_validation_error",
                "Submitting the login form with empty fields shows a validation error.",
                "Auth",
                Priority.MEDIUM,
                "fe:empty_login /login",
                [
                    ("action", "Navigate to /login"),
                    ("action", "Submit the form with both fields empty"),
                    ("assertion", "A validation error is shown and URL stays /login"),
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
        if has_login:
            cases.append(
                _case(
                    nid(),
                    "logout_returns_to_login_and_clears_session",
                    "Logging out returns to /login and protected routes redirect again.",
                    "Auth",
                    Priority.MEDIUM,
                    "fe:logout /dashboard",
                    [
                        ("action", "Log in"),
                        ("action", "Click the logout button"),
                        ("assertion", "Login page is shown"),
                        ("action", "Navigate to /dashboard again"),
                        ("assertion", "Still on the login page (session cleared)"),
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
                    "search_with_match_filters_the_product_list",
                    "Searching for an existing product narrows the list to that product.",
                    "Products",
                    Priority.MEDIUM,
                    "fe:search_match /products",
                    [
                        ("action", "Log in and create a uniquely-named product"),
                        ("action", "Open /products and search for that exact name"),
                        ("assertion", "Exactly the matching product row is shown"),
                    ],
                )
            )
            cases.append(
                _case(
                    nid(),
                    "delete_product_removes_it_from_the_list",
                    "Deleting a product removes its row from the list.",
                    "Products",
                    Priority.MEDIUM,
                    "fe:delete_product /products",
                    [
                        ("action", "Log in and create a uniquely-named product"),
                        (
                            "action",
                            "Search for it and click its delete button, accepting the confirm",
                        ),
                        ("assertion", "The product row disappears from the list"),
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
        cases.append(
            _case(
                nid(),
                "create_product_with_invalid_data_shows_validation_error",
                "Submitting the product form with invalid data keeps the user on the form.",
                "Products",
                Priority.MEDIUM,
                "fe:create_invalid /products/new",
                [
                    ("action", "Log in and open /products/new"),
                    ("action", "Fill a too-short name and no SKU, then submit"),
                    ("assertion", "Form stays visible with validation errors; no navigation"),
                ],
            )
        )

    return cases


__all__ = ["generate_frontend_plan"]
