"""E2E tests for HTML content in translations.

Verifies that translations containing HTML tags render correctly in the
browser after saving via the widget — tags should be parsed as HTML, not
displayed as literal text like ``<strong>bold</strong>``.
"""

from helpers import (
    api_delete,
    api_restore_po_default,
    api_save,
    check_active_toggle,
    open_modal,
    wait_for_fields_loaded,
)
from playwright.sync_api import Page, expect


class TestHtmlContentInTranslations:
    """Saving a translation with HTML tags should render them as HTML, not literal text."""

    MSGID = "demo.title"

    def test_html_tags_rendered_after_save_via_widget(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        """Type HTML into the widget textarea, save, and verify the DOM contains
        an actual <strong> element rather than the literal string '<strong>'."""
        open_modal(page_as_superuser_for_backend, self.MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)

        textarea = page_as_superuser_for_backend.locator("#lt-input-en-0")
        textarea.fill("Live <strong>Translations</strong> Demo")
        check_active_toggle(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        span = page_as_superuser_for_backend.locator(f'lt-t[data-lt-msgid="{self.MSGID}"]').first
        # The <strong> tag should be parsed as HTML — a <strong> child should exist
        strong = span.locator("strong")
        expect(strong).to_have_count(1)
        expect(strong).to_have_text("Translations")

        # Cleanup
        api_delete(page_as_superuser_for_backend, base_url_for_backend, self.MSGID, ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, self.MSGID, ["en"])

    def test_html_tags_rendered_after_api_save_and_reload(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        """Save HTML via the API, reload the page, and verify the server-rendered
        output contains actual HTML elements (not escaped entities)."""
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            self.MSGID,
            {"en": "Live <em>Translations</em> Demo"},
            {"en": True},
        )
        page_as_superuser_for_backend.reload()
        page_as_superuser_for_backend.wait_for_load_state("domcontentloaded")

        span = page_as_superuser_for_backend.locator(f'lt-t[data-lt-msgid="{self.MSGID}"]').first
        em = span.locator("em")
        expect(em).to_have_count(1)
        expect(em).to_have_text("Translations")

        # Cleanup
        api_delete(page_as_superuser_for_backend, base_url_for_backend, self.MSGID, ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, self.MSGID, ["en"])

    def test_literal_text_not_visible_for_html_tags(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        """The literal string '<strong>' should NOT appear as visible text."""
        open_modal(page_as_superuser_for_backend, self.MSGID)
        wait_for_fields_loaded(page_as_superuser_for_backend)

        textarea = page_as_superuser_for_backend.locator("#lt-input-en-0")
        textarea.fill("Click <strong>here</strong> now")
        check_active_toggle(page_as_superuser_for_backend)
        page_as_superuser_for_backend.locator(".lt-btn--save").click()
        expect(page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=5000)

        span = page_as_superuser_for_backend.locator(f'lt-t[data-lt-msgid="{self.MSGID}"]').first

        # The visible text should be "Click here now", not "Click <strong>here</strong> now"
        expect(span).to_have_text("Click here now")

        # Cleanup
        api_delete(page_as_superuser_for_backend, base_url_for_backend, self.MSGID, ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, self.MSGID, ["en"])
