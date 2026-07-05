# Suitest GitHub Action

Run Suitest E2E/API tests in CI and post the pass/fail result — with a failure
excerpt per broken case — as a single, self-updating comment on the pull
request. The comment is **upserted** by a hidden marker, so re-runs edit the same
comment instead of spamming new ones. The job's exit code drives the merge gate.

## Usage

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
      - run: npm ci && npm run start &   # your app — your responsibility
      - run: npx wait-on http://localhost:3000
      - uses: suiflex/suitest-action@v1
        with:
          api-url: ${{ vars.SUITEST_API_URL }}
          api-key: ${{ secrets.SUITEST_API_KEY }}
```

## Inputs

| Input     | Default                | Description                                          |
|-----------|------------------------|------------------------------------------------------|
| `config`  | `suitest.config.json`  | Path to the Suitest config.                          |
| `api-url` | `""`                   | Suitest server URL. Empty = pure CI, no server.      |
| `api-key` | `""`                   | Suitest API key (store as a secret).                 |

## Exit codes (merge gate)

`0` = all tests passed · `1` = a test failed (blocks the merge) · `2` = infra
error (setup/config failed before tests ran).

## Notes

- `permissions: pull-requests: write` is required — the built-in `GITHUB_TOKEN`
  needs it to post/update the comment.
- Starting and readying your app (`npm run start &` + `wait-on`) is your
  responsibility; the action only runs the tests and reports.
- In pure-CI mode (no `api-url`), evidence videos aren't linked — the comment
  still renders the pass/fail table and failure excerpts.
- Cross-repo consumption needs a standalone public repo (`suiflex/suitest-action`)
  holding a copy of `action.yml`; this folder is the source of truth.
