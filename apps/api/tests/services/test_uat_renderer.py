"""Renderer smoke tests — valid PDF bytes, both locales, evidence embed (no DB)."""

from __future__ import annotations

import base64

from suitest_api.services.uat_document import UatDocument, UatRow, UatSection
from suitest_api.services.uat_renderer import render_pdf

# 1x1 transparent PNG — a minimal valid image for the evidence path.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _doc(*, locale: str = "id", evidence: list[str] | None = None) -> UatDocument:
    return UatDocument(
        title="UAT Portal Debitur",
        generated_at="29 Jun 2026 12:00 UTC",
        locale=locale,  # type: ignore[arg-type]
        pass_pct=100,
        sections=[
            UatSection(
                module_name="Login",
                rows=[
                    UatRow(
                        no=1,
                        modul_fitur="Form Login",
                        test_case="Verifikasi login valid",
                        steps=["Masukkan username", "Klik Login"],
                        results=["Diarahkan ke dashboard"],
                        status="PASSED",
                        evidence=evidence or [],
                    )
                ],
            )
        ],
    )


def test_render_pdf_is_valid_pdf() -> None:
    pdf = render_pdf(_doc())
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_render_pdf_embeds_evidence_image() -> None:
    uri = "data:image/png;base64," + base64.b64encode(_PNG).decode("ascii")
    pdf = render_pdf(_doc(evidence=[uri]))
    assert pdf[:5] == b"%PDF-"


def test_both_locales_render_and_differ() -> None:
    id_pdf = render_pdf(_doc(locale="id"))
    en_pdf = render_pdf(_doc(locale="en"))
    assert id_pdf[:5] == b"%PDF-" and en_pdf[:5] == b"%PDF-"
    # Different banner/labels → different content streams.
    assert id_pdf != en_pdf


def test_typographic_characters_do_not_crash() -> None:
    # Helvetica is a Latin-1 core font; an em dash used to raise mid-render and
    # surface as a bare 500 on the export endpoint.
    doc = _doc()
    doc.title = "RDB V43 \u2014 \u201cgrid\u201d selection\u2026"
    doc.sections[0].module_name = "Editor \u2014 caret"
    doc.sections[0].rows[0].test_case = "Verifikasi user tidak bisa \u2192 pindah"
    doc.sections[0].rows[0].steps = ["Klik \u2018Copy\u2019", "Tekan \U0001f600"]
    pdf = render_pdf(doc)
    assert pdf[:5] == b"%PDF-"


def test_bad_evidence_uri_does_not_crash() -> None:
    pdf = render_pdf(_doc(evidence=["data:image/png;base64,not-valid-b64!!"]))
    assert pdf[:5] == b"%PDF-"


def test_undecodable_evidence_image_does_not_crash() -> None:
    # Valid base64, unreadable image — a truncated screenshot. Pillow used to
    # raise inside pdf.output(), long after _first_image had waved it through.
    uri = "data:image/png;base64," + base64.b64encode(_PNG[:20]).decode("ascii")
    assert render_pdf(_doc(evidence=[uri]))[:5] == b"%PDF-"


def _page_count(pdf: bytes) -> int:
    """Read the page-tree /Count — the structure assertion that survives compression."""
    marker = pdf.rindex(b"/Count ") + len(b"/Count ")
    digits = bytes(c for c in pdf[marker : marker + 8] if 48 <= c <= 57)
    return int(digits)


def test_document_has_cover_summary_results_and_signoff() -> None:
    # Cover + summary + results + sign-off: a one-page dump is a regression.
    assert _page_count(render_pdf(_doc())) >= 4
