import pytest
from conftest import api_delete, api_restore_po_default, api_save, close_modal, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestHistoryRestore:
    def test_restore_button_visible_on_older_entries(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "First version"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Second version"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entries = page_as_superuser_for_backend.locator(".lt-history__entry")
        newest = entries.nth(0)
        expect(newest.locator(".lt-history__restore-btn")).to_have_count(0)
        older = entries.nth(1)
        expect(older.locator(".lt-history__restore-btn")).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_button_hidden_on_newest_entry(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Only entry"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entry = page_as_superuser_for_backend.locator(".lt-history__entry").first
        expect(entry.locator(".lt-history__restore-btn")).to_have_count(0)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_button_not_on_state_changes(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "State test"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "State test"},
            {"en": False},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        deactivate_entry = page_as_superuser_for_backend.locator(".lt-history__entry--deactivate").first
        expect(deactivate_entry).to_be_visible()
        expect(deactivate_entry.locator(".lt-history__restore-btn")).to_have_count(0)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_clicking_restore_shows_confirmation(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "First"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Second"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        older_entry = page_as_superuser_for_backend.locator(".lt-history__entry").nth(1)
        older_entry.locator(".lt-history__restore-btn").click()
        confirm = older_entry.locator(".lt-history__restore-confirm")
        expect(confirm).to_be_visible()
        expect(older_entry.locator(".lt-history__restore-activate")).to_be_visible()
        expect(older_entry.locator(".lt-history__restore-inactive")).to_be_visible()
        expect(older_entry.locator(".lt-history__restore-cancel")).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_cancel_hides_confirmation(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "First"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Second"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        older_entry = page_as_superuser_for_backend.locator(".lt-history__entry").nth(1)
        older_entry.locator(".lt-history__restore-btn").click()
        expect(older_entry.locator(".lt-history__restore-confirm")).to_be_visible()
        older_entry.locator(".lt-history__restore-cancel").click()
        expect(older_entry.locator(".lt-history__restore-confirm")).to_be_hidden()
        expect(older_entry.locator(".lt-history__restore-btn")).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_and_activate(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hi"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        older_entry = page_as_superuser_for_backend.locator(".lt-history__entry").nth(1)
        older_entry.locator(".lt-history__restore-btn").click()
        older_entry.locator(".lt-history__restore-activate").click()
        page_as_superuser_for_backend.wait_for_timeout(2000)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("Hello", timeout=5000)
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        expect(page_as_superuser_for_backend.locator("#lt-input-en")).to_have_value("Hello")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_as_inactive(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Old text"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "New text"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        older_entry = page_as_superuser_for_backend.locator(".lt-history__entry").nth(1)
        older_entry.locator(".lt-history__restore-btn").click()
        older_entry.locator(".lt-history__restore-inactive").click()
        page_as_superuser_for_backend.wait_for_timeout(2000)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("Live Translations Demo", timeout=5000)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_from_delete_uses_old_value(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Custom"},
            {"en": True},
        )
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        delete_entry = page_as_superuser_for_backend.locator(".lt-history__entry--delete").first
        delete_entry.locator(".lt-history__restore-btn").click()
        delete_entry.locator(".lt-history__restore-activate").click()
        page_as_superuser_for_backend.wait_for_timeout(2000)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]')
        expect(span).to_have_text("Custom", timeout=5000)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_restore_creates_new_history_entry(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Original"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Updated"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entries_before = page_as_superuser_for_backend.locator(".lt-history__entry").count()
        older_entry = page_as_superuser_for_backend.locator(".lt-history__entry").nth(1)
        older_entry.locator(".lt-history__restore-btn").click()
        older_entry.locator(".lt-history__restore-activate").click()
        page_as_superuser_for_backend.wait_for_timeout(2000)
        # Reopen modal and check history again
        close_modal(page_as_superuser_for_backend)
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entries_after = page_as_superuser_for_backend.locator(".lt-history__entry").count()
        assert entries_after > entries_before
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
