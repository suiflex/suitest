"""``suitest-output/`` directory layout.

Mirrors the TestSprite ``testsprite_tests/`` folder (PRD + plan + ``TCxxx.py``
at top level, ``tmp/`` for code-summary / config snapshot / results / report)
but rooted at a single ``suitest-output/`` tree so a repo stays clean::

    suitest-output/
      backend/  (or frontend/)
        standard_prd.json
        suitest_backend_test_plan.json
        TC001_*.py ...
        tmp/
          code_summary.json
          config.snapshot.json
          test_results.json
          raw_report.md
      tcm/                 ← source-of-truth mirror (cases.json, runs.json)
      reports/             ← summary.{md,json,html}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suitest_lifecycle.models import Mode


@dataclass(frozen=True)
class Paths:
    root: Path
    mode_dir: Path
    tmp_dir: Path
    tcm_dir: Path
    reports_dir: Path
    mode: Mode

    @property
    def prd_json(self) -> Path:
        return self.mode_dir / "standard_prd.json"

    @property
    def test_plan_json(self) -> Path:
        return self.mode_dir / f"suitest_{self.mode.value}_test_plan.json"

    @property
    def code_summary_json(self) -> Path:
        return self.tmp_dir / "code_summary.json"

    @property
    def config_snapshot_json(self) -> Path:
        return self.tmp_dir / "config.snapshot.json"

    @property
    def test_results_json(self) -> Path:
        return self.tmp_dir / "test_results.json"

    @property
    def raw_report_md(self) -> Path:
        return self.tmp_dir / "raw_report.md"

    @property
    def tcm_cases_json(self) -> Path:
        return self.tcm_dir / "cases.json"

    @property
    def tcm_runs_json(self) -> Path:
        return self.tcm_dir / "runs.json"

    def test_file(self, filename: str) -> Path:
        return self.mode_dir / filename

    def ensure(self) -> None:
        for d in (self.mode_dir, self.tmp_dir, self.tcm_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)


def build_paths(output_dir: Path, mode: Mode) -> Paths:
    root = Path(output_dir)
    mode_dir = root / mode.value
    return Paths(
        root=root,
        mode_dir=mode_dir,
        tmp_dir=mode_dir / "tmp",
        tcm_dir=root / "tcm",
        reports_dir=root / "reports",
        mode=mode,
    )
