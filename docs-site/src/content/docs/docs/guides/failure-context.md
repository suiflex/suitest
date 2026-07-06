---
title: The failure context bundle
description: What get_failure_context returns, how its 8 KB byte budget works, and how an agent uses the bundle to fix failing code.
---

When a run fails, an agent needs enough context to fix the application code:
which step failed, what the error was, what the page actually looked like, and
what the app logged. It does not need a 40 MB trace or a video it cannot
watch. `get_failure_context` returns exactly that middle ground: a structured
markdown bundle per failed case, byte-budgeted to fit an agent context window.

## When to call it

Call `get_failure_context` whenever a run reports failing tests and you (or
your agent) intend to fix the code. The tool description says this verbatim,
so MCP agents pick it up on their own after a red `run_tests`. It never
re-runs anything: it reads the stored `reports/summary.json` from the last
local run.

- No prior run: an error envelope telling you to run the lifecycle first.
- Prior run with no failures: a success envelope with an empty
  `failure_context` and `failed_cases: 0`.
- Prior run with failures: the bundle.

## What it returns

The standard tool envelope, with the bundle in `data`:

```json
{
  "success": true,
  "summary": "2 failing case(s); context ready for repair",
  "data": {
    "failure_context": "## Test: user_can_submit_checkout ...",
    "failed_cases": 2
  },
  "artifacts": [],
  "errors": []
}
```

`failure_context` is one markdown document. Each failing case gets a section,
separated by `---`.

## What each case section contains

| Block | Content | Filter |
|-------|---------|--------|
| Heading | Case title, failing step index out of total, optional classification label such as `[STALE]` or `[FLAKE]` | first FAILED or ERROR step |
| **Step** | The failing step's description | |
| **Error** | The innermost error message (the last non-empty traceback line) | capped at 500 characters |
| **DOM at failure** | HTML excerpt clipped to the lines around the failed selector, plus 2 lines of context on each side | per-line caps so a minified monster line cannot bury the match |
| **Console** | Browser console output | errors and warnings only, last 20 lines |
| **Network** | Request log | non-2xx/3xx responses only, last 10, each with up to 400 characters of response body |
| **Evidence** | Links to the screenshot and video files | `file://` URIs; missing files are skipped, never fatal |

The DOM excerpt is selector-aware: the failed selector is split into tokens
(`#submit-btn` becomes `submit`, `btn`) and only lines containing those tokens,
plus nearby context, survive. That is what lets an agent see "the button is
still there, it just has a different id" without reading the whole page.

## The byte budget

The bundle is hard-capped at 8192 bytes by default. The cap is applied to the
encoded bytes, so multibyte content cannot smuggle the output over budget.

- The budget is split evenly across failing cases, with a floor of 1024 bytes
  per case.
- Within a case, the DOM excerpt gets at most a third of the case budget.

Many failures therefore mean shorter sections each, but every failing case is
always represented.

## Example output

The bundle for one failing case is shaped like this:

````markdown
## Test: user_can_submit_checkout (FAIL at step 3/6)

**Step 3/6**: Click the checkout submit button

**Error**: TimeoutError: locator("#submit-btn") not found after 15000ms

**DOM at failure** (excerpt):
```html
…
<form class="checkout-form">
  <button id="checkout-submit" class="btn-primary">Place order</button>
</form>
…
```

**Console** (error/warning only):
[error] Uncaught TypeError: Cannot read properties of null (reading 'submit')

**Network** (failures only):
POST http://localhost:3000/api/checkout -> 500 {"error":"cart is empty"}

**Evidence**: [screenshot](file:///.../TC003.png) · [video](file:///.../TC003.webm)
````

An agent reading this sees the whole story at once: the test looked for
`#submit-btn`, the DOM shows the button now renders as `#checkout-submit`, the
console shows a null reference, and the API returned a 500. That is enough to
decide whether the fix belongs in the app code, the markup, or the test.

## Where the data comes from

- **Source of truth**: `reports/summary.json` under the config's output
  directory, written by the last run. Only FAILED and ERROR cases are
  included.
- **Evidence links**: the run's screenshot and video file names, resolved to
  absolute `file://` URIs. A missing file drops that link rather than raising;
  a partial bundle beats no bundle.
- **DOM, console, network**: an optional `<TC>.context.json` sidecar per test,
  written by the frontend recorder when evidence recording is enabled. Without
  the sidecar those blocks are simply absent and the bundle still carries the
  step, error, and evidence links.

See [Evidence](/docs/concepts/evidence/) for how runs capture screenshots,
videos, and step results in the first place.

## How an agent uses it

The closed loop from [the agent workflow](/docs/guides/agent-workflow/):

```text
run_tests            -> success=false, 2 failed
get_failure_context  -> bundle above
edit the app code    -> restore the stable id, fix the null access
run_tests            -> success=true
```

Because the bundle is plain markdown inside a JSON envelope, the agent does
not parse screenshots or scrub videos. It reads the excerpt, maps the failed
selector to the actual DOM, and edits the code. The evidence links stay
available for a human to verify the fix visually.

:::note
The same renderer powers the CI PR comment, with a smaller budget of 1500
bytes per failing case. The comment shows the short excerpt; the full 8 KB
bundle is always available via `get_failure_context`. See
[CI with the GitHub Action](/docs/guides/ci-github-action/).
:::

## Edge cases worth knowing

- **Classification labels**: when the run data classified a failure (for
  example STALE for a case whose target changed underneath it), the label is
  appended to the case heading, so agents can deprioritize flaky or stale
  cases before touching code.
- **No selector, no tokens**: if the failed selector yields no usable tokens,
  the DOM block falls back to the head of the document up to the budget.
- **Backend runs**: the bundle works for any mode; DOM, console, and network
  blocks appear only when a sidecar exists, which is a frontend recorder
  feature.
