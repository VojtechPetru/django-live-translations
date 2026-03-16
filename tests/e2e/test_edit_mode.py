"""E2E tests for edit mode — toggle, highlighting, and click-to-open behavior."""

from helpers import activate_edit_mode, deactivate_edit_mode, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestEditModeToggle:
    def test_keyboard_shortcut_activates_edit_mode(self, page_as_superuser: Page) -> None:
        body = page_as_superuser.locator("body")
        expect(body).not_to_have_class("lt-edit-mode")
        activate_edit_mode(page_as_superuser)
        expect(body).to_have_class("lt-edit-mode")

    def test_keyboard_shortcut_deactivates_edit_mode(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        expect(page_as_superuser.locator("body")).to_have_class("lt-edit-mode")
        deactivate_edit_mode(page_as_superuser)
        expect(page_as_superuser.locator("body")).not_to_have_class("lt-edit-mode")

    def test_shortcut_ignored_when_focus_in_textarea(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        textarea = page_as_superuser.locator("dialog.lt-dialog textarea").first
        textarea.focus()
        page_as_superuser.keyboard.press("Control+Shift+KeyE")
        # Edit mode should still be active because shortcut is ignored in textarea
        expect(page_as_superuser.locator("body")).to_have_class("lt-edit-mode")

    def test_shortcut_ignored_when_focus_in_input(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        input_el = page_as_superuser.locator("dialog.lt-dialog input").first
        input_el.focus()
        page_as_superuser.keyboard.press("Control+Shift+KeyE")
        expect(page_as_superuser.locator("body")).to_have_class("lt-edit-mode")

    def test_translatable_spans_highlighted_in_edit_mode(self, page_as_superuser: Page) -> None:
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first
        # Before edit mode — no dashed outline
        outline_before = page_as_superuser.evaluate("el => getComputedStyle(el).outlineStyle", span.element_handle())
        assert outline_before != "dashed"
        activate_edit_mode(page_as_superuser)
        outline_after = page_as_superuser.evaluate("el => getComputedStyle(el).outlineStyle", span.element_handle())
        assert outline_after == "dashed"

    def test_attribute_elements_highlighted_in_edit_mode(self, page_as_superuser: Page) -> None:
        attr_el = page_as_superuser.locator("[data-lt-attrs]").first
        activate_edit_mode(page_as_superuser)
        outline = page_as_superuser.evaluate("el => getComputedStyle(el).outlineStyle", attr_el.element_handle())
        assert outline == "solid"

    def test_hover_increases_outline_opacity(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first
        expect(span).to_be_visible()
        color_before = span.evaluate("el => getComputedStyle(el).outlineColor")
        span.hover()
        # CSS transition takes 150ms; wait for it to complete
        page_as_superuser.wait_for_timeout(250)
        color_after = span.evaluate("el => getComputedStyle(el).outlineColor")
        # The outline color should change on hover (opacity increase means different rgba value)
        assert color_before != color_after

    def test_no_outlines_when_edit_mode_inactive(self, page_as_superuser: Page) -> None:
        span = page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first
        outline_style = page_as_superuser.evaluate("el => getComputedStyle(el).outlineStyle", span.element_handle())
        assert outline_style in ("none", "")

    def test_clicking_translatable_span_opens_modal(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first.click()
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        expect(dialog).to_be_visible(timeout=3000)
        title = page_as_superuser.locator(".lt-dialog__title")
        expect(title).to_have_text("Edit Translation")

    def test_clicking_outside_edit_mode_does_nothing(self, page_as_superuser: Page) -> None:
        expect(page_as_superuser.locator("body")).not_to_have_class("lt-edit-mode")
        page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first.click()
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        expect(dialog).to_have_count(0)

    def test_clicking_attribute_element_opens_modal(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "attrs.tooltip_trans", attr=True)
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        expect(dialog).to_be_visible()
        title = page_as_superuser.locator(".lt-dialog__title")
        expect(title).to_have_text("Edit Translation")
