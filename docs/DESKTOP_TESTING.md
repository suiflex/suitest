# Desktop Testing (M14) — Design, slint-mcp and tauri-mcp Contracts

> Cross-links: [MCP_PLUGINS.md](./MCP_PLUGINS.md), [ROADMAP.md](./ROADMAP.md),
> [DATA_MODEL.md](./DATA_MODEL.md), [DEPLOYMENT.md](./DEPLOYMENT.md),
> [ARCHITECTURE.md](./ARCHITECTURE.md), [BLACKBOX_UI_TESTING.md](./BLACKBOX_UI_TESTING.md).
>
> Companion example: [`examples/slint-demo/`](../examples/slint-demo/).

This doc defines the **M14 desktop-testing milestone** (M14-1 .. M14-3) and the
**slint-mcp wire contract** that any external runner binary must implement so a
Slint desktop app can be automated the way Playwright automates the browser DOM.

---

## 1. Goal & non-goals

**Goal.** Let a Suitest case target a *desktop* application (`target_kind =
FE_DESKTOP`) and drive it with typed MCP tools — click, type, read state,
assert text/visibility/value — exactly as browser steps drive the DOM.

**Non-goals (this milestone).**
- No OS-level window automation of *arbitrary* native apps (covered by M14-1
  computer-use for screen-level fallback).
- No modification of the target app's source. The driver speaks to the running
  app through Slint's accessibility surface; instrumentation hooks are optional
  and opt-in (see [§4.2](#42-property-bridge-os-and-slint-only)).
- No bundling of the external runner binaries into the Suitest image.

---

## 2. Four backends (M14-1 .. M14-3, plus Tauri)

Desktop automation is not one problem. Suitest ships **four provider configs**
in `builtin_specs.py`. Two name external binaries resolved at runtime via
`command_pin` (they stay **outside the image** — see
[DEPLOYMENT.md](./DEPLOYMENT.md)) and are **not implemented in this repo**;
`slint-mcp` and `tauri-mcp` need no binary at all and are bundled in-process.

| ID | M14 item | Driver | Transport | Best for |
|----|----------|--------|-----------|----------|
| `computer-use-mcp` | **M14-1** | Screen pixels + OS input | stdio, `command_pin` | Any legacy/native app; last-resort fallback |
| `electron-mcp` | **M14-2** | Chrome DevTools Protocol inside Electron (Playwright `_electron`) | stdio, `command_pin` | Electron apps with real DOM |
| `slint-mcp` | **M14-3** | Slint's own embedded MCP server | **bundled, in-process** | Slint apps (Rust, cross-platform, optionally headless) |
| `tauri-mcp` | — | W3C WebDriver served inside the app (`tauri-plugin-wdio-webdriver`) | **bundled, in-process** | Tauri 2 apps on Windows, Linux **and macOS** |

> **`slint-mcp` changed shape after this document was first written.** It was
> specified as an external `slint-mcp` binary, and no such binary was ever
> built. Slint 1.17 made one unnecessary: the framework embeds an MCP server
> *inside the application under test*, reachable over HTTP when the app runs
> with `SLINT_MCP_PORT` and is built with `--features slint/mcp`. The provider
> is therefore a **bridge** — `suitest_mcp.bundled.slint` — that owns the app
> process and maps the `slint.*` contract below onto the app's own tools
> (`find_elements_by_id`, `click_element`, `set_element_value`,
> `dispatch_key_event`, `take_screenshot`, …). The contract is what keeps test
> steps stable when Slint renames its surface.
>
> `SLINT_EMIT_DEBUG_INFO=1` is required: it is what keeps element ids in the
> compiled UI. `slint.screenshot` returns an MCP image block, which the runner
> stores as a `SCREENSHOT` artifact.

### 2.1 Routing & default

`routing.py` maps `TargetKind.FE_DESKTOP` to `computer-use-mcp` as the default.
Steps that need structure pin a more specific provider:

```python
DEFAULT_ROUTING = {
    ...
    TargetKind.FE_DESKTOP: ("computer-use-mcp", None),  # default = screen-level
}
```

- `computer-use-mcp` is the FE_DESKTOP default (it works on *anything*).
- `electron-mcp` / `slint-mcp` are chosen per step when a structural driver is
  available — same selector grammar, better fidelity, faster, headless-capable.

### 2.2 Residency rule (command_pin)

`computer-use-mcp` and `electron-mcp` are not shipped in the image (`slint-mcp`
is bundled and needs nothing — see the note above). `command_pin` maps the
logical command name to an absolute host binary supplied by the operator/CI
runner, so:
- the image stays thin and the executor host owns its binaries/versions;
- no native GUI/Chrome/OS-API deps leak into the Suitest image;
- `examples/slint-demo` and tests never reach into the `rdb` repo (that repo is
  a *sample target only* and is not modified).

---

### 2.3 tauri-mcp: a standard protocol, and why that matters

`tauri-mcp` (`suitest_mcp.bundled.tauri`) follows the same shape as `slint-mcp`
— it owns the application process and bridges a stable `tauri.*` contract onto
what the app already speaks — but the wire protocol is not bespoke. It is
**W3C WebDriver**, served from inside the app by `tauri-plugin-wdio-webdriver`.

Two consequences:

* **macOS works.** The standalone `tauri-driver` binary drives the platform's
  native WebDriver and exists only for Windows and Linux. An in-process server
  sidesteps that, which is how the official `@wdio/tauri-service` supports
  macOS too. There is no paid component and no external driver to install.
* **Nothing is app-specific.** Any Tauri 2 app that registers the plugin is
  drivable, and the app's own code never learns it is under test.

The app under test must be built with the plugin registered — the same bargain
Slint makes. Gate it on a cargo feature so a release build carries no server:

```toml
[features]
wdio = ["dep:tauri-plugin-wdio-webdriver"]

[dependencies]
tauri-plugin-wdio-webdriver = { version = "1", optional = true }
```

```rust
let builder = tauri::Builder::default();
#[cfg(feature = "wdio")]
let builder = builder.plugin(tauri_plugin_wdio_webdriver::init());
```

A `debug_assertions` gate is the alternative the plugin's own docs show, but it
opens the port during any ordinary `tauri dev`; a feature does not.

**Do not** add `wdio-webdriver:default` to `capabilities/*.json`. A build
without the feature then fails with `Permission ... not found`, and the set
grants no IPC anyway — the plugin is an HTTP server, not a command surface, and
it comes up without being listed.

Tools: `tauri.launch`, `tauri.close`, `tauri.click`, `tauri.type_text`,
`tauri.get_text`, `tauri.assert_text`, `tauri.assert_visible`, `tauri.eval`,
`tauri.screenshot`, `tauri.start_video`, `tauri.stop_video`. Selectors are W3C
strategies — pass `css` or `xpath`.

`tauri.screenshot` returns an MCP image block and `tauri.stop_video` an MP4
resource, which the runner files as `SCREENSHOT` and `VIDEO` artifacts. Video
needs `ffmpeg` on PATH, and is worth pairing with
`SUITEST_EVIDENCE_RECORDING=1`: steps otherwise complete faster than the
sampler, and a two-frame recording of a passing case tells nobody anything.

`tauri.eval` is the seam onto Rust: the page's own
`window.__TAURI_INTERNALS__.invoke` reaches real commands, so a step can assert
on what the backend actually did rather than only on what the DOM shows.

`tauri.launch` takes an optional `command`; omit it to attach to an app that is
already running, which is what a local `tauri dev` session wants.

## 3. slint-mcp: selector grammar

`slint-mcp` drives the app through Slint's **accessible tree** — the same
semantics used by screen readers — so no browser DOM and (with the software
renderer) no display server are required.

Selectors are JSON objects. Priority when resolving:

1. `id` — the **Slint element id**, written `Component::element-id`. The
   compiler keeps these when the app is built with `SLINT_EMIT_DEBUG_INFO=1`,
   so an app needs no accessibility annotations to be drivable at all.
2. `label` — the accessible label, i.e. what the user reads. Needed more often
   than it looks: ids are *component-scoped*, so `PrimaryButton::ta` matches
   every instance of that component on screen.
3. `index` — last resort when neither is unique.

```jsonc
// by element id
{ "id": "ConnPicker::add-ta" }

// by what the user sees — the only way to tell two PrimaryButtons apart
{ "label": "New Query" }

// narrow an id down by label, or failing that by position
{ "id": "PrimaryButton::ta", "label": "Connect" }
{ "id": "CodeEditor::focus-scope", "index": 1 }
```

Resolution **polls** until the element appears — `timeout_s`, default 15s, `0`
to fail immediately. A UI settles after the call that changed it (a click that
opens a pane returns before the pane has rendered), so a single look makes every
test a race. A malformed selector still fails immediately: naming no element at
all is an authoring mistake, not a timing one.

`find_elements_by_id` searches *descendants*, so a window's own root id never
matches; reach the root through `get_window_properties` instead.

### 3.1 Tagging in the `.slint` source

The example screen tags every interactive element via Slint's accessibility
properties (rendered by the compiler into the accessible tree):

```slint
Button {
    accessible-id: "btn-submit";
    accessible-label: "Submit";
    text: "Submit";
}
```

Supported roles that Suitest's assertions recognise: `button`, `check box`,
`text input`, `text`, `heading`, `radio button`, `slider`, `combo box`,
`list`, `table`. Unknown roles degrade to a generic node with an `id`.

---

## 4. slint-mcp tool contract

The runner exposes a standard MCP server (stdio transport) with `tools/list`
describing the catalog below. Suitest's `invoker` calls them through the normal
`mcp` client; every tool returns a structured JSON result and
`suitest_output`/`call_timeout` semantics.

### 4.1 Lifecycle

| Tool | Params | Returns / effect |
|------|--------|------------------|
| `slint.launch` | `path` (`.slint` or app binary), `args?`, `headless?` (default true) | 200-style `{ ok, pid, root }`; mounts the UI tree |
| `slint.close` | — | tears down the instance |

### 4.2 Property bridge (OS + Slint only)

| Tool | Params | Returns / effect |
|------|--------|------------------|
| `slint.get_property` | `selector`, `property?` | current value of the resolved element (text / checked / value) |
| `slint.set_property` | `selector`, `value`, `property?` | writes the value |
| `slint.click` | `selector` | dispatches `accessible-action-default()` on the element |
| `slint.drag` | `selector`, `to_id`/`to_label` or `x`+`y`, `button?` | presses at the element's centre, interpolates to the destination, releases — range selection, sliders, reordering |
| `slint.accessibility_action` | `selector`, `action` | invokes an accessible action (`Default_`, `Increment`, `Decrement`, ...) |
| `slint.type_text` | `selector`, `text`, `clear?` | sets text-input content (focused) |
| `slint.check` / `slint.uncheck` | `selector` | toggles a check box |

> The **property bridge touches only the OS+Slint surface**: Slint properties
> you expose explicitly (e.g. `out property <string> status-text`) plus
> OS-level signals (focus, geometry). It does **not** read arbitrary app state,
> keeping the driver decoupled from app internals — same philosophy as
> `accessible-id` after compile.

### 4.3 Assertions

| Tool | Params | Pass condition |
|------|--------|----------------|
| `slint.assert_visible` | `selector`, `equals` (bool) | element present (and, if given, visible) |
| `slint.assert_text` | `selector`, `equals` | resolved text equals string |
| `slint.assert_checked` | `selector`, `equals` (bool) | check box state equals bool |
| `slint.assert_value` | `selector`, `equals` | numeric/label value equals |

### 4.4 Diagnostics

| Tool | Params | Returns |
|------|--------|---------|
| `slint.screenshot` | `selector?` | base64 PNG of window / element |
| `slint.element_tree` | `max_elements?` | flat dump of the window's elements (ids, labels, handles) for debugging/stepping |
| `slint.start_video` / `slint.stop_video` | `interval_ms?` | frames sampled between the two calls, encoded to MP4 by ffmpeg and attached as a VIDEO artifact — the run shows the interaction, not just its end state |
| `slint.start_recording` / `slint.stop_recording` | — | the events the app received between the two calls, each with `Accepted` or `Ignored` — separates "the step never arrived" from "the app ignored it" |

---

## 5. Execution model

- Headless by default: Slint's software renderer means `slint.launch` works in
  CI without a display server; set `headless: false` to run on a real desktop.
- State round-trips through Suitest's existing **step protocol**: each `code`
  block declares `tool` + `arguments` + optional `assertions` (see the
  `suite.json` in `examples/slint-demo/`), so desktop steps are first-class
  steps, not a separate engine.
- Deterministic replay relies on `accessible-id` stability: an un-tagged widget
  is resolved by label+role, which is stable only if the app's UI copy is.

---

## 6. Testing strategy (how we validate this milestone)

1. **Example smoke suite** — `examples/slint-demo/suite.json` (S1 idle, S2
   submit, S3 reset) targeting `FE_DESKTOP` with provider `slint-mcp`. This is
   the canonical replay artifact and can run at zero tier.
2. **Unit tests** (in `packages/mcp/tests`) — assert:
   - `routing.DEFAULT_ROUTING[TargetKind.FE_DESKTOP] == ("computer-use-mcp", None)`,
   - the three desktop providers are registered in `BUILTIN_SPECS` with
     `kind == "desktop"`, `${provider}.launch` tools, and `command_pin`
     residency flags.
3. **Contract compliance (optional harness)** — a local `slint-mcp`
   implementation (not in this repo; the `rdb` repo is the sample target) must
   satisfy the `tools/list` catalog in [§4](#4-slint-mcp-tool-contract) and
   resolve the `examples/slint-demo` selectors.

---

## 7. Out of scope / follow-ups

- **M14-2** Electron DOM automation detail (Playwright `_electron` selection in
  the `electron-mcp` config).
- OS-native window find/handles beyond computer-use; native accessibility
  (macOS AX / Windows UIA) for non-Slint apps is a later milestone.
- Screenshot diffing / visual regression for desktop is parked (see
  [ROADMAP.md](./ROADMAP.md) backlog).
