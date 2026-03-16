"""E2E tests for preview mode — cookie, amber/blue outlines, auto-edit-mode, and text display."""

import re

from helpers import api_delete, api_restore_po_default, api_save
from playwright.sync_api import Page, expect


def _enable_preview(page: Page, base_url: str) -> None:
    page.context.add_cookies([{"name": "lt_preview", "value": "1", "url": base_url}])
    page.reload()
    page.wait_for_load_state("networkidle")


def _disable_preview(page: Page, base_url: str) -> None:
    page.context.add_cookies([{"name": "lt_preview", "value": "", "url": base_url}])
    page.reload()
    page.wait_for_load_state("networkidle")


class TestPreviewMode:
    def test_preview_mode_activates_via_keyboard(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        # Keyboard shortcut sets cookie and triggers page reload
        with page_as_superuser_for_backend.expect_navigation():
            page_as_superuser_for_backend.keyboard.press("Control+Shift+KeyP")
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        cookies = page_as_superuser_for_backend.context.cookies()
        preview_cookie = next((c for c in cookies if c["name"] == "lt_preview"), None)
        assert preview_cookie is not None
        assert preview_cookie["value"] == "1"
        preview_flag = page_as_superuser_for_backend.evaluate("() => window.__LT_CONFIG__?.preview")
        assert preview_flag is True
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)

    def test_preview_cookie_persists_across_pages(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        page_as_superuser_for_backend.goto(f"{base_url_for_backend}/cs/")
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        cookies = page_as_superuser_for_backend.context.cookies()
        preview_cookie = next((c for c in cookies if c["name"] == "lt_preview"), None)
        assert preview_cookie is not None
        assert preview_cookie["value"] == "1"
        # Cleanup — navigate back to EN
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        page_as_superuser_for_backend.goto(f"{base_url_for_backend}/en/")
        page_as_superuser_for_backend.wait_for_load_state("networkidle")

    def test_preview_shows_inactive_with_amber_outline(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Preview Amber Text"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_preview_auto_activates_edit_mode(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        body = page_as_superuser_for_backend.locator("body")
        expect(body).to_have_class(re.compile(r"lt-edit-mode"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)

    def test_active_translations_have_blue_outline_in_preview(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Active Override"},
            {"en": True},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "about.heading",
            {"en": "Inactive About"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        active_span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        inactive_span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="about.heading"]').first
        expect(active_span).not_to_have_class(re.compile(r"lt-preview"))
        expect(inactive_span).to_have_class(re.compile(r"lt-preview"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "about.heading", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "about.heading", ["en"])

    def test_preview_shows_inactive_override_text(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Custom Preview Text"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_text("Custom Preview Text")
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_normal_mode_shows_po_default_for_inactive(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Invisible Inactive Text"},
            {"en": False},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_text("Live Translations Demo")
        # Cleanup
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_disabling_preview_removes_amber_outlines(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Will Disappear"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        preview_elements = page_as_superuser_for_backend.locator(".lt-preview")
        expect(preview_elements).to_have_count(0)
        span_after = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span_after).to_have_text("Live Translations Demo")
        # Cleanup
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
