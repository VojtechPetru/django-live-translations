"""E2E tests for dynamic content support -- marker resolution after htmx swaps."""

import re

from helpers import activate_edit_mode, wait_for_htmx_swap
from playwright.sync_api import Page, expect


class TestHtmxMarkerResolution:
    """Verify that translations in htmx-swapped content are interactive."""

    def test_htmx_swap_resolves_markers(self, page_as_superuser: Page) -> None:
        """After htmx outerHTML swap, new content has <lt-t> elements."""
        expect(page_as_superuser.locator("#plurals-card lt-t").first).to_be_visible()

        page_as_superuser.locator(".n-pill:not(.active)").first.click()
        wait_for_htmx_swap(page_as_superuser, "#plurals-card")

        lt_elements = page_as_superuser.locator("#plurals-card lt-t")
        expect(lt_elements.first).to_be_visible()

    def test_htmx_swapped_element_opens_modal(self, page_as_superuser: Page) -> None:
        """Clicking a translated element in htmx-swapped content opens the edit modal."""
        page_as_superuser.locator(".n-pill:not(.active)").first.click()
        wait_for_htmx_swap(page_as_superuser, "#plurals-card")

        activate_edit_mode(page_as_superuser)
        page_as_superuser.locator("#plurals-card lt-t").first.click()
        expect(page_as_superuser.locator("dialog.lt-dialog[open]")).to_be_visible(timeout=3000)

    def test_no_zwc_markers_after_swap(self, page_as_superuser: Page) -> None:
        """No ZWC start flags (FEFF, WJ) remain in swapped content after marker resolution."""
        page_as_superuser.locator(".n-pill:not(.active)").first.click()
        wait_for_htmx_swap(page_as_superuser, "#plurals-card")

        has_markers = page_as_superuser.evaluate(
            r"""() => {
            const text = document.getElementById('plurals-card').textContent || '';
            return /\uFEFF/.test(text) || /\u2060/.test(text);
        }"""
        )
        assert not has_markers, "ZWC markers or start flags found in swapped content"

    def test_no_template_elements_remain_after_swap(self, page_as_superuser: Page) -> None:
        """String table <template> elements are consumed and removed after swap."""
        page_as_superuser.locator(".n-pill:not(.active)").first.click()
        wait_for_htmx_swap(page_as_superuser, "#plurals-card")

        count = page_as_superuser.evaluate("() => document.querySelectorAll('template[data-lt-strings]').length")
        assert count == 0, "Unconsumed <template data-lt-strings> elements remain in DOM"

    def test_multiple_htmx_swaps(self, page_as_superuser: Page) -> None:
        """Multiple consecutive htmx swaps all resolve correctly."""
        pills = page_as_superuser.locator(".n-pill")
        count = pills.count()

        for i in range(min(count, 3)):
            pills.nth(i).click()
            wait_for_htmx_swap(page_as_superuser, "#plurals-card")
            expect(page_as_superuser.locator("#plurals-card lt-t").first).to_be_visible()

    def test_edit_mode_styling_applies_to_swapped_content(self, page_as_superuser: Page) -> None:
        """When edit mode is active, htmx-swapped <lt-t> elements get edit-mode styling."""
        activate_edit_mode(page_as_superuser)
        expect(page_as_superuser.locator("body")).to_have_class(re.compile(r"lt-edit-mode"))

        page_as_superuser.locator(".n-pill:not(.active)").first.click()
        wait_for_htmx_swap(page_as_superuser, "#plurals-card")

        # The new lt-t elements should be visible (CSS applies via .lt-edit-mode ancestor)
        expect(page_as_superuser.locator("#plurals-card lt-t").first).to_be_visible()

    def test_rescan_public_api_exists(self, page_as_superuser: Page) -> None:
        """window.__LT_RESCAN__ is exposed as a function."""
        result = page_as_superuser.evaluate("() => typeof window.__LT_RESCAN__")
        assert result == "function"
