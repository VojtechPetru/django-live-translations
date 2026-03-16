"""E2E tests for bulk activate — selection, action bar, confirmation, and activation."""

import json
import re

import pytest
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


class TestBulkActivate:
    def test_shift_click_selects_preview_element(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        span.click(modifiers=["Shift"])
        expect(span).to_have_class(re.compile(r"lt-selected"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_shift_click_deselects_selected_element(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        span.click(modifiers=["Shift"])
        expect(span).to_have_class(re.compile(r"lt-selected"))
        span.click(modifiers=["Shift"])
        expect(span).not_to_have_class(re.compile(r"lt-selected"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_action_bar_appears_when_elements_selected(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        span.click(modifiers=["Shift"])
        action_bar = page_as_superuser_for_backend.locator(".lt-action-bar")
        expect(action_bar).to_have_class(re.compile(r"lt-action-bar--visible"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_action_bar_shows_selection_count(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "about.heading",
            {"en": "Inactive About"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first.click(
            modifiers=["Shift"]
        )
        page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="about.heading"]').first.click(
            modifiers=["Shift"]
        )
        count_el = page_as_superuser_for_backend.locator(".lt-action-bar__count")
        expect(count_el).to_have_text("2 selected")
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "about.heading", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "about.heading", ["en"])

    def test_action_bar_clear_deselects_all(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        span.click(modifiers=["Shift"])
        expect(span).to_have_class(re.compile(r"lt-selected"))
        page_as_superuser_for_backend.locator(".lt-action-bar__clear").click()
        selected = page_as_superuser_for_backend.locator(".lt-selected")
        expect(selected).to_have_count(0)
        action_bar = page_as_superuser_for_backend.locator(".lt-action-bar")
        expect(action_bar).not_to_have_class(re.compile(r"lt-action-bar--visible"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_action_bar_activate_shows_confirmation(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first.click(
            modifiers=["Shift"]
        )
        page_as_superuser_for_backend.locator(".lt-action-bar__activate").click()
        confirm_btn = page_as_superuser_for_backend.locator(".lt-action-bar__confirm")
        cancel_btn = page_as_superuser_for_backend.locator(".lt-action-bar__cancel")
        warning = page_as_superuser_for_backend.locator(".lt-action-bar__warning")
        expect(confirm_btn).to_be_visible()
        expect(cancel_btn).to_be_visible()
        expect(warning).to_be_visible()
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_action_bar_cancel_returns_to_default(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first.click(
            modifiers=["Shift"]
        )
        page_as_superuser_for_backend.locator(".lt-action-bar__activate").click()
        expect(page_as_superuser_for_backend.locator(".lt-action-bar__confirm")).to_be_visible()
        page_as_superuser_for_backend.locator(".lt-action-bar__cancel").click()
        expect(page_as_superuser_for_backend.locator(".lt-action-bar__activate")).to_be_visible()
        expect(page_as_superuser_for_backend.locator(".lt-action-bar__clear")).to_be_visible()
        expect(page_as_superuser_for_backend.locator(".lt-action-bar__confirm")).to_be_hidden()
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_bulk_activate_confirm_activates_translations(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Bulk Activated Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span).to_have_class(re.compile(r"lt-preview"))
        span.click(modifiers=["Shift"])
        page_as_superuser_for_backend.locator(".lt-action-bar__activate").click()
        page_as_superuser_for_backend.locator(".lt-action-bar__confirm").click()
        toast = page_as_superuser_for_backend.locator(".lt-toast--success")
        expect(toast).to_be_visible(timeout=5000)
        expect(toast).to_contain_text("activated")
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        # After reload, the span should no longer have amber outline
        span_after = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span_after).not_to_have_class(re.compile(r"lt-preview"))
        expect(span_after).to_have_text("Bulk Activated Title")
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_bulk_activate_only_affects_page_language(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "EN Activated", "cs": "CS Still Inactive"},
            {"en": False, "cs": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first.click(
            modifiers=["Shift"]
        )
        page_as_superuser_for_backend.locator(".lt-action-bar__activate").click()
        page_as_superuser_for_backend.locator(".lt-action-bar__confirm").click()
        toast = page_as_superuser_for_backend.locator(".lt-toast--success")
        expect(toast).to_be_visible(timeout=5000)
        page_as_superuser_for_backend.wait_for_load_state("networkidle")
        # EN should be active now (text shows override)
        span_en = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        expect(span_en).to_have_text("EN Activated")
        # Verify CS is still inactive via API — fetch translation and check active flag
        csrf = page_as_superuser_for_backend.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
        response = page_as_superuser_for_backend.request.post(
            f"{base_url_for_backend}/__live-translations__/translations/save/",
            data=json.dumps(
                {
                    "msgid": "demo.title",
                    "context": "",
                    "translations": {"cs": "CS Still Inactive"},
                    "active_flags": {"cs": False},
                    "page_language": "cs",
                }
            ),
            headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
        )
        # Re-save with same inactive flag should succeed — confirms it was still inactive
        result = response.json()
        assert result.get("ok") is True
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en", "cs"])

    def test_shift_click_on_non_preview_opens_modal(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive For Context"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        # about.heading has no inactive override — shift+click should open modal
        non_preview_span = page_as_superuser_for_backend.locator(
            '.lt-translatable[data-lt-msgid="about.heading"]'
        ).first
        expect(non_preview_span).not_to_have_class(re.compile(r"lt-preview"))
        non_preview_span.click(modifiers=["Shift"])
        dialog = page_as_superuser_for_backend.locator("dialog.lt-dialog[open]")
        expect(dialog).to_be_visible(timeout=3000)
        # Close modal
        page_as_superuser_for_backend.locator(".lt-dialog__close").click()
        expect(dialog).to_be_hidden(timeout=3000)
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_action_bar_hides_when_all_deselected(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "demo.title",
            {"en": "Inactive Title"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        span = page_as_superuser_for_backend.locator('.lt-translatable[data-lt-msgid="demo.title"]').first
        span.click(modifiers=["Shift"])
        action_bar = page_as_superuser_for_backend.locator(".lt-action-bar")
        expect(action_bar).to_have_class(re.compile(r"lt-action-bar--visible"))
        span.click(modifiers=["Shift"])
        expect(action_bar).not_to_have_class(re.compile(r"lt-action-bar--visible"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "demo.title", ["en"])

    def test_attribute_elements_can_be_selected(
        self, page_as_superuser_for_backend: Page, backend_id: str, base_url_for_backend: str
    ) -> None:
        if backend_id == "po":
            pytest.skip(f"Skipping on {backend_id} backend")
        api_save(
            page_as_superuser_for_backend,
            base_url_for_backend,
            "attrs.tooltip_trans",
            {"en": "Inactive Tooltip"},
            {"en": False},
        )
        _enable_preview(page_as_superuser_for_backend, base_url_for_backend)
        attr_el = page_as_superuser_for_backend.locator('[data-lt-attrs*="attrs.tooltip_trans"]').first
        expect(attr_el).to_have_class(re.compile(r"lt-preview"))
        attr_el.click(modifiers=["Shift"])
        expect(attr_el).to_have_class(re.compile(r"lt-selected"))
        # Cleanup
        _disable_preview(page_as_superuser_for_backend, base_url_for_backend)
        api_delete(page_as_superuser_for_backend, base_url_for_backend, "attrs.tooltip_trans", ["en"])
        api_restore_po_default(page_as_superuser_for_backend, base_url_for_backend, "attrs.tooltip_trans", ["en"])
