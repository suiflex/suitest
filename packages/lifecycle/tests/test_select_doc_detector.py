from __future__ import annotations

from suitest_lifecycle.blackbox.detector import classify_button_intent, is_document_selection_action
from suitest_lifecycle.blackbox.models import ElementInfo


def test_detect_bilingual_doc_selection():
    btn_id = ElementInfo(tag="button", text="Pilih", css=".btn.btn-default")
    btn_en = ElementInfo(tag="a", text="Select Document", role="button")
    btn_attach = ElementInfo(tag="button", text="Lampirkan File")
    btn_irrelevant = ElementInfo(tag="button", text="Cancel")

    assert is_document_selection_action(btn_id) is True
    assert is_document_selection_action(btn_en) is True
    assert is_document_selection_action(btn_attach) is True
    assert is_document_selection_action(btn_irrelevant) is False


def test_classify_button_intent_recognizes_select_document():
    btn_doc = ElementInfo(tag="button", text="Pilih Dokumen")
    intent = classify_button_intent(btn_doc)
    assert intent == "SELECT_DOCUMENT"
