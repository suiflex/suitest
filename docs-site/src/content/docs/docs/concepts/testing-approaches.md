---
title: Black-box, gray-box, white-box
description: How Suitest separates what the tester can observe (black-box, gray-box, white-box) from test scope (unit to E2E), how the approach is resolved, and what each one changes in generation and reporting.
---

Suitest treats **what the tester can observe** and **how much of the system a
test covers** as two separate dimensions. Mixing them is what produces the
familiar lie of "we have repo access, so these are white-box tests" — access is
not observation.

| Dimension | Values |
|-----------|--------|
| Testing approach | `BLACK_BOX`, `GRAY_BOX`, `WHITE_BOX` |
| Test level | `UNIT`, `COMPONENT`, `INTEGRATION`, `SYSTEM`, `E2E` |

Every case and every result carries `testingApproach`, `testLevel`,
`framework`, and `strategyRef`, so a report never has to guess which one it is
looking at. The web UI shows approach badges and filters on the case list.

## What each approach means here

### Black-box — drive the running app, no source

You have a URL and test credentials; you may have no repository at all. The
crawler discovers routes, forms and auth flows from the DOM, and the generated
Playwright tests assert only what a user can observe.

Use it for staging environments, third-party or legacy apps, and acceptance
testing where the source deliberately stays out of scope.

→ [Blackbox testing from a URL](/docs/guides/blackbox-testing/)

### Gray-box — read the source, still test through the seams

The default when Suitest analyses a repository. Suitest reads your routes,
handlers, models and pages to decide **what is worth testing and where the risk
is**, then still drives the system through its public seams: HTTP requests,
the DOM, the database. Internals inform the plan; they are not the oracle.

This is the approach behind the normal agent workflow — `analyze_project` →
`generate_backend_tests` / `generate_frontend_tests` → `run_*`.

→ [Testing from your IDE agent](/docs/guides/agent-workflow/)

### White-box — run the repository's own tests

Suitest executes the unit and component tests that already live in your
repository, through a framework adapter, and normalizes their results and
coverage into the same cases, runs and evidence as everything else. Suitest
does not write these tests or impose a coverage percentage; it discovers,
executes and reports them.

→ [White-box testing with your own suite](/docs/guides/whitebox-testing/)

## How the approach is chosen

`testing.approach` in `suitest.config.json` accepts `auto`, `black-box`,
`gray-box`, or `white-box`.

With `auto` (the default), the resolution follows the **analysis source**:

| Analysis source | `auto` resolves to |
|-----------------|--------------------|
| `repo` (default) | `GRAY_BOX` |
| `openapi`, `postman`, `blackbox` / crawl, live UI | `BLACK_BOX` |

`WHITE_BOX` is never inferred — it is explicit, and it requires a compatible
local test framework. That asymmetry is deliberate: source availability must
not silently upgrade every test to "white-box", and repository access must not
silently claim coverage the tests do not have.

Precedence for a stored case is: **case override → suite default →
`BLACK_BOX`**.

```json
{
  "mode": "backend",
  "testing": {
    "approach": "gray-box",
    "level": "INTEGRATION"
  }
}
```

See [`suitest.config.json`](/docs/reference/configuration/#testing) for the full
block.

## The risk strategy behind every generation

Whatever the approach, generation writes a deterministic strategy file next to
the plan before anything runs:

```text
suitest-output/
└── backend|frontend/
    ├── standard_prd.json
    ├── suitest_<mode>_test_strategy.json
    ├── suitest_<mode>_test_plan.json
    └── ...
```

The strategy records access signals, risks and failure modes, assumptions,
oracles, coverage dimensions, exclusions, and QA checks — and each risk names
the approach recommended for it. At ZERO tier it is built deterministically;
with an LLM configured it can be enriched, but a human approves a version
before it becomes the project's approved strategy.

The QA checks encode the posture the generated suite is held to: question
unstated assumptions, prioritise impact over case count, require an observable
oracle per case, cover negative, boundary, permission, state, concurrency,
dependency, recovery and accessibility risks where relevant, reject duplicate
or brittle assertions, and record what was excluded and what risk remains.

## Choosing

| Situation | Approach |
|-----------|----------|
| No repository, only a URL and credentials | Black-box |
| You own the repo and want E2E/API coverage that survives refactors | Gray-box |
| You already have pytest / Vitest / Jest suites and want them in the TCM with coverage | White-box |
| Acceptance sign-off with a customer | Black-box, exported as a [UAT document](/docs/concepts/evidence/) |
