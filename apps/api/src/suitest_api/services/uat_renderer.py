"""Render a UatDocument to a branded PDF with fpdf2 (pure-Python, no system libs).

Chosen over WeasyPrint deliberately: the export must run both in Docker AND in the
npx local bundle (uvicorn on a user laptop, deps from wheels). fpdf2 + Pillow are
self-contained wheels; WeasyPrint would need native pango/cairo that a bare laptop
lacks. Deterministic, ZERO-tier. Labels are a small in-module locale dict.

Layout reproduces sample-dokumen-uat.pdf: navy banner title, document subtitle,
date + pass %, then one navy-headed table per suite section with a green/red/amber
status cell and an embedded screenshot in the Evidence column.
"""

from __future__ import annotations

import base64
from io import BytesIO

from fpdf import FPDF
from fpdf.fonts import FontFace

from suitest_api.services.uat_document import UatDocument

_NAVY = (31, 58, 95)
_NAVY2 = (51, 80, 122)
_WHITE = (255, 255, 255)
_STATUS_COLOR = {"PASSED": (21, 128, 61), "FAILED": (185, 28, 28), "NOT RUN": (161, 98, 7)}

_LABELS: dict[str, dict[str, str]] = {
    "id": {
        "doc_title": "BERITA ACARA USER ACCEPTANCE TEST (UAT)",
        "no": "No",
        "modul": "Modul/ Fitur",
        "test_case": "Test Case",
        "test_step": "Test Step",
        "test_result": "Test Result",
        "status": "Status",
        "evidence": "Evidence",
        "result_percent": "Persentase",
        "generated": "Tanggal",
        "not_run": "BELUM DIJALANKAN",
    },
    "en": {
        "doc_title": "USER ACCEPTANCE TEST (UAT) REPORT",
        "no": "No",
        "modul": "Module / Feature",
        "test_case": "Test Case",
        "test_step": "Test Step",
        "test_result": "Test Result",
        "status": "Status",
        "evidence": "Evidence",
        "result_percent": "Pass rate",
        "generated": "Date",
        "not_run": "NOT RUN",
    },
}


class _UatPdf(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(136, 136, 136)
        self.cell(0, 8, "Powered by Suiflex  -  Suitest", align="C")


def _first_image(evidence: list[str]) -> BytesIO | None:
    """Decode the first evidence data-URI to a stream fpdf2 can embed; None on failure."""
    if not evidence:
        return None
    try:
        b64 = evidence[0].split(",", 1)[1]
        return BytesIO(base64.b64decode(b64))
    except Exception:  # bad/absent image must never break the export
        return None


def render_pdf(doc: UatDocument) -> bytes:
    """Render the document to PDF bytes (fpdf2). Pure, deterministic, ZERO-tier."""
    labels = _LABELS.get(doc.locale, _LABELS["id"])
    pdf = _UatPdf(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    # Banner + subtitle + meta line.
    pdf.set_fill_color(*_NAVY)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 12, labels["doc_title"], align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_NAVY)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, doc.title, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(
        0,
        6,
        f"{labels['generated']}: {doc.generated_at}    {labels['result_percent']}: {doc.pass_pct}%",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)

    headings = [
        labels[k]
        for k in ("no", "modul", "test_case", "test_step", "test_result", "status", "evidence")
    ]
    for section in doc.sections:
        pdf.set_fill_color(*_NAVY2)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, section.module_name, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 8)
        with pdf.table(
            col_widths=(6, 16, 22, 30, 30, 12, 24),
            text_align=("CENTER", "LEFT", "LEFT", "LEFT", "LEFT", "CENTER", "CENTER"),
            headings_style=FontFace(emphasis="BOLD", color=_WHITE, fill_color=_NAVY2),
            line_height=5,
        ) as table:
            table.row(headings)
            for r in section.rows:
                row = table.row()
                row.cell(str(r.no))
                row.cell(r.modul_fitur)
                row.cell(r.test_case)
                row.cell("\n".join(f"{i}. {s}" for i, s in enumerate(r.steps, 1)))
                row.cell("\n".join(f"{i}. {s}" for i, s in enumerate(r.results, 1)))
                disp = labels["not_run"] if r.status == "NOT RUN" else r.status
                row.cell(disp, style=FontFace(emphasis="BOLD", color=_STATUS_COLOR[r.status]))
                img = _first_image(r.evidence)
                if img is not None:
                    row.cell(img=img, img_fill_width=True)
                else:
                    row.cell("")

    return bytes(pdf.output())
