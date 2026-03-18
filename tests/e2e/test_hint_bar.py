"""E2E tests for the hint bar — visibility, buttons, dragging, and state persistence."""

import json
import re

from helpers import activate_edit_mode, deactivate_edit_mode
from playwright.sync_api import Page, expect


class TestHintBar:
    def test_hint_bar_visible_on_load(self, page_as_superuser: Page) -> None:
        hint = page_as_superuser.locator(".lt-hint")
        expect(hint).to_be_visible()
        expect(hint).to_have_class(re.compile(r"lt-hint--visible"))

    def test_hint_bar_contains_brand_label(self, page_as_superuser: Page) -> None:
        brand = page_as_superuser.locator(".lt-hint__brand")
        expect(brand).to_have_text("Live Translations")

    def test_hint_bar_shows_edit_shortcut(self, page_as_superuser: Page) -> None:
        edit_btn = page_as_superuser.locator('.lt-hint__action[data-mode="edit"]')
        expect(edit_btn).to_be_visible()
        kbd = edit_btn.locator(".lt-hint__kbd")
        expect(kbd).to_be_visible()

    def test_hint_bar_shows_preview_shortcut(self, page_as_superuser: Page) -> None:
        preview_btn = page_as_superuser.locator('.lt-hint__action[data-mode="preview"]')
        expect(preview_btn).to_be_visible()
        kbd = preview_btn.locator(".lt-hint__kbd")
        expect(kbd).to_be_visible()

    def test_edit_button_toggles_edit_mode_on(self, page_as_superuser: Page) -> None:
        edit_btn = page_as_superuser.locator('.lt-hint__action[data-mode="edit"]')
        edit_btn.click()
        expect(page_as_superuser.locator("body")).to_have_class(re.compile(r"lt-edit-mode"))
        expect(edit_btn).to_have_class(re.compile(r"lt-hint__action--active"))

    def test_edit_button_toggles_edit_mode_off(self, page_as_superuser: Page) -> None:
        edit_btn = page_as_superuser.locator('.lt-hint__action[data-mode="edit"]')
        edit_btn.click()
        expect(page_as_superuser.locator("body")).to_have_class(re.compile(r"lt-edit-mode"))
        edit_btn.click()
        expect(page_as_superuser.locator("body")).not_to_have_class(re.compile(r"lt-edit-mode"))

    def test_preview_button_sets_cookie_and_reloads(self, page_as_superuser: Page) -> None:
        preview_btn = page_as_superuser.locator('.lt-hint__action[data-mode="preview"]')
        preview_btn.click()
        page_as_superuser.wait_for_load_state("domcontentloaded")
        cookies = page_as_superuser.context.cookies()
        preview_cookie = [c for c in cookies if c["name"] == "lt_preview"]
        assert len(preview_cookie) == 1
        assert preview_cookie[0]["value"] == "1"
        preview_btn_after = page_as_superuser.locator('.lt-hint__action[data-mode="preview"]')
        expect(preview_btn_after).to_have_class(re.compile(r"lt-hint__action--active"))

    def test_preview_button_clears_cookie_on_second_click(self, page_as_superuser: Page) -> None:
        preview_btn = page_as_superuser.locator('.lt-hint__action[data-mode="preview"]')
        # First click: enable preview
        preview_btn.click()
        page_as_superuser.wait_for_load_state("domcontentloaded")
        # Second click: disable preview
        page_as_superuser.locator('.lt-hint__action[data-mode="preview"]').click()
        page_as_superuser.wait_for_load_state("domcontentloaded")
        cookies = page_as_superuser.context.cookies()
        preview_cookie = [c for c in cookies if c["name"] == "lt_preview" and c["value"] == "1"]
        assert len(preview_cookie) == 0

    def test_hint_bar_edit_active_state_reflects_keyboard_toggle(self, page_as_superuser: Page) -> None:
        edit_btn = page_as_superuser.locator('.lt-hint__action[data-mode="edit"]')
        expect(edit_btn).not_to_have_class(re.compile(r"lt-hint__action--active"))
        activate_edit_mode(page_as_superuser)
        expect(edit_btn).to_have_class(re.compile(r"lt-hint__action--active"))
        deactivate_edit_mode(page_as_superuser)
        expect(edit_btn).not_to_have_class(re.compile(r"lt-hint__action--active"))

    def test_hint_bar_draggable(self, page_as_superuser: Page) -> None:
        bar = page_as_superuser.locator(".lt-hint")
        box = bar.bounding_box()
        assert box is not None
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        page_as_superuser.mouse.move(start_x, start_y)
        page_as_superuser.mouse.down()
        page_as_superuser.mouse.move(start_x + 100, start_y, steps=10)
        page_as_superuser.mouse.up()
        new_box = bar.bounding_box()
        assert new_box is not None
        assert abs(new_box["x"] - box["x"]) > 50

    def test_hint_bar_position_persists_in_localstorage(self, page_as_superuser: Page) -> None:
        bar = page_as_superuser.locator(".lt-hint")
        box = bar.bounding_box()
        assert box is not None
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        page_as_superuser.mouse.move(start_x, start_y)
        page_as_superuser.mouse.down()
        page_as_superuser.mouse.move(start_x + 100, start_y, steps=10)
        page_as_superuser.mouse.up()
        stored = page_as_superuser.evaluate("() => localStorage.getItem('lt_hint_pos')")
        assert stored is not None
        pos = json.loads(stored)
        assert "x" in pos
        assert "y" in pos

    def test_hint_bar_restores_position_from_localstorage(self, page_as_superuser: Page, base_url: str) -> None:
        saved_pos = {"x": 50, "y": 50}
        page_as_superuser.evaluate(
            "pos => localStorage.setItem('lt_hint_pos', JSON.stringify(pos))",
            saved_pos,
        )
        page_as_superuser.goto(f"{base_url}/en/")
        page_as_superuser.wait_for_load_state("domcontentloaded")
        bar = page_as_superuser.locator(".lt-hint")
        expect(bar).to_be_visible()
        box = bar.bounding_box()
        assert box is not None
        assert abs(box["x"] - saved_pos["x"]) < 10
        assert abs(box["y"] - saved_pos["y"]) < 10

    def test_hint_bar_drag_does_not_trigger_button_click(self, page_as_superuser: Page) -> None:
        edit_btn = page_as_superuser.locator('.lt-hint__action[data-mode="edit"]')
        btn_box = edit_btn.bounding_box()
        assert btn_box is not None
        start_x = btn_box["x"] + btn_box["width"] / 2
        start_y = btn_box["y"] + btn_box["height"] / 2
        page_as_superuser.mouse.move(start_x, start_y)
        page_as_superuser.mouse.down()
        # Drag well past the threshold (3px)
        page_as_superuser.mouse.move(start_x + 100, start_y, steps=10)
        page_as_superuser.mouse.up()
        # Edit mode should NOT have been toggled
        expect(page_as_superuser.locator("body")).not_to_have_class(re.compile(r"lt-edit-mode"))

    def test_hint_bar_shift_click_tip_visible_only_in_preview(self, page_as_superuser: Page) -> None:
        tip = page_as_superuser.locator(".lt-hint__tip")
        # Not in preview mode — tip should not be visible
        expect(tip).not_to_have_class(re.compile(r"lt-hint__tip--visible"))
        # Enter preview mode
        preview_btn = page_as_superuser.locator('.lt-hint__action[data-mode="preview"]')
        preview_btn.click()
        page_as_superuser.wait_for_load_state("domcontentloaded")
        tip_after = page_as_superuser.locator(".lt-hint__tip")
        expect(tip_after).to_have_class(re.compile(r"lt-hint__tip--visible"))
