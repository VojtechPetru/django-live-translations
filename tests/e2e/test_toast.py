"""E2E tests for toast notifications — error display, auto-dismiss, and deduplication."""

import re

import pytest
from conftest import API_PREFIX, activate_edit_mode, api_delete, api_restore_po_default, api_save
from playwright.sync_api import Page, Route, expect


class TestToastNotifications:
    def _click_span_with_intercepted_api(self, page: Page) -> None:
        """Activate edit mode and click a span while the translations API is intercepted."""
        body_classes = page.locator("body").get_attribute("class") or ""
        if "lt-edit-mode" not in body_classes:
            activate_edit_mode(page)
        page.locator('.lt-translatable[data-lt-msgid="demo.title"]').first.click()

    def test_error_toast_on_api_failure(self, page_as_superuser: Page) -> None:
        def intercept_get(route: Route) -> None:
            route.fulfill(status=500, content_type="application/json", body='{"error": "Server error"}')

        page_as_superuser.route(f"**{API_PREFIX}/translations/?*", intercept_get)
        try:
            self._click_span_with_intercepted_api(page_as_superuser)
            toast = page_as_superuser.locator(".lt-toast")
            expect(toast).to_be_visible(timeout=5000)
            expect(toast).to_have_class(re.compile(r"lt-toast--error"))
        finally:
            page_as_superuser.unroute(f"**{API_PREFIX}/translations/?*")

    def test_toast_auto_dismisses(self, page_as_superuser: Page) -> None:
        def intercept_get(route: Route) -> None:
            route.fulfill(status=500, content_type="application/json", body='{"error": "Timeout"}')

        page_as_superuser.route(f"**{API_PREFIX}/translations/?*", intercept_get)
        try:
            self._click_span_with_intercepted_api(page_as_superuser)
            toast = page_as_superuser.locator(".lt-toast")
            expect(toast).to_be_visible(timeout=5000)
            # Toast disappears within ~3.3 seconds
            expect(toast).to_be_hidden(timeout=6000)
        finally:
            page_as_superuser.unroute(f"**{API_PREFIX}/translations/?*")

    def test_error_toast_shows_message(self, page_as_superuser: Page) -> None:
        def intercept_get(route: Route) -> None:
            route.fulfill(status=500, content_type="application/json", body='{"error": "Custom error msg"}')

        page_as_superuser.route(f"**{API_PREFIX}/translations/?*", intercept_get)
        try:
            self._click_span_with_intercepted_api(page_as_superuser)
            toast = page_as_superuser.locator(".lt-toast")
            expect(toast).to_be_visible(timeout=5000)
            # Frontend shows generic message for GET failures: "Failed to load translations: GET failed: 500"
            expect(toast).to_contain_text("Failed to load translations")
        finally:
            page_as_superuser.unroute(f"**{API_PREFIX}/translations/?*")

    def test_new_toast_replaces_existing(self, page_as_superuser: Page) -> None:
        call_count = {"n": 0}

        def intercept_get(route: Route) -> None:
            call_count["n"] += 1
            route.fulfill(status=500, content_type="application/json", body=f'{{"error": "Error {call_count["n"]}"}}')

        page_as_superuser.route(f"**{API_PREFIX}/translations/?*", intercept_get)
        try:
            # First error toast
            self._click_span_with_intercepted_api(page_as_superuser)
            toast = page_as_superuser.locator(".lt-toast")
            expect(toast).to_be_visible(timeout=5000)
            # Close modal if open, then click again
            page_as_superuser.keyboard.press("Escape")
            page_as_superuser.wait_for_timeout(500)
            self._click_span_with_intercepted_api(page_as_superuser)
            # Only one toast should exist
            expect(page_as_superuser.locator(".lt-toast")).to_have_count(1, timeout=3000)
        finally:
            page_as_superuser.unroute(f"**{API_PREFIX}/translations/?*")

    def test_bulk_activate_success_toast(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip("PO backend reloads too fast for toast to be visible")
        page = page_as_superuser_for_backend
        base_url = base_url_for_backend
        api_save(page, base_url, "demo.title", {"en": "Bulk Toast Test"}, {"en": False})
        page.context.add_cookies([{"name": "lt_preview", "value": "1", "url": base_url}])
        page.reload()
        page.wait_for_load_state("networkidle")

        span = page.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        span.click(modifiers=["Shift"])
        page.locator(".lt-action-bar__activate").click()
        page.locator(".lt-action-bar__confirm").click()
        toast = page.locator(".lt-toast--success")
        expect(toast).to_be_visible(timeout=10000)
        expect(toast).to_contain_text("activated")

        page.context.clear_cookies()
        api_delete(page, base_url, "demo.title", ["en"])
        api_restore_po_default(page, base_url, "demo.title", ["en"])
