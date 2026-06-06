# Security Policy

## Supported versions

Suitest is pre-1.0 during the M0–M4 build. Security fixes target the latest
`main` and the most recent tagged release.

| Version | Supported |
|---------|-----------|
| latest `main` | ✅ |
| latest release tag | ✅ |
| older tags | ❌ |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email **security@suitest.dev** with:

- A description of the issue and its impact.
- Steps to reproduce (proof-of-concept if possible).
- Affected version / commit.

We aim to acknowledge within **48 hours** and provide a remediation timeline
within **7 days**. We will credit reporters in the release notes unless you
prefer to remain anonymous.

## Scope & hardening notes

Because Suitest is self-hosted and runs untrusted MCP servers + user-supplied
LLM keys, the following are in scope:

- Secret handling — all stored secrets are AES-GCM encrypted (`packages/core/crypto`);
  report any plaintext leakage, including in exports (`*_encrypted` columns must be
  REDACTED) or logs.
- MCP sandbox escape — user-registered MCP commands run sandboxed; report any
  host filesystem / network egress beyond the configured allowlist.
- Tenant isolation — report any cross-workspace data access.
- AuthZ — capability tier / autonomy gating bypass, role escalation.
- Injection / SSRF in webhook receivers and generators.

## Out of scope

- Vulnerabilities requiring a malicious workspace OWNER (they already control the
  tenant).
- Issues in third-party MCP servers you choose to register.
- Denial of service from self-hosted misconfiguration.
