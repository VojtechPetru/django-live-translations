"""E2E tests for the permission system — widget visibility and API access control."""

from helpers import API_PREFIX
from playwright.sync_api import Page, expect


class TestPermissionSystem:
    def test_superuser_sees_hint_bar(self, page_as_superuser: Page) -> None:
        hint = page_as_superuser.locator(".lt-hint")
        expect(hint).to_be_visible()

    def test_superuser_sees_widget_js_injected(self, page_as_superuser: Page) -> None:
        config = page_as_superuser.evaluate("() => typeof window.__LT_CONFIG__")
        assert config != "undefined"

    def test_superuser_sees_lt_config_with_correct_languages(self, page_as_superuser: Page) -> None:
        config = page_as_superuser.evaluate("() => window.__LT_CONFIG__")
        assert isinstance(config, dict)
        assert sorted(config["languages"]) == ["cs", "en", "es"]
        assert config["csrfToken"]

    def test_superuser_page_has_translatable_spans(self, page_as_superuser: Page) -> None:
        spans = page_as_superuser.locator("lt-t[data-lt-msgid]")
        expect(spans.first).to_be_visible()
        assert spans.count() > 1

    def test_regular_user_no_hint_bar(self, page_as_regular_user: Page) -> None:
        hint = page_as_regular_user.locator(".lt-hint")
        expect(hint).to_have_count(0)

    def test_regular_user_no_widget_js(self, page_as_regular_user: Page) -> None:
        config = page_as_regular_user.evaluate("() => typeof window.__LT_CONFIG__")
        assert config == "undefined"

    def test_anonymous_user_no_hint_bar(self, page_anonymous: Page) -> None:
        hint = page_anonymous.locator(".lt-hint")
        expect(hint).to_have_count(0)

    def test_anonymous_user_no_translatable_spans(self, page_anonymous: Page) -> None:
        spans = page_anonymous.locator("lt-t")
        expect(spans).to_have_count(0)

    def test_api_get_translations_returns_403_for_anonymous(self, page_anonymous: Page, base_url: str) -> None:
        response = page_anonymous.request.get(
            f"{base_url}{API_PREFIX}/translations/",
            params={"msgid": "test", "context": ""},
        )
        assert response.status == 403

    def test_api_save_returns_403_for_regular_user(self, page_as_regular_user: Page, base_url: str) -> None:
        csrf = page_as_regular_user.evaluate("() => document.cookie.match(/csrftoken=([^;]+)/)?.[1] || ''")
        response = page_as_regular_user.request.post(
            f"{base_url}{API_PREFIX}/translations/save/",
            data={
                "msgid": "test",
                "context": "",
                "translations": {"en": {"0": "Test"}},
                "active_flags": {"en": True},
                "page_language": "en",
            },
            headers={"X-CSRFToken": csrf},
        )
        assert response.status == 403

    def test_api_delete_returns_403_for_anonymous(self, page_anonymous: Page, base_url: str) -> None:
        response = page_anonymous.request.post(
            f"{base_url}{API_PREFIX}/translations/delete/",
            data={"msgid": "test", "context": "", "page_language": "en"},
        )
        assert response.status == 403

    def test_api_history_returns_403_for_regular_user(self, page_as_regular_user: Page, base_url: str) -> None:
        response = page_as_regular_user.request.get(
            f"{base_url}{API_PREFIX}/translations/history/",
            params={"msgid": "test", "context": ""},
        )
        assert response.status == 403

    def test_api_bulk_activate_returns_403_for_anonymous(self, page_anonymous: Page, base_url: str) -> None:
        response = page_anonymous.request.post(
            f"{base_url}{API_PREFIX}/translations/bulk-activate/",
            data={"language": "en", "keys": []},
        )
        assert response.status == 403
