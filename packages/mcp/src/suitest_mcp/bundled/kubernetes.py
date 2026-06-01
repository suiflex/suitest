"""Bundled ``kubernetes-mcp`` provider (M2-10).

In-process MCP server for ``INFRA``-tier steps — read-only K8s resource
assertions. Uses the official ``kubernetes`` client's dynamic API (generic over
any ``kind``), imported lazily so the registry never requires it. Sync client
calls are offloaded with :func:`asyncio.to_thread`.

Config: ``config_json['kubeconfig']`` path (else in-cluster service-account
config). Tools: ``k8s.get`` / ``k8s.list`` / ``k8s.assert_condition``.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent, Tool

from suitest_mcp.bundled.in_process_runtime import BundledServer, register_bundled_builder

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig

PROVIDER_NAME = "kubernetes-mcp"


def _tool_catalog() -> list[Tool]:
    string: dict[str, Any] = {"type": "string"}
    base_props = {
        "apiVersion": string,
        "kind": string,
        "namespace": string,
        "name": string,
    }
    return [
        Tool(
            name="k8s.get",
            description="Get one resource by kind/namespace/name.",
            inputSchema={"type": "object", "required": ["kind", "name"], "properties": base_props},
        ),
        Tool(
            name="k8s.list",
            description="List resources of a kind in a namespace.",
            inputSchema={
                "type": "object",
                "required": ["kind"],
                "properties": {**base_props, "labelSelector": string},
            },
        ),
        Tool(
            name="k8s.assert_condition",
            description="Assert a JSONPath on a resource equals an expected value.",
            inputSchema={
                "type": "object",
                "required": ["kind", "name", "jsonpath", "equals"],
                "properties": {**base_props, "jsonpath": string, "equals": {}},
            },
        ),
    ]


def _require_k8s() -> tuple[Any, Any]:
    try:
        k8s_client = importlib.import_module("kubernetes.client")
        k8s_config = importlib.import_module("kubernetes.config")
        k8s_dynamic = importlib.import_module("kubernetes.dynamic")
    except ImportError as exc:  # pragma: no cover - depends on image build
        raise RuntimeError(
            "kubernetes-mcp requires the 'kubernetes' client (bundle it in the runner image)"
        ) from exc
    return (k8s_client, k8s_config), k8s_dynamic


class KubernetesServer:
    """``BundledServer`` for K8s targets (lazy kubernetes client, read-only)."""

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "k8s.get":
            obj = await asyncio.to_thread(self._fetch, arguments)
            return [TextContent(type="text", text=json.dumps(obj, default=str))]
        if name == "k8s.list":
            items = await asyncio.to_thread(self._fetch_list, arguments)
            return [TextContent(type="text", text=json.dumps(items, default=str))]
        if name == "k8s.assert_condition":
            return await asyncio.to_thread(self._assert_condition, arguments)
        raise ValueError(f"unknown kubernetes-mcp tool: {name!r}")

    async def aclose(self) -> None:
        return None

    # -- sync helpers (run in a worker thread) -------------------------------

    def _dynamic(self) -> Any:
        (k8s_client, k8s_config), k8s_dynamic = _require_k8s()
        kubeconfig = self._provider.config_json.get("kubeconfig")
        if kubeconfig:
            k8s_config.load_kube_config(config_file=str(kubeconfig))
        else:
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
        return k8s_dynamic.DynamicClient(k8s_client.ApiClient())

    def _resource(self, args: dict[str, Any]) -> Any:
        client = self._dynamic()
        api_version = str(args.get("apiVersion", "v1"))
        kind = str(args["kind"])
        return client.resources.get(api_version=api_version, kind=kind)

    def _fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        res = self._resource(args)
        obj = res.get(name=str(args["name"]), namespace=args.get("namespace"))
        return dict(obj.to_dict())

    def _fetch_list(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        res = self._resource(args)
        listing = res.get(namespace=args.get("namespace"), label_selector=args.get("labelSelector"))
        return [dict(i.to_dict()) for i in listing.items]

    def _assert_condition(self, args: dict[str, Any]) -> list[TextContent]:
        from jsonpath_ng.ext import parse as jsonpath_parse

        obj = self._fetch(args)
        matches = [m.value for m in jsonpath_parse(str(args["jsonpath"])).find(obj)]
        if not matches:
            raise AssertionError(f"k8s.assert_condition: {args['jsonpath']!r} matched nothing")
        if matches[0] != args["equals"]:
            raise AssertionError(
                f"k8s.assert_condition: {args['jsonpath']!r} = {matches[0]!r}, "
                f"expected {args['equals']!r}"
            )
        return [TextContent(type="text", text=json.dumps({"ok": True, "matched": matches[0]}))]


def build_kubernetes_server(provider: McpProviderConfig) -> BundledServer:
    return KubernetesServer(provider)


register_bundled_builder(PROVIDER_NAME, build_kubernetes_server)
