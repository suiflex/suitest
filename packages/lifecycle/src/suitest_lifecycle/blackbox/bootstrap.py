"""Bootstrap wizard — the TestSprite-style "prompt → browser form" flow.

The ``bootstrap_project`` MCP tool spins up a tiny stdlib web server on a
random localhost port, opens the user's browser at a one-page setup form
(target URL, credentials, crawl scope, optional **markdown PRD upload**),
writes ``suitest.config.json`` (+ ``PRD.md``) into the project directory, then
shuts itself down and returns the config path to the agent — which continues
the pipeline (discover → generate → run → report) unattended.

Stdlib only: http.server + email.parser for the multipart form.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_FORM_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Suitest — Project Setup</title>
<style>
  :root {{ --bg:#0a0a0a; --card:#111; --line:#262626; --fg:#fafafa; --mut:#a3a3a3;
          --dim:#737373; --acc:#4ade80; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }}
  .wrap {{ max-width:640px; margin:48px auto; padding:0 20px; }}
  .logo {{ font-weight:700; font-size:18px; letter-spacing:-.02em; }}
  .logo span {{ color:var(--acc); }}
  h1 {{ font-size:22px; letter-spacing:-.01em; margin:24px 0 4px; }}
  p.sub {{ color:var(--mut); margin:0 0 24px; font-size:13px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:20px; margin-bottom:16px; }}
  .card h2 {{ font-size:13px; margin:0 0 12px; color:var(--fg); }}
  label {{ display:block; font-size:12px; color:var(--mut); margin:12px 0 4px; }}
  input[type=text],input[type=password],input[type=number] {{ width:100%; padding:9px 11px;
    background:var(--bg); border:1px solid var(--line); border-radius:7px; color:var(--fg);
    font-size:13px; outline:none; }}
  input:focus {{ border-color:var(--acc); }}
  .row {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .check {{ display:flex; gap:8px; align-items:center; margin-top:12px; font-size:13px;
           color:var(--mut); }}
  .check input {{ accent-color:var(--acc); }}
  .drop {{ border:1px solid var(--line); border-radius:8px; padding:18px; text-align:center;
          color:var(--dim); font-size:12.5px; background:var(--bg); }}
  button {{ width:100%; margin-top:8px; padding:12px; background:var(--acc); color:#052e12;
           font-weight:600; font-size:14px; border:0; border-radius:8px; cursor:pointer; }}
  button:hover {{ opacity:.9; }}
  .hint {{ color:var(--dim); font-size:11.5px; margin-top:4px; }}
</style></head>
<body><div class="wrap">
  <div class="logo">sui<span>test</span></div>
  <h1>Project setup</h1>
  <p class="sub">Blackbox UI testing (ZERO tier — deterministic, no LLM key needed).
     Project: <code>{project}</code></p>
  <form method="post" action="/submit" enctype="multipart/form-data">
    <div class="card">
      <h2>Target</h2>
      <label>Application URL *</label>
      <input type="text" name="targetUrl" placeholder="http://localhost:3000" required>
      <div class="row">
        <div><label>Login path</label>
          <input type="text" name="loginUrl" value="/login"></div>
        <div><label>Output directory</label>
          <input type="text" name="output" value="suitest-output"></div>
      </div>
    </div>
    <div class="card">
      <h2>Test credentials (optional — leave empty for public apps)</h2>
      <div class="row">
        <div><label>Username / email</label>
          <input type="text" name="username" placeholder="qa@example.com"></div>
        <div><label>Password</label>
          <input type="password" name="password"></div>
      </div>
    </div>
    <div class="card">
      <h2>Crawl scope</h2>
      <div class="row">
        <div><label>Max routes</label><input type="number" name="maxRoutes" value="30"></div>
        <div><label>Max depth</label><input type="number" name="maxDepth" value="3"></div>
      </div>
      <label>Exclude paths (comma separated)</label>
      <input type="text" name="exclude" value="/logout, /billing, /payment">
      <div class="check"><input type="checkbox" name="safeMode" checked>
        Safe mode — never click destructive actions (recommended)</div>
      <div class="check"><input type="checkbox" name="allowMutation">
        Allow mutating form submits (only with a resettable test database)</div>
    </div>
    <div class="card">
      <h2>Product spec (optional)</h2>
      <div class="drop">
        <input type="file" name="prd" accept=".md,.markdown"><br>
        Markdown PRD — with a workspace LLM configured, the plan becomes
        requirement-driven (TestSprite-style)
      </div>
      <div class="hint">Without a PRD the deterministic baseline suite is generated.</div>
    </div>
    <button type="submit">Save &amp; continue in your IDE</button>
  </form>
</div></body></html>"""

_DONE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<style>body{background:#0a0a0a;color:#fafafa;font:15px -apple-system,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.b{text-align:center}.t{color:#4ade80;font-size:40px}</style></head>
<body><div class="b"><div class="t">&#10003;</div>
<h2>Configuration saved</h2><p style="color:#a3a3a3">You can close this tab —
your IDE agent is continuing with discovery &rarr; tests &rarr; report.</p>
</div></body></html>"""


class _State:
    def __init__(self, project: Path) -> None:
        self.project = project
        self.done = threading.Event()
        self.result: dict[str, Any] = {}


def _parse_multipart(ctype: str, body: bytes) -> dict[str, tuple[str, bytes]]:
    """Return ``{field: (filename, value_bytes)}`` from a multipart POST."""
    msg = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body
    )
    out: dict[str, tuple[str, bytes]] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        out[str(name)] = (filename, payload)
    return out


def _build_config(fields: dict[str, tuple[str, bytes]], project: Path) -> dict[str, Any]:
    def val(key: str, default: str = "") -> str:
        return fields.get(key, ("", b""))[1].decode("utf-8", "replace").strip() or default

    target = val("targetUrl").rstrip("/")
    prd_name, prd_bytes = fields.get("prd", ("", b""))
    prd_rel = ""
    if prd_name and prd_bytes.strip():
        prd_rel = "PRD.md"
        (project / prd_rel).write_bytes(prd_bytes)

    config: dict[str, Any] = {
        "mode": "frontend",
        "projectName": project.name or "blackbox-project",
        "baseUrl": target,
        "output": val("output", "suitest-output"),
        "server": {"autostart": False},
        # Publishing is mandatory in the blackbox pipeline — the run stage
        # pushes into the Suitest TCM whenever the MCP server has credentials.
        "publish": {"enabled": True},
        "ui": {
            "mode": "blackbox",
            "targetUrl": target,
            "auth": {
                "strategy": "form",
                "loginUrl": val("loginUrl", "/login"),
                "username": val("username"),
                "password": val("password"),
            },
            "crawl": {
                "maxDepth": int(val("maxDepth", "3") or 3),
                "maxRoutes": int(val("maxRoutes", "30") or 30),
                "exclude": [x.strip() for x in val("exclude").split(",") if x.strip()],
                "safeMode": "safeMode" in fields,
            },
            "testGeneration": {"allowMutation": "allowMutation" in fields},
        },
    }
    if prd_rel:
        config["prdFile"] = prd_rel
    return config


def _make_handler(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # keep MCP stdio clean
            pass

        def _send(self, html: str, code: int = 200) -> None:
            data = html.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 — http.server API
            self._send(_FORM_HTML.format(project=state.project))

        def do_POST(self) -> None:  # noqa: N802 — http.server API
            length = int(self.headers.get("Content-Length", "0"))
            fields = _parse_multipart(self.headers.get("Content-Type", ""), self.rfile.read(length))
            config = _build_config(fields, state.project)
            config_path = state.project / "suitest.config.json"
            config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            state.result = {
                "configPath": str(config_path),
                "targetUrl": config["baseUrl"],
                "prdFile": config.get("prdFile", ""),
                "safeMode": config["ui"]["crawl"]["safeMode"],
            }
            self._send(_DONE_HTML)
            state.done.set()

    return Handler


def run_bootstrap_wizard(
    project_path: str | Path = ".",
    *,
    open_browser: bool = True,
    timeout_sec: int = 600,
    on_ready: Any = None,
) -> dict[str, Any]:
    """Serve the setup form; block until submitted (or timeout). Returns
    ``{configPath, targetUrl, prdFile, safeMode, url}``; empty dict on timeout.
    ``on_ready(url)`` is invoked once the server is listening (tests hook this).
    """
    project = Path(project_path).resolve()
    project.mkdir(parents=True, exist_ok=True)
    state = _State(project)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if on_ready is not None:
            on_ready(url)
        if open_browser:
            webbrowser.open(url)
        finished = state.done.wait(timeout=timeout_sec)
    finally:
        server.shutdown()
    if not finished:
        return {}
    return {**state.result, "url": url}


__all__ = ["run_bootstrap_wizard"]
