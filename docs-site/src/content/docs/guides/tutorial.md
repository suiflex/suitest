---
title: "Tutorial: your first run"
description: Author a case, run it through MCP, see the result.
---

1. **Create a project + suite** from the Test Cases screen.
2. **Author a case** with steps. Each step has an `action`, `expected`, an
   `mcp_provider` (e.g. `playwright-mcp`), and a `target_kind` (e.g. `FE_WEB`).
3. **Run it** — from the UI, or the CLI:

   ```bash
   suitest run --project <projectId> --case <caseId> --branch main --wait
   ```

4. **Inspect** logs + per-step screenshots in the run detail view. On failure a
   defect is filed automatically (rule-based at ZERO; AI-diagnosed at LOCAL/CLOUD).

See the [examples/](https://github.com/suitest-dev/suitest/tree/main/examples)
directory for Playwright, OpenAPI-contract, and mixed-MCP starting points.
