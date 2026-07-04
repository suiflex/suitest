#!/usr/bin/env python3
"""Tiny stand-in for ``GET /api/v1/api-keys/whoami`` so CI can boot the MCP server.

``suitest_lifecycle.mcp_server`` refuses to start unless SUITEST_API_URL +
SUITEST_API_KEY verify against the whoami endpoint. CI has no live API, so the
boot-smoke steps run this stub and point SUITEST_API_URL at it. Accepts the key
from ``SUITEST_API_KEY`` (default ``sk_suitest_ci``) on 127.0.0.1:41999.
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

KEY = os.environ.get("SUITEST_API_KEY", "sk_suitest_ci")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        ok = (
            self.path == "/api/v1/api-keys/whoami"
            and self.headers.get("Authorization") == f"Bearer {KEY}"
        )
        body = b'{"workspaceId":"ci"}' if ok else b'{"detail":"invalid key"}'
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 41999), Handler).serve_forever()
