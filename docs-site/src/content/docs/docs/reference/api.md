---
title: API reference
description: The Suitest REST API.
---

The API is documented by an OpenAPI 3 schema served live by your instance:

- Schema: `GET /openapi.json`
- Interactive docs: `/docs` (Swagger UI)

The official [Python SDK](https://github.com/suiflex/suitest/tree/main/sdk/python)
and [TypeScript SDK](https://github.com/suiflex/suitest/tree/main/sdk/typescript)
track this schema. Authenticate with a bearer token and scope requests with the
`X-Workspace-Id` header.
