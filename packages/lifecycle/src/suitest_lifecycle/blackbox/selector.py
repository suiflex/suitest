"""General selector strategy — rank an element's addressing options.

Priority (docs/BLACKBOX_UI_TESTING.md):
1. data-testid / data-cy / data-test
2. ARIA role + accessible name
3. associated label text
4. placeholder
5. input type / name / autocomplete
6. button text / link text
7. stable CSS path fallback
8. XPath only when literally nothing else exists (we synthesize one from the
   CSS path, so in practice tier 7 always wins first)

The output is a **Playwright (python, async) locator expression string** that
generated tests embed verbatim, e.g. ``page.get_by_label("Email")``. The old
suitest-example testid convention is therefore just tier 1 — never a
requirement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from suitest_lifecycle.blackbox.models import ElementInfo

_IMPLICIT_ROLE = {
    "button": "button",
    "a": "link",
    "select": "combobox",
    "textarea": "textbox",
}


def _q(value: str) -> str:
    """Escape a python double-quoted string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _role_of(el: ElementInfo) -> str:
    if el.role:
        return el.role
    if el.tag == "input":
        t = el.input_type.lower()
        if t in ("submit", "button"):
            return "button"
        if t == "checkbox":
            return "checkbox"
        if t == "radio":
            return "radio"
        return "textbox"
    return _IMPLICIT_ROLE.get(el.tag, "")


def _accessible_name(el: ElementInfo) -> str:
    return el.aria_label or el.label or el.text.strip()


def build_locator(el: ElementInfo, *, ignore_testids: bool = False) -> str:
    """Best locator expression for ``el`` per the strategy above."""
    # 1 — test attributes
    if el.testid and not ignore_testids:
        if el.testid_attr in ("", "data-testid"):
            return f'page.get_by_test_id("{_q(el.testid)}")'
        return f'page.locator(\'[{el.testid_attr}="{_q(el.testid)}"]\')'
    # 2 — role + accessible name
    role = _role_of(el)
    name = _accessible_name(el)
    if role in ("button", "link", "checkbox", "radio", "combobox") and name:
        return f'page.get_by_role("{role}", name="{_q(name)}").first'
    # 3 — label
    if el.label:
        return f'page.get_by_label("{_q(el.label)}").first'
    # 4 — placeholder
    if el.placeholder:
        return f'page.get_by_placeholder("{_q(el.placeholder)}").first'
    # 5 — input name / type / autocomplete
    if el.tag in ("input", "textarea", "select"):
        if el.name:
            return f"page.locator('{el.tag}[name=\"{_q(el.name)}\"]').first"
        if el.autocomplete:
            return f"page.locator('{el.tag}[autocomplete=\"{_q(el.autocomplete)}\"]').first"
        if el.input_type:
            return f"page.locator('input[type=\"{_q(el.input_type)}\"]').first"
    # 6 — visible text (buttons / links)
    if el.text.strip():
        if role:
            return f'page.get_by_role("{role}", name="{_q(el.text.strip())}").first'
        return f'page.get_by_text("{_q(el.text.strip())}", exact=False).first'
    # 5b — dom id (stable-ish, before raw css)
    if el.dom_id:
        return f'page.locator("#{_q(el.dom_id)}")'
    # 7 — stable CSS path
    if el.css:
        return f'page.locator("{_q(el.css)}").first'
    # 8 — XPath as the absolute last resort
    return f'page.locator("xpath=//{el.tag or "*"}").first'


def describe(el: ElementInfo) -> str:
    """Short human label for reports/step descriptions."""
    return (
        el.label
        or el.aria_label
        or el.placeholder
        or el.text.strip()
        or el.name
        or el.testid
        or el.dom_id
        or f"<{el.tag}>"
    )[:60]
