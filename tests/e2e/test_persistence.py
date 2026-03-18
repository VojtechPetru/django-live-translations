"""E2E tests for state persistence — edit mode, preview cookie, and hint bar position."""

import json
import re

from helpers import activate_edit_mode, disable_preview, enable_preview
from playwright.sync_api import Page, expect


class TestPersistence:
    def test_edit_mode_persists_after_internal_reload(self, page_as_superuser: Page, base_url: str) -> None:
        # Widget persists edit mode via sessionStorage when _reloadPage() is called
        # Simulate: set the key manually and reload, edit mode should auto-activate
        page_as_superuser.evaluate("() => sessionStorage.setItem('lt_edit_mode', '1')")
        page_as_superuser.goto(f"{base_url}/en/")
        page_as_superuser.wait_for_load_state("domcontentloaded")
        expect(page_as_superuser.locator("body")).to_have_class(re.compile(r"lt-edit-mode"), timeout=3000)

    def test_edit_mode_not_persisted_on_regular_toggle(self, page_as_superuser: Page) -> None:
        # Regular keyboard toggle does NOT set sessionStorage
        activate_edit_mode(page_as_superuser)
        stored = page_as_superuser.evaluate("() => sessionStorage.getItem('lt_edit_mode')")
        assert stored is None

    def test_preview_cookie_survives_reload(self, page_as_superuser: Page, base_url: str) -> None:
        enable_preview(page_as_superuser, base_url)
        cookies = page_as_superuser.context.cookies()
        assert any(c["name"] == "lt_preview" and c["value"] == "1" for c in cookies)
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("domcontentloaded")
        cookies_after = page_as_superuser.context.cookies()
        assert any(c["name"] == "lt_preview" and c["value"] == "1" for c in cookies_after)
        preview_flag = page_as_superuser.evaluate("() => window.__LT_CONFIG__?.preview")
        assert preview_flag is True
        disable_preview(page_as_superuser, base_url)

    def test_preview_cookie_clears_on_toggle_off(self, page_as_superuser: Page, base_url: str) -> None:
        enable_preview(page_as_superuser, base_url)
        assert any(c["name"] == "lt_preview" and c["value"] == "1" for c in page_as_superuser.context.cookies())
        # Toggle preview off via keyboard (triggers page reload)
        with page_as_superuser.expect_navigation():
            page_as_superuser.keyboard.press("Control+Shift+KeyP")
        page_as_superuser.wait_for_load_state("domcontentloaded")
        cookies_after = page_as_superuser.context.cookies()
        assert not any(c["name"] == "lt_preview" and c["value"] == "1" for c in cookies_after)

    def test_hint_bar_position_survives_reload(self, page_as_superuser: Page, base_url: str) -> None:
        bar = page_as_superuser.locator(".lt-hint")
        box = bar.bounding_box()
        assert box is not None
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        page_as_superuser.mouse.move(start_x, start_y)
        page_as_superuser.mouse.down()
        page_as_superuser.mouse.move(start_x + 150, start_y + 50, steps=10)
        page_as_superuser.mouse.up()
        stored = page_as_superuser.evaluate("() => localStorage.getItem('lt_hint_pos')")
        assert stored is not None
        pos = json.loads(stored)
        assert "x" in pos
        assert "y" in pos
        page_as_superuser.goto(f"{base_url}/en/")
        page_as_superuser.wait_for_load_state("domcontentloaded")
        bar_after = page_as_superuser.locator(".lt-hint")
        expect(bar_after).to_be_visible()
        box_after = bar_after.bounding_box()
        assert box_after is not None
        assert abs(box_after["x"] - pos["x"]) < 10
        assert abs(box_after["y"] - pos["y"]) < 10
