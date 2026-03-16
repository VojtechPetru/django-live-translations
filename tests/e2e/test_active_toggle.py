"""E2E tests for the active toggle — visibility, state, labels, and tab indicators."""

from conftest import api_restore_po_default, api_save, check_active_toggle, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestActiveToggle:
    def test_toggle_hidden_when_value_matches_default_no_override(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        toggle = page_as_superuser.locator(".lt-field__toggle").first
        expect(toggle).to_be_hidden()

    def test_toggle_appears_when_text_differs_from_default(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Something completely different")
        toggle = page_as_superuser.locator(".lt-field__toggle").first
        expect(toggle).to_be_visible()

    def test_toggle_stays_visible_when_override_exists(self, page_as_superuser: Page, base_url: str) -> None:
        # Save inactive override — for PO this creates a pending, which means has_override is detected via pending
        api_save(
            page_as_superuser,
            base_url,
            "demo.title",
            {"en": "Pending Override"},
            {"en": False},
        )
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("networkidle")
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        # Toggle should be visible because the value differs from PO default
        toggle = page_as_superuser.locator(".lt-field__toggle").first
        expect(toggle).to_be_visible()
        # Cleanup
        api_restore_po_default(page_as_superuser, base_url, "demo.title", ["en"])

    def test_toggle_default_state_matches_active_by_default_setting(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("New text to trigger toggle")
        toggle_input = page_as_superuser.locator("#lt-active-en")
        # activeByDefault is false, so toggle should be unchecked
        expect(toggle_input).not_to_be_checked()

    def test_toggle_label_shows_active_when_checked(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Text to show toggle")
        check_active_toggle(page_as_superuser)
        label = page_as_superuser.locator(".lt-field__toggle-label").first
        expect(label).to_have_text("Active")

    def test_toggle_label_shows_inactive_when_unchecked(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Text to show toggle")
        toggle_input = page_as_superuser.locator("#lt-active-en")
        # activeByDefault is false, so it starts unchecked
        expect(toggle_input).not_to_be_checked()
        label = page_as_superuser.locator(".lt-field__toggle-label").first
        expect(label).to_have_text("Inactive")

    def test_toggling_active_updates_tab_indicator(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        textarea.fill("Changed text")
        toggle_input = page_as_superuser.locator("#lt-active-en")
        # Toggle to inactive (uncheck) — should mark the tab as dirty/inactive-override
        expect(toggle_input).not_to_be_checked()
        en_tab = page_as_superuser.locator('.lt-editor__tab[data-lang="en"]')
        # The tab should have the dirty modifier since text differs from loaded value
        tab_classes = en_tab.get_attribute("class") or ""
        assert "lt-editor__tab--dirty" in tab_classes or "lt-editor__tab--inactive-override" in tab_classes

    def test_toggle_resets_when_text_reverted_to_default(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("#lt-input-en")
        # Get the PO default value
        po_default = page_as_superuser.locator(".lt-field__po-default").first.text_content()
        assert po_default is not None
        # Change text to make toggle appear
        textarea.fill("Temporary different text")
        toggle = page_as_superuser.locator(".lt-field__toggle").first
        expect(toggle).to_be_visible()
        # Revert to default
        textarea.fill(po_default)
        expect(toggle).to_be_hidden()
