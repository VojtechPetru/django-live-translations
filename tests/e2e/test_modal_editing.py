"""E2E tests for modal editing — textarea, PO defaults, and fuzzy indicators."""

import re

from helpers import (
    api_restore_po_default,
    api_save,
    check_active_toggle,
    close_modal,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect


class TestModalEditing:
    def test_textarea_shows_current_translation(self, page_as_superuser: Page, base_url: str) -> None:
        # Ensure PO default is restored in case a previous test left dirty state
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("networkidle")
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        expect(textarea).to_have_value("Live Translations Demo")

    def test_textarea_auto_resizes_on_input(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        initial_height = page_as_superuser.evaluate("el => el.offsetHeight", textarea.element_handle())
        textarea.focus()
        textarea.press("End")
        for _ in range(5):
            textarea.press("Enter")
        new_height = page_as_superuser.evaluate("el => el.offsetHeight", textarea.element_handle())
        assert new_height > initial_height

    def test_po_default_shown_for_current_language(self, page_as_superuser: Page, base_url: str) -> None:
        # Ensure PO default is restored in case a previous test left dirty state
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("networkidle")
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        po_default = page_as_superuser.locator(".lt-field__po-default")
        expect(po_default).to_be_visible()
        expect(po_default).to_contain_text("Live Translations Demo")

    def test_po_default_is_copyable(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.context.grant_permissions(["clipboard-read", "clipboard-write"])
        po_wrap = page_as_superuser.locator(".lt-field__po-wrap").first
        po_wrap.click()
        # After copy, the wrap gets a --copied class
        expect(po_wrap).to_have_class(re.compile(r"--copied"), timeout=2000)

    def test_po_default_wrap_visible_when_po_entry_exists(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        po_wrap = page_as_superuser.locator(".lt-field__po-wrap").first
        expect(po_wrap).to_be_visible()
        po_label = page_as_superuser.locator(".lt-field__po-label").first
        expect(po_label).to_have_text("Default")

    def test_no_fuzzy_class_for_normal_entry(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        expect(textarea).not_to_have_class("lt-field__input--fuzzy")

    def test_saving_preserves_no_fuzzy_class(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Updated Title")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        # Reopen modal to verify saved state
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        expect(textarea).not_to_have_class("lt-field__input--fuzzy")
        close_modal(page_as_superuser)
        # Restore original PO value to not leave state for other tests
        api_save(page_as_superuser, base_url, "demo.title", {"en": "Live Translations Demo"}, {"en": True})
