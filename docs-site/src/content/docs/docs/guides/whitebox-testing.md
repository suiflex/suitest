---
title: White-box testing with your own suite
description: Run the pytest, Vitest or Jest tests that already live in your repository through Suitest, and publish their results and coverage as normal cases and runs.
---

White-box mode does not generate tests. It **runs the suite you already have**
— pytest, Vitest or Jest — and publishes each native test as a case, with its
result, its source, and normalized coverage, into the same TCM as your
generated black-box and gray-box tests.

That gets your unit and component layer onto the same dashboard, traceability
matrix and reports as your E2E layer, without rewriting anything or adopting a
new runner.

The local contract is `suitest.whitebox.v1`.

## What you need

- A repository with tests the framework can already run on its own
- One of the reference adapters: **pytest**, **Vitest**, **Jest**
- No LLM, no API key — this is ZERO tier

If `<repo>/.venv` exists, the pytest adapter runs your tests with **that**
interpreter, so they import your dependencies. Suitest only provisions pytest
into its own environment when there is no project interpreter to use — it will
not install packages into your venv uninvited. The Node adapters shell out to
`npm exec`, which resolves your `node_modules`.

## Configure

```json
{
  "mode": "backend",
  "projectName": "example",
  "projectPath": ".",
  "baseUrl": "http://localhost",
  "server": { "autostart": false },
  "testing": {
    "approach": "white-box",
    "level": "UNIT",
    "framework": "pytest",
    "coverageFile": "coverage.json"
  },
  "output": "suitest-output"
}
```

`approach` must be `white-box` explicitly — it is never inferred from the fact
that Suitest can see your source. See
[Black-box, gray-box, white-box](/docs/concepts/testing-approaches/).

`framework` may be omitted; detection then falls back to the repository's own
signals:

| Detected from | Adapter |
|---------------|---------|
| `pyproject.toml` or `pytest.ini` | `pytest` |
| `vitest` in `package.json` | `vitest` |
| `jest` in `package.json` | `jest` |

If nothing matches, the run fails with `no white-box adapter detected; set
testing.framework to pytest, vitest, or jest` rather than guessing.

## Run it

From the CLI:

```bash
suitest test --config suitest.config.json
```

From an IDE agent, the same config drives two MCP tools:

| Tool | Does |
|------|------|
| `whitebox_discover_tests` | Lists the framework, the command it will run, the discovered test files and the coverage file — without executing anything |
| `whitebox_run_tests` | Executes them and publishes the run (forces `approach: white-box` regardless of the config) |

Discovery is the safe first call: it tells you exactly what would execute.

## What gets discovered

| Adapter | Test file patterns | Default coverage file |
|---------|--------------------|-----------------------|
| pytest | `test_*.py`, `*_test.py` | `coverage.json` |
| Vitest / Jest | `*.test.ts(x)`, `*.spec.ts(x)`, `*.test.js`, `*.spec.js` | `coverage/coverage-final.json` |

`.git`, `.venv`, `node_modules`, `dist`, `build` and `suitest-output` are
skipped. Each target is executed directly, without a shell.

Set `testing.coverageFile` to override the default path (relative paths resolve
against `projectPath`).

## What lands in Suitest

- One **case per native test target**, carrying the native source as its
  automation code, so the code is readable in the case detail view
- `testingApproach: WHITE_BOX`, plus `testLevel`, `framework` and `strategyRef`
  on every case and result — the case list can filter on the approach badge
- A **run** with per-test outcomes, published through the same
  `PublishSession` as every other run
- The coverage JSON uploaded as an artifact and its normalized summary stored
  on the run — coverage.py and Istanbul shapes are both understood

Coverage thresholds stay where they belong: in your repository's own
configuration. Suitest reports the number, it does not impose one.

## Mixing approaches in one project

Nothing stops a project from holding all three. A common split:

- white-box `UNIT` cases from your existing pytest suite
- gray-box `INTEGRATION` / `E2E` cases generated from the repo
- black-box `E2E` cases against staging, exported as the UAT document for
  sign-off

They share one traceability matrix, and every case says which approach it is,
so a coverage claim can always be traced back to what was actually observed.
