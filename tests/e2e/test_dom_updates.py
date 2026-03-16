"""E2E tests for in-place DOM updates — span text, attributes, and preview class toggling."""

import re

import pytest
from helpers import (
    api_delete,
    api_restore_po_default,
    api_save,
    check_active_toggle,
    disable_preview,
    enable_preview,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect


class TestInPlaceDomUpdates:
    def test_save_active_updates_span_text(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        textarea = page_as_superuser_for_backend.locator("#lt-input-en")
        textarea.fill("Updated Title")
        check_active_toggle(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser_for_backend.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_have_text("Updated Title")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_save_inactive_reverts_to_default(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        textarea = page_as_superuser_for_backend.locator("#lt-input-en")
        textarea.fill("Inactive Text")
        toggle = page_as_superuser_for_backend.locator("#lt-active-en")
        expect(toggle).not_to_be_checked()
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser_for_backend.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_have_text("Live Translations Demo")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_delete_override_reverts_to_default(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Custom Override"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        span = page_as_superuser_for_backend.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_have_text("Custom Override")
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        delete_btn = page_as_superuser_for_backend.locator(".lt-btn--delete-override")
        delete_btn.click()
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        expect(span).to_have_text("Live Translations Demo")
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_attribute_translation_update(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        open_modal(page_as_superuser_for_backend, "attrs.tooltip_trans", attr=True)
        wait_for_fields_loaded(page_as_superuser_for_backend)
        textarea = page_as_superuser_for_backend.locator("#lt-input-en")
        textarea.fill("Updated tooltip text")
        check_active_toggle(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        attr_el = page_as_superuser_for_backend.locator('[data-lt-attrs*="attrs.tooltip_trans"]').first
        expect(attr_el).to_have_attribute("title", "Updated tooltip text")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "attrs.tooltip_trans", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "attrs.tooltip_trans", ["en"])

    def test_multiple_elements_same_msgid_all_update(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        spans = page_as_superuser_for_backend.locator('lt-t[data-lt-msgid="demo.title"]')
        count = spans.count()
        assert count >= 1, "Expected at least one element with demo.title msgid"
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        textarea = page_as_superuser_for_backend.locator("#lt-input-en")
        textarea.fill("Broadcast Update")
        check_active_toggle(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        for i in range(count):
            expect(spans.nth(i)).to_have_text("Broadcast Update")
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_preview_entry_gets_amber_class_after_save(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        textarea = page_as_superuser_for_backend.locator("#lt-input-en")
        textarea.fill("Preview Inactive Text")
        toggle = page_as_superuser_for_backend.locator("#lt-active-en")
        expect(toggle).not_to_be_checked()
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser_for_backend.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_activating_removes_preview_class(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Pending Activation"},
            {"en": False},
        )
        enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        open_modal(page_as_superuser_for_backend, "demo.title")
        wait_for_fields_loaded(page_as_superuser_for_backend)
        check_active_toggle(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        expect(span).not_to_have_class(re.compile(r"lt-preview"))
        disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
