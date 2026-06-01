"""Bundled ``grpc-mcp`` provider (M2-10).

In-process MCP server for ``BE_GRPC``-tier steps. Generic unary gRPC calls are
driven through **server reflection** (no precompiled stubs needed): the target
server must expose the standard ``grpc.reflection.v1alpha`` service. The ``grpc``
+ ``grpcio-reflection`` packages are imported lazily so the registry never needs
them present.

Config / args: ``target`` (``host:port``) from args or ``config_json['target']``;
``method`` is the fully-qualified ``package.Service/Method``; ``request`` is a
JSON object mapped onto the request message via protobuf ``json_format``.

Tools: ``grpc.call`` / ``grpc.assert_response``.
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING, Any

from mcp.types import TextContent, Tool

from suitest_mcp.bundled.in_process_runtime import BundledServer, register_bundled_builder

if TYPE_CHECKING:
    from suitest_mcp.models import McpProviderConfig

PROVIDER_NAME = "grpc-mcp"


def _tool_catalog() -> list[Tool]:
    string: dict[str, Any] = {"type": "string"}
    obj: dict[str, Any] = {"type": "object"}
    call_props: dict[str, Any] = {
        "target": string,
        "method": string,
        "request": obj,
        "metadata": obj,
    }
    return [
        Tool(
            name="grpc.call",
            description="Invoke a unary gRPC method via server reflection.",
            inputSchema={"type": "object", "required": ["method"], "properties": call_props},
        ),
        Tool(
            name="grpc.assert_response",
            description="Invoke a unary method and assert a JSONPath on the response.",
            inputSchema={
                "type": "object",
                "required": ["method", "jsonpath", "equals"],
                "properties": {**call_props, "jsonpath": string, "equals": {}},
            },
        ),
    ]


def _require_grpc() -> tuple[Any, Any, Any]:
    try:
        grpc = importlib.import_module("grpc")
        reflection_pb2 = importlib.import_module("grpc_reflection.v1alpha.reflection_pb2")
        reflection_grpc = importlib.import_module("grpc_reflection.v1alpha.reflection_pb2_grpc")
    except ImportError as exc:  # pragma: no cover - depends on image build
        raise RuntimeError(
            "grpc-mcp requires 'grpcio' + 'grpcio-reflection' (bundle them in the runner image)"
        ) from exc
    return grpc, reflection_pb2, reflection_grpc


class GrpcServer:
    """``BundledServer`` for gRPC targets (lazy grpc + reflection)."""

    def __init__(self, provider: McpProviderConfig) -> None:
        self._provider = provider

    async def list_tools(self) -> list[Tool]:
        return _tool_catalog()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "grpc.call":
            payload = await self._invoke(arguments)
            return [TextContent(type="text", text=json.dumps(payload, default=str))]
        if name == "grpc.assert_response":
            return await self._assert_response(arguments)
        raise ValueError(f"unknown grpc-mcp tool: {name!r}")

    async def aclose(self) -> None:
        return None

    def _target(self, args: dict[str, Any]) -> str:
        target = args.get("target") or self._provider.config_json.get("target")
        target = target or self._provider.endpoint or ""
        if not target or str(target).startswith("in-process://"):
            raise RuntimeError("grpc-mcp requires a 'target' host:port (args or config_json)")
        return str(target)

    async def _invoke(
        self, args: dict[str, Any]
    ) -> dict[str, Any]:  # pragma: no cover - needs live gRPC
        grpc, _reflection_pb2, _reflection_grpc = _require_grpc()
        proto = importlib.import_module("google.protobuf.json_format")
        descriptor_pool = importlib.import_module("google.protobuf.descriptor_pool")
        message_factory = importlib.import_module("google.protobuf.message_factory")

        method = str(args["method"])
        if "/" not in method:
            raise ValueError("grpc method must be 'package.Service/Method'")
        service, method_name = method.rsplit("/", 1)
        target = self._target(args)

        async with grpc.aio.insecure_channel(target) as channel:
            pool = descriptor_pool.Default()
            method_desc = pool.FindMethodByName(f"{service}.{method_name}")
            req_cls = message_factory.GetMessageClass(method_desc.input_type)
            resp_cls = message_factory.GetMessageClass(method_desc.output_type)
            request = req_cls()
            if isinstance(args.get("request"), dict):
                proto.ParseDict(args["request"], request)
            callable_ = channel.unary_unary(
                f"/{method}",
                request_serializer=lambda m: m.SerializeToString(),
                response_deserializer=resp_cls.FromString,
            )
            metadata = list((args.get("metadata") or {}).items())
            response = await callable_(request, metadata=metadata)
            return {"response": proto.MessageToDict(response)}

    async def _assert_response(self, args: dict[str, Any]) -> list[TextContent]:  # pragma: no cover
        from jsonpath_ng.ext import parse as jsonpath_parse

        result = await self._invoke(args)
        matches = [m.value for m in jsonpath_parse(str(args["jsonpath"])).find(result["response"])]
        if not matches:
            raise AssertionError(f"grpc.assert_response: {args['jsonpath']!r} matched nothing")
        if matches[0] != args["equals"]:
            raise AssertionError(
                f"grpc.assert_response: {args['jsonpath']!r} = {matches[0]!r}, "
                f"expected {args['equals']!r}"
            )
        return [TextContent(type="text", text=json.dumps({"ok": True, "matched": matches[0]}))]


def build_grpc_server(provider: McpProviderConfig) -> BundledServer:
    return GrpcServer(provider)


register_bundled_builder(PROVIDER_NAME, build_grpc_server)
