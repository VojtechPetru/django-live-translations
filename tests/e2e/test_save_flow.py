"""E2E tests for save flow — active/inactive saves, multi-language, and validation."""

import pytest
from helpers import (
    SUPERUSER,
    api_delete,
    api_get_translations,
    api_restore_po_default,
    api_save,
    check_active_toggle,
    close_modal,
    login,
    open_modal,
    uncheck_active_toggle,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect


class TestSaveFlowPOBackend:
    def test_save_active_translation(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Custom Title")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("Custom Title")
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_save_inactive_translation(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Inactive Override")
        toggle = page_as_superuser.locator("#lt-active-en")
        expect(toggle).not_to_be_checked()
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("Live Translations Demo")
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_save_multiple_languages_at_once(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)

        en_textarea = page_as_superuser.locator("#lt-input-en")
        en_textarea.fill("English Override")
        check_active_toggle(page_as_superuser, "en")

        page_as_superuser.locator('.lt-editor__tab[data-lang="cs"]').click()
        cs_textarea = page_as_superuser.locator("#lt-input-cs")
        cs_textarea.fill("Czech Override")
        check_active_toggle(page_as_superuser, "cs")

        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        expect(page_as_superuser.locator("#lt-input-en")).to_have_value("English Override")
        page_as_superuser.locator('.lt-editor__tab[data-lang="cs"]').click()
        expect(page_as_superuser.locator("#lt-input-cs")).to_have_value("Czech Override")

        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en", "cs"])

    def test_save_inactive_then_reopen_shows_pending(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Pending Text")
        toggle = page_as_superuser.locator("#lt-active-en")
        expect(toggle).not_to_be_checked()
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        expect(page_as_superuser.locator("#lt-input-en")).to_have_value("Pending Text")
        expect(page_as_superuser.locator("#lt-active-en")).not_to_be_checked()

        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_save_inactive_matching_current_auto_activates(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Live Translations Demo")
        uncheck_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        en_toggle = page_as_superuser.locator("#lt-active-en")
        # PO backend auto-activates when pending matches current msgstr
        if en_toggle.is_visible():
            expect(en_toggle).to_be_checked()

        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])


class TestSaveFlowDBBackend:
    @pytest.fixture(autouse=True)
    def _setup(self, page: Page, db_base_url: str) -> None:
        login(page, db_base_url, *SUPERUSER)
        page.goto(f"{db_base_url}/en/")
        page.wait_for_load_state("networkidle")

    def test_save_creates_translation_entry(self, page: Page, db_base_url: str) -> None:
        result = api_save(page, db_base_url, "demo.title", {"en": "DB Created"}, {"en": True})
        assert result.get("ok") is True
        assert result["display"]["text"] == "DB Created"
        api_delete(page, db_base_url, "demo.title", ["en"])

    def test_save_updates_existing_entry(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "demo.title", {"en": "First"}, {"en": True})
        result = api_save(page, db_base_url, "demo.title", {"en": "Second"}, {"en": True})
        assert result.get("ok") is True
        assert result["display"]["text"] == "Second"
        api_delete(page, db_base_url, "demo.title", ["en"])

    def test_save_active_override_changes_displayed_text(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "demo.title", {"en": "DB Active"}, {"en": True})
        page.reload()
        page.wait_for_load_state("networkidle")
        span = page.locator('lt-t[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("DB Active")
        api_delete(page, db_base_url, "demo.title", ["en"])

    def test_save_inactive_override_does_not_change_displayed_text(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "demo.title", {"en": "DB Inactive"}, {"en": False})
        page.reload()
        page.wait_for_load_state("networkidle")
        span = page.locator('lt-t[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("Live Translations Demo")
        api_delete(page, db_base_url, "demo.title", ["en"])


class TestSaveNoPhantomEntries:
    """Saving one language must not create DB overrides for other languages."""

    @pytest.fixture(autouse=True)
    def _setup(self, page: Page, db_base_url: str) -> None:
        login(page, db_base_url, *SUPERUSER)
        page.goto(f"{db_base_url}/en/")
        page.wait_for_load_state("networkidle")
        # Clean slate: remove any leftover overrides from previous tests
        api_delete(page, db_base_url, "demo.title", ["en", "cs"])

    def test_api_save_single_lang_no_override_on_other(self, page: Page, db_base_url: str) -> None:
        """Saving only EN via API must not create a DB override for CS."""
        api_save(page, db_base_url, "demo.title", {"en": "Only English"}, {"en": True})

        data = api_get_translations(page, db_base_url, "demo.title")
        assert data["translations"]["en"]["has_override"] is True
        assert data["translations"]["cs"]["has_override"] is False

        api_delete(page, db_base_url, "demo.title", ["en"])

    def test_api_save_both_langs_unchanged_lang_no_override(self, page: Page, db_base_url: str) -> None:
        """Sending both languages where CS text + active flag match the PO default
        must not create a CS override (backend defense-in-depth)."""
        # Get PO defaults first
        defaults = api_get_translations(page, db_base_url, "demo.title")
        cs_default = defaults["translations"]["cs"]["msgstr"]

        # Save both, but CS value matches PO default and active flag matches
        # TRANSLATION_ACTIVE_BY_DEFAULT (False on the E2E server).
        api_save(
            page,
            db_base_url,
            "demo.title",
            {"en": "Changed English", "cs": cs_default},
            {"en": True, "cs": False},
        )

        data = api_get_translations(page, db_base_url, "demo.title")
        assert data["translations"]["en"]["has_override"] is True
        assert data["translations"]["cs"]["has_override"] is False

        api_delete(page, db_base_url, "demo.title", ["en"])

    def test_widget_save_single_lang_no_phantom(self, page: Page, db_base_url: str) -> None:
        """Editing only EN in the widget must not create a CS override."""
        open_modal(page, "demo.title")
        wait_for_fields_loaded(page)

        # Edit only EN
        textarea = page.locator("#lt-input-en")
        textarea.fill("Widget English Only")
        check_active_toggle(page, "en")

        # Do NOT touch CS tab at all
        page.locator(".lt-btn--save").click()
        expect(page.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Verify CS has no override
        data = api_get_translations(page, db_base_url, "demo.title")
        assert data["translations"]["en"]["has_override"] is True
        assert data["translations"]["cs"]["has_override"] is False

        api_delete(page, db_base_url, "demo.title", ["en"])


class TestSaveValidation:
    PLACEHOLDER_MSGID = "edit_mode.toggle_hint %(key)s"

    def test_placeholder_mismatch_shows_error(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, self.PLACEHOLDER_MSGID)
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("No placeholder here")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(error).to_contain_text("missing")
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_visible()

    def test_placeholder_error_shows_per_language_details(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, self.PLACEHOLDER_MSGID)
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Missing the placeholder")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(error).to_contain_text("%(key)s")

    def test_save_with_correct_placeholders_succeeds(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, self.PLACEHOLDER_MSGID)
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Press %(key)s to do something")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        api_restore_po_default(page_as_superuser, base_url, self.PLACEHOLDER_MSGID, ["en"])

    def test_error_banner_clears_on_next_valid_save(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, self.PLACEHOLDER_MSGID)
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("No placeholder")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)

        textarea.fill("Fixed with %(key)s included")
        page_as_superuser.locator(".lt-btn--save").click()
        expect(error).to_be_hidden(timeout=5000)
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        api_restore_po_default(page_as_superuser, base_url, self.PLACEHOLDER_MSGID, ["en"])

    def test_error_banner_cleared_on_modal_reopen(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, self.PLACEHOLDER_MSGID)
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("No placeholder")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        error = page_as_superuser.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)

        close_modal(page_as_superuser)
        open_modal(page_as_superuser, self.PLACEHOLDER_MSGID)
        wait_for_fields_loaded(page_as_superuser)
        expect(page_as_superuser.locator(".lt-dialog__error")).to_be_hidden()
