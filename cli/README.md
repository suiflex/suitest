# suitest (CLI)

Command-line interface for [Suitest](https://suitest.dev), built on `suitest-sdk`.

```bash
pip install suitest-cli
export SUITEST_API_URL=https://suitest.example
export SUITEST_TOKEN=...           # bearer token
export SUITEST_WORKSPACE_ID=ws_1

suitest cases list
suitest mcp ls
suitest run --project prj_1 --case case_1 --branch main --wait
```

Exit code is non-zero on API error (and on a failed run with `--wait`), so it
composes in CI. Licensed Apache-2.0.
