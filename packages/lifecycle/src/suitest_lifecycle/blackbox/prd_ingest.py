"""Uploaded-PRD ingestion — markdown in, structured requirements out.

TestSprite-parity flow: the user brings a **markdown** product spec (that is
the required format); Suitest turns it into a test plan. Parsing here is
deterministic (stdlib only) — headings become features, bullet lines become
requirements — so the artifact is stable context for the LLM planner and
readable on its own in ``prd_ingest.json``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")


@dataclass
class PrdSection:
    heading: str
    level: int
    requirements: list[str] = field(default_factory=list)
    text: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PrdDocument:
    title: str = ""
    source_file: str = ""
    sections: list[PrdSection] = field(default_factory=list)

    @property
    def requirements(self) -> list[str]:
        return [r for s in self.sections for r in s.requirements]

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "sourceFile": self.source_file,
            "sections": [s.to_json() for s in self.sections],
            "requirementCount": len(self.requirements),
        }

    def as_prompt_context(self, *, max_chars: int = 12_000) -> str:
        """Compact PRD rendering for the LLM planner prompt."""
        lines: list[str] = [f"PRD: {self.title}" if self.title else "PRD"]
        for s in self.sections:
            lines.append(f"\n{'#' * max(s.level, 1)} {s.heading}")
            if s.text:
                lines.append(s.text)
            for r in s.requirements:
                lines.append(f"- {r}")
        return "\n".join(lines)[:max_chars]


def parse_prd_markdown(text: str, *, source_file: str = "") -> PrdDocument:
    doc = PrdDocument(source_file=source_file)
    current: PrdSection | None = None
    prose: list[str] = []

    def flush_prose() -> None:
        nonlocal prose
        if current is not None and prose:
            current.text = " ".join(prose)[:600]
        prose = []

    for raw in text.splitlines():
        line = raw.rstrip()
        m = _HEADING.match(line)
        if m:
            flush_prose()
            level = len(m.group(1))
            heading = m.group(2).strip()
            if not doc.title and level == 1:
                doc.title = heading
                current = None
                continue
            current = PrdSection(heading=heading, level=level)
            doc.sections.append(current)
            continue
        b = _BULLET.match(line)
        if b and current is not None:
            current.requirements.append(b.group(1)[:300])
            continue
        if line.strip() and current is not None:
            prose.append(line.strip())
    flush_prose()

    # PRD with no headings at all → one implicit section from the whole body.
    if not doc.sections and text.strip():
        doc.sections.append(PrdSection(heading="Requirements", level=2, text=text.strip()[:600]))
    return doc


def load_prd(path: str | Path) -> PrdDocument:
    p = Path(path)
    if p.suffix.lower() not in (".md", ".markdown"):
        raise ValueError(f"PRD must be a markdown file (.md), got: {p.name}")
    return parse_prd_markdown(p.read_text(encoding="utf-8"), source_file=str(p))


__all__ = ["PrdDocument", "PrdSection", "load_prd", "parse_prd_markdown"]
