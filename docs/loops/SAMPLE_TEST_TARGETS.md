# Sample test targets — manual walkthrough (ZERO + LLM)

> Hands-on samples for trying Suitest end-to-end yourself. Pick a target, build
> the project **from an empty Suitest** (no seed data), author a few cases, run
> them, triage. Two passes per target: **ZERO** (no LLM) and **LLM** (API key).
>
> Everything below is described as **what you do in the product** (screens, the
> `suitest` CLI, public URLs). No internal source files — you don't need them.

## Ground rules

- **Start empty.** Fresh Suitest, no demo seed. You create the workspace →
  project → suite → cases from scratch. That is the real new-user path.
- **Targets are sanctioned sandboxes** built for automated testing (Targets A & B).
  Hammer them freely — public test accounts, no real data, resettable.
- **Target C is a real production site** (oss.go.id) — **read-only public pages
  only**. No login, no account creation, no form submission, low request rate.
- **Execution is identical in both tiers.** The LLM only changes *authoring* and
  *triage*; it never runs the test. So each target's "run" step is the same.

---

## Target A — Swag Labs (https://www.saucedemo.com) — web e-commerce

The classic automation demo: login → browse → cart → checkout. Stable markup,
public credentials, perfect first sample. `target_kind = FE_WEB`, driven by the
browser MCP (`playwright-mcp`).

Public test accounts (documented by the site):
- `standard_user` / `secret_sauce` — happy path
- `locked_out_user` / `secret_sauce` — should be blocked

### ZERO pass (no LLM)

1. Create project **"Swag Labs Smoke"** → suite **"Checkout journey"**.
2. (Optional) Use the **URL Crawler** generator on `https://www.saucedemo.com`
   to seed draft cases, then trim. Or author by hand:
   - **C1 — Login valid:** open site, type `standard_user` / `secret_sauce`,
     submit → assert URL is the inventory page and a product list is visible.
   - **C2 — Login locked out:** `locked_out_user` / `secret_sauce` → assert the
     "locked out" error message appears.
   - **C3 — Add to cart:** from C1 state, add one item → assert cart badge = `1`.
   - **C4 — Checkout happy path:** cart → checkout → fill name/zip → finish →
     assert "Thank you for your order!".
   - **C5 — Sort:** change the sort dropdown to "Price (low to high)" → assert
     first item price ≤ last item price.
3. Mark **"Checkout journey"** as the project's **gating suite**.
4. Run it: `suitest run --suite "Checkout journey" --wait`. Deterministic.
   Artifacts captured: screenshots + HAR per step.
5. **Triage yourself** from the screenshots/HAR (ZERO has no AI). Re-run a couple
   times; the analytics view flags a case as flaky if results vary.

### LLM pass (API key set)

Same project, but let AI help:
- **Author faster:** use **URL-semantic generation** with the intent
  *"alur checkout dari login sampai order selesai"* → the agent explores the site
  and drafts the journey cases for you. Review the DRAFTs before activating.
- **Triage faster:** when a case fails, **AI diagnosis** labels it
  `FLAKE / REGRESSION / ENVIRONMENT / TEST_BUG` with a confidence score and a
  suggested fix — instead of you reading raw HAR.

---

## Target B — restful-booker (https://restful-booker.herokuapp.com) — REST API

A free API sandbox with auth + CRUD + a published Swagger/OpenAPI spec. Great for
showing **deterministic OpenAPI generation** and contract testing.
`target_kind = BE_REST`, driven by the HTTP MCP (`api-http-mcp`).

Public test auth (documented): `admin` / `password123` → returns a token.

### ZERO pass (no LLM)

1. Create project **"Booker API"** → suite **"Booking contract"**.
2. Use the **OpenAPI import** generator: point it at the site's Swagger spec →
   it auto-generates contract cases per endpoint. Then keep the core ones:
   - **C1 — Health:** `GET /ping` → expect `201`.
   - **C2 — Auth:** `POST /auth` with the test creds → expect a `token` in the body.
   - **C3 — Create:** `POST /booking` with a booking payload → expect `200` + an
     `bookingid` and the echoed fields match what you sent.
   - **C4 — Read:** `GET /booking/{id}` (id from C3) → fields match C3.
   - **C5 — Auth negative:** `DELETE /booking/{id}` *without* a token → expect
     `403`; then with the C2 token → expect `201/200`.
3. Run: `suitest run --suite "Booking contract" --wait`. Fast, stable, low-flake —
   this is the layer you lean on for CI gating.
4. Triage from the response bodies captured as artifacts.

> Tip: this is where **setup/teardown** matters once it lands — C2 (get token) as
> a setup step, delete-the-booking as a teardown so cases don't leak state.

### LLM pass (API key set)

- **Author:** feed a short PRD ("a booking has firstname, lastname, dates,
  deposit; auth required to mutate") → **PRD generation** drafts positive +
  negative cases per rule. Review DRAFTs.
- **Triage:** flaky `5xx` from the free Heroku dyno is common — **AI diagnosis**
  will tend to mark those `FLAKE`/`ENVIRONMENT` rather than `REGRESSION`, saving
  you the judgment call.

---

## Target C — https://oss.go.id (OSS RBA) — real site, READ-ONLY

A real Indonesian government licensing portal (Next.js app). Use it **only** to
practice read-only public-page checks. **Do not** log in, register, or submit
forms; keep the request rate low; respect the site's terms. `target_kind = FE_WEB`.

Grounded from a quick look at the homepage:
- Title: *"OSS RBA - Sistem Perizinan Berusaha Terintegrasi Secara Elektronik"*.
- Hero: *"Lancar dan aman kelola usaha dengan NIB"*.
- KBLI lookup: the **"Cek Sekarang"** button → `/kbli` (check which permit your
  business needs — public, read-only).
- News: `/berita`; Help: `/faq`; Guides video: `/video`.
- Login lives on a separate portal (`ui-login.oss.go.id`) — **leave it alone**.

### ZERO pass (no LLM)

1. Create project **"OSS Public Read-only"** → suite **"Public pages smoke"**.
2. Author read-only cases:
   - **C1 — Homepage:** open `https://oss.go.id/` → assert title contains "OSS"
     and the NIB hero text is visible.
   - **C2 — KBLI page:** click "Cek Sekarang" / open `/kbli` → assert the search
     input renders. (Optionally type a keyword and assert results render — still
     read-only.)
   - **C3 — News:** open `/berita` → assert article cards list; open one article →
     assert it loads (no 404).
   - **C4 — FAQ:** open `/faq` → assert content renders.
   - **C5 — Footer contacts:** assert the WhatsApp/Email/contact links resolve
     (link present + reachable), without submitting anything.
3. Run read-only. Capture screenshots. Because it's a real SPA, expect occasional
   timing flakiness — good practice for re-run + flaky detection.

### LLM pass (API key set)

- **Author:** URL-semantic generation with a **read-only** intent like
  *"temukan informasi izin lewat pencarian KBLI"* → drafts a navigation journey.
  Review and strip anything that would mutate state.
- **Triage:** AI diagnosis on the SPA timing failures (mostly `FLAKE`/`ENV`).

---

## What to expect per tier (summary)

| Step | ZERO | LLM |
|------|------|-----|
| Author cases | by hand, or OpenAPI / Recorder / URL-Crawler generators | + PRD / URL-semantic / MCP-discovery drafts |
| Search your cases | semantic (if embeddings on) or keyword | same |
| Run | deterministic via MCP | **identical** |
| Triage failures | you read artifacts | AI diagnosis (category + confidence + fix) |
| Cost | none | per token (budget guard applies) |

Start with **Target A or B at ZERO** — that's the fastest way to feel the whole
loop without any key. Add the LLM pass once you want authoring/triage help.
