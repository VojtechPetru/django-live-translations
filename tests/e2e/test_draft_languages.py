"""E2E tests for draft language support — picker badge, switching, active toggle, save."""

from helpers import api_get_translations, api_save, open_modal, wait_for_fields_loaded
from playwright.sync_api import Page, expect


class TestDraftLanguages:
    """Draft language (es) is in LIVE_TRANSLATIONS['LANGUAGES'] but not in Django LANGUAGES."""

    def test_draft_badge_in_language_picker(self, page_as_superuser: Page) -> None:
        """Draft language shows a 'Draft' badge in the hint bar language picker."""
        trigger = page_as_superuser.locator(".lt-hint__lang-trigger")
        expect(trigger).to_be_visible()
        trigger.click()

        menu = page_as_superuser.locator(".lt-hint__lang-menu")
        expect(menu).to_have_class(r"lt-hint__lang-menu lt-hint__lang-menu--open")

        # The "es" item should have a draft badge
        es_badge = menu.locator(".lt-hint__lang-badge")
        expect(es_badge).to_be_visible()
        expect(es_badge).to_have_text("Draft")

    def test_switch_to_draft_language(self, page_as_superuser: Page, base_url: str) -> None:
        """Clicking a draft language sets the lt_lang cookie and reloads."""
        trigger = page_as_superuser.locator(".lt-hint__lang-trigger")
        trigger.click()

        menu = page_as_superuser.locator(".lt-hint__lang-menu")
        expect(menu).to_have_class(r"lt-hint__lang-menu lt-hint__lang-menu--open")

        # Click Spanish (the draft language)
        es_item = menu.locator(".lt-hint__lang-item", has_text="Spanish")
        es_item.click()
        page_as_superuser.wait_for_load_state("domcontentloaded")

        # Verify lt_lang cookie is set
        cookies = page_as_superuser.context.cookies()
        lt_lang_cookie = [c for c in cookies if c["name"] == "lt_lang"]
        assert len(lt_lang_cookie) == 1
        assert lt_lang_cookie[0]["value"] == "es"

        # Verify the picker shows ES as active
        trigger_after = page_as_superuser.locator(".lt-hint__lang-trigger")
        expect(trigger_after).to_contain_text("ES")

    def test_active_toggle_hidden_for_draft(self, page_as_superuser: Page, base_url: str) -> None:
        """The active/inactive toggle is hidden when editing a draft language tab."""
        # Switch to Spanish first
        page_as_superuser.context.add_cookies([{"name": "lt_lang", "value": "es", "url": base_url}])
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("domcontentloaded")

        # Open a translation modal
        open_modal(page_as_superuser, "demo.title")
        wait_for_fields_loaded(page_as_superuser)

        # Switch to the Spanish tab
        es_tab = page_as_superuser.locator(".lt-editor__tab", has_text="Spanish")
        es_tab.click()

        # The toggle should be hidden
        toggle = page_as_superuser.locator(".lt-field__toggle")
        expect(toggle).to_be_hidden()

    def test_switch_back_clears_draft_cookie(self, page_as_superuser: Page, base_url: str) -> None:
        """Switching from a draft language to a published one clears the lt_lang cookie."""
        # Start on draft language
        page_as_superuser.context.add_cookies([{"name": "lt_lang", "value": "es", "url": base_url}])
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("domcontentloaded")

        # Open the picker and click English
        trigger = page_as_superuser.locator(".lt-hint__lang-trigger")
        trigger.click()
        en_item = page_as_superuser.locator(".lt-hint__lang-menu .lt-hint__lang-item", has_text="English")
        en_item.click()
        page_as_superuser.wait_for_load_state("domcontentloaded")

        # lt_lang cookie should be cleared (absent or empty)
        cookies = page_as_superuser.context.cookies()
        lt_lang_cookie = [c for c in cookies if c["name"] == "lt_lang" and c["value"]]
        assert len(lt_lang_cookie) == 0

    def test_save_draft_translation(self, page_as_superuser: Page, base_url: str) -> None:
        """Saving a translation for a draft language stores it as active."""
        # Switch to Spanish
        page_as_superuser.context.add_cookies([{"name": "lt_lang", "value": "es", "url": base_url}])
        page_as_superuser.reload()
        page_as_superuser.wait_for_load_state("domcontentloaded")

        # Save via API with active_flags=False — should be forced to active by the server
        result = api_save(
            page_as_superuser,
            base_url,
            "demo.title",
            {"es": "Demo de Traducciones"},
            {"es": False},
            page_language="es",
        )
        assert result["ok"] is True

        # Verify the translation is active by fetching it
        data = api_get_translations(page_as_superuser, base_url, "demo.title")
        es_entry = data["translations"]["es"]
        assert es_entry["msgstr_forms"]["0"] == "Demo de Traducciones"
        assert es_entry["is_active"] is True
