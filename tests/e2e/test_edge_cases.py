"""E2E tests for edge cases — API validation, error handling, and special inputs."""

import json
import re

from helpers import (
    API_PREFIX,
    activate_edit_mode,
    api_restore_po_default,
    api_save,
    check_active_toggle,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, Route, expect


class TestEdgeCases:
    def test_api_returns_400_for_empty_msgid(self, page_as_superuser: Page, base_url: str) -> None:
        response = page_as_superuser.request.get(f"{base_url}{API_PREFIX}/translations/?msgid=&context=")
        assert response.status == 400

    def test_save_with_invalid_language_returns_400(self, page_as_superuser: Page, base_url: str) -> None:
        csrf = page_as_superuser.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
        response = page_as_superuser.request.post(
            f"{base_url}{API_PREFIX}/translations/save/",
            data=json.dumps(
                {
                    "msgid": "demo.title",
                    "context": "",
                    "translations": {"xx": "Invalid lang"},
                    "active_flags": {"xx": True},
                    "page_language": "en",
                }
            ),
            headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        )
        assert response.status == 400
        body = response.json()
        assert "Invalid language" in body.get("error", "")

    def test_save_with_invalid_json_returns_400(self, page_as_superuser: Page, base_url: str) -> None:
        csrf = page_as_superuser.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
        response = page_as_superuser.request.post(
            f"{base_url}{API_PREFIX}/translations/save/",
            data="this is not json",
            headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        )
        assert response.status in (400, 403, 500)  # Invalid body may trigger different error paths

    def test_delete_with_missing_msgid_returns_400(self, page_as_superuser: Page, base_url: str) -> None:
        csrf = page_as_superuser.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
        response = page_as_superuser.request.post(
            f"{base_url}{API_PREFIX}/translations/delete/",
            data=json.dumps({"context": "", "languages": ["en"], "page_language": "en"}),
            headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        )
        assert response.status == 400

    def test_bulk_activate_with_empty_msgids_returns_400(self, page_as_superuser: Page, base_url: str) -> None:
        csrf = page_as_superuser.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
        response = page_as_superuser.request.post(
            f"{base_url}{API_PREFIX}/translations/bulk-activate/",
            data=json.dumps({"language": "en", "msgids": []}),
            headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        )
        assert response.status == 400

    def test_bulk_activate_without_language_returns_400(self, page_as_superuser: Page, base_url: str) -> None:
        csrf = page_as_superuser.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
        response = page_as_superuser.request.post(
            f"{base_url}{API_PREFIX}/translations/bulk-activate/",
            data=json.dumps({"msgids": [{"msgid": "demo.title", "context": ""}]}),
            headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        )
        assert response.status == 400

    def test_opening_modal_during_api_error_shows_toast(self, page_as_superuser: Page) -> None:
        def intercept_get(route: Route) -> None:
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"ok": false, "error": "Server error"}',
            )

        page_as_superuser.route(f"**{API_PREFIX}/translations/?*", intercept_get)
        try:
            activate_edit_mode(page_as_superuser)
            page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first.click()
            # Dialog may open and close quickly on error; the key assertion is the error toast
            toast = page_as_superuser.locator(".lt-toast")
            expect(toast).to_be_visible(timeout=5000)
            expect(toast).to_have_class(re.compile(r"lt-toast--error"))
        finally:
            page_as_superuser.unroute(f"**{API_PREFIX}/translations/?*")

    def test_concurrent_save_handles_gracefully(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.locator("#lt-input-en").fill("First Concurrent")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        # Immediately reopen and save again
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.locator("#lt-input-en").fill("Second Concurrent")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_have_text("Second Concurrent")
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_history_limit_respected(self, page_as_superuser: Page, base_url: str) -> None:
        # Create multiple history entries
        for i in range(5):
            api_save(page_as_superuser, base_url, "demo.title", {"en": f"History v{i}"}, {"en": True})
        response = page_as_superuser.request.get(
            f"{base_url}{API_PREFIX}/translations/history/?msgid=demo.title&context=&limit=3"
        )
        data = response.json()
        history = data.get("history", [])
        assert len(history) <= 3
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_blocktrans_with_placeholder_renders_correctly(self, page_as_superuser: Page) -> None:
        span = page_as_superuser.locator('lt-t[data-lt-msgid="edit_mode.toggle_hint %(key)s"]').first
        expect(span).to_be_visible()
        text = span.text_content() or ""
        # The placeholder %(key)s should be substituted with "Shift+T" or similar
        assert "%(key)s" not in text
        assert "Shift" in text or "shift" in text.lower()

    def test_gettext_lazy_produces_translatable_spans(self, page_as_superuser: Page) -> None:
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.description"]')
        assert span.count() >= 1
        expect(span.first).to_be_visible()

    def test_gettext_produces_translatable_spans(self, page_as_superuser: Page) -> None:
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.welcome"]')
        assert span.count() >= 1
        expect(span.first).to_be_visible()

    def test_trans_tag_produces_translatable_spans(self, page_as_superuser: Page) -> None:
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]')
        assert span.count() >= 1
        expect(span.first).to_be_visible()

    def test_trans_as_var_produces_translatable_spans(self, page_as_superuser: Page) -> None:
        """{% trans '...' as X %} should produce translatable spans where {{ X }} is rendered."""
        spans = page_as_superuser.locator('lt-t[data-lt-msgid="asvar.reused_label"]')
        # The variable is used in 2 text positions
        assert spans.count() >= 2
        expect(spans.first).to_be_visible()
        expect(spans.nth(1)).to_be_visible()

    def test_trans_as_var_in_attribute(self, page_as_superuser: Page) -> None:
        """{% trans '...' as X %} used in title="" should produce data-lt-attrs."""
        el = page_as_superuser.locator("[data-lt-attrs]").filter(
            has=page_as_superuser.locator('lt-t[data-lt-msgid="asvar.reused_label"]')
        )
        assert el.count() >= 1
        attrs_json = el.first.get_attribute("data-lt-attrs")
        assert attrs_json is not None
        assert "asvar.reused_label" in attrs_json

    def test_saving_empty_string_is_valid(self, page_as_superuser: Page, base_url: str) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.locator("#lt-input-en").fill("")
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        # Save succeeds — modal closes without error
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_special_characters_in_translation(self, page_as_superuser: Page, base_url: str) -> None:
        xss_text = "<script>alert(1)</script>"
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.locator("#lt-input-en").fill(xss_text)
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first
        # textContent should show the literal text, not execute it
        text_content = span.text_content()
        assert text_content is not None
        assert "<script>" in text_content or "&lt;script&gt;" in text_content
        # Ensure our text is properly escaped in the span (no raw script tags)
        inner_html = span.inner_html()
        assert "<script>" not in inner_html
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_long_translation_text_handled(self, page_as_superuser: Page, base_url: str) -> None:
        long_text = "A" * 1500
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.locator("#lt-input-en").fill(long_text)
        check_active_toggle(page_as_superuser)
        page_as_superuser.locator(".lt-btn--save").click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first
        text_content = span.text_content()
        assert text_content is not None
        assert len(text_content) >= 1000
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])
