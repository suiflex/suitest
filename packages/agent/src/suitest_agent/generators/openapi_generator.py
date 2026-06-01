"""Deterministic OpenAPI 3.0 → per-operation contract suite (M2 Task 2).

Pure rules, NO LLM — runs in every tier. Given an OpenAPI 3.0 document the
generator walks every operation and synthesises one or more
:class:`~suitest_shared.schemas.generator_input.TestCaseDraft`s targeting the
``api-http-mcp`` provider. Case kinds (each gated by
:class:`OpenApiGeneratorOptions`):

* ``contract`` — happy path, expects the operation's success status (and, when
  enabled, validates the response body against its declared JSON schema).
* ``auth_negative`` — missing + invalid bearer token, expects 401/403 (only
  when the operation or the spec declares security).
* ``required_field`` — one case per required request-body field, omitting just
  that field, expects 4xx.
* ``boundary`` — numeric/string min-1 / max+1 / empty / over-long, expects 4xx.
* ``rate_limit`` — issues ``limit + 1`` requests, expects 429 (only when a
  response documents ``x-ratelimit-*`` headers or a ``429`` status).

The emitted ``step.code`` is literal Python the runner ``exec``s against the
``mcp.api.request(...)`` tool. It carries Jinja-style ``{{ ... }}`` placeholders
(``{{base_url}}``, ``{{auth.token}}``, ``{{uuid}}``) the runner resolves at
runtime — see plan-06 §2.3.3. The renderer NEVER emits ``eval``/``__import__``;
the only callables referenced are ``mcp.api.request`` and ``validate_jsonschema``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from faker import Faker
from openapi_pydantic.v3.v3_0 import OpenAPI, Operation, PathItem
from suitest_shared.domain.enums import CaseSource, Priority, TargetKind
from suitest_shared.schemas.generator_input import (
    OpenApiGeneratorOptions,
    TestCaseDraft,
    TestStepDraft,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    import httpx

# HTTP methods we generate against, in deterministic emission order.
_HTTP_METHODS: tuple[str, ...] = ("get", "post", "put", "patch", "delete")

# Runtime placeholders resolved by the runner (M1c). Kept as module constants so
# the renderer and tests agree on the exact literal token strings.
_BASE_URL = "{{base_url}}"
_AUTH_TOKEN = "{{auth.token}}"
_UUID = "{{uuid}}"

# Provider every generated step routes through (api-http-mcp, BE_REST).
_PROVIDER = "api-http-mcp"

# Number of requests a rate-limit case fires when the spec documents no explicit
# limit value — enough to trip a typical small bucket without being abusive.
_DEFAULT_RATE_LIMIT_PROBE = 5


class OpenApiSpecError(ValueError):
    """Raised when a spec cannot be fetched or parsed into a valid OpenAPI doc."""


JsonObj = dict[str, object]


class OpenApiGenerator:
    """Stateful per-request generator. Reusable across one generation only.

    ``Faker`` is seeded deterministically so identical specs + options produce
    byte-identical example bodies — the suite is reproducible (a generated case
    diff means the spec actually changed, not the RNG).
    """

    def __init__(self, http_client: httpx.AsyncClient, options: OpenApiGeneratorOptions) -> None:
        self._http = http_client
        self._options = options
        self._faker = Faker()
        self._faker.seed_instance(1337)
        self._spec: OpenAPI | None = None
        self._raw: JsonObj = {}
        self._spec_url: str | None = None

    # ------------------------------------------------------------------
    # Spec ingestion
    # ------------------------------------------------------------------

    async def fetch_spec(self, spec_url: str | None, spec_content: str | None) -> OpenAPI:
        """Load + parse the spec from ``spec_url`` (fetched) or ``spec_content``.

        Accepts JSON or YAML content. Raises :class:`OpenApiSpecError` on any
        network, decode, or schema-validation failure so the service can stream a
        single structured ``error`` event and close.
        """
        if spec_content is not None:
            raw_text = spec_content
        elif spec_url is not None:
            try:
                resp = await self._http.get(spec_url)
                resp.raise_for_status()
            except Exception as exc:
                raise OpenApiSpecError(f"failed to fetch spec from {spec_url}: {exc}") from exc
            raw_text = resp.text
            self._spec_url = spec_url
        else:
            raise OpenApiSpecError("either spec_url or spec_content is required")

        raw = self._decode(raw_text)
        try:
            spec = OpenAPI.model_validate(raw)
        except Exception as exc:
            raise OpenApiSpecError(f"invalid OpenAPI 3.0 document: {exc}") from exc
        self._spec = spec
        self._raw = raw
        return spec

    @staticmethod
    def _decode(raw_text: str) -> JsonObj:
        """Parse ``raw_text`` as JSON, falling back to YAML."""
        try:
            parsed: object = json.loads(raw_text)
        except json.JSONDecodeError:
            try:
                import yaml

                parsed = yaml.safe_load(raw_text)
            except Exception as exc:
                raise OpenApiSpecError(f"spec is neither valid JSON nor YAML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise OpenApiSpecError("spec root must be a mapping")
        return cast("JsonObj", parsed)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate(self) -> AsyncIterator[TestCaseDraft]:
        """Yield every :class:`TestCaseDraft` for the loaded spec.

        Async-generator so the service can persist + stream each draft as it is
        produced (back-pressure friendly for large specs).
        """
        if self._spec is None:
            raise OpenApiSpecError("call fetch_spec() before generate()")

        spec_security = self._spec.security or []
        raw_paths = self._raw_paths()

        for path, path_item in self._iter_paths():
            raw_path_item = raw_paths.get(path, {})
            for method in _HTTP_METHODS:
                operation = getattr(path_item, method, None)
                if operation is None:
                    continue
                if not self._tag_allowed(operation):
                    continue
                raw_op = self._raw_operation(raw_path_item, method)
                for draft in self._generate_for_operation(
                    method=method,
                    path=path,
                    operation=operation,
                    raw_op=raw_op,
                    spec_security=spec_security,
                ):
                    yield draft

    def op_summaries(self) -> list[str]:
        """Compact ``METHOD path — summary (params)`` lines for LLM enrichment.

        Honours ``tags_filter`` so the enricher (M3-8) sees the same operation
        set the deterministic suite covered. Used to ground the edge-case prompt
        without shipping the entire (possibly huge) raw spec to the model.
        """
        if self._spec is None:
            raise OpenApiSpecError("call fetch_spec() before op_summaries()")
        lines: list[str] = []
        for path, path_item in self._iter_paths():
            for method in _HTTP_METHODS:
                operation = getattr(path_item, method, None)
                if operation is None or not self._tag_allowed(operation):
                    continue
                summary = operation.summary or operation.operationId or ""
                params = [p.name for p in (operation.parameters or []) if getattr(p, "name", None)]
                suffix = f" (params: {', '.join(params)})" if params else ""
                lines.append(f"{method.upper()} {path} — {summary}{suffix}".rstrip())
        return lines

    def _iter_paths(self) -> list[tuple[str, PathItem]]:
        assert self._spec is not None
        paths = self._spec.paths or {}
        return sorted(paths.items())

    def _raw_paths(self) -> dict[str, JsonObj]:
        raw_paths = self._raw.get("paths")
        if not isinstance(raw_paths, dict):
            return {}
        return {k: v for k, v in raw_paths.items() if isinstance(v, dict)}

    @staticmethod
    def _raw_operation(raw_path_item: JsonObj, method: str) -> JsonObj:
        op = raw_path_item.get(method)
        return op if isinstance(op, dict) else {}

    def _tag_allowed(self, operation: Operation) -> bool:
        if not self._options.tags_filter:
            return True
        op_tags = set(operation.tags or [])
        return bool(op_tags & set(self._options.tags_filter))

    # ------------------------------------------------------------------
    # Per-operation case synthesis
    # ------------------------------------------------------------------

    def _generate_for_operation(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        raw_op: JsonObj,
        spec_security: Sequence[object],
    ) -> list[TestCaseDraft]:
        drafts: list[TestCaseDraft] = []
        cap = self._options.max_cases_per_operation

        success_status = self._success_status(raw_op)
        body_schema = self._request_body_schema(raw_op)
        secured = bool(operation.security) or bool(spec_security)

        # 1. contract (always) ------------------------------------------------
        drafts.append(
            self._contract_case(
                method=method,
                path=path,
                operation=operation,
                body_schema=body_schema,
                success_status=success_status,
                secured=secured,
                raw_op=raw_op,
            )
        )

        # 2. auth_negative ----------------------------------------------------
        if self._options.include_negative_auth and secured:
            drafts.extend(
                self._auth_negative_cases(
                    method=method,
                    path=path,
                    operation=operation,
                    body_schema=body_schema,
                )
            )

        # 3. required_field ---------------------------------------------------
        if self._options.include_required_field_tests and body_schema is not None:
            drafts.extend(
                self._required_field_cases(
                    method=method,
                    path=path,
                    operation=operation,
                    body_schema=body_schema,
                    secured=secured,
                )
            )

        # 4. boundary ---------------------------------------------------------
        if self._options.include_boundary_tests and body_schema is not None:
            drafts.extend(
                self._boundary_cases(
                    method=method,
                    path=path,
                    operation=operation,
                    body_schema=body_schema,
                    secured=secured,
                )
            )

        # 5. rate_limit -------------------------------------------------------
        if self._options.include_rate_limit_tests and self._has_rate_limit(raw_op):
            drafts.append(
                self._rate_limit_case(
                    method=method,
                    path=path,
                    operation=operation,
                    body_schema=body_schema,
                    secured=secured,
                    raw_op=raw_op,
                )
            )

        return drafts[:cap]

    # -- case builders -----------------------------------------------------

    def _contract_case(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        body_schema: JsonObj | None,
        success_status: int,
        secured: bool,
        raw_op: JsonObj,
    ) -> TestCaseDraft:
        body = self._build_example_body(body_schema) if body_schema is not None else None
        response_schema = (
            self._success_response_schema(raw_op)
            if self._options.include_schema_validation
            else None
        )
        code = self._render_request_code(
            method=method,
            path=path,
            body=body,
            expected_status=success_status,
            secured=secured,
            response_schema=response_schema,
        )
        return self._draft(
            method=method,
            path=path,
            operation=operation,
            case_kind="contract",
            expected=f"Responds {success_status} with a schema-valid body",
            code=code,
            data={"body": body} if body is not None else None,
        )

    def _auth_negative_cases(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        body_schema: JsonObj | None,
    ) -> list[TestCaseDraft]:
        body = self._build_example_body(body_schema) if body_schema is not None else None
        cases: list[TestCaseDraft] = []
        for label, token in (("missing", None), ("invalid", "xxxx")):
            code = self._render_request_code(
                method=method,
                path=path,
                body=body,
                expected_status=(401, 403),
                secured=True,
                auth_token_override=token,
            )
            cases.append(
                self._draft(
                    method=method,
                    path=path,
                    operation=operation,
                    case_kind="auth_negative",
                    name_suffix=label,
                    expected="Rejects unauthenticated request with 401 or 403",
                    code=code,
                )
            )
        return cases

    def _required_field_cases(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        body_schema: JsonObj,
        secured: bool,
    ) -> list[TestCaseDraft]:
        required = body_schema.get("required")
        if not isinstance(required, list):
            return []
        full = self._build_example_body(body_schema)
        cases: list[TestCaseDraft] = []
        for field in required:
            if not isinstance(field, str) or not isinstance(full, dict):
                continue
            partial = {k: v for k, v in full.items() if k != field}
            code = self._render_request_code(
                method=method,
                path=path,
                body=partial,
                expected_status=(400, 422),
                secured=secured,
            )
            cases.append(
                self._draft(
                    method=method,
                    path=path,
                    operation=operation,
                    case_kind="required_field",
                    name_suffix=f"missing {field}",
                    expected=f"Rejects body missing required field '{field}' with 4xx",
                    code=code,
                    data={"omitted_field": field, "body": partial},
                )
            )
        return cases

    def _boundary_cases(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        body_schema: JsonObj,
        secured: bool,
    ) -> list[TestCaseDraft]:
        properties = body_schema.get("properties")
        if not isinstance(properties, dict):
            return []
        full = self._build_example_body(body_schema)
        base: JsonObj = full if isinstance(full, dict) else {}
        cases: list[TestCaseDraft] = []
        for field_name, field_schema in properties.items():
            if not isinstance(field_schema, dict):
                continue
            for label, value in self._boundary_values(field_schema):
                violating = dict(base)
                violating[field_name] = value
                code = self._render_request_code(
                    method=method,
                    path=path,
                    body=violating,
                    expected_status=(400, 422),
                    secured=secured,
                )
                cases.append(
                    self._draft(
                        method=method,
                        path=path,
                        operation=operation,
                        case_kind="boundary",
                        name_suffix=f"{field_name} {label}",
                        expected=(f"Rejects out-of-range '{field_name}' ({label}) with 4xx"),
                        code=code,
                        data={"field": field_name, "violation": label, "body": violating},
                    )
                )
        return cases

    def _rate_limit_case(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        body_schema: JsonObj | None,
        secured: bool,
        raw_op: JsonObj,
    ) -> TestCaseDraft:
        body = self._build_example_body(body_schema) if body_schema is not None else None
        limit = self._documented_rate_limit(raw_op) or _DEFAULT_RATE_LIMIT_PROBE
        # One step per probe request; the final request expects 429.
        steps: list[TestStepDraft] = []
        for i in range(limit + 1):
            is_last = i == limit
            code = self._render_request_code(
                method=method,
                path=path,
                body=body,
                expected_status=429 if is_last else None,
                secured=secured,
            )
            steps.append(
                TestStepDraft(
                    order=i + 1,
                    action=f"Issue request {i + 1} of {limit + 1} to {method.upper()} {path}",
                    expected=(
                        "Server returns 429 Too Many Requests once the rate limit is exceeded"
                        if is_last
                        else "Request accepted (under the rate limit)"
                    ),
                    code=code,
                    mcp_provider=_PROVIDER,
                    target_kind=TargetKind.BE_REST,
                    data={"body": body} if body is not None else None,
                )
            )
        return TestCaseDraft(
            name=f"{method.upper()} {path} — rate_limit",
            description=(
                f"Fires {limit + 1} requests to verify the documented rate limit "
                "enforces a 429 response."
            ),
            priority=Priority.P2,
            source=CaseSource.MCP,
            target_kind=TargetKind.BE_REST,
            tags=self._tags(path),
            generated_from=self._provenance(method, path, operation, "rate_limit"),
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Draft + step assembly
    # ------------------------------------------------------------------

    def _draft(
        self,
        *,
        method: str,
        path: str,
        operation: Operation,
        case_kind: str,
        expected: str,
        code: str,
        name_suffix: str | None = None,
        data: JsonObj | None = None,
    ) -> TestCaseDraft:
        title = f"{method.upper()} {path} — {case_kind}"
        if name_suffix:
            title = f"{title} ({name_suffix})"
        summary = operation.summary or operation.description or ""
        description = f"{case_kind} test for {method.upper()} {path}."
        if summary:
            description = f"{description} {summary}".strip()
        return TestCaseDraft(
            name=title,
            description=description,
            priority=Priority.P2,
            source=CaseSource.MCP,
            target_kind=TargetKind.BE_REST,
            tags=self._tags(path),
            generated_from=self._provenance(method, path, operation, case_kind),
            steps=[
                TestStepDraft(
                    order=1,
                    action=f"Send {method.upper()} {path}",
                    expected=expected,
                    code=code,
                    mcp_provider=_PROVIDER,
                    target_kind=TargetKind.BE_REST,
                    data=data,
                )
            ],
        )

    def _tags(self, path: str) -> list[str]:
        segment = path.split("/")[1] if "/" in path and len(path.split("/")) > 1 else "api"
        segment = segment or "api"
        tags = ["api-contract", segment]
        if self._options.tag_prefix:
            tags = [self._options.tag_prefix, *tags]
        return tags

    def _provenance(self, method: str, path: str, operation: Operation, case_kind: str) -> JsonObj:
        return {
            "source": "OPENAPI",
            "operation_id": operation.operationId,
            "path": path,
            "method": method,
            "case_kind": case_kind,
            "spec_url": self._spec_url,
        }

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    def _success_status(self, raw_op: JsonObj) -> int:
        responses = raw_op.get("responses")
        if not isinstance(responses, dict):
            return 200
        for code in responses:
            if isinstance(code, str) and code.startswith("2") and code.isdigit():
                return int(code)
        return 200

    def _request_body_schema(self, raw_op: JsonObj) -> JsonObj | None:
        request_body = raw_op.get("requestBody")
        if not isinstance(request_body, dict):
            return None
        content = request_body.get("content")
        if not isinstance(content, dict):
            return None
        media = content.get("application/json")
        if not isinstance(media, dict):
            return None
        schema = media.get("schema")
        if not isinstance(schema, dict):
            return None
        return self._resolve_ref(schema)

    def _success_response_schema(self, raw_op: JsonObj) -> JsonObj | None:
        responses = raw_op.get("responses")
        if not isinstance(responses, dict):
            return None
        for code, response in responses.items():
            if not (isinstance(code, str) and code.startswith("2")):
                continue
            if not isinstance(response, dict):
                continue
            content = response.get("content")
            if not isinstance(content, dict):
                continue
            media = content.get("application/json")
            if not isinstance(media, dict):
                continue
            schema = media.get("schema")
            if isinstance(schema, dict):
                return self._resolve_ref(schema)
        return None

    def _resolve_ref(self, schema: JsonObj, _depth: int = 0) -> JsonObj:
        """Resolve a top-level ``$ref`` against ``components/schemas`` (one hop).

        Guards against runaway recursion (self-referential schemas) via a depth
        cap; circular refs resolve to the last seen node rather than looping.
        """
        if _depth > 8:
            return schema
        ref = schema.get("$ref")
        if not isinstance(ref, str):
            return schema
        prefix = "#/components/schemas/"
        if not ref.startswith(prefix):
            return schema
        name = ref[len(prefix) :]
        components = self._raw.get("components")
        if not isinstance(components, dict):
            return schema
        schemas = components.get("schemas")
        if not isinstance(schemas, dict):
            return schema
        target = schemas.get(name)
        if not isinstance(target, dict):
            return schema
        return self._resolve_ref(target, _depth + 1)

    def _has_rate_limit(self, raw_op: JsonObj) -> bool:
        responses = raw_op.get("responses")
        if not isinstance(responses, dict):
            return False
        for code, response in responses.items():
            if code == "429":
                return True
            if not isinstance(response, dict):
                continue
            headers = response.get("headers")
            if isinstance(headers, dict) and any(
                isinstance(h, str) and h.lower().startswith("x-ratelimit") for h in headers
            ):
                return True
        return False

    def _documented_rate_limit(self, raw_op: JsonObj) -> int | None:
        responses = raw_op.get("responses")
        if not isinstance(responses, dict):
            return None
        for response in responses.values():
            if not isinstance(response, dict):
                continue
            headers = response.get("headers")
            if not isinstance(headers, dict):
                continue
            for name, header in headers.items():
                if not (isinstance(name, str) and name.lower() == "x-ratelimit-limit"):
                    continue
                if isinstance(header, dict):
                    example = header.get("example")
                    if isinstance(example, int):
                        return example
                    if isinstance(example, str) and example.isdigit():
                        return int(example)
        return None

    # ------------------------------------------------------------------
    # Example body synthesis
    # ------------------------------------------------------------------

    def _build_example_body(self, schema: JsonObj | None) -> object:
        """Synthesise a JSON-serialisable example value for ``schema``.

        Preference order: explicit ``example`` → first of ``examples`` → recurse
        by ``type`` with format-aware Faker fallbacks. ``required`` keys are
        always present in generated objects.
        """
        if schema is None:
            return None
        resolved = self._resolve_ref(schema)
        return self._build_value(resolved, _depth=0)

    def _build_value(self, schema: JsonObj, *, _depth: int) -> object:
        if _depth > 8:
            return None
        schema = self._resolve_ref(schema)

        if "example" in schema:
            return schema["example"]
        examples = schema.get("examples")
        if isinstance(examples, list) and examples:
            return examples[0]

        # allOf — shallow-merge member objects (deterministic union).
        all_of = schema.get("allOf")
        if isinstance(all_of, list) and all_of:
            merged: JsonObj = {}
            for member in all_of:
                if isinstance(member, dict):
                    value = self._build_value(member, _depth=_depth + 1)
                    if isinstance(value, dict):
                        merged.update(value)
            if merged:
                return merged
        for combinator in ("anyOf", "oneOf"):
            variants = schema.get(combinator)
            if isinstance(variants, list) and variants and isinstance(variants[0], dict):
                return self._build_value(variants[0], _depth=_depth + 1)

        enum = schema.get("enum")
        if isinstance(enum, list) and enum:
            return enum[0]

        schema_type = schema.get("type")
        if schema_type == "object" or "properties" in schema:
            return self._build_object(schema, _depth=_depth)
        if schema_type == "array":
            items = schema.get("items")
            inner = self._build_value(items, _depth=_depth + 1) if isinstance(items, dict) else "x"
            return [inner]
        if schema_type == "integer":
            return self._build_integer(schema)
        if schema_type == "number":
            return self._build_number(schema)
        if schema_type == "boolean":
            return True
        if schema_type == "string":
            return self._build_string(schema)
        # Unknown / untyped — a string keeps the body JSON-serialisable.
        return "value"

    def _build_object(self, schema: JsonObj, *, _depth: int) -> JsonObj:
        result: JsonObj = {}
        properties = schema.get("properties")
        required = schema.get("required")
        required_keys = (
            {k for k in required if isinstance(k, str)} if isinstance(required, list) else set()
        )
        if isinstance(properties, dict):
            for name, prop in properties.items():
                if not isinstance(name, str) or not isinstance(prop, dict):
                    continue
                result[name] = self._build_value(prop, _depth=_depth + 1)
            # Required keys missing from properties still get a placeholder.
            for name in required_keys:
                if name not in result:
                    result[name] = "value"
        return result

    def _build_integer(self, schema: JsonObj) -> int:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        lo = minimum if isinstance(minimum, int) else 0
        hi = maximum if isinstance(maximum, int) else max(lo, 100)
        if hi < lo:
            hi = lo
        return int(self._faker.random_int(min=lo, max=hi))

    def _build_number(self, schema: JsonObj) -> float:
        return float(self._build_integer(schema))

    def _build_string(self, schema: JsonObj) -> str:
        fmt = schema.get("format")
        if fmt == "email":
            return f"test+{_UUID}@example.com"
        if fmt == "uuid":
            return _UUID
        if fmt in ("date-time", "date"):
            return "2026-01-01T00:00:00Z" if fmt == "date-time" else "2026-01-01"
        if fmt == "uri" or fmt == "url":
            return "https://example.com/resource"
        min_length = schema.get("minLength")
        base = self._faker.word()
        if isinstance(min_length, int) and len(base) < min_length:
            base = base + "x" * (min_length - len(base))
        max_length = schema.get("maxLength")
        if isinstance(max_length, int) and len(base) > max_length:
            base = base[:max_length]
        return base

    # ------------------------------------------------------------------
    # Boundary value enumeration
    # ------------------------------------------------------------------

    def _boundary_values(self, schema: JsonObj) -> list[tuple[str, object]]:
        resolved = self._resolve_ref(schema)
        schema_type = resolved.get("type")
        values: list[tuple[str, object]] = []
        if schema_type in ("integer", "number"):
            minimum = resolved.get("minimum")
            maximum = resolved.get("maximum")
            if isinstance(minimum, int | float):
                values.append(("below minimum", minimum - 1))
            if isinstance(maximum, int | float):
                values.append(("above maximum", maximum + 1))
        elif schema_type == "string":
            min_length = resolved.get("minLength")
            max_length = resolved.get("maxLength")
            if isinstance(min_length, int) and min_length >= 1:
                values.append(("empty string", ""))
            if isinstance(max_length, int):
                values.append(("over max length", "x" * (max_length + 1)))
        return values

    # ------------------------------------------------------------------
    # Code rendering
    # ------------------------------------------------------------------

    def _render_request_code(
        self,
        *,
        method: str,
        path: str,
        body: object,
        expected_status: int | tuple[int, ...] | None,
        secured: bool,
        response_schema: JsonObj | None = None,
        auth_token_override: str | None | object = _UUID,
    ) -> str:
        """Emit runner-executable Python for one ``mcp.api.request(...)`` call.

        ``auth_token_override`` controls the ``Authorization`` header for the
        negative-auth cases: the sentinel default keeps the ``{{auth.token}}``
        placeholder; ``None`` omits the header (missing-token case); a literal
        string injects an explicit bogus token (invalid-token case). No ``eval``
        or ``__import__`` is ever emitted — only ``mcp.api.request`` and
        ``validate_jsonschema`` are referenced.
        """
        url = f"{_BASE_URL}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if secured:
            if auth_token_override is _UUID:
                headers["Authorization"] = f"Bearer {_AUTH_TOKEN}"
            elif isinstance(auth_token_override, str):
                headers["Authorization"] = f"Bearer {auth_token_override}"
            # auth_token_override is None → omit Authorization (missing-token case)

        lines: list[str] = [
            "response = await mcp.api.request(",
            f"    method={method.upper()!r},",
            f"    url={url!r},",
            f"    headers={headers!r},",
        ]
        if body is not None:
            lines.append(f"    body={body!r},")
        lines.append(")")

        if expected_status is None:
            lines.append("# transitional request (no status assertion)")
        elif isinstance(expected_status, tuple):
            allowed = ", ".join(str(s) for s in expected_status)
            lines.append(
                f"assert response.status in ({allowed}), "
                f'f"Expected one of ({allowed}), got {{response.status}}"'
            )
        else:
            lines.append(
                f"assert response.status == {expected_status}, "
                f'f"Expected {expected_status}, got {{response.status}}"'
            )

        if response_schema is not None:
            schema_literal = json.dumps(response_schema, sort_keys=True)
            lines.append(f"assert validate_jsonschema(response.body, {schema_literal!r})")

        return "\n".join(lines)
