"""Retest hardening — project binding, change detection, failure classification,
generated-code reuse metadata.

Stdlib-only (like the rest of the lifecycle core). Four concerns, one flow:

1. **Binding** — before a publish-enabled run, validate ``publish.projectId``
   against the server. Valid → retest. Missing → repair by slug/name via the
   read-only ``/ingest/resolve-project`` endpoint (config file is rewritten on
   success). Unrepairable → the run FAILS LOUDLY and inserts nothing; recreate
   happens only on an explicit flag.
2. **Snapshot** — every generation persists an app fingerprint (endpoints /
   routes / per-case step hashes). The next run diffs against it and classifies
   what changed (route_removed, request_schema_changed, …).
3. **Failure classification** — raw runner errors are mapped onto structured
   kinds (selector_changed, endpoint_not_found, auth_failure, …) so the MCP
   response and the TCM can tell a UI bug from a dead backend.
4. **Codegen metadata** — per-case input/code hashes + versions in
   ``codegen_meta.json``; unchanged inputs reuse the existing files, changed
   ones bump the version and keep the prior file under ``history/``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from suitest_lifecycle.models import Mode

if TYPE_CHECKING:
    from pathlib import Path

    from suitest_lifecycle.config import Config
    from suitest_lifecycle.models import CodeSummary, PlanCase, TestResult
    from suitest_lifecycle.paths import Paths


# --------------------------------------------------------------------------- #
# Project binding
# --------------------------------------------------------------------------- #
class BindingClient(Protocol):
    """The one server call binding resolution needs (satisfied by SuitestClient)."""

    def resolve_project(
        self, *, project_id: str = "", project_slug: str = "", project_name: str = ""
    ) -> dict[str, object]: ...


@dataclass
class BindingResult:
    # local_only | first_setup | valid | repaired | missing | recreate_requested | unverified
    status: str
    action: str
    project_id: str = ""
    detail: str = ""
    candidates: list[dict[str, object]] = field(default_factory=list)

    @property
    def blocks_publish(self) -> bool:
        """True when the run must NOT insert anything server-side."""
        return self.status == "missing"

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {"status": self.status, "action": self.action}
        if self.project_id:
            out["projectId"] = self.project_id
        if self.detail:
            out["detail"] = self.detail
        if self.candidates:
            out["candidates"] = self.candidates
        return out


def project_slug(name: str) -> str:
    """Mirror of the server's project-slug shape: lowercase, alnum + dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:64] or "project"


def rewrite_project_id(config_path: Path, project_id: str) -> bool:
    """Persist a repaired/recreated projectId back into suitest.config.json."""
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return False
        pub = raw.setdefault("publish", {})
        if not isinstance(pub, dict):
            return False
        pub["projectId"] = project_id
        config_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return True
    except (OSError, ValueError):
        return False


def _make_client(config: Config) -> BindingClient:
    import os

    from suitest_lifecycle.http_client import SuitestClient

    api_url = config.publish.api_url or os.environ.get("SUITEST_API_URL", "")
    token = config.publish.token or os.environ.get("SUITEST_API_KEY") or None
    return SuitestClient(
        api_url, token=token, workspace_id=config.publish.workspace_id or None, timeout=30.0
    )


def resolve_binding(
    config: Config, *, recreate: bool = False, client: BindingClient | None = None
) -> BindingResult:
    """Decide what this run is allowed to do with the configured project binding."""
    if not config.publish.enabled:
        return BindingResult("local_only", "publish_disabled")
    if client is None:
        client = _make_client(config)

    slug = project_slug(config.project_name)
    if not config.publish.project_id:
        return BindingResult(
            "first_setup",
            "will_create_by_slug",
            detail=f"no projectId configured — server will find-or-create slug '{slug}'",
        )

    try:
        resolved = client.resolve_project(
            project_id=config.publish.project_id,
            project_slug=slug,
            project_name=config.project_name,
        )
    except Exception as exc:  # network/auth hiccup — server still rejects bad ids on publish
        return BindingResult(
            "unverified",
            "server_unreachable",
            project_id=config.publish.project_id,
            detail=f"{type(exc).__name__}: {exc}",
        )

    status = str(resolved.get("status", "missing"))
    if status == "valid":
        return BindingResult(
            "valid", "reused_existing_project", project_id=config.publish.project_id
        )
    if status == "repaired":
        new_id = str(resolved.get("projectId", ""))
        rewrote = rewrite_project_id(config.config_path, new_id)
        return BindingResult(
            "repaired",
            "rebound_by_" + str(resolved.get("matchedBy", "match")),
            project_id=new_id,
            detail=(
                f"stale projectId '{config.publish.project_id}' repaired to '{new_id}'"
                + ("" if rewrote else " (config file NOT rewritten — update it manually)")
            ),
        )
    # missing
    raw_candidates = resolved.get("candidates", [])
    candidates = (
        [c for c in raw_candidates if isinstance(c, dict)]
        if isinstance(raw_candidates, list)
        else []
    )
    if recreate:
        return BindingResult(
            "recreate_requested",
            "will_recreate_by_slug",
            detail=f"projectId '{config.publish.project_id}' not found; "
            f"explicit recreate flag set — server will find-or-create slug '{slug}'",
        )
    return BindingResult(
        "missing",
        "fail",
        project_id=config.publish.project_id,
        detail=(
            f"projectId '{config.publish.project_id}' not found in the workspace and no "
            "unambiguous project matched by name/slug. Nothing was published. Fix "
            "publish.projectId in suitest.config.json, or re-run with recreateProject "
            "explicitly set to create a fresh project."
        ),
        candidates=candidates,
    )


# --------------------------------------------------------------------------- #
# App fingerprint snapshot + diff
# --------------------------------------------------------------------------- #
def _sha(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def build_fingerprint(
    summary: CodeSummary,
    cases: list[PlanCase],
    elements: dict[str, object] | None = None,
) -> dict[str, object]:
    """App fingerprint for the change-detection diff.

    ``elements`` is an optional per-route payload of interactive-element
    identity (selectors, testids, form structure) from a live crawl/blackbox
    discovery — it powers selector-level change detection. Callers must pass
    STABLE identity only (no screenshot paths / visible dynamic text), or every
    retest would look like a UI change.
    """
    endpoints = {
        f"{e.method} {e.path}": {
            "auth": e.auth_required,
            "exampleHash": _sha(e.request_example) if e.request_example else "",
        }
        for e in summary.endpoints
    }
    pages = {p.route: {"name": p.name, "protected": p.protected} for p in summary.pages}
    case_hashes = {
        c.title: _sha([c.source_ref, [(s.type, s.description) for s in c.steps]]) for c in cases
    }
    return {
        "mode": summary.mode.value,
        "endpoints": endpoints,
        "pages": pages,
        "elements": {route: _sha(payload) for route, payload in (elements or {}).items()},
        "cases": case_hashes,
    }


def snapshot_path(paths: Paths) -> Path:
    return paths.tmp_dir / "app_snapshot.json"


def load_snapshot(paths: Paths) -> dict[str, object] | None:
    p = snapshot_path(paths)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except ValueError:
        return None


def save_snapshot(paths: Paths, fingerprint: dict[str, object]) -> None:
    snapshot_path(paths).write_text(json.dumps(fingerprint, indent=2), encoding="utf-8")


def _as_dict(raw: object) -> dict[str, object]:
    return raw if isinstance(raw, dict) else {}


def diff_fingerprint(prev: dict[str, object] | None, cur: dict[str, object]) -> dict[str, object]:
    """Compare two app fingerprints into a classified change report."""
    if prev is None:
        return {
            "first": True,
            "changed": False,
            "uiChanged": False,
            "apiChanged": False,
            "breaking": False,
            "changes": [],
        }

    changes: list[dict[str, str]] = []

    def _add(kind: str, ref: str, detail: str) -> None:
        changes.append({"kind": kind, "ref": ref, "detail": detail})

    pe, ce = _as_dict(prev.get("endpoints")), _as_dict(cur.get("endpoints"))
    for key in sorted(pe.keys() - ce.keys()):
        _add("endpoint_removed", key, "endpoint no longer discovered (breaking)")
    for key in sorted(ce.keys() - pe.keys()):
        _add("endpoint_added", key, "new endpoint discovered")
    for key in sorted(pe.keys() & ce.keys()):
        p, c = _as_dict(pe[key]), _as_dict(ce[key])
        if p.get("auth") != c.get("auth"):
            _add("auth_flow_changed", key, f"auth requirement {p.get('auth')} -> {c.get('auth')}")
        if p.get("exampleHash") != c.get("exampleHash"):
            _add("request_schema_changed", key, "request body shape changed")

    pp, cp = _as_dict(prev.get("pages")), _as_dict(cur.get("pages"))
    for key in sorted(pp.keys() - cp.keys()):
        _add("route_removed", key, "route no longer discovered (breaking)")
    for key in sorted(cp.keys() - pp.keys()):
        _add("route_added", key, "new route discovered")
    for key in sorted(pp.keys() & cp.keys()):
        p, c = _as_dict(pp[key]), _as_dict(cp[key])
        if p.get("protected") != c.get("protected"):
            _add(
                "auth_flow_changed", key, f"protected {p.get('protected')} -> {c.get('protected')}"
            )
        elif p != c:
            _add("route_changed", key, "page metadata changed")

    # Selector-level UI diff: per-route interactive-element digests from the
    # live crawl. Only routes present in BOTH snapshots are compared — adds and
    # removals are already reported by the pages diff above. Skipped entirely
    # when either run had no element capture (repo-analysis frontend runs).
    pel, cel = _as_dict(prev.get("elements")), _as_dict(cur.get("elements"))
    if pel and cel:
        for key in sorted(pel.keys() & cel.keys()):
            if pel[key] != cel[key]:
                _add(
                    "selector_changed",
                    key,
                    "interactive elements/selectors on this route changed",
                )

    pc, cc = _as_dict(prev.get("cases")), _as_dict(cur.get("cases"))
    for key in sorted(pc.keys() - cc.keys()):
        _add("case_removed", key, "scenario no longer generated (will be marked stale)")
    for key in sorted(cc.keys() - pc.keys()):
        _add("case_added", key, "new scenario generated")
    for key in sorted(pc.keys() & cc.keys()):
        if pc[key] != cc[key]:
            _add("case_steps_changed", key, "scenario steps changed (case will be updated)")

    breaking_kinds = {"endpoint_removed", "route_removed", "auth_flow_changed"}
    api_kinds = {"endpoint_removed", "endpoint_added", "request_schema_changed"}
    ui_kinds = {"route_removed", "route_added", "route_changed", "selector_changed"}
    kinds = {c["kind"] for c in changes}
    return {
        "first": False,
        "changed": bool(changes),
        "uiChanged": bool(kinds & ui_kinds),
        "apiChanged": bool(kinds & api_kinds),
        "breaking": bool(kinds & breaking_kinds),
        "changes": changes,
    }


# --------------------------------------------------------------------------- #
# Failure classification
# --------------------------------------------------------------------------- #
_FRONTEND_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"strict mode violation|not attached|detached|element.{0,20}not found", re.I),
        "element_missing",
    ),
    (
        re.compile(r"waiting for (locator|selector)|locator\(|selector|get_by_", re.I),
        "selector_changed",
    ),
    (re.compile(r"to_?have_?url|navigation|net::ERR_ABORTED|goto", re.I), "navigation_changed"),
)

_BACKEND_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b404\b|not found", re.I), "endpoint_not_found"),
    (re.compile(r"\b405\b|method not allowed", re.I), "method_mismatch"),
    (re.compile(r"\b422\b|validation", re.I), "validation_error"),
    (
        re.compile(r"expected \d{3}.*got \d{3}|status_?code|assert \d{3}", re.I),
        "status_code_changed",
    ),
    (
        re.compile(r"keyerror|jsonschema|schema|missing (key|field)|unexpected (key|field)", re.I),
        "response_schema_changed",
    ),
)

_GENERIC_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"ECONNREFUSED|connection refused|net::ERR_CONNECTION_REFUSED|"
            r"failed to establish a new connection|connectionerror|ERR_NAME_NOT_RESOLVED",
            re.I,
        ),
        "backend_down",
    ),
    (
        re.compile(r"\b401\b|\b403\b|unauthorized|forbidden|invalid (token|credential)", re.I),
        "auth_failure",
    ),
    (re.compile(r"CORS|cross-origin", re.I), "cors_network_issue"),
    (re.compile(r"\b50[023]\b|internal server error|bad gateway", re.I), "server_error"),
    (re.compile(r"timed? ?out|timeout", re.I), "timeout"),
)


def classify_failure(error: str, mode: Mode, *, api_changed: bool = False) -> str:
    """Map a raw runner error onto a structured failure kind."""
    if not error:
        return ""
    mode_rules = _FRONTEND_RULES if mode is Mode.FRONTEND else _BACKEND_RULES
    for pattern, kind in (*mode_rules, *_GENERIC_RULES):
        if pattern.search(error):
            if kind == "auth_failure" and mode is Mode.FRONTEND:
                return "auth_flow_changed"
            # A frontend failure while the API contract moved is an integration
            # break, not a UI bug — unless the error is clearly DOM-level.
            if (
                mode is Mode.FRONTEND
                and api_changed
                and kind in {"response_schema_changed", "status_code_changed", "server_error"}
            ):
                return "frontend_backend_integration_changed"
            return kind
    if mode is Mode.FRONTEND and api_changed:
        return "frontend_backend_integration_changed"
    return "assertion_outdated" if "assert" in error.lower() else "unclassified"


def classify_results(
    results: list[TestResult], mode: Mode, *, api_changed: bool = False
) -> dict[str, str]:
    """test_id -> failure kind, for failed/errored results only."""
    out: dict[str, str] = {}
    for r in results:
        if r.status.value in ("FAILED", "ERROR") and (
            kind := classify_failure(r.error, mode, api_changed=api_changed)
        ):
            out[r.test_id] = kind
    return out


# --------------------------------------------------------------------------- #
# Generated-code metadata (versioning + reuse)
# --------------------------------------------------------------------------- #
def meta_path(paths: Paths) -> Path:
    return paths.mode_dir / "codegen_meta.json"


def load_codegen_meta(paths: Paths) -> dict[str, dict[str, object]]:
    p = meta_path(paths)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


def case_input_hash(case: PlanCase, dom_digest: str, codegen: str) -> str:
    return _sha(
        [case.source_ref, [(s.type, s.description) for s in case.steps], dom_digest, codegen]
    )


def can_reuse_generated(
    cases: list[PlanCase],
    paths: Paths,
    meta: dict[str, dict[str, object]],
    dom_digest: str,
    codegen: str,
) -> bool:
    """True when every planned case's inputs match the last generation AND its
    file still exists — the whole export (incl. LLM codegen) can be skipped."""
    if not meta or not cases:
        return False
    for c in cases:
        entry = meta.get(c.title)
        if entry is None or entry.get("inputHash") != case_input_hash(c, dom_digest, codegen):
            return False
        file_name = str(entry.get("file", ""))
        if not file_name or not paths.test_file(file_name).is_file():
            return False
        c.automation_file = file_name  # re-link the plan to the reused file
    return True


def reconcile_codegen(
    cases: list[PlanCase],
    paths: Paths,
    prior: dict[str, dict[str, object]],
    stash: dict[str, str],
    dom_digest: str,
    codegen: str,
    *,
    reused: bool = False,
    export_error: str = "",
) -> tuple[dict[str, dict[str, object]], dict[str, int]]:
    """Post-export bookkeeping: hash files, bump versions, archive old code.

    Returns (meta, summary) with summary counts new/regenerated/unchanged/
    reused/needs_review. Changed files get their previous content copied to
    ``history/<file>.v<prev-version>`` so regeneration never silently destroys
    a reviewed test.
    """
    meta: dict[str, dict[str, object]] = {}
    counts = {"new": 0, "regenerated": 0, "unchanged": 0, "reused": 0, "needs_review": 0}
    history_dir = paths.mode_dir / "history"

    for c in cases:
        if not c.automation_file:
            continue
        fp = paths.test_file(c.automation_file)
        code = fp.read_text(encoding="utf-8") if fp.is_file() else ""
        entry: dict[str, object] = {
            "file": c.automation_file,
            "inputHash": case_input_hash(c, dom_digest, codegen),
            "codeHash": _sha(code),
            "sourceRef": c.source_ref,
        }
        prev = prior.get(c.title)
        prev_version = int(str(prev.get("version", 1))) if prev else 0
        if export_error:
            entry["version"] = prev_version or 1
            entry["status"] = "needs_review"
            entry["error"] = export_error
            counts["needs_review"] += 1
        elif reused or (prev and prev.get("codeHash") == entry["codeHash"]):
            entry["version"] = prev_version or 1
            entry["status"] = "reused" if reused else "unchanged"
            counts["reused" if reused else "unchanged"] += 1
        elif prev:
            entry["version"] = prev_version + 1
            entry["status"] = "regenerated"
            counts["regenerated"] += 1
            old_code = stash.get(c.automation_file, "")
            if old_code:
                history_dir.mkdir(parents=True, exist_ok=True)
                (history_dir / f"{c.automation_file}.v{prev_version}").write_text(
                    old_code, encoding="utf-8"
                )
        else:
            entry["version"] = 1
            entry["status"] = "new"
            counts["new"] += 1
        meta[c.title] = entry

    meta_path(paths).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta, counts


__all__ = [
    "BindingClient",
    "BindingResult",
    "build_fingerprint",
    "can_reuse_generated",
    "case_input_hash",
    "classify_failure",
    "classify_results",
    "diff_fingerprint",
    "load_codegen_meta",
    "load_snapshot",
    "project_slug",
    "reconcile_codegen",
    "resolve_binding",
    "rewrite_project_id",
    "save_snapshot",
]
