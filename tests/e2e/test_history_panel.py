import re

import pytest
from conftest import api_delete, api_restore_po_default, api_save, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestHistoryPanel:
    def test_history_button_toggles_to_history_view(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-dialog__title")).to_have_text("Edit History")
        expect(page_as_superuser_for_backend.locator(".lt-dialog__fields")).to_be_hidden()
        expect(page_as_superuser_for_backend.locator(".lt-dialog__history")).to_be_visible()

    def test_history_button_toggles_back_to_edit_view(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-dialog__title")).to_have_text("Edit History")
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-dialog__title")).to_have_text("Edit Translation")
        expect(page_as_superuser_for_backend.locator(".lt-dialog__fields")).to_be_visible()
        expect(page_as_superuser_for_backend.locator(".lt-dialog__history")).to_be_hidden()

    def test_empty_history_shows_message(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        empty = page_as_superuser_for_backend.locator(".lt-history__empty")
        expect(empty).to_be_visible(timeout=5000)
        expect(empty).to_contain_text("No edit history")

    def test_history_shows_create_entry(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Created for history"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entry = page_as_superuser_for_backend.locator(".lt-history__entry--create")
        expect(entry.first).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_shows_update_entry(
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
        entry = page_as_superuser_for_backend.locator(".lt-history__entry--update")
        expect(entry.first).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_shows_delete_entry(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Will be deleted"},
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
        entry = page_as_superuser_for_backend.locator(".lt-history__entry--delete")
        expect(entry.first).to_be_visible()

    def test_history_shows_activate_entry(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Activate test"},
            {"en": False},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Activate test"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entry = page_as_superuser_for_backend.locator(".lt-history__entry--activate")
        expect(entry.first).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_shows_deactivate_entry(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Deactivate test"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Deactivate test"},
            {"en": False},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entry = page_as_superuser_for_backend.locator(".lt-history__entry--deactivate")
        expect(entry.first).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_diff_view_by_default(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello world"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello everyone"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        update_entry = page_as_superuser_for_backend.locator(".lt-history__entry--update").first
        diff = update_entry.locator(".lt-history__diff")
        expect(diff).to_be_visible()
        expect(update_entry.locator(".lt-diff--equal").first).to_be_visible()
        expect(update_entry.locator(".lt-diff--delete").first).to_be_visible()
        expect(update_entry.locator(".lt-diff--insert").first).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_diff_value_tab_toggle(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello world"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello everyone"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        update_entry = page_as_superuser_for_backend.locator(".lt-history__entry--update").first
        value_tab = update_entry.locator(".lt-history__content-tab:not(.lt-history__content-tab--active)")
        value_tab.click()
        expect(update_entry.locator(".lt-history__diff")).to_be_hidden()
        expect(update_entry.locator(".lt-history__values")).to_be_visible()
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_value_view_shows_before_after(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello world"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Hello everyone"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        update_entry = page_as_superuser_for_backend.locator(".lt-history__entry--update").first
        value_tab = update_entry.locator(".lt-history__content-tab:not(.lt-history__content-tab--active)")
        value_tab.click()
        labels = update_entry.locator(".lt-history__value-label")
        expect(labels).to_have_count(2)
        expect(labels.nth(0)).to_have_text("Before")
        expect(labels.nth(1)).to_have_text("After")
        values = update_entry.locator(".lt-history__value-text")
        expect(values).to_have_count(2)
        expect(values.nth(0)).to_have_text("Hello world")
        expect(values.nth(1)).to_have_text("Hello everyone")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_shows_user_name(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "User name test"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entry = page_as_superuser_for_backend.locator(".lt-history__entry").first
        expect(entry).to_contain_text("admin")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_shows_timestamp(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Timestamp test"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        entry = page_as_superuser_for_backend.locator(".lt-history__entry").first
        timestamp_text = entry.locator("time").text_content()
        assert timestamp_text is not None
        assert len(timestamp_text.strip()) > 0
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_history_language_filter_pills(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "EN filter test", "cs": "CS filter test"},
            {"en": True, "cs": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        filters = page_as_superuser_for_backend.locator(".lt-history__filters")
        expect(filters).to_be_visible()
        pills = filters.locator(".lt-history__filter-pill")
        expect(pills).to_have_count(3, timeout=5000)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])

    def test_history_filter_by_language(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "EN only"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"cs": "CS only"},
            {"cs": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--history").click()
        expect(page_as_superuser_for_backend.locator(".lt-history__timeline")).to_be_visible(timeout=5000)
        all_entries_before = page_as_superuser_for_backend.locator(".lt-history__entry")
        total_count = all_entries_before.count()
        cs_pill = page_as_superuser_for_backend.locator(".lt-history__filter-pill").filter(has_text="cs")
        cs_pill.click()
        expect(cs_pill).to_have_class(re.compile(r"--active"))
        visible_entries = page_as_superuser_for_backend.locator(".lt-history__entry:visible")
        assert visible_entries.count() < total_count
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])

    def test_activate_deactivate_have_no_diff_tabs(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "State change test"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "State change test"},
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
        tabs = deactivate_entry.locator(".lt-history__content-tab")
        expect(tabs).to_have_count(0)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
