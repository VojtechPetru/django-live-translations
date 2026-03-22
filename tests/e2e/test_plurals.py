"""E2E tests for plural translations — modal rendering, save flow, delete, history, and validation."""

import pytest
from helpers import (
    api_delete,
    api_save,
    check_active_toggle,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect

NOTIFICATION_MSGID = "plurals.notification_one %(count)s"
NOTIFICATION_PLURAL = "plurals.notification_other %(count)s"

EN_NOTIFICATION_DEFAULTS = {
    "0": "You have %(count)s new notification.",
    "1": "You have %(count)s new notifications.",
}
CS_NOTIFICATION_DEFAULTS = {
    "0": "Máte %(count)s nové oznámení.",
    "1": "Máte %(count)s nová oznámení.",
    "2": "Máte %(count)s nových oznámení.",
    "3": "Máte %(count)s nových oznámení.",
}


def _cleanup_notification(page: Page, base_url: str, backend_id: str) -> None:
    api_delete(page, base_url, NOTIFICATION_MSGID, ["en", "cs"], msgid_plural=NOTIFICATION_PLURAL)
    if backend_id == "po":
        api_save(
            page,
            base_url,
            NOTIFICATION_MSGID,
            {"en": EN_NOTIFICATION_DEFAULTS, "cs": CS_NOTIFICATION_DEFAULTS},
            {"en": True, "cs": True},
            msgid_plural=NOTIFICATION_PLURAL,
        )


class TestPluralModalRendering:
    def test_shows_two_textareas_for_english(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-en-1")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-en-2")).to_have_count(0)

    def test_shows_four_textareas_for_czech(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="cs"]').click()
        expect(page_as_superuser_for_backend.locator("#lt-input-cs-0")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-cs-1")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-cs-2")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-cs-3")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-cs-4")).to_have_count(0)

    def test_shows_form_labels(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        labels = page_as_superuser_for_backend.locator(".lt-field__form-label")
        expect(labels).to_have_count(2)
        expect(labels.nth(0)).to_have_text("Form 0")
        expect(labels.nth(1)).to_have_text("Form 1")

    def test_textareas_show_po_defaults(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_have_value(EN_NOTIFICATION_DEFAULTS["0"])
        expect(page_as_superuser_for_backend.locator("#lt-input-en-1")).to_have_value(EN_NOTIFICATION_DEFAULTS["1"])

    def test_po_defaults_shown_per_form(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        defaults = page_as_superuser_for_backend.locator(".lt-field__po-default")
        expect(defaults.first).to_be_visible()
        expect(defaults.first).to_contain_text(EN_NOTIFICATION_DEFAULTS["0"])

    def test_non_plural_shows_single_textarea(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, "plurals.heading")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_be_visible()
        expect(page_as_superuser_for_backend.locator("#lt-input-en-1")).to_have_count(0)
        expect(page_as_superuser_for_backend.locator(".lt-field__form-label")).to_have_count(0)


class TestPluralSaveFlow:
    def test_save_shows_reload_toast(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("You have %(count)s alert.")
        page_as_superuser_for_backend.locator("#lt-input-en-1").fill("You have %(count)s alerts.")
        check_active_toggle(page_as_superuser_for_backend, "en")
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        toast = page_as_superuser_for_backend.locator(".lt-toast")
        expect(toast).to_be_visible(timeout=5000)
        expect(toast).to_contain_text("Reload")
        _cleanup_notification(page_as_superuser_for_backend, base_url_for_backend, backend_id)

    def test_save_does_not_update_dom_in_place(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        element = page_as_superuser_for_backend.locator(f'lt-t[data-lt-msgid="{NOTIFICATION_MSGID}"]')
        original_text = element.text_content()
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("Changed %(count)s singular.")
        page_as_superuser_for_backend.locator("#lt-input-en-1").fill("Changed %(count)s plural.")
        check_active_toggle(page_as_superuser_for_backend, "en")
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        assert element.text_content() == original_text
        _cleanup_notification(page_as_superuser_for_backend, base_url_for_backend, backend_id)

    def test_save_persists_all_forms(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("Persisted %(count)s one.")
        page_as_superuser_for_backend.locator("#lt-input-en-1").fill("Persisted %(count)s many.")
        check_active_toggle(page_as_superuser_for_backend, "en")
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_have_value("Persisted %(count)s one.")
        expect(page_as_superuser_for_backend.locator("#lt-input-en-1")).to_have_value("Persisted %(count)s many.")
        _cleanup_notification(page_as_superuser_for_backend, base_url_for_backend, backend_id)

    def test_edits_preserved_across_tab_switch(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("Tab switch %(count)s one.")
        page_as_superuser_for_backend.locator("#lt-input-en-1").fill("Tab switch %(count)s many.")
        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="cs"]').click()
        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="en"]').click()
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_have_value("Tab switch %(count)s one.")
        expect(page_as_superuser_for_backend.locator("#lt-input-en-1")).to_have_value("Tab switch %(count)s many.")


class TestPluralDeleteOverride:
    @pytest.fixture(autouse=True)
    def _skip_po_backend(self, backend_id: str) -> None:
        if backend_id == "po":
            pytest.skip("Delete override is DB-only (PO backend has no DB overrides)")

    def test_delete_button_visible_for_plural_with_override(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            NOTIFICATION_MSGID,
            {"en": EN_NOTIFICATION_DEFAULTS},
            {"en": True},
            msgid_plural=NOTIFICATION_PLURAL,
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator(".lt-btn--delete-override")).to_be_visible()
        api_delete(
            page_as_superuser_for_backend,
            base_url_for_backend,
            NOTIFICATION_MSGID,
            ["en"],
            msgid_plural=NOTIFICATION_PLURAL,
        )

    def test_delete_reverts_to_defaults(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            NOTIFICATION_MSGID,
            {"en": {"0": "Override %(count)s one.", "1": "Override %(count)s many."}},
            {"en": True},
            msgid_plural=NOTIFICATION_PLURAL,
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--delete-override").click()
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_have_value(EN_NOTIFICATION_DEFAULTS["0"])
        expect(page_as_superuser_for_backend.locator("#lt-input-en-1")).to_have_value(EN_NOTIFICATION_DEFAULTS["1"])


class TestPluralHistory:
    @pytest.fixture(autouse=True)
    def _skip_po_backend(self, backend_id: str) -> None:
        if backend_id == "po":
            pytest.skip("History with form tags is DB-only")

    def test_history_shows_form_tags(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            NOTIFICATION_MSGID,
            {"en": {"0": "History %(count)s one.", "1": "History %(count)s many."}},
            {"en": True},
            msgid_plural=NOTIFICATION_PLURAL,
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        expect(page_as_superuser_for_backend.locator(".lt-history__form-tag")).to_be_visible()
        api_delete(
            page_as_superuser_for_backend,
            base_url_for_backend,
            NOTIFICATION_MSGID,
            ["en"],
            msgid_plural=NOTIFICATION_PLURAL,
        )


class TestPluralValidation:
    def test_missing_placeholder_shows_error(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("Missing placeholder here.")
        check_active_toggle(page_as_superuser_for_backend, "en")
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        error = page_as_superuser_for_backend.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_visible()

    def test_correct_placeholders_saves(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("Valid %(count)s singular.")
        page_as_superuser_for_backend.locator("#lt-input-en-1").fill("Valid %(count)s plural.")
        check_active_toggle(page_as_superuser_for_backend, "en")
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        _cleanup_notification(page_as_superuser_for_backend, base_url_for_backend, backend_id)

    def test_one_form_missing_placeholder_blocks_save(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, NOTIFICATION_MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator("#lt-input-en-0").fill("Has %(count)s placeholder.")
        page_as_superuser_for_backend.locator("#lt-input-en-1").fill("No placeholder here.")
        check_active_toggle(page_as_superuser_for_backend, "en")
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        error = page_as_superuser_for_backend.locator(".lt-dialog__error")
        expect(error).to_be_visible(timeout=5000)
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_visible()
