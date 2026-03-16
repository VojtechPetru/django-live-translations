"""Shared test helpers — interaction utilities, API wrappers, constants."""

import json
import re

from playwright.sync_api import Page, expect

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_PREFIX = "/__live-translations__"

SUPERUSER = ("admin", "admin123")
STAFF_USER = ("staff", "staff123")

# Known PO defaults for cleanup — saving original value back restores PO state
PO_DEFAULTS = {
    ("demo.title", "en"): "Live Translations Demo",
    ("demo.title", "cs"): "Demo živých překladů",
    ("demo.welcome", "en"): "Welcome to the demo application!",
    ("demo.welcome", "cs"): "Vítejte v demo aplikaci!",
    ("demo.description", "en"): "A minimal example app for testing django-live-translations.",
    ("demo.description", "cs"): "Minimální příklad pro testování django-live-translations.",
    ("about.heading", "en"): "About this page",
    ("about.heading", "cs"): "O této stránce",
    ("attrs.tooltip_trans", "en"): "This tooltip was translated with the trans tag",
    ("attrs.tooltip_trans", "cs"): "Tento tooltip byl přeložen pomocí tagu trans",
    ("attrs.tooltip_gettext", "en"): "This tooltip was translated with gettext()",
    ("attrs.tooltip_gettext", "cs"): "Tento tooltip byl přeložen pomocí gettext()",
}

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def login(page: Page, base_url: str, username: str, password: str) -> None:
    """Log in via the Django admin login page."""
    page.goto(f"{base_url}/en/admin/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", password)
    page.click('input[type="submit"]')
    page.wait_for_url("**/admin/**")
    assert "/login/" not in page.url, f"Login failed for user '{username}' — still on login page: {page.url}"


# ---------------------------------------------------------------------------
# Edit mode
# ---------------------------------------------------------------------------


def activate_edit_mode(page: Page) -> None:
    """Toggle edit mode on via keyboard shortcut."""
    page.keyboard.press("Control+Shift+KeyE")
    expect(page.locator("body")).to_have_class(re.compile(r"lt-edit-mode"), timeout=3000)


def deactivate_edit_mode(page: Page) -> None:
    """Toggle edit mode off via keyboard shortcut."""
    page.keyboard.press("Control+Shift+KeyE")
    expect(page.locator("body")).not_to_have_class(re.compile(r"lt-edit-mode"), timeout=3000)


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------


def open_modal(page: Page, msgid: str, *, attr: bool = False) -> None:
    """Activate edit mode and click a translatable element to open the modal."""
    if not page.locator("body").get_attribute("class", timeout=500) or "lt-edit-mode" not in (
        page.locator("body").get_attribute("class") or ""
    ):
        activate_edit_mode(page)
    if attr:
        page.evaluate(
            """(msgid) => {
                const el = document.querySelector('[data-lt-attrs*="' + msgid + '"]');
                if (el) el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
            }""",
            msgid,
        )
    else:
        page.locator(f'.lt-translatable[data-lt-msgid="{msgid}"]').first.click()
    expect(page.locator("dialog.lt-dialog[open]")).to_be_visible(timeout=3000)


def wait_for_fields_loaded(page: Page) -> None:
    """Wait for the modal fields to finish loading."""
    expect(page.locator(".lt-dialog__loading")).to_be_hidden(timeout=5000)
    expect(page.locator(".lt-dialog__fields")).to_be_visible(timeout=5000)


def close_modal(page: Page) -> None:
    """Close the modal via the close button."""
    page.locator(".lt-dialog__close").click()
    expect(page.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=3000)


# ---------------------------------------------------------------------------
# Active toggles
# ---------------------------------------------------------------------------


def check_active_toggle(page: Page, lang: str = "en") -> None:
    """Check the active toggle for a language. Uses JS because the checkbox is CSS-hidden."""
    page.evaluate(
        """(lang) => {
            const cb = document.getElementById('lt-active-' + lang);
            if (cb && !cb.checked) { cb.click(); }
        }""",
        lang,
    )


def uncheck_active_toggle(page: Page, lang: str = "en") -> None:
    """Uncheck the active toggle for a language. Uses JS because the checkbox is CSS-hidden."""
    page.evaluate(
        """(lang) => {
            const cb = document.getElementById('lt-active-' + lang);
            if (cb && cb.checked) { cb.click(); }
        }""",
        lang,
    )


# ---------------------------------------------------------------------------
# API wrappers
# ---------------------------------------------------------------------------


def api_save(
    page: Page,
    base_url: str,
    msgid: str,
    translations: dict[str, str],
    active_flags: dict[str, bool] | None = None,
    *,
    context: str = "",
    page_language: str = "en",
) -> dict:
    """Save a translation via the API directly (for test setup)."""
    csrf = page.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
    body: dict = {
        "msgid": msgid,
        "context": context,
        "translations": translations,
        "active_flags": active_flags or {lang: True for lang in translations},
        "page_language": page_language,
    }
    response = page.request.post(
        f"{base_url}{API_PREFIX}/translations/save/",
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
        },
    )
    return response.json()


def api_delete(
    page: Page,
    base_url: str,
    msgid: str,
    languages: list[str] | None = None,
    *,
    context: str = "",
    page_language: str = "en",
) -> dict:
    """Delete a translation override via the API directly (for test setup)."""
    csrf = page.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
    body: dict = {
        "msgid": msgid,
        "context": context,
        "page_language": page_language,
    }
    if languages:
        body["languages"] = languages
    response = page.request.post(
        f"{base_url}{API_PREFIX}/translations/delete/",
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
        },
    )
    return response.json()


def api_restore_po_default(
    page: Page,
    base_url: str,
    msgid: str,
    languages: list[str] | None = None,
    *,
    context: str = "",
) -> None:
    """Restore PO defaults for a msgid. For PO backend cleanup — saves original values back."""
    langs = languages or ["en", "cs"]
    translations = {}
    active_flags = {}
    for lang in langs:
        default = PO_DEFAULTS.get((msgid, lang))
        if default is not None:
            translations[lang] = default
            active_flags[lang] = True
    if translations:
        api_save(page, base_url, msgid, translations, active_flags, context=context)
