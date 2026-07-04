---
title: CLI
description: The suitest command-line interface.
---

```bash
pip install suiflex-suitest-cli
export SUITEST_API_URL=https://suitest.example
export SUITEST_TOKEN=...
export SUITEST_WORKSPACE_ID=ws_1

suitest cases list
suitest mcp ls
suitest run --project prj_1 --case case_1 --branch main --wait
```

Exit code is non-zero on API error or a failed run (`--wait`), so it composes in
CI pipelines.
