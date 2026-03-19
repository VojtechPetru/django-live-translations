"""E2E tests for client-side HTML structure validation.

Verifies that the widget warns translators about malformed HTML (unclosed tags,
mismatched tags) before saving, and that the "Save anyway" override works.
"""

from helpers import (
    api_restore_po_default,
    check_active_toggle,
    close_modal,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect


class TestHtmlValidation:
    """Client-side HTML validation warns about malformed tags, with 'Save anyway' override."""

    MSGID = "demo.title"

    def test_unclosed_tag_shows_warning(self, page_as_superuser: Page) -> None:
        """Unclosed <strong> tag triggers a visible warning; dialog stays open."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Live <strong>Translations Demo")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()

        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(error).to_contain_text("Unclosed")
        expect(error).to_contain_text("<strong>")
        # Dialog must stay open (save was blocked)
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_visible()

    def test_mismatched_tag_shows_warning(self, page_as_superuser: Page) -> None:
        """Mismatched closing tag triggers a warning."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("<strong>text</em>")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()

        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        # Validator reports: stray </em> (no matching open) + unclosed <strong>
        expect(error).to_contain_text("</em>")
        expect(error).to_contain_text("Unclosed")
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_visible()

    def test_save_anyway_bypasses_warning(self, page_as_superuser: Page, base_url: str) -> None:
        """After warning, 'Save anyway' click proceeds with the save."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Live <strong>Translations Demo")
        check_active_toggle(page_as_superuser)

        save_btn = page_as_superuser.locator(".lt-btn--save")
        save_btn.click()

        # Warning shown, button text changed
        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(save_btn).to_have_text("Save anyway")

        # Click again to override
        save_btn.click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Verify DOM was updated
        span = page_as_superuser.locator(f'lt-t[data-lt-msgid="{self.MSGID}"]').first
        expect(span).to_contain_text("Translations Demo")

        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, self.MSGID, ["en"])

    def test_valid_html_saves_without_warning(self, page_as_superuser: Page, base_url: str) -> None:
        """Well-formed HTML saves immediately without any warning."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Live <strong>Translations</strong> Demo")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()

        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, self.MSGID, ["en"])

    def test_plain_text_saves_without_warning(self, page_as_superuser: Page, base_url: str) -> None:
        """Plain text (no HTML) saves immediately without any warning."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Plain text, no HTML at all")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()

        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, self.MSGID, ["en"])

    def test_warning_resets_on_textarea_edit(self, page_as_superuser: Page, base_url: str) -> None:
        """Editing textarea after warning resets the 'Save anyway' state."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Live <strong>Translations Demo")
        check_active_toggle(page_as_superuser)

        save_btn = page_as_superuser.locator(".lt-btn--save")
        save_btn.click()

        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(save_btn).to_have_text("Save anyway")

        # Fix the HTML by typing valid content
        textarea.fill("Live <strong>Translations</strong> Demo")

        # Button should revert to "Save" and error should clear
        expect(save_btn).to_have_text("Save")
        expect(error).to_be_hidden()

        # Now save should succeed without warning
        save_btn.click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, self.MSGID, ["en"])

    def test_warning_cleared_on_modal_reopen(self, page_as_superuser: Page) -> None:
        """Reopening the modal clears any previous HTML warning."""
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Live <strong>Translations Demo")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()

        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)

        close_modal(page_as_superuser)
        open_modal(page_as_superuser, self.MSGID)
        wait_for_fields_loaded(page_as_superuser)

        expect(page_as_superuser.locator(".lt-dialog__error")).to_be_hidden()
        expect(page_as_superuser.locator(".lt-btn--save")).to_have_text("Save")
