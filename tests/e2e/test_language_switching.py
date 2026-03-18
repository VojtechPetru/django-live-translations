"""E2E tests for language switching — tabs, tab state indicators, and page language."""

import re

import pytest
from helpers import api_delete, api_restore_po_default, api_save, close_modal, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestLanguageSwitching:
    def test_language_tabs_visible_with_multiple_languages(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        tabs_container = page_as_superuser.locator(".lt-editor__tabs")
        expect(tabs_container).to_be_visible()
        tabs = page_as_superuser.locator(".lt-editor__tab")
        expect(tabs).to_have_count(3)

    def test_tabs_have_correct_language_codes(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        en_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="en"]')
        cs_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="cs"]')
        expect(en_tab).to_be_visible()
        expect(cs_tab).to_be_visible()

    def test_current_page_language_selected_by_default(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        en_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="en"]')
        expect(en_tab).to_have_class(re.compile(r"--active"))

    def test_clicking_tab_switches_language(self, page_as_superuser: Page, base_url: str) -> None:
        # Ensure PO defaults are clean
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en", "cs"])
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        cs_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="cs"]')
        cs_tab.click()
        expect(cs_tab).to_have_class(re.compile(r"--active"))
        en_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="en"]')
        expect(en_tab).not_to_have_class(re.compile(r"--active"))
        cs_textarea = page_as_superuser.locator("#lt-input-cs")
        expect(cs_textarea).to_be_visible()
        expect(cs_textarea).to_have_value("Demo živých překladů")

    def test_edits_preserved_when_switching_tabs(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        en_textarea = page_as_superuser.locator("#lt-input-en")
        en_textarea.fill("Modified EN Title")
        # Switch to CS
        page_as_superuser.locator('.lt-editor__tab[data-lang="cs"]').click()
        expect(page_as_superuser.locator("#lt-input-cs")).to_be_visible()
        # Switch back to EN
        page_as_superuser.locator('.lt-editor__tab[data-lang="en"]').click()
        expect(en_textarea).to_have_value("Modified EN Title")

    def test_dirty_dot_appears_on_modified_tab(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        en_textarea = page_as_superuser.locator("#lt-input-en")
        en_textarea.fill("Dirty change")
        en_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="en"]')
        dirty_dot = en_tab.locator('[data-role="dirty"]')
        expect(dirty_dot).to_be_visible()

    def test_dirty_dot_disappears_when_reverted(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        en_textarea = page_as_superuser.locator("#lt-input-en")
        original_value = en_textarea.input_value()
        en_textarea.fill("Temporary change")
        en_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="en"]')
        dirty_dot = en_tab.locator('[data-role="dirty"]')
        expect(dirty_dot).to_be_visible()
        en_textarea.fill(original_value)
        expect(dirty_dot).to_be_hidden()

    def test_inactive_override_tab_has_amber_dot(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip("PO backend never sets has_override=True")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Override"},
            {"en": False},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        en_tab = page_as_superuser_for_backend.locator('.lt-editor__tab[data-lang="en"]')
        status_dot = en_tab.locator('[data-role="status"]')
        expect(status_dot).to_be_visible()
        expect(status_dot).to_have_class(re.compile(r"lt-editor__dot--inactive"))
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_delete_marked_tab_has_red_dot(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip("Delete override is DB-only")
        api_save(
            page_as_superuser_for_backend, base_url_for_backend, "demo.title", {"en": "For Delete Mark"}, {"en": True}
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

    def test_switching_page_language_shows_correct_translations(self, page_as_superuser: Page, base_url: str) -> None:
        # Ensure PO defaults are clean before checking
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en", "cs"])
        page_as_superuser.goto(f"{base_url}/cs/")
        page_as_superuser.wait_for_load_state("domcontentloaded")
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        cs_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="cs"]')
        expect(cs_tab).to_have_class(re.compile(r"--active"))
        cs_textarea = page_as_superuser.locator("#lt-input-cs")
        expect(cs_textarea).to_have_value("Demo živých překladů")
        # Navigate back to EN for other tests
        close_modal(page_as_superuser)
        page_as_superuser.goto(f"{base_url}/en/")
        page_as_superuser.wait_for_load_state("domcontentloaded")
