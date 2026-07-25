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


def test_bad_evidence_uri_does_not_crash() -> None:
    pdf = render_pdf(_doc(evidence=["data:image/png;base64,not-valid-b64!!"]))
    assert pdf[:5] == b"%PDF-"
