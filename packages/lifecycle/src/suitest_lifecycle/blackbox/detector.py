"""Heuristic detectors: login form + page pattern. Deterministic, no LLM.

Nothing here references any app-specific ``data-testid`` — the old
suitest-example convention is only an input signal (via the selector strategy's
tier 1), never a requirement.
"""

from __future__ import annotations

import re

from suitest_lifecycle.blackbox.models import ElementInfo, LoginForm, PageInfo
from suitest_lifecycle.blackbox.selector import build_locator

_USERNAME_HINTS = ("email", "e-mail", "user", "login", "account", "identifier", "phone")
_SUBMIT_HINTS = ("sign in", "log in", "login", "masuk", "submit", "continue", "next")
_REMEMBER_HINTS = ("remember", "ingat", "keep me")
_DESTRUCTIVE_HINTS = (
    "delete",
    "remove",
    "destroy",
    "logout",
    "log out",
    "sign out",
    "keluar",
    "hapus",
    "cancel subscription",
    "unsubscribe",
    "payment",
    "pay ",
    "checkout",
    "billing",
    "publish",
    "send",
    "approve",
    "reject",
    "submit final",
    "deactivate",
)

_ERROR_TEXT_RE = re.compile(
    r"(something went wrong|internal server error|unexpected error|exception|traceback"
    r"|terjadi kesalahan)",
    re.I,
)
_FORBIDDEN_RE = re.compile(r"(forbidden|unauthorized|access denied|403|401|tidak berhak)", re.I)
_NOT_FOUND_RE = re.compile(r"(not found|404|page (doesn.t|does not) exist|halaman tidak)", re.I)
_EMPTY_RE = re.compile(r"(no \w+ yet|nothing here|empty|no results|no data|tidak ada \w+)", re.I)


def _blob(el: ElementInfo) -> str:
    return " ".join(
        (
            el.testid,
            el.name,
            el.dom_id,
            el.placeholder,
            el.label,
            el.aria_label,
            el.autocomplete,
            el.text,
            el.tooltip,
            el.icon_hint,
        )
    ).lower()


def is_destructive(el: ElementInfo) -> bool:
    """SafeMode gate — never click/submit these during crawl or generated tests."""
    return any(h in _blob(el) for h in _DESTRUCTIVE_HINTS)


_SELECT_DOC_HINTS = (
    "pilih",
    "select",
    "choose",
    "attach",
    "lampirkan",
    "gunakan",
    "pakai",
    "apply",
)


def is_document_selection_action(element: ElementInfo) -> bool:
    """Check if an interactive element represents choosing a document from a table or library."""
    blob = f"{_blob(element)} {element.css} {element.role}".lower()
    return any(h in blob for h in _SELECT_DOC_HINTS)


def classify_button_intent(el: ElementInfo) -> str:
    """Classify the user intent of a button, including icon-only controls.

    Returns: 'SEARCH', 'LOOKUP_MODAL', 'CREATE', 'EDIT', 'DELETE', 'UPLOAD', 'CALENDAR', 'SUBMIT', or 'CUSTOM'.
    """
    blob = _blob(el)
    if el.input_type == "submit" or any(
        k in blob for k in ("submit", "simpan", "save", "kirim", "lanjut", "next", "continue")
    ):
        return "SUBMIT"
    if is_destructive(el):
        return "DELETE"
    if "lookup" in blob or "modal-trigger" in blob or "modal-toggle" in blob:
        return "LOOKUP_MODAL"
    if any(k in blob for k in ("search", "icon:search", "fa-search", "cari")):
        return "SEARCH"
    if any(k in blob for k in ("edit", "icon:pencil", "icon:edit", "ubah", "ganti")):
        return "EDIT"
    if any(k in blob for k in ("add", "icon:plus", "tambah", "new", "baru", "create")):
        return "CREATE"
    if any(k in blob for k in ("upload", "icon:upload", "unggah", "import")):
        return "UPLOAD"
    if any(k in blob for k in ("calendar", "icon:calendar", "kalender", "date", "jadwal")):
        return "CALENDAR"
    if is_document_selection_action(el):
        return "SELECT_DOCUMENT"
    return "CUSTOM"


def detect_login_form(page: PageInfo, *, ignore_testids: bool = False) -> LoginForm:
    """Find username/password/submit (+ remember) among a page's elements.

    Works on ANY attribute the DOM offers: type, name, autocomplete, label,
    placeholder, aria-label, visible text. Returns an empty LoginForm when no
    password field exists (``.found()`` is False).
    """
    form = LoginForm(route=page.route)

    password = next(
        (e for e in page.inputs if e.input_type == "password" or "password" in _blob(e)),
        None,
    )
    if password is None:
        return form

    username = None
    for e in page.inputs:
        if e is password or e.input_type in ("checkbox", "radio", "hidden", "submit"):
            continue
        blob = _blob(e)
        if e.input_type == "email" or e.autocomplete in ("username", "email"):
            username = e
            break
        if any(h in blob for h in _USERNAME_HINTS):
            username = e
            break
    if username is None:  # fall back to the text input right before the password
        text_inputs = [
            e
            for e in page.inputs
            if e is not password and e.input_type in ("", "text", "email", "tel")
        ]
        username = text_inputs[0] if text_inputs else None
    if username is None:
        return form

    submit = None
    for b in page.buttons:
        blob = _blob(b)
        if is_destructive(b):
            continue
        if b.input_type == "submit" or any(h in blob for h in _SUBMIT_HINTS):
            submit = b
            break
    if submit is None and page.buttons:
        submit = page.buttons[0]
    if submit is None:
        return form

    form.username = build_locator(username, ignore_testids=ignore_testids)
    form.password = build_locator(password, ignore_testids=ignore_testids)
    form.submit = build_locator(submit, ignore_testids=ignore_testids)

    remember = next(
        (
            e
            for e in page.inputs
            if e.input_type == "checkbox" and any(h in _blob(e) for h in _REMEMBER_HINTS)
        ),
        None,
    )
    if remember is not None:
        form.remember = build_locator(remember, ignore_testids=ignore_testids)

    error = next((e for e in page.inputs + page.buttons if "error" in _blob(e)), None)
    if error is not None:
        form.error = build_locator(error, ignore_testids=ignore_testids)

    if page.has_captcha and page.captcha_input_selector:
        form.captcha_input = page.captcha_input_selector
        form.captcha_image = page.captcha_image_selector
    else:
        has_c, c_in, c_img, _, _ = detect_captcha_form(page)
        if has_c:
            form.captcha_input = c_in
            form.captcha_image = c_img
    return form


def detect_page_pattern(page: PageInfo) -> str:
    """Classify a crawled page into one of ``PAGE_PATTERNS``."""
    text = page.visible_text_sample
    if page.blank:
        return "blank"
    if _NOT_FOUND_RE.search(text) or _NOT_FOUND_RE.search(page.title):
        return "not_found"
    if _FORBIDDEN_RE.search(text):
        return "forbidden"
    if _ERROR_TEXT_RE.search(text):
        return "error"
    if any(e.input_type == "password" for e in page.inputs):
        return "login"
    if page.has_modal:
        return "modal"
    if page.has_table:
        return "list"
    if _EMPTY_RE.search(text):
        return "empty"
    form_inputs = [e for e in page.inputs if e.input_type not in ("checkbox", "radio", "hidden")]
    if len(form_inputs) >= 2 and page.buttons:
        return "form"
    route = page.route.lower()
    if any(k in route for k in ("dashboard", "home", "overview")) or "dashboard" in text.lower():
        return "dashboard"
    if re.search(r"/\d+$|/[0-9a-f-]{8,}$", page.route):
        return "detail"
    return "unknown"


def detect_captcha_form(page: PageInfo) -> tuple[bool, str, str, str, str]:
    """Detect if page contains a CAPTCHA input + image pairing.

    Returns (has_captcha, input_selector, image_selector, captcha_type, refresh_target).
    """
    if page.has_captcha and page.captcha_input_selector:
        return (
            True,
            page.captcha_input_selector,
            page.captcha_image_selector,
            page.captcha_type or "auto",
            page.refresh_target or page.captcha_image_selector,
        )

    for el in page.inputs:
        blob = _blob(el)
        if "captcha" in blob or "security_code" in blob or "verify_code" in blob:
            in_sel = (
                f"#{el.dom_id}"
                if el.dom_id
                else (f"input[name='{el.name}']" if el.name else "input")
            )
            if el.frame_selector:
                in_sel = f"{el.frame_selector} >> {in_sel}"
            img_sel = "#img-captcha"
            if el.frame_selector:
                img_sel = f"{el.frame_selector} >> {img_sel}"
            return True, in_sel, img_sel, "auto", img_sel
    return False, "", "", "", ""
