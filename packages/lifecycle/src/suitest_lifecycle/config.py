"""``suitest.config.json`` — the lifecycle front-door.

Mirrors the TestSprite *Testing Configuration* screen (mode / scope / auth /
local server port / PRD) and adds the two pieces TestSprite hides behind its
cloud: an explicit **server start command** (Suitest spawns the target) and an
explicit **readiness probe**.

The file is plain JSON so non-Python users can author it. This module parses it
into typed dataclasses with sane defaults and clear validation errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from suitest_lifecycle.models import Mode


class ConfigError(ValueError):
    """Raised when ``suitest.config.json`` is missing required fields."""


@dataclass
class AuthConfig:
    type: str = "none"  # none | bearer | basic
    login_path: str = "/api/auth/login"
    username: str = ""
    password: str = ""
    token_field: str = "token"  # JSON field holding the bearer token in login response
    username_field: str = "email"  # request-body key for the username/email
    password_field: str = "password"  # request-body key for the password


@dataclass
class ServerConfig:
    autostart: bool = True
    start_command: str = ""  # e.g. "npm run dev"; empty + autostart=True -> error
    cwd: str = "."  # relative to project_path
    ready_timeout_sec: int = 60
    ready_log_pattern: str = ""  # optional substring/regex in stdout marking ready
    env: dict[str, str] = field(default_factory=dict)
    stop_grace_sec: int = 5


@dataclass
class DependencyConfig:
    """A supporting service to start before the main target (e.g. the backend a
    frontend run depends on for login/API). Started + readiness-gated in order,
    torn down after the run."""

    name: str
    start_command: str
    cwd: Path  # absolute
    base_url: str
    ready_path: str
    port: int
    ready_timeout_sec: int = 60
    ready_log_pattern: str = ""
    env: dict[str, str] = field(default_factory=dict)
    stop_grace_sec: int = 5

    @property
    def ready_url(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.ready_path.lstrip("/")


@dataclass
class PublishConfig:
    """Publish lifecycle results into a running Suitest (Approach A / REST ingest)."""

    enabled: bool = False
    api_url: str = "http://localhost:4000"
    token: str = ""
    workspace_id: str = ""
    project_id: str = ""
    suite_name: str = ""


@dataclass
class Config:
    mode: Mode
    project_name: str
    project_path: Path  # absolute, resolved
    base_url: str  # e.g. http://localhost:4000
    api_base_path: str = "/api"  # backend only
    ready_path: str = ""  # readiness probe path; default derived per mode
    port: int = 0  # derived from base_url if 0
    scope: str = "codebase"  # codebase | diff
    # Where test discovery comes from:
    #   repo    — static source analysis (needs the project checkout)
    #   openapi — fetch/read an OpenAPI spec (no repo; backend)
    #   postman — read a Postman v2 collection (no repo; backend)
    #   crawl   — live DOM crawl (no repo; frontend)
    analysis_source: str = "repo"
    openapi_url: str = ""  # path/URL to openapi.json (analysis_source=openapi)
    openapi_file: str = ""  # local OpenAPI file (relative to config)
    postman_file: str = ""  # local Postman v2 collection (relative to config)
    auth: AuthConfig = field(default_factory=AuthConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    dependencies: list[DependencyConfig] = field(default_factory=list)
    test_ids: list[str] = field(default_factory=list)  # empty = all
    additional_instruction: str = ""
    enrich: bool = False  # LLM enrichment (real provider via the Suitest LLM proxy when reachable)
    # Blackbox DOM engine ("ui" section) — no-repo frontend testing from a URL
    # + credentials. Parsed into suitest_lifecycle.blackbox.models.BlackboxUiConfig;
    # kept as `object` here so the stdlib-only core has no import-order coupling.
    ui: object | None = None
    # Uploaded product spec (markdown, TestSprite-parity flow). When set and an
    # LLM bridge is reachable, the plan is PRD-driven on top of the baseline.
    prd_file: str = ""
    # Frontend codegen strategy:
    #   auto          — deterministic archetypes first; LLM writes the body for
    #                   cases no archetype supports (requires the LLM proxy).
    #   llm           — LLM writes EVERY frontend test body (TestSprite-style;
    #                   arbitrary apps, no data-testid convention needed).
    #   deterministic — archetypes only (ZERO baseline; unknown cases fail loud).
    codegen: str = "auto"
    publish: PublishConfig = field(default_factory=PublishConfig)
    output_dir: Path = field(default_factory=lambda: Path("suitest-output"))
    config_path: Path = field(default_factory=lambda: Path("suitest.config.json"))

    @property
    def api_url(self) -> str:
        """Base URL including the api prefix (backend), e.g. .../api."""
        return self.base_url.rstrip("/") + "/" + self.api_base_path.strip("/")


def _require(data: dict[str, object], key: str) -> object:
    if key not in data:
        raise ConfigError(f"suitest.config.json: missing required key '{key}'")
    return data[key]


def _port_from_url(url: str) -> int:
    tail = url.rsplit(":", 1)[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return int(digits) if digits else (443 if url.startswith("https") else 80)


def load_config(path: str | Path) -> Config:
    """Load and validate a ``suitest.config.json`` into a :class:`Config`."""
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.is_file():
        raise ConfigError(f"config not found: {cfg_path}")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("suitest.config.json must be a JSON object")

    mode = Mode(str(_require(raw, "mode")).lower())
    base_dir = cfg_path.parent

    analysis_source = str(raw.get("analysisSource", "repo")).lower()
    ui_raw = raw.get("ui")
    ui_cfg = None
    if isinstance(ui_raw, dict):
        from suitest_lifecycle.blackbox.models import BlackboxUiConfig

        ui_cfg = BlackboxUiConfig.from_raw(ui_raw)
        # A "ui.mode: blackbox" section IS the analysis source for frontend runs
        # unless the config explicitly pinned another one.
        if mode is Mode.FRONTEND and "analysisSource" not in raw and ui_cfg.mode == "blackbox":
            analysis_source = "blackbox"
    openapi_url = str(raw.get("openapiUrl", ""))
    openapi_file = str(raw.get("openapiFile", ""))
    postman_file = str(raw.get("postmanFile", ""))

    # Repo mode needs the checkout; no-repo modes don't (discovery is from the
    # live service / a spec), so projectPath becomes optional then.
    project_path_raw = str(raw.get("projectPath", "."))
    project_path = (base_dir / project_path_raw).resolve()
    if analysis_source == "repo" and not project_path.is_dir():
        raise ConfigError(f"projectPath does not exist: {project_path}")

    # HARD RULE: a backend without the repo MUST bring an API contract —
    # OpenAPI or a Postman collection. Black-box-from-URL-only is not enough to
    # generate reliable backend tests.
    if mode is Mode.BACKEND and analysis_source != "repo":
        if not (openapi_url or openapi_file or postman_file):
            raise ConfigError(
                "no-repo backend requires an API contract: set one of "
                "'openapiUrl', 'openapiFile', or 'postmanFile'"
            )

    if "baseUrl" not in raw and ui_cfg is not None and ui_cfg.target_url:
        raw = {**raw, "baseUrl": ui_cfg.target_url}
    base_url = str(_require(raw, "baseUrl")).rstrip("/")
    if ui_cfg is not None and not ui_cfg.target_url:
        ui_cfg.target_url = base_url

    auth_raw = raw.get("auth", {})
    auth = AuthConfig()
    if isinstance(auth_raw, dict):
        auth = AuthConfig(
            type=str(auth_raw.get("type", "none")),
            login_path=str(auth_raw.get("loginPath", auth.login_path)),
            username=str(auth_raw.get("username", "")),
            password=str(auth_raw.get("password", "")),
            token_field=str(auth_raw.get("tokenField", auth.token_field)),
            username_field=str(auth_raw.get("usernameField", "email")),
            password_field=str(auth_raw.get("passwordField", "password")),
        )

    server_raw = raw.get("server", {})
    server = ServerConfig()
    if isinstance(server_raw, dict):
        env_raw = server_raw.get("env", {})
        env: dict[str, str] = {}
        if isinstance(env_raw, dict):
            env = {str(k): str(v) for k, v in env_raw.items()}
        server = ServerConfig(
            autostart=bool(server_raw.get("autostart", True)),
            start_command=str(server_raw.get("startCommand", "")),
            cwd=str(server_raw.get("cwd", ".")),
            ready_timeout_sec=int(server_raw.get("readyTimeoutSec", 60)),
            ready_log_pattern=str(server_raw.get("readyLogPattern", "")),
            env=env,
            stop_grace_sec=int(server_raw.get("stopGraceSec", 5)),
        )
    if server.autostart and not server.start_command:
        raise ConfigError(
            "server.autostart is true but server.startCommand is empty — "
            "set a start command (e.g. 'npm run dev') or autostart=false"
        )

    dependencies: list[DependencyConfig] = []
    deps_raw = raw.get("dependencies", [])
    if isinstance(deps_raw, list):
        for entry in deps_raw:
            if not isinstance(entry, dict):
                continue
            dep_cmd = str(entry.get("startCommand", ""))
            if not dep_cmd:
                raise ConfigError("dependencies[].startCommand is required")
            dep_base = str(entry.get("baseUrl", "")).rstrip("/")
            if not dep_base:
                raise ConfigError("dependencies[].baseUrl is required")
            dep_cwd = (base_dir / str(entry.get("cwd", "."))).resolve()
            dep_env_raw = entry.get("env", {})
            dep_env = (
                {str(k): str(v) for k, v in dep_env_raw.items()}
                if isinstance(dep_env_raw, dict)
                else {}
            )
            dependencies.append(
                DependencyConfig(
                    name=str(entry.get("name", dep_cwd.name)),
                    start_command=dep_cmd,
                    cwd=dep_cwd,
                    base_url=dep_base,
                    ready_path=str(entry.get("readyPath", "/")),
                    port=int(entry.get("port", 0) or 0) or _port_from_url(dep_base),
                    ready_timeout_sec=int(entry.get("readyTimeoutSec", 60)),
                    ready_log_pattern=str(entry.get("readyLogPattern", "")),
                    env=dep_env,
                    stop_grace_sec=int(entry.get("stopGraceSec", 5)),
                )
            )

    publish = PublishConfig()
    pub_raw = raw.get("publish", {})
    if isinstance(pub_raw, dict):
        publish = PublishConfig(
            enabled=bool(pub_raw.get("enabled", False)),
            api_url=str(pub_raw.get("apiUrl", "http://localhost:4000")).rstrip("/"),
            token=str(pub_raw.get("token", "")),
            workspace_id=str(pub_raw.get("workspaceId", "")),
            project_id=str(pub_raw.get("projectId", "")),
            suite_name=str(pub_raw.get("suiteName", "")),
        )

    ids_raw = raw.get("testIds", [])
    test_ids = [str(x) for x in ids_raw] if isinstance(ids_raw, list) else []

    ready_path = str(raw.get("readyPath", ""))
    if not ready_path:
        ready_path = "/api/health" if mode is Mode.BACKEND else "/"

    output_raw = str(raw.get("output", "suitest-output"))
    output_dir = (base_dir / output_raw).resolve()

    port_raw = int(raw.get("port", 0) or 0)
    port = port_raw or _port_from_url(base_url)

    return Config(
        mode=mode,
        project_name=str(raw.get("projectName", project_path.name)),
        project_path=project_path,
        base_url=base_url,
        api_base_path=str(raw.get("apiBasePath", "/api")),
        ready_path=ready_path,
        port=port,
        scope=str(raw.get("scope", "codebase")),
        analysis_source=analysis_source,
        openapi_url=openapi_url,
        openapi_file=str((base_dir / openapi_file).resolve()) if openapi_file else "",
        postman_file=str((base_dir / postman_file).resolve()) if postman_file else "",
        auth=auth,
        server=server,
        dependencies=dependencies,
        test_ids=test_ids,
        additional_instruction=str(raw.get("additionalInstruction", "")),
        enrich=bool(raw.get("enrich", False)),
        ui=ui_cfg,
        prd_file=str((base_dir / str(raw["prdFile"])).resolve()) if raw.get("prdFile") else "",
        codegen=str(raw.get("codegen", "auto")).lower(),
        publish=publish,
        output_dir=output_dir,
        config_path=cfg_path,
    )
