"""Minimal Zod schema reader — extracts create-payload field shapes.

Lets the backend exporter synthesise *valid* request bodies (so generated CRUD
tests actually pass) without an LLM. Parses ``export const xSchema = z.object({…})``
blocks and reads each field's base type + ``optional``/``int``/``min`` markers.
Heuristic and intentionally conservative: unknown constructs are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SCHEMA_RE = re.compile(r"""export\s+const\s+(?P<name>\w+)\s*=\s*z\.object\(\{""")
# A field starts as `<name>: z` — the base type may be on the next line
# (`stock: z\n  .number()`), so we only anchor on `z` here and read the type
# from the field's segment.
_FIELD_START_RE = re.compile(r"""(?P<name>\b\w+)\s*:\s*z\b""")
_BASE_TYPE_RE = re.compile(r"""\.\s*(?P<type>string|number|boolean|date|array|enum|object|coerce)\b""")


@dataclass(frozen=True)
class ZodField:
    name: str
    base_type: str  # string | number | boolean | ...
    required: bool
    is_int: bool
    min_value: float | None


def _extract_object_body(text: str, open_index: int) -> str:
    """Return the substring inside the ``z.object({`` … ``})`` starting at open_index."""
    depth = 0
    i = open_index
    start = -1
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            if depth == 1:
                start = i + 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return ""


def _parse_fields(body: str) -> list[ZodField]:
    starts = list(_FIELD_START_RE.finditer(body))
    fields: list[ZodField] = []
    for idx, m in enumerate(starts):
        seg_end = starts[idx + 1].start() if idx + 1 < len(starts) else len(body)
        segment = body[m.start() : seg_end]
        name = m.group("name")
        type_match = _BASE_TYPE_RE.search(segment)
        if type_match is None:
            continue  # not a real field (e.g. a nested option object)
        base = type_match.group("type")
        if base == "coerce":
            inner = _BASE_TYPE_RE.search(segment[type_match.end() :])
            base = inner.group("type") if inner else "number"
        required = ".optional(" not in segment and ".nullable(" not in segment
        is_int = ".int(" in segment
        min_value: float | None = None
        mm = re.search(r"\.min\(\s*([0-9]+(?:\.[0-9]+)?)", segment)
        if mm:
            min_value = float(mm.group(1))
        fields.append(
            ZodField(name=name, base_type=base, required=required, is_int=is_int, min_value=min_value)
        )
    return fields


def find_create_schema(project_path: Path, resource: str) -> list[ZodField]:
    """Find the create-payload fields for ``resource`` (e.g. 'products').

    Looks for a schema whose name contains 'create' and the singular/plural of
    the resource (``createProductSchema`` for resource ``products``). Falls back
    to the first ``create*Schema`` found.
    """
    src = project_path / "src"
    if not src.is_dir():
        src = project_path
    singular = resource[:-1] if resource.endswith("s") else resource
    best: list[ZodField] | None = None
    fallback: list[ZodField] | None = None

    for f in sorted(src.rglob("*.ts")):
        if ".d.ts" in f.name:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for m in _SCHEMA_RE.finditer(text):
            name = m.group("name")
            body = _extract_object_body(text, m.end() - 1)
            fields = _parse_fields(body)
            if not fields:
                continue
            lname = name.lower()
            if "create" in lname and (singular in lname or resource in lname):
                best = fields
            elif "create" in lname and fallback is None:
                fallback = fields
    return best if best is not None else (fallback or [])


def sample_value(field: ZodField, unique_token: str) -> object:
    """Produce a valid Python value for a field (used to build request bodies)."""
    if field.base_type == "string":
        if field.name.lower() == "sku":
            return f"SKU-{unique_token}"
        if field.name.lower() in {"email"}:
            return f"user_{unique_token}@example.com"
        min_len = int(field.min_value or 0)
        base = f"Sutest {field.name.title()}"
        return base if len(base) >= min_len else base + "x" * (min_len - len(base))
    if field.base_type == "number":
        base_num = field.min_value if field.min_value is not None else 1
        return int(base_num) + 9 if field.is_int else float(base_num) + 9.99
    if field.base_type == "boolean":
        return True
    return f"val_{unique_token}"
