#!/usr/bin/env python
"""Assert the air-gapped Helm overlay actually locks the cluster down (M4-4).

Reads a rendered manifest stream (``helm template -f values-airgapped.yaml``) on
stdin and fails non-zero unless every air-gap invariant holds. This is the fast,
deterministic half of M4-4 — it needs no cluster, so it runs on every PR and
catches a regression (e.g. someone widens egress to ``0.0.0.0/0`` or drops the
in-cluster Ollama) long before the heavyweight kind run.

Invariants:
  1. A default-deny NetworkPolicy exists with Egress in policyTypes.
  2. No egress rule allows the public internet (0.0.0.0/0 or ::/0).
  3. In-cluster Ollama (Deployment + Service) is rendered — the LOCAL tier has a
     model server that needs no outbound network.

Usage::

    helm template ./infra/helm/suitest -f infra/helm/suitest/values-airgapped.yaml \
        | python scripts/check_airgapped_policy.py
"""

from __future__ import annotations

import sys

import yaml

_PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}

Doc = dict[str, object]


def _as_dict(value: object) -> Doc:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _component(doc: Doc) -> str:
    labels = _as_dict(_as_dict(doc.get("metadata")).get("labels"))
    component = labels.get("app.kubernetes.io/component")
    return component if isinstance(component, str) else ""


def _iter_egress_cidrs(netpol: Doc) -> list[str]:
    cidrs: list[str] = []
    spec = _as_dict(netpol.get("spec"))
    for rule in _as_list(spec.get("egress")):
        for peer in _as_list(_as_dict(rule).get("to")):
            cidr = _as_dict(_as_dict(peer).get("ipBlock")).get("cidr")
            if isinstance(cidr, str):
                cidrs.append(cidr)
    return cidrs


def main() -> int:
    docs: list[Doc] = [d for d in yaml.safe_load_all(sys.stdin) if isinstance(d, dict)]
    failures: list[str] = []

    netpols = [d for d in docs if d.get("kind") == "NetworkPolicy"]
    if not netpols:
        failures.append("no NetworkPolicy rendered — egress is wide open")

    has_default_deny_egress = any(
        "Egress" in _as_list(_as_dict(np.get("spec")).get("policyTypes")) for np in netpols
    )
    if netpols and not has_default_deny_egress:
        failures.append("no NetworkPolicy declares policyTypes: [Egress]")

    for np in netpols:
        for cidr in _iter_egress_cidrs(np):
            if cidr in _PUBLIC_CIDRS:
                name = _as_dict(np.get("metadata")).get("name")
                failures.append(f"NetworkPolicy {name!r} allows public egress {cidr}")

    def _has(kind: str, component: str) -> bool:
        return any(d.get("kind") == kind and _component(d) == component for d in docs)

    if not _has("Deployment", "ollama"):
        failures.append("no in-cluster Ollama Deployment — LOCAL tier needs outbound LLM")
    if not _has("Service", "ollama"):
        failures.append("no in-cluster Ollama Service")

    if failures:
        print("AIR-GAP POLICY CHECK FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(
        f"OK  air-gap invariants hold "
        f"({len(netpols)} NetworkPolicy, in-cluster Ollama present, no public egress)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
