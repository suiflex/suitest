# M1d MCP bundling prototype — Docker findings

**Date**: 2026-05-30
**Status**: De-risking artifact for PR-12 (Jira MCP) + PR-14 (GitHub MCP)
**Scope**: Verify the multi-stage Dockerfile pattern that bundles `jirac-mcp` and `github-mcp-server` into the Suitest API image.
**Artifact**: [`Dockerfile.mcp-prototype`](../../../Dockerfile.mcp-prototype) at repo root.

This document captures the binary asset URLs, image-size impact, glibc/musl compatibility verdict, and the multi-arch buildx result so that PR-12 and PR-14 reviewers do not have to re-solve the same Docker concerns in parallel.

---

## 1. Binary asset URLs per arch

Both vendors ship Linux amd64 and arm64 tarballs. All four URLs confirmed `HTTP 200` via `curl -I` on 2026-05-30.

### `jirac-mcp` — `mulhamna/jira-commands@jira-mcp-v2.0.1`

| Arch | Asset URL |
| --- | --- |
| `linux/amd64` | `https://github.com/mulhamna/jira-commands/releases/download/jira-mcp-v2.0.1/jirac-mcp-linux-x86_64.tar.gz` |
| `linux/arm64` | `https://github.com/mulhamna/jira-commands/releases/download/jira-mcp-v2.0.1/jirac-mcp-linux-aarch64.tar.gz` |

**Tarball layout** (relative paths):

```
./LICENSE-MIT
./LICENSE-APACHE
./README.md
./jirac-mcp-linux-x86_64        # arch-suffixed binary name
```

> Note: the binary inside the tarball is named `jirac-mcp-linux-<arch>`, NOT `jirac-mcp`. The Dockerfile renames it via `install` into `/usr/local/bin/jirac-mcp`.

### `github-mcp-server` — `github/github-mcp-server@v1.1.2`

| Arch | Asset URL |
| --- | --- |
| `linux/amd64` | `https://github.com/github/github-mcp-server/releases/download/v1.1.2/github-mcp-server_Linux_x86_64.tar.gz` |
| `linux/arm64` | `https://github.com/github/github-mcp-server/releases/download/v1.1.2/github-mcp-server_Linux_arm64.tar.gz` |

**Tarball layout**:

```
LICENSE
README.md
github-mcp-server
```

Binary is canonically named `github-mcp-server` — no rename needed.

---

## 2. Image size delta

Built on the test box (Darwin arm64, Docker 29.4.0 with OrbStack-style backend) targeting linux/arm64 only:

| Image | Size (reported) | Size (bytes → MiB) |
| --- | --- | --- |
| `python:3.12-slim` (bare) | `144 MB` | `137.7 MiB` |
| `suitest-mcp-prototype:test` (bundled) | `176 MB` | `167.8 MiB` |
| **Δ** | **`+32 MB` / `+30.1 MiB`** | |

Of the ~30 MiB delta:

- `jirac-mcp` binary: ~14–15 MiB extracted (Rust, glibc-dynamic, stripped, PIE)
- `github-mcp-server` binary: ~15–16 MiB extracted (Go, fully static, stripped)
- `ca-certificates` package: already present in `python:3.12-slim`, the explicit `apt-get install` is a no-op (`0 upgraded, 0 newly installed, 0 to remove`). It is kept in the Dockerfile so the dependency is documented in case the future base image drops it.

Compressed tarball sizes (informational, for build-cache pulls): jirac ≈ 4.5 MiB, github-mcp ≈ 7.0 MiB.

**Verdict**: a ~30 MiB delta is acceptable for the Suitest production image. No squash / multi-binary-strip is needed.

---

## 3. Glibc / musl compatibility verdict

Determined by `file` against each extracted binary and a smoke run inside `python:3.12-slim`:

| Binary | Linkage | Runs on `python:3.12-slim` (Debian glibc)? |
| --- | --- | --- |
| `jirac-mcp-linux-x86_64` | `ELF 64-bit … dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2, … GNU/Linux 2.0.0, stripped` | **YES** |
| `jirac-mcp-linux-aarch64` | `ELF 64-bit … dynamically linked, interpreter /lib/ld-linux-aarch64.so.1, … GNU/Linux 2.0.0, stripped` | **YES** |
| `github-mcp-server` (both arches) | `ELF 64-bit … statically linked, stripped` | **YES** |

Both arches of `jirac-mcp` confirmed running `--version` successfully under `python:3.12-slim` in the buildx multi-arch run.

**Cannot run inside alpine** — `jirac-mcp` is glibc-linked, alpine is musl. The Dockerfile therefore:

1. Uses `alpine:3.19` only as a **download/extract** stage (lighter than debian-slim for a one-shot `curl + tar`).
2. Defers the `--version` smoke test to the final `python:3.12-slim` stage, where both binaries can execute.

`python:3.12-slim` (Debian-based, glibc) is sufficient — **no need to switch to `python:3.12` (non-slim)**. The existing `infra/docker/Dockerfile.api` base does not need to change for M1d.

---

## 4. Buildx multi-arch result

`docker buildx version` reports `v0.33.0` on the test box.

Command exercised:

```bash
docker buildx create --name suitest-mcp-builder --driver docker-container --use
docker buildx build --builder suitest-mcp-builder \
  --platform linux/amd64,linux/arm64 \
  -f Dockerfile.mcp-prototype --target final .
```

Result: **both `linux/amd64` and `linux/arm64` built successfully**, including the build-time `RUN /usr/local/bin/jirac-mcp --version && /usr/local/bin/github-mcp-server --version` smoke test on each platform.

Key gotchas captured in the Dockerfile:

- `--platform=$BUILDPLATFORM` on each extractor stage avoids invoking QEMU just to run `curl` / `tar`. Only the final stage exercises `$TARGETPLATFORM`.
- The case-on-`$TARGETARCH` selects the matching asset for the *target* even though the extractor itself runs natively on the *builder*. This is the documented buildx pattern for downloading arch-specific assets.
- Default Docker driver does not support `--platform a,b`; reviewers building multi-arch locally must `docker buildx create --driver docker-container`.

---

## 5. Recommended Dockerfile pattern for PR-12 + PR-14

Both PRs should follow the same shape — copy-paste safe:

```dockerfile
ARG <VENDOR>_VERSION=<tag>

FROM --platform=$BUILDPLATFORM alpine:3.19 AS <vendor>-mcp
ARG TARGETARCH
ARG <VENDOR>_VERSION
RUN apk add --no-cache curl tar \
 && case "$TARGETARCH" in \
      amd64) asset="<…linux-x86_64.tar.gz>" ;; \
      arm64) asset="<…linux-arm64.tar.gz>"  ;; \
      *) echo "unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/<vendor>.tar.gz \
      "https://github.com/<org>/<repo>/releases/download/${<VENDOR>_VERSION}/${asset}" \
 && mkdir -p /out && tar -xzf /tmp/<vendor>.tar.gz -C /out \
 && install -m 0755 /out/<binary> /usr/local/bin/<binary> \
 && rm -rf /tmp/<vendor>.tar.gz /out
```

Then in the final stage (which `infra/docker/Dockerfile.api` already provides):

```dockerfile
COPY --from=<vendor>-mcp /usr/local/bin/<binary> /usr/local/bin/<binary>
RUN /usr/local/bin/<binary> --version    # build-time smoke test
```

### PR-12 specifics (jirac-mcp)

- Use the asset rename: tarball ships `jirac-mcp-linux-<arch>`, install into `/usr/local/bin/jirac-mcp`.
- Do **not** add `RUN /usr/local/bin/jirac-mcp --version` inside the alpine extractor stage — it will fail (glibc binary, musl host).
- Pin `ARG JIRAC_VERSION=jira-mcp-v2.0.1` so the version is bumpable in one place.

### PR-14 specifics (github-mcp-server)

- Tarball entry name matches the target binary (`github-mcp-server`) — no rename.
- Binary is fully static; could even be smoke-tested in the alpine extractor, but defer to the final stage for symmetry with PR-12.
- Pin `ARG GH_MCP_VERSION=v1.1.2`.

### Integration into `infra/docker/Dockerfile.api`

`infra/docker/Dockerfile.api` already has a single `FROM python:3.12-slim AS base` stage. PR-12 and PR-14 should:

1. Move the existing `base` stage so it becomes the **final** stage of a multi-stage file (rename the current `base` alias to `final` or keep `base` and reference it from `COPY --from=…` blocks).
2. Insert the two extractor stages **above** `base` / `final`.
3. Add the two `COPY --from=…` lines into `base` / `final` after `uv sync`.
4. Add `apt-get install -y --no-install-recommends ca-certificates` to the existing apt step — already pulled in by `build-essential` transitively but worth being explicit.

Both PRs touch the same file, so coordinate the merge order: whichever lands first owns the multi-stage refactor; the second PR just adds its extractor stage and `COPY` line.

---

## 6. Blockers / gaps

- **None for the binary side.** Both vendors publish Linux amd64 + arm64 tarballs at well-formed URLs, both binaries execute under `python:3.12-slim`, and the multi-stage pattern builds clean under buildx for both platforms.
- **macOS dev caveat**: the bundled image is Linux-only. Devs on Darwin running the runner locally without Docker will not have `jirac-mcp` / `github-mcp-server` on `PATH`. That is the M1d spec's existing assumption (these MCP servers are spawned by the runner from inside the container).
- **Default Docker driver**: cannot do multi-arch builds without switching to `docker-container`. CI must use `docker buildx create --driver docker-container` (or run on a buildkit runner) — flag this in the M1d CI workflow when it lands.

---

## 7. Verification command summary

```bash
# Native arch build + smoke test (works with default docker driver)
docker build -f Dockerfile.mcp-prototype --target final -t suitest-mcp-prototype:test .
docker run --rm suitest-mcp-prototype:test /usr/local/bin/jirac-mcp --version
docker run --rm suitest-mcp-prototype:test /usr/local/bin/github-mcp-server --version

# Size delta
docker images python:3.12-slim suitest-mcp-prototype:test

# Multi-arch dry-run (requires docker-container builder)
docker buildx create --name mcp-multi --driver docker-container --use
docker buildx build --platform linux/amd64,linux/arm64 \
  -f Dockerfile.mcp-prototype --target final .
docker buildx rm mcp-multi
```

All four commands above were exercised on 2026-05-30 against the prototype Dockerfile and passed.
