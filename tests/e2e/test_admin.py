"""E2E tests for Django admin interface — DB backend only."""

import pytest
from helpers import API_PREFIX, SUPERUSER, api_delete, api_save, login
from playwright.sync_api import Page, expect


class TestAdminInterface:
    @pytest.fixture(autouse=True)
    def _setup(self, page: Page, db_base_url: str) -> None:
        login(page, db_base_url, *SUPERUSER)
        page.goto(f"{db_base_url}/en/")
        page.wait_for_load_state("networkidle")
        self._page = page
        self._base_url = db_base_url

    @pytest.fixture(autouse=True)
    def _cleanup_entries(self, page: Page, db_base_url: str) -> None:
        yield
        # Clean up any test entries via admin bulk delete
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        checkbox_all = page.locator("#action-toggle")
        if checkbox_all.is_visible():
            rows = page.locator("#result_list tbody tr")
            if rows.count() > 0:
                checkbox_all.check()
                page.select_option('select[name="action"]', "delete_selected")
                page.locator('button[name="index"]').click()
                page.wait_for_load_state("networkidle")
                confirm = page.locator('input[type="submit"]')
                if confirm.is_visible():
                    confirm.click()
                    page.wait_for_load_state("networkidle")

    def test_admin_list_view_loads(self, page: Page, db_base_url: str) -> None:
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#content h1")).to_contain_text("Translation override")
        expect(page.locator("#changelist")).to_be_visible()

    def test_admin_create_entry(self, page: Page, db_base_url: str) -> None:
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/add/")
        page.wait_for_load_state("networkidle")
        page.fill("#id_language", "en")
        page.fill("#id_msgid", "admin.test.create")
        page.fill("#id_msgstr", "Admin Created Entry")
        page.locator("#id_is_active").check()
        page.locator('input[name="_save"]').click()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".messagelist")).to_be_visible()
        # Verify entry appears in list
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#result_list")).to_contain_text("admin.test.create")

    def test_admin_edit_entry(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.edit", {"en": "Original"}, {"en": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.locator("#result_list a").filter(has_text="admin.test.edit").first.click()
        page.wait_for_load_state("networkidle")
        page.fill("#id_msgstr", "Updated Via Admin")
        page.locator('input[name="_save"]').click()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".messagelist")).to_be_visible()
        # Verify the update
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#result_list")).to_contain_text("Updated Via Admin")

    def test_admin_shows_po_default(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "demo.title", {"en": "Custom Override"}, {"en": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.locator("#result_list a").filter(has_text="demo.title").first.click()
        page.wait_for_load_state("networkidle")
        # The admin change form should show the PO default somewhere
        po_default = page.locator(".po-default-display, .readonly, .help")
        body_text = page.locator("#content").text_content() or ""
        assert "Live Translations Demo" in body_text or po_default.count() > 0
        api_delete(page, db_base_url, "demo.title", ["en"])

    def test_admin_delete_single_entry(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.delete", {"en": "To Delete"}, {"en": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.locator("#result_list a").filter(has_text="admin.test.delete").first.click()
        page.wait_for_load_state("networkidle")
        page.locator(".deletelink, .deletelink-box a").first.click()
        page.wait_for_load_state("networkidle")
        page.locator('input[type="submit"]').click()
        page.wait_for_load_state("networkidle")
        # Verify entry is gone
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        body_text = page.locator("#content").text_content() or ""
        assert "admin.test.delete" not in body_text

    def test_admin_bulk_delete(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.bulk1", {"en": "Bulk 1"}, {"en": True})
        api_save(page, db_base_url, "admin.test.bulk2", {"en": "Bulk 2"}, {"en": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.locator("#action-toggle").check()
        page.select_option('select[name="action"]', "delete_selected")
        page.locator('button[name="index"]').click()
        page.wait_for_load_state("networkidle")
        page.locator('input[type="submit"]').click()
        page.wait_for_load_state("networkidle")
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        rows = page.locator("#result_list tbody tr")
        assert rows.count() == 0

    def test_admin_activate_action(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.act1", {"en": "Activate 1"}, {"en": False})
        api_save(page, db_base_url, "admin.test.act2", {"en": "Activate 2"}, {"en": False})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.locator("#action-toggle").check()
        page.select_option('select[name="action"]', "activate_translations")
        page.locator('button[name="index"]').click()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".messagelist")).to_be_visible()
        # Verify entries are now active — check the active column icons
        active_icons = page.locator("#result_list .field-is_active img[alt='True']")
        assert active_icons.count() >= 2

    def test_admin_deactivate_action(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.deact1", {"en": "Deactivate 1"}, {"en": True})
        api_save(page, db_base_url, "admin.test.deact2", {"en": "Deactivate 2"}, {"en": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.locator("#action-toggle").check()
        page.select_option('select[name="action"]', "deactivate_translations")
        page.locator('button[name="index"]').click()
        page.wait_for_load_state("networkidle")
        expect(page.locator(".messagelist")).to_be_visible()
        # Verify entries are now inactive
        inactive_icons = page.locator("#result_list .field-is_active img[alt='False']")
        assert inactive_icons.count() >= 2

    def test_admin_list_filters(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.filter", {"en": "English Entry"}, {"en": True})
        api_save(page, db_base_url, "admin.test.filter", {"cs": "Czech Entry"}, {"cs": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        rows_before = page.locator("#result_list tbody tr").count()
        assert rows_before >= 2
        # Click language filter for "en"
        page.locator("#changelist-filter a").filter(has_text="en").first.click()
        page.wait_for_load_state("networkidle")
        rows_after = page.locator("#result_list tbody tr").count()
        assert rows_after < rows_before
        # All visible entries should be EN
        languages = page.locator("#result_list .field-language").all_text_contents()
        for lang in languages:
            assert "en" in lang.lower()

    def test_admin_search(self, page: Page, db_base_url: str) -> None:
        api_save(page, db_base_url, "admin.test.searchable", {"en": "Searchable"}, {"en": True})
        api_save(page, db_base_url, "admin.test.other", {"en": "Other Entry"}, {"en": True})
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/")
        page.wait_for_load_state("networkidle")
        page.fill("#searchbar", "searchable")
        page.locator('#changelist-search input[type="submit"]').click()
        page.wait_for_load_state("networkidle")
        rows = page.locator("#result_list tbody tr")
        assert rows.count() >= 1
        body_text = page.locator("#result_list").text_content() or ""
        assert "admin.test.searchable" in body_text
        assert "admin.test.other" not in body_text

    def test_admin_save_records_history(self, page: Page, db_base_url: str) -> None:
        # Create entry via admin form
        page.goto(f"{db_base_url}/en/admin/live_translations/translationentry/add/")
        page.wait_for_load_state("networkidle")
        page.fill("#id_language", "en")
        page.fill("#id_msgid", "admin.test.history")
        page.fill("#id_msgstr", "History Test Entry")
        page.locator("#id_is_active").check()
        page.locator('input[name="_save"]').click()
        page.wait_for_load_state("networkidle")
        # Check history via API
        response = page.request.get(
            f"{db_base_url}{API_PREFIX}/translations/history/?msgid=admin.test.history&context=&limit=50"
        )
        data = response.json()
        history = data.get("history", [])
        assert len(history) >= 1
        actions = [e.get("action") for e in history]
        assert "create" in actions
