# Brewly — Suitest demo target

Tiny coffee-shop order app used by the 30-second demo (`make demo`). It is a
**fixture, not a product**: in-memory state, no auth, deterministic seed data.

| File | Purpose |
|------|---------|
| `app.py` | FastAPI app — menu, orders, stock validation, bulk discount, static UI |
| `static/index.html` | Storefront UI (order flow used by the FE_WEB demo case) |
| `PRD.md` | The product requirements document used as AI-generation input |
| `suite.json` | Committed AI-generation output — the suite `demo-seed` imports |
| `Dockerfile` | `demo-app` compose service image |

## Run standalone

```bash
docker build -t brewly . && docker run -p 8089:8089 brewly
# UI:      http://localhost:8089
# OpenAPI: http://localhost:8089/openapi.json
```

## Tests

```bash
PYTHONPATH=. uvx --with fastapi --with httpx pytest test_app.py
```

## Determinism

`POST /api/reset` restores seed data (4 items, stock 10 each) so demo runs are
repeatable.
