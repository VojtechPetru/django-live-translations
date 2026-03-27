"""E2E tests for delete override — marking, unmarking, saving deletions, and mixed operations."""

import re

import pytest
from helpers import (
    api_delete,
    api_restore_po_default,
    api_save,
    check_active_toggle,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect


class TestDeleteOverride:
    @pytest.fixture(autouse=True)
    def _skip_po_backend(self, backend_id: str) -> None:
        """PO backend never sets has_override=True, so delete button is always hidden."""
        if backend_id == "po":
            pytest.skip("Delete override is DB-only (PO backend has no DB overrides)")

    def test_delete_button_hidden_when_no_override(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        # Fixture already cleaned DB overrides; just ensure none exist via API.
        # NOTE: do NOT call api_restore_po_default here — on the DB backend it
        # creates a new TranslationEntry, making has_override=True and the
        # delete button visible (the exact opposite of what this test checks).
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        expect(delete_btn).to_be_hidden()

    def test_delete_button_visible_when_override_exists(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Override for delete test"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        expect(delete_btn).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_clicking_delete_marks_language_for_deletion(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "To be marked"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()
        expect(delete_btn).to_have_class(re.compile(r"--checked"))
        textarea = page_as_superuser_for_backend.locator("#lt-input-en-0")
        expect(textarea).to_have_class(re.compile(r"--marked-delete"))
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_clicking_delete_again_unmarks(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Toggle delete"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()
        expect(delete_btn).to_have_class(re.compile(r"--checked"))
        delete_btn.click()
        expect(delete_btn).not_to_have_class(re.compile(r"--checked"))
        textarea = page_as_superuser_for_backend.locator("#lt-input-en-0")
        expect(textarea).not_to_have_class(re.compile(r"--marked-delete"))
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_marked_deletion_disables_textarea(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Will be disabled"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()
        textarea = page_as_superuser_for_backend.locator("#lt-input-en-0")
        expect(textarea).to_be_disabled()
        expect(textarea).to_have_class(re.compile(r"--marked-delete"))
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_marked_deletion_shows_red_dot_on_tab(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Red dot test"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()
        en_tab = page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="en"]')
        status_dot = en_tab.locator('[data-role="status"]')
        expect(status_dot).to_be_visible()
        expect(status_dot).to_have_class(re.compile(r"lt-editor__dot--delete"))
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_save_with_deletion_mark_deletes_override(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Will be deleted via save"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn_after = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        expect(delete_btn_after).to_be_hidden()
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_have_value("Live Translations Demo")
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_save_mixed_delete_and_save(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "EN override", "cs": "CS override"},
            {"en": True, "cs": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)

        # Mark EN for deletion
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()

        # Switch to CS and edit text
        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="cs"]').click()
        cs_textarea = page_as_superuser_for_backend.locator("#lt-input-cs-0")
        cs_textarea.fill("Updated CS")
        check_active_toggle(page_as_superuser_for_backend, "cs")

        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Verify: EN deleted, CS updated
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        en_delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        expect(en_delete_btn).to_be_hidden()

        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="cs"]').click()
        expect(page_as_superuser_for_backend.locator("#lt-input-cs-0")).to_have_value("Updated CS")

        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])

    def test_delete_all_overrides(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "EN to delete", "cs": "CS to delete"},
            {"en": True, "cs": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)

        # Mark EN for deletion
        en_delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        en_delete_btn.click()

        # Switch to CS and mark for deletion
        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="cs"]').click()
        cs_delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        cs_delete_btn.click()

        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        # Verify both overrides are gone
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator(".lt-btn--delete-override")).to_be_hidden()
        expect(page_as_superuser_for_backend.locator("#lt-input-en-0")).to_have_value("Live Translations Demo")

        page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="cs"]').click()
        expect(page_as_superuser_for_backend.locator(".lt-btn--delete-override")).to_be_hidden()
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
