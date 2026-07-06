---
title: CI with the GitHub Action
description: Run Suitest in GitHub Actions, gate merges on exit codes, and get one self-updating PR comment with per-failure excerpts.
---

The Suitest GitHub Action runs your test suite in CI and posts the result,
with a failure excerpt per broken case, as a single self-updating comment on
the pull request. The job's exit code drives the merge gate. Under the hood it
is a composite action that sets up Node and Python and runs
`npx -y @suiflex/suitest-mcp ci`, the same lifecycle your IDE agent runs
through `run_tests`.

## Full workflow example

You start your own app; the action only runs the tests and reports.

```yaml
name: suitest
on: pull_request
permissions:
  pull-requests: write   # required for the PR comment
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run start &          # your app, your responsibility
      - run: npx wait-on http://localhost:3000
      - uses: suiflex/suitest-action@v1
        with:
          config: suitest.config.json
          api-url: ${{ vars.SUITEST_API_URL }}
          api-key: ${{ secrets.SUITEST_API_KEY }}
```

The action provisions Node 22 and Python 3.12, exports your inputs as
`SUITEST_API_URL`, `SUITEST_API_KEY`, and `GITHUB_TOKEN`, and runs the suite
against the config you point it at. See the
[configuration reference](/docs/reference/configuration/) for what goes in
`suitest.config.json`.

## Inputs

| Input | Default | Description |
|-------|---------|-------------|
| `config` | `suitest.config.json` | Path to the Suitest config |
| `api-url` | `""` | Suitest server URL. Empty means pure CI, no server |
| `api-key` | `""` | Suitest API key. Store it as a repository secret |

## Exit codes: the merge gate

| Code | Meaning | Effect |
|------|---------|--------|
| `0` | all tests passed | job green, merge allowed |
| `1` | at least one test failed | job red, blocks the merge |
| `2` | infra error: setup, config, or interpreter failed before tests ran | job red, investigate the workflow, not the app |

Exit `2` distinguishes "the app is broken" from "CI itself is broken": a
missing Python interpreter, a bad config, or a lifecycle failure that produced
no test results at all. A required status check on this job is all the branch
protection you need.

## The PR comment

One comment per PR, updated in place. The renderer embeds a hidden marker
(`<!-- suitest-report -->`) and the publisher looks for it to update the
existing comment instead of posting a new one, so re-runs never spam the
thread.

The comment contains:

- A headline with the pass count, a pass or fail icon, and the duration.
- A table with one row per case: title, status, evidence link (when a server
  is configured).
- A collapsed **Failure detail** section with an excerpt per failing case:
  the failed step, the error, and the trimmed DOM, console, and network
  context, budgeted at 1500 bytes per case.
- A link to the full report and videos on your Suitest server, when
  `api-url` is set.

:::tip
The 1500-byte excerpt is the short form of the same bundle
`get_failure_context` returns to agents, which is budgeted at 8 KB. When the
comment is not enough to diagnose, run the suite locally and pull the full
bundle. See [Failure context](/docs/guides/failure-context/).
:::

## Local preview with --dry-run

You can run the exact CI entry point locally and print the comment markdown
instead of publishing it:

```bash
npx -y @suiflex/suitest-mcp ci --config suitest.config.json --dry-run
```

Everything after `ci` passes straight through to the CI runner, so `--config`
and `--dry-run` behave identically in the workflow and on your laptop. The
exit code still reflects the run outcome, which makes this handy in pre-push
hooks too. The `ci` subcommand is documented with the rest of the CLI in the
[CLI reference](/docs/reference/cli/).

## Pure CI mode: no server

Leave `api-url` and `api-key` empty and the suite runs entirely inside the
job. The comment still renders the pass/fail table and per-failure excerpts;
what you lose is evidence links and the dashboard link, since videos and
screenshots have no server to live on.

With a server configured, every CI run also publishes cases, runs, and video
evidence into the web TCM, so CI failures are reviewable with full evidence
alongside runs from IDE agents. See
[the agent workflow](/docs/guides/agent-workflow/) for that side of the loop.

## Notes and troubleshooting

- `permissions: pull-requests: write` is required. The built-in
  `GITHUB_TOKEN` needs it to post and update the comment.
- Starting and readying your app (`npm run start &` plus `npx wait-on`) is
  your responsibility. If the app is not up when tests start, expect failures
  or exit `2` depending on how far the lifecycle got.
- If the forge is not recognized or no token is available, the comment
  markdown is printed to the job log instead of failing the run. Your gate
  still works; you just read the result in the log.
- The action runs on a forge-agnostic renderer: the comment is plain
  markdown, so the same `ci` entry point is usable outside GitHub by
  consuming the printed output.
- Config discovery, target startup, and readiness waits inside the run are
  the same as local runs; a config that works with `run_tests` in your IDE
  works unchanged in CI.
