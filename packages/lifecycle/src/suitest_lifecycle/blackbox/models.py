"""Serializable data model for the blackbox engine.

Everything round-trips through plain JSON (``to_json``/``from_json``) so the
same discovery artifact feeds Zero's deterministic generator, the MCP tools,
and (optionally) an LLM as reasoning context. Stdlib-only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# --------------------------------------------------------------------------- #
# DOM elements
# --------------------------------------------------------------------------- #


@dataclass
class ElementInfo:
    """One interactive element as captured from the live DOM.

    Carries every attribute the selector strategy can rank — the element is
    addressable even when the app has no ``data-testid`` convention at all.
    """

    tag: str = ""
    kind: str = ""  # input | button | link | select | textarea | checkbox | radio
    testid: str = ""  # data-testid | data-cy | data-test (first found)
    testid_attr: str = ""  # which attribute carried it
    role: str = ""  # explicit role attr or implicit (button/link/...)
    aria_label: str = ""
    label: str = ""  # associated <label> text
    placeholder: str = ""
    name: str = ""
    input_type: str = ""
    autocomplete: str = ""
    text: str = ""  # visible text (buttons/links)
    dom_id: str = ""
    href: str = ""
    css: str = ""  # stable-ish css path fallback
    required: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(raw: dict[str, Any]) -> ElementInfo:
        known = {f for f in ElementInfo.__dataclass_fields__}
        return ElementInfo(**{k: v for k, v in raw.items() if k in known})


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


@dataclass
class LoginForm:
    """Detected login form — locator EXPRESSIONS (Playwright, python) per part."""

    route: str = ""
    username: str = ""  # locator expression, e.g. page.get_by_label("Email")
    password: str = ""
    submit: str = ""
    remember: str = ""
    error: str = ""  # error region locator (may be empty until observed)

    def found(self) -> bool:
        return bool(self.username and self.password and self.submit)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(raw: dict[str, Any]) -> LoginForm:
        known = {f for f in LoginForm.__dataclass_fields__}
        return LoginForm(**{k: v for k, v in raw.items() if k in known})


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

PAGE_PATTERNS = (
    "login",
    "dashboard",
    "list",
    "detail",
    "form",
    "modal",
    "empty",
    "error",
    "forbidden",
    "not_found",
    "blank",
    "unknown",
)


@dataclass
class PageInfo:
    """One crawled route with its digest + evidence pointers."""

    route: str
    url: str = ""
    title: str = ""
    pattern: str = "unknown"  # one of PAGE_PATTERNS
    protected: bool = False
    depth: int = 0
    inputs: list[ElementInfo] = field(default_factory=list)
    buttons: list[ElementInfo] = field(default_factory=list)
    links: list[ElementInfo] = field(default_factory=list)
    nav_routes: list[str] = field(default_factory=list)  # internal hrefs found here
    testids: list[str] = field(default_factory=list)
    has_table: bool = False
    row_locator: str = ""  # repeated-row locator when a list/table was detected
    has_form: bool = False
    has_modal: bool = False
    search_locator: str = ""
    pagination_locator: str = ""
    console_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    screenshot: str = ""  # evidence path
    blank: bool = False
    visible_text_sample: str = ""

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["inputs"] = [e.to_json() for e in self.inputs]
        d["buttons"] = [e.to_json() for e in self.buttons]
        d["links"] = [e.to_json() for e in self.links]
        return d

    @staticmethod
    def from_json(raw: dict[str, Any]) -> PageInfo:
        known = {f for f in PageInfo.__dataclass_fields__}
        data = {k: v for k, v in raw.items() if k in known}
        for key in ("inputs", "buttons", "links"):
            data[key] = [ElementInfo.from_json(e) for e in raw.get(key, [])]
        return PageInfo(**data)


# --------------------------------------------------------------------------- #
# Discovery result (the engine's central artifact)
# --------------------------------------------------------------------------- #


@dataclass
class LoginProbe:
    """Outcome of actually performing the login during discovery."""

    attempted: bool = False
    success: bool = False
    landed_route: str = ""
    error_locator: str = ""  # observed error region on a failed probe
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(raw: dict[str, Any]) -> LoginProbe:
        known = {f for f in LoginProbe.__dataclass_fields__}
        return LoginProbe(**{k: v for k, v in raw.items() if k in known})


@dataclass
class DiscoveryResult:
    base_url: str = ""
    login: LoginForm | None = None
    login_probe: LoginProbe = field(default_factory=LoginProbe)
    pages: list[PageInfo] = field(default_factory=list)
    skipped_routes: list[str] = field(default_factory=list)  # safeMode / excluded
    errors: list[str] = field(default_factory=list)

    def page(self, route: str) -> PageInfo | None:
        for p in self.pages:
            if p.route == route:
                return p
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "baseUrl": self.base_url,
            "login": self.login.to_json() if self.login else None,
            "loginProbe": self.login_probe.to_json(),
            "pages": [p.to_json() for p in self.pages],
            "skippedRoutes": self.skipped_routes,
            "errors": self.errors,
        }

    @staticmethod
    def from_json(raw: dict[str, Any]) -> DiscoveryResult:
        return DiscoveryResult(
            base_url=str(raw.get("baseUrl", "")),
            login=LoginForm.from_json(raw["login"]) if raw.get("login") else None,
            login_probe=LoginProbe.from_json(raw.get("loginProbe", {})),
            pages=[PageInfo.from_json(p) for p in raw.get("pages", [])],
            skipped_routes=list(raw.get("skippedRoutes", [])),
            errors=list(raw.get("errors", [])),
        )


# --------------------------------------------------------------------------- #
# Config (suitest.config.json "ui" section)
# --------------------------------------------------------------------------- #


@dataclass
class BlackboxAuth:
    strategy: str = "form"
    login_url: str = "/login"
    username: str = ""
    password: str = ""


@dataclass
class BlackboxCrawl:
    max_depth: int = 3
    max_routes: int = 30
    max_actions_per_page: int = 20
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    safe_mode: bool = True
    # Validation aid: pretend the app has no data-testid convention so the
    # heuristic tiers (role/label/placeholder/name/text) get exercised.
    ignore_testids: bool = False


@dataclass
class BlackboxSelectors:
    """Optional manual overrides — locator expressions or raw CSS."""

    login_username: str = ""
    login_password: str = ""
    login_submit: str = ""


@dataclass
class BlackboxTestGeneration:
    include_smoke: bool = True
    include_auth: bool = True
    include_navigation: bool = True
    include_forms: bool = True
    include_tables: bool = True
    allow_mutation: bool = False


@dataclass
class BlackboxUiConfig:
    mode: str = "blackbox"
    target_url: str = ""
    auth: BlackboxAuth = field(default_factory=BlackboxAuth)
    crawl: BlackboxCrawl = field(default_factory=BlackboxCrawl)
    selectors: BlackboxSelectors = field(default_factory=BlackboxSelectors)
    test_generation: BlackboxTestGeneration = field(default_factory=BlackboxTestGeneration)
    headed: bool = False
    record_video: bool = True

    @staticmethod
    def from_raw(raw: dict[str, Any]) -> BlackboxUiConfig:
        auth = raw.get("auth") or {}
        crawl = raw.get("crawl") or {}
        selectors = raw.get("selectors") or {}
        gen = raw.get("testGeneration") or {}
        return BlackboxUiConfig(
            mode=str(raw.get("mode", "blackbox")),
            target_url=str(raw.get("targetUrl", "")).rstrip("/"),
            auth=BlackboxAuth(
                strategy=str(auth.get("strategy", "form")),
                login_url=str(auth.get("loginUrl", "/login")),
                username=str(auth.get("username", "")),
                password=str(auth.get("password", "")),
            ),
            crawl=BlackboxCrawl(
                max_depth=int(crawl.get("maxDepth", 3)),
                max_routes=int(crawl.get("maxRoutes", 30)),
                max_actions_per_page=int(crawl.get("maxActionsPerPage", 20)),
                include=[str(x) for x in crawl.get("include", [])],
                exclude=[str(x) for x in crawl.get("exclude", [])],
                safe_mode=bool(crawl.get("safeMode", True)),
                ignore_testids=bool(crawl.get("ignoreTestIds", False)),
            ),
            selectors=BlackboxSelectors(
                login_username=str(selectors.get("loginUsername", "")),
                login_password=str(selectors.get("loginPassword", "")),
                login_submit=str(selectors.get("loginSubmit", "")),
            ),
            test_generation=BlackboxTestGeneration(
                include_smoke=bool(gen.get("includeSmoke", True)),
                include_auth=bool(gen.get("includeAuth", True)),
                include_navigation=bool(gen.get("includeNavigation", True)),
                include_forms=bool(gen.get("includeForms", True)),
                include_tables=bool(gen.get("includeTables", True)),
                allow_mutation=bool(gen.get("allowMutation", False)),
            ),
            headed=bool(raw.get("headed", False)),
            record_video=bool(raw.get("recordVideo", True)),
        )
