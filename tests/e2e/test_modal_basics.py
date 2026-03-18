"""E2E tests for modal structure — title, msgid, hints, buttons, and closing behavior."""

import re

from helpers import API_PREFIX, activate_edit_mode, close_modal, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestModalStructure:
    def test_modal_has_edit_translation_title(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        title = page_as_superuser.locator(".lt-dialog__title")
        expect(title).to_have_text("Edit Translation")

    def test_modal_shows_msgid(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        msgid_text = page_as_superuser.locator(".lt-dialog__msgid-text")
        expect(msgid_text).to_have_text("demo.title")

    def test_modal_shows_msgid_label(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        label = page_as_superuser.locator(".lt-dialog__msgid-label")
        expect(label).to_have_text("msgid")

    def test_modal_shows_attribute_label_for_attr_translations(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "attrs.tooltip_trans", attr=True)
        label = page_as_superuser.locator(".lt-dialog__msgid-label")
        # Attribute translations show "msgid · <attr_name>" with a middle dot
        expect(label).to_contain_text("msgid")
        expect(label).to_contain_text("title")

    def test_modal_copy_msgid_button(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        # Grant clipboard permissions for headless mode
        page_as_superuser.context.grant_permissions(["clipboard-read", "clipboard-write"])
        msgid_el = page_as_superuser.locator(".lt-dialog__msgid")
        msgid_el.click()
        # After successful copy, the element gets a --copied class
        expect(msgid_el).to_have_class(re.compile(r"--copied"), timeout=2000)

    def test_modal_shows_translator_hint_when_available(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.welcome")
        hint = page_as_superuser.locator(".lt-dialog__hint")
        expect(hint).to_be_visible()
        expect(hint).to_contain_text("Greeting shown on the homepage")

    def test_modal_hides_hint_when_not_available(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        hint = page_as_superuser.locator(".lt-dialog__hint")
        expect(hint).to_be_hidden()

    def test_modal_shows_loading_then_fields(self, page_as_superuser: Page) -> None:
        activate_edit_mode(page_as_superuser)
        # Intercept the API call and add a delay
        page_as_superuser.route(
            f"**{API_PREFIX}/translations/*",
            lambda route: (
                page_as_superuser.wait_for_timeout(1000),
                route.continue_(),
            )[-1],
        )
        page_as_superuser.locator('lt-t[data-lt-msgid="demo.title"]').first.click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_visible(timeout=3000)
        # Loading should be visible while waiting
        loading = page_as_superuser.locator(".lt-dialog__loading")
        expect(loading).to_be_visible(timeout=2000)
        # Eventually fields should load
        fields = page_as_superuser.locator(".lt-dialog__fields")
        expect(fields).to_be_visible(timeout=5000)
        expect(loading).to_be_hidden()
        # Clean up route
        page_as_superuser.unroute(f"**{API_PREFIX}/translations/*")

    def test_close_via_x_button(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        close_modal(page_as_superuser)
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        expect(dialog).to_be_hidden()

    def test_close_via_cancel_button(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.locator(".lt-btn--cancel").click()
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        expect(dialog).to_be_hidden(timeout=3000)

    def test_close_via_escape_key(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        page_as_superuser.keyboard.press("Escape")
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        expect(dialog).to_be_hidden(timeout=3000)

    def test_close_via_backdrop_click(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        dialog = page_as_superuser.locator("dialog.lt-dialog[open]")
        dialog_box = dialog.bounding_box()
        assert dialog_box is not None
        # Click at the very edge of the dialog (outside the form, but on the backdrop)
        page_as_superuser.mouse.click(dialog_box["x"] + 2, dialog_box["y"] + 2)
        expect(dialog).to_be_hidden(timeout=3000)

    def test_closing_modal_returns_to_active_state(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        close_modal(page_as_superuser)
        expect(page_as_superuser.locator("body")).to_have_class("lt-edit-mode")

    def test_modal_has_save_button(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)
        save_btn = page_as_superuser.locator(".lt-btn--save")
        expect(save_btn).to_be_visible()

    def test_modal_has_history_button(self, page_as_superuser: Page) -> None:
        open_modal(page_as_superuser, "demo.title")
        history_btn = page_as_superuser.locator(".lt-btn--history")
        expect(history_btn).to_be_visible()
