"""Render a UatDocument to a branded PDF with fpdf2 (pure-Python, no system libs).

Chosen over WeasyPrint deliberately: the export must run both in Docker AND in the
npx local bundle (uvicorn on a user laptop, deps from wheels). fpdf2 + Pillow are
self-contained wheels; WeasyPrint would need native pango/cairo that a bare laptop
lacks. Deterministic, ZERO-tier. Labels are a small in-module locale dict.

Document structure (sign-off grade, mirrors sample-dokumen-uat.pdf plus the
Suiflex brand cover):

1. Cover      — dark brand page: Suitest mark, eyebrow, title, project, date.
2. Summary    — document info, per-status counts, scope table, status legend.
3. Results    — one navy-headed table per suite section, white/zebra body, an
                embedded screenshot in the Evidence column.
4. Sign-off   — prepared / reviewed / approved boxes.

Every page after the cover carries a running header and a "Powered by Suiflex"
footer with ``page N of M``.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace
from PIL import Image

from suitest_api.services.uat_document import UatDocument

_NAVY = (31, 58, 95)
_NAVY2 = (51, 80, 122)
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)
_INK = (17, 24, 39)
_MUTED = (110, 122, 138)
# Sample-document palette: white body, a very light blue on alternating rows and
# thin blue-grey rules. Navy is reserved for the banner and the heading rows.
_ZEBRA = (234, 240, 248)
_RULE = (140, 160, 185)
# Suiflex brand (apps/web/public/logo.svg): near-black surface, green accent.
_BRAND_BG = (10, 10, 10)
_BRAND_GREEN = (74, 222, 128)
_BRAND_GREEN_DIM = (43, 122, 74)
_BRAND_FG = (240, 240, 240)

_STATUS_COLOR = {"PASSED": (21, 128, 61), "FAILED": (185, 28, 28), "NOT RUN": (161, 98, 7)}
_STATUS_ORDER = ("PASSED", "FAILED", "NOT RUN")

_LABELS: dict[str, dict[str, str]] = {
    "id": {
        "doc_title": "BERITA ACARA USER ACCEPTANCE TEST (UAT)",
        "eyebrow": "SUIFLEX - SUITEST",
        "cover_kicker": "Dokumen Hasil Pengujian",
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
        "summary_title": "Ringkasan Eksekusi",
        "info_title": "Informasi Dokumen",
        "field": "Keterangan",
        "value": "Isi",
        "doc_type": "Jenis Dokumen",
        "doc_type_value": "Berita Acara User Acceptance Test",
        "project": "Proyek / Aplikasi",
        "total_cases": "Total Test Case",
        "passed": "Lulus (PASSED)",
        "failed": "Gagal (FAILED)",
        "notrun": "Belum Dijalankan",
        "pass_rate": "Persentase Kelulusan",
        "scope_title": "Ruang Lingkup Pengujian",
        "module": "Modul / Suite",
        "count": "Jumlah",
        "legend_title": "Keterangan Status",
        "legend_passed": "Hasil aktual sesuai dengan hasil yang diharapkan.",
        "legend_failed": "Hasil aktual tidak sesuai; dicatat sebagai temuan.",
        "legend_notrun": "Belum dieksekusi pada run terakhir.",
        "results_title": "Detail Hasil Pengujian",
        "signoff_title": "Lembar Persetujuan",
        "signoff_note": (
            "Dengan ditandatanganinya dokumen ini, para pihak menyatakan bahwa "
            "pelaksanaan User Acceptance Test telah dilakukan sesuai ruang lingkup "
            "di atas dan hasilnya diterima."
        ),
        "prepared": "Disiapkan oleh",
        "reviewed": "Diperiksa oleh",
        "approved": "Disetujui oleh",
        "sig_name": "Nama",
        "sig_role": "Jabatan",
        "sig_date": "Tanggal / Tanda tangan",
        "page": "Halaman %s dari %s",
    },
    "en": {
        "doc_title": "USER ACCEPTANCE TEST (UAT) REPORT",
        "eyebrow": "SUIFLEX - SUITEST",
        "cover_kicker": "Test Execution Record",
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
        "summary_title": "Execution Summary",
        "info_title": "Document Information",
        "field": "Field",
        "value": "Value",
        "doc_type": "Document type",
        "doc_type_value": "User Acceptance Test report",
        "project": "Project / Application",
        "total_cases": "Total test cases",
        "passed": "Passed",
        "failed": "Failed",
        "notrun": "Not run",
        "pass_rate": "Pass rate",
        "scope_title": "Test Scope",
        "module": "Module / Suite",
        "count": "Cases",
        "legend_title": "Status Legend",
        "legend_passed": "Actual result matches the expected result.",
        "legend_failed": "Actual result differs; recorded as a finding.",
        "legend_notrun": "Not executed in the latest run.",
        "results_title": "Detailed Results",
        "signoff_title": "Sign-off",
        "signoff_note": (
            "By signing this document the parties confirm that the User Acceptance "
            "Test was executed against the scope above and that the results are "
            "accepted."
        ),
        "prepared": "Prepared by",
        "reviewed": "Reviewed by",
        "approved": "Approved by",
        "sig_name": "Name",
        "sig_role": "Role",
        "sig_date": "Date / Signature",
        "page": "Page %s of %s",
    },
}


# fpdf2 core fonts (Helvetica) encode Latin-1 only; anything outside that range
# raises FPDFUnicodeEncodingException mid-render. LLM-written case titles and
# suite names routinely carry typographic punctuation, which used to 500 the
# whole export.
_LATIN1_FALLBACK = str.maketrans(
    {
        "\u2014": "-",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2192": "->",
        "\u2022": "-",
        "\u00a0": " ",
    }
)


def _latin1(text: str) -> str:
    """Coerce text into the Latin-1 range Helvetica can encode.

    ponytail: transliteration, not an embedded Unicode font. Ship a TTF via
    ``add_font`` if a non-Latin locale (CJK, Cyrillic) is ever added.
    """
    return text.translate(_LATIN1_FALLBACK).encode("latin-1", "replace").decode("latin-1")


def _encodable(doc: UatDocument) -> UatDocument:
    """Copy the document with every rendered string coerced to Latin-1.

    Done once at the entry point rather than at each of the 30+ draw calls, and
    on a copy so the caller's document is untouched. ``evidence`` is left alone —
    it holds base64 data URIs, which are ASCII by construction.
    """
    return replace(
        doc,
        title=_latin1(doc.title),
        generated_at=_latin1(doc.generated_at),
        sections=[
            replace(
                section,
                module_name=_latin1(section.module_name),
                rows=[
                    replace(
                        row,
                        modul_fitur=_latin1(row.modul_fitur),
                        test_case=_latin1(row.test_case),
                        steps=[_latin1(x) for x in row.steps],
                        results=[_latin1(x) for x in row.results],
                    )
                    for row in section.rows
                ],
            )
            for section in doc.sections
        ],
    )


class _UatPdf(FPDF):
    """Running header/footer. Both are suppressed on the cover page."""

    def __init__(self, labels: dict[str, str], project: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._labels = labels
        self._project = project

    def _is_cover(self) -> bool:
        # By page number, not a flag: ``footer()`` runs when the page is closed,
        # which is after the cover routine has already moved on.
        return self.page_no() == 1

    def header(self) -> None:
        """Endorsed-brand running head: product mark + name, rule, doc title.

        The product that issued the document owns the running head; the
        organisation appears once per page at endorsement scale in the footer.
        Two equal marks in the same head would read as co-branding (two owning
        entities), which is not the relationship here.
        """
        if self._is_cover():
            return
        _suitest_mark(self, x=self.l_margin, y=6.4, size=6.6)
        text_x = self.l_margin + 9  # clear space ~ the mark's own width
        self.set_xy(text_x, 8)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_NAVY)
        self.cell(16, 5, "SUITEST")
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        self.line(text_x + 17, 8, text_x + 17, 13)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_MUTED)
        self.set_xy(text_x + 20, 8)
        self.cell(0, 5, self._labels["doc_title"])
        self.cell(0, 5, self._project, align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_BRAND_GREEN)
        self.set_line_width(0.6)
        self.line(self.l_margin, 15, self.w - self.r_margin, 15)
        self.set_line_width(0.2)
        self.set_y(21)

    def footer(self) -> None:
        if self._is_cover():
            return
        _suiflex_mark(self, x=self.l_margin, y=self.h - 12.4, size=4.4)
        self.set_y(-12)
        self.set_x(self.l_margin + 6)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, "Powered by Suiflex", align="L")
        self.cell(0, 6, self._labels["page"] % (self.page_no(), "{nb}"), align="R")


_LOGO = Path(__file__).resolve().parent.parent / "assets" / "suiflex-mark.png"


def _suiflex_mark(pdf: FPDF, x: float, y: float, size: float) -> None:
    """Draw the Suiflex organisation mark from the packaged PNG.

    The PNG ships inside the ``suitest_api`` package (hatchling includes package
    data), so it travels with the wheel and the npx bundle. A missing asset must
    not 500 the export — the Suitest mark stands in.
    """
    if _LOGO.is_file():
        pdf.image(str(_LOGO), x=x, y=y, h=size, keep_aspect_ratio=True)
        return
    _suitest_mark(pdf, x=x, y=y, size=size)


def _suitest_mark(pdf: FPDF, x: float, y: float, size: float, *, tile: bool = True) -> None:
    """Draw the Suitest product mark (apps/web/public/logo.svg) as vectors.

    Vector, not a second PNG: the mark is four primitives, so it stays crisp at
    the 6mm header size without shipping another asset.
    """
    u = size / 32.0  # the SVG is authored on a 32x32 grid
    if tile:
        pdf.set_fill_color(*_BRAND_BG)
        pdf.rect(x, y, size, size, style="F", round_corners=True, corner_radius=7 * u)
    pdf.set_fill_color(*_BRAND_GREEN)
    pdf.rect(
        x + 8 * u,
        y + 9.5 * u,
        16 * u,
        3.4 * u,
        style="F",
        round_corners=True,
        corner_radius=1.7 * u,
    )
    pdf.set_fill_color(*_BRAND_GREEN_DIM)
    pdf.rect(
        x + 8 * u,
        y + 16.4 * u,
        7.5 * u,
        3.4 * u,
        style="F",
        round_corners=True,
        corner_radius=1.7 * u,
    )
    pdf.set_draw_color(*_BRAND_GREEN)
    pdf.set_line_width(3.2 * u)
    pdf.polyline(
        [
            (x + 18.6 * u, y + 18.9 * u),
            (x + 21.2 * u, y + 21.5 * u),
            (x + 25.8 * u, y + 16.1 * u),
        ]
    )
    pdf.set_line_width(0.2)


def _first_image(evidence: list[str]) -> BytesIO | None:
    """Decode the first evidence data-URI to a stream fpdf2 can embed; None on failure."""
    if not evidence:
        return None
    try:
        b64 = evidence[0].split(",", 1)[1]
        buf = BytesIO(base64.b64decode(b64))
        # Decoding base64 is not enough: fpdf2 hands the bytes to Pillow at
        # ``output()`` time, and a truncated or mislabelled screenshot raises
        # UnidentifiedImageError there — far from this call site, as a bare 500.
        Image.open(buf).verify()
        buf.seek(0)
        return buf
    except Exception:  # bad/absent image must never break the export
        return None


def _numbered(entries: list[str]) -> str:
    """Number only the entries that carry text.

    Action steps have no ``expected``, so numbering the raw list printed bare
    "1." / "2." markers in the Test Result column.
    """
    kept = [text.strip() for text in entries if text and text.strip()]
    return "\n".join(f"{i}. {text}" for i, text in enumerate(kept, 1))


def _counts(doc: UatDocument) -> dict[str, int]:
    tally = {status: 0 for status in _STATUS_ORDER}
    for section in doc.sections:
        for row in section.rows:
            tally[row.status] += 1
    return tally


def _reset_body_style(pdf: FPDF) -> None:
    """Return the pen to body defaults (a banner leaves navy fill/white text behind)."""
    pdf.set_fill_color(*_WHITE)
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.2)
    pdf.set_text_color(*_BLACK)
    pdf.set_font("Helvetica", "", 9)


def _section_title(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*_BRAND_GREEN)
    pdf.set_line_width(0.5)
    y = pdf.get_y() + 1.2  # clear of the descenders
    pdf.line(pdf.l_margin, y, pdf.l_margin + 24, y)
    pdf.ln(4)
    _reset_body_style(pdf)


def _key_value_table(pdf: FPDF, rows: list[tuple[str, str]], labels: dict[str, str]) -> None:
    with pdf.table(
        col_widths=(60, 120),
        text_align=("LEFT", "LEFT"),
        headings_style=FontFace(emphasis="BOLD", color=_WHITE, fill_color=_NAVY2),
        cell_fill_color=_ZEBRA,
        cell_fill_mode="EVEN_ROWS",
        line_height=6,
        padding=1.8,
    ) as table:
        table.row([labels["field"], labels["value"]])
        for key, value in rows:
            row = table.row()
            row.cell(key)
            row.cell(value)


def _cover(pdf: _UatPdf, doc: UatDocument, labels: dict[str, str]) -> None:
    # The cover paints down to the bottom margin; auto page break would spill the
    # footer block onto an empty second page.
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_fill_color(*_BRAND_BG)
    pdf.rect(0, 0, pdf.w, pdf.h, style="F")

    # Brand lockup, endorsed hierarchy: the product that issued the document
    # leads (Suitest mark + wordmark); the organisation signs it off underneath
    # at endorsement scale (Suiflex mark + "powered by"), never at equal weight.
    mark_size = 30.0
    mark_top = 50.0
    _suitest_mark(pdf, x=pdf.l_margin, y=mark_top, size=mark_size, tile=False)
    lockup_x = pdf.l_margin + mark_size + 4
    pdf.set_xy(lockup_x, mark_top + 9)
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(*_BRAND_FG)
    pdf.cell(0, 9, "SUITEST", new_x="LEFT", new_y="NEXT")
    pdf.set_x(lockup_x)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(160, 168, 178)
    pdf.cell(0, 5, labels["doc_type_value"], new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(pdf.l_margin, 104)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(*_BRAND_GREEN)
    pdf.cell(0, 6, labels["cover_kicker"].upper(), new_x="LMARGIN", new_y="NEXT")

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*_BRAND_FG)
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 11, labels["doc_title"], align="L")

    pdf.ln(4)
    pdf.set_draw_color(*_BRAND_GREEN)
    pdf.set_line_width(0.8)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(8)

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*_BRAND_FG)
    pdf.cell(0, 8, doc.title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(160, 168, 178)
    pdf.cell(0, 6, f"{labels['generated']}: {doc.generated_at}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0,
        6,
        f"{labels['result_percent']}: {doc.pass_pct}%",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    # Organisation endorsement sits at the foot of the cover, the conventional
    # place for a "published by" signature, at a fraction of the product mark.
    endorse_y = pdf.h - 32
    _suiflex_mark(pdf, x=pdf.l_margin, y=endorse_y, size=8)
    pdf.set_xy(pdf.l_margin + 11, endorse_y + 1.6)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_BRAND_GREEN)
    pdf.cell(0, 5, "powered by suiflex", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(pdf.l_margin + 11, endorse_y + 5.4)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(130, 138, 148)
    pdf.cell(0, 5, f"Generated by Suitest  -  {doc.generated_at}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_auto_page_break(auto=True, margin=18)


def _summary(pdf: _UatPdf, doc: UatDocument, labels: dict[str, str]) -> None:
    pdf.add_page()
    _reset_body_style(pdf)
    _section_title(pdf, labels["summary_title"])

    tally = _counts(doc)
    total = sum(tally.values())
    _key_value_table(
        pdf,
        [
            (labels["doc_type"], labels["doc_type_value"]),
            (labels["project"], doc.title),
            (labels["generated"], doc.generated_at),
            (labels["total_cases"], str(total)),
            (labels["passed"], str(tally["PASSED"])),
            (labels["failed"], str(tally["FAILED"])),
            (labels["notrun"], str(tally["NOT RUN"])),
            (labels["pass_rate"], f"{doc.pass_pct}%"),
        ],
        labels,
    )

    pdf.ln(6)
    _section_title(pdf, labels["scope_title"])
    with pdf.table(
        col_widths=(120, 30, 30),
        text_align=("LEFT", "CENTER", "CENTER"),
        headings_style=FontFace(emphasis="BOLD", color=_WHITE, fill_color=_NAVY2),
        cell_fill_color=_ZEBRA,
        cell_fill_mode="EVEN_ROWS",
        line_height=6,
        padding=1.8,
    ) as table:
        table.row([labels["module"], labels["count"], labels["status"]])
        for section in doc.sections:
            passed = sum(1 for row in section.rows if row.status == "PASSED")
            row = table.row()
            row.cell(section.module_name)
            row.cell(str(len(section.rows)))
            row.cell(f"{passed}/{len(section.rows)}")

    pdf.ln(6)
    _section_title(pdf, labels["legend_title"])
    legend = (
        ("PASSED", labels["legend_passed"]),
        ("FAILED", labels["legend_failed"]),
        ("NOT RUN", labels["legend_notrun"]),
    )
    for status, text in legend:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_STATUS_COLOR[status])
        display = labels["not_run"] if status == "NOT RUN" else status
        pdf.cell(38, 6, display)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")


def _results(pdf: _UatPdf, doc: UatDocument, labels: dict[str, str]) -> None:
    pdf.add_page()
    _reset_body_style(pdf)
    _section_title(pdf, labels["results_title"])

    headings = [
        labels[key]
        for key in ("no", "modul", "test_case", "test_step", "test_result", "status", "evidence")
    ]
    for index, section in enumerate(doc.sections):
        if index:
            pdf.ln(4)
        pdf.set_fill_color(*_NAVY2)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 7, section.module_name, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        # Reset the pen the banner left behind: without this the table body
        # inherits the navy fill and the whole document reads as a blue block.
        _reset_body_style(pdf)
        pdf.set_font("Helvetica", "", 8)
        with pdf.table(
            col_widths=(6, 16, 22, 28, 28, 12, 30),
            text_align=("CENTER", "LEFT", "LEFT", "LEFT", "LEFT", "CENTER", "CENTER"),
            headings_style=FontFace(emphasis="BOLD", color=_WHITE, fill_color=_NAVY2),
            cell_fill_color=_ZEBRA,
            cell_fill_mode="EVEN_ROWS",
            line_height=5,
            padding=1.5,
        ) as table:
            table.row(headings)
            for r in section.rows:
                row = table.row()
                row.cell(str(r.no))
                row.cell(r.modul_fitur)
                row.cell(r.test_case)
                row.cell(_numbered(r.steps))
                row.cell(_numbered(r.results))
                disp = labels["not_run"] if r.status == "NOT RUN" else r.status
                row.cell(disp, style=FontFace(emphasis="BOLD", color=_STATUS_COLOR[r.status]))
                img = _first_image(r.evidence)
                if img is not None:
                    row.cell(img=img, img_fill_width=True)
                else:
                    row.cell("")


def _signoff(pdf: _UatPdf, doc: UatDocument, labels: dict[str, str]) -> None:
    pdf.add_page()
    _reset_body_style(pdf)
    _section_title(pdf, labels["signoff_title"])
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_INK)
    pdf.multi_cell(0, 5, labels["signoff_note"], align="L")
    pdf.ln(6)

    width = (pdf.w - pdf.l_margin - pdf.r_margin - 8) / 3
    top = pdf.get_y()
    for index, role in enumerate(("prepared", "reviewed", "approved")):
        x = pdf.l_margin + index * (width + 4)
        pdf.set_xy(x, top)
        pdf.set_fill_color(*_NAVY2)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(width, 7, labels[role], align="C", fill=True)
        pdf.set_draw_color(*_RULE)
        pdf.rect(x, top + 7, width, 46)
        pdf.set_text_color(*_MUTED)
        pdf.set_font("Helvetica", "", 8)
        # Signature space on top, then the three ruled fields inside the box.
        for line, key in enumerate(("sig_name", "sig_role", "sig_date")):
            base = top + 33 + line * 6
            pdf.set_xy(x + 2, base)
            pdf.cell(width - 4, 4, f"{labels[key]}:", align="L")
            pdf.line(x + 2, base + 5, x + width - 2, base + 5)
    pdf.set_y(top + 53 + 8)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_MUTED)
    pdf.cell(
        0,
        5,
        f"{doc.title}  -  {doc.generated_at}  -  {labels['result_percent']}: {doc.pass_pct}%",
        align="C",
    )


def render_pdf(doc: UatDocument) -> bytes:
    """Render the document to PDF bytes (fpdf2). Pure, deterministic, ZERO-tier."""
    labels = _LABELS.get(doc.locale, _LABELS["id"])
    doc = _encodable(doc)
    pdf = _UatPdf(labels, doc.title)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.alias_nb_pages()
    pdf.set_title(f"{labels['doc_title']} - {doc.title}")
    pdf.set_author("Suitest by Suiflex")
    pdf.set_creator("Suitest")

    _cover(pdf, doc, labels)
    _summary(pdf, doc, labels)
    _results(pdf, doc, labels)
    _signoff(pdf, doc, labels)

    return bytes(pdf.output())
