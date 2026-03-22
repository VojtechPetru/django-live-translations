"""Tests for view error paths (live_translations.views).

Most error paths are triggered by real conditions (empty msgid → ValueError,
placeholder mismatch → PlaceholderValidationError).  Backend errors use
specialised error backends injected via Django settings.
"""

import json
import typing as t

import pytest

if t.TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

from live_translations import conf
from live_translations.views import (
    bulk_activate,
    delete_translation,
    get_translations,
    save_translations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAVE_PATH = "/__live-translations__/translations/save/"
_DELETE_PATH = "/__live-translations__/translations/delete/"
_GET_PATH = "/__live-translations__/translations/"
_BULK_PATH = "/__live-translations__/translations/bulk-activate/"

_BASE_SETTINGS = {
    "BACKEND": "tests.backends.TestBackend",
    "LANGUAGES": ["en"],
    "LOCALE_DIR": "/tmp",
    "PERMISSION_CHECK": "tests.permissions.allow_all",
}


# ---------------------------------------------------------------------------
# save_translations
# ---------------------------------------------------------------------------


class TestSaveTranslationsView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = _BASE_SETTINGS
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_invalid_json_400(self, make_request):
        request = make_request("post", _SAVE_PATH, raw_body=b"not json")
        response = save_translations(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"

    @pytest.mark.django_db
    def test_value_error_400(self, make_request):
        """Empty msgid triggers ValueError in services.save_translations."""
        request = make_request("post", _SAVE_PATH, data={"msgid": "", "translations": {"en": {"0": "Hi"}}})
        response = save_translations(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "msgid is required"

    @pytest.mark.django_db
    def test_placeholder_error_400(self, make_request):
        """Placeholder mismatch triggers PlaceholderValidationError naturally."""
        request = make_request("post", _SAVE_PATH, data={"msgid": "Hello %s", "translations": {"en": {"0": "Hi"}}})
        response = save_translations(request)
        assert response.status_code == 400
        body = json.loads(response.content)
        assert body["error"] == "Placeholder mismatch"
        assert "en" in body["details"]

    @pytest.mark.django_db
    def test_file_not_found_404(self, make_request, settings: "SettingsWrapper"):
        """FileNotFoundBackend raises FileNotFoundError → view returns 404."""
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "tests.backends.FileNotFoundBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": "/tmp",
            "PERMISSION_CHECK": "tests.permissions.allow_all",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        request = make_request("post", _SAVE_PATH, data={"msgid": "hello", "translations": {"en": {"0": "Hi"}}})
        response = save_translations(request)
        assert response.status_code == 404
        assert json.loads(response.content)["error"] == "PO file not found"

    def test_backend_error_500(self, make_request, settings: "SettingsWrapper"):
        """SaveErrorBackend raises RuntimeError → view returns 500."""
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "tests.backends.SaveErrorBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": "/tmp",
            "PERMISSION_CHECK": "tests.permissions.allow_all",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        request = make_request("post", _SAVE_PATH, data={"msgid": "hello", "translations": {"en": {"0": "Hi"}}})
        response = save_translations(request)
        assert response.status_code == 500
        assert json.loads(response.content)["error"] == "Backend error"


# ---------------------------------------------------------------------------
# get_translations
# ---------------------------------------------------------------------------


class TestGetTranslationsView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = _BASE_SETTINGS
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    @pytest.mark.django_db
    def test_value_error_400(self, make_request):
        """Empty msgid triggers ValueError in services.get_translations."""
        request = make_request("get", _GET_PATH, data={"msgid": ""})
        response = get_translations(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "msgid is required"

    def test_backend_error_500(self, make_request, settings: "SettingsWrapper"):
        """GetErrorBackend raises RuntimeError → view returns 500."""
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "tests.backends.GetErrorBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": "/tmp",
            "PERMISSION_CHECK": "tests.permissions.allow_all",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        request = make_request("get", _GET_PATH, data={"msgid": "hello"})
        response = get_translations(request)
        assert response.status_code == 500
        assert json.loads(response.content)["error"] == "Backend error"


# ---------------------------------------------------------------------------
# delete_translation
# ---------------------------------------------------------------------------


class TestDeleteTranslationView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = _BASE_SETTINGS
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_invalid_json_400(self, make_request):
        request = make_request("post", _DELETE_PATH, raw_body=b"not json")
        response = delete_translation(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"


# ---------------------------------------------------------------------------
# bulk_activate
# ---------------------------------------------------------------------------


class TestBulkActivateView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = _BASE_SETTINGS
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_invalid_json_400(self, make_request):
        request = make_request("post", _BULK_PATH, raw_body=b"not json")
        response = bulk_activate(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"

    def test_invalid_msgid_item_400(self, make_request):
        request = make_request("post", _BULK_PATH, data={"language": "en", "msgids": [{"no_msgid": "x"}]})
        response = bulk_activate(request)
        assert response.status_code == 400
        assert "msgid" in json.loads(response.content)["error"]

    def test_non_dict_item_400(self, make_request):
        request = make_request("post", _BULK_PATH, data={"language": "en", "msgids": ["just-a-string"]})
        response = bulk_activate(request)
        assert response.status_code == 400
        assert "msgid" in json.loads(response.content)["error"]


# ---------------------------------------------------------------------------
# Per-language permission granularity
# ---------------------------------------------------------------------------

_LANG_PERM_SETTINGS = {
    "BACKEND": "tests.backends.TestBackend",
    "LANGUAGES": ["en", "cs", "de"],
    "LOCALE_DIR": "/tmp",
    "PERMISSION_CHECK": "tests.permissions.allow_en_cs",
}


class TestPerLanguagePermission:
    """Per-language permission checks on write views."""

    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = _LANG_PERM_SETTINGS
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    @pytest.mark.django_db
    def test_save_permitted_language_succeeds(self, make_request):
        request = make_request("post", _SAVE_PATH, data={"msgid": "hello", "translations": {"en": {"0": "Hi"}}})
        response = save_translations(request)
        assert response.status_code == 200

    def test_save_forbidden_language_403(self, make_request):
        request = make_request("post", _SAVE_PATH, data={"msgid": "hello", "translations": {"de": {"0": "Hallo"}}})
        response = save_translations(request)
        assert response.status_code == 403
        body = json.loads(response.content)
        assert "de" in body["error"]

    def test_save_mixed_permitted_forbidden_403(self, make_request):
        request = make_request(
            "post", _SAVE_PATH, data={"msgid": "hello", "translations": {"en": {"0": "Hi"}, "de": {"0": "Hallo"}}}
        )
        response = save_translations(request)
        assert response.status_code == 403

    def test_delete_forbidden_language_403(self, make_request):
        request = make_request("post", _DELETE_PATH, data={"msgid": "hello", "context": "", "language": "de"})
        response = delete_translation(request)
        assert response.status_code == 403

    def test_delete_all_with_partial_permission_403(self, make_request):
        """Delete-all (no languages specified) requires permission for all configured languages."""
        request = make_request("post", _DELETE_PATH, data={"msgid": "hello", "context": ""})
        response = delete_translation(request)
        assert response.status_code == 403

    def test_bulk_activate_forbidden_language_403(self, make_request):
        request = make_request("post", _BULK_PATH, data={"language": "de", "msgids": [{"msgid": "hello"}]})
        response = bulk_activate(request)
        assert response.status_code == 403

    def test_get_translations_with_partial_permission_succeeds(self, make_request):
        """Read views should work even with partial language permission."""
        request = make_request("get", _GET_PATH, data={"msgid": "hello"})
        response = get_translations(request)
        # Should not be 403 (read access is unrestricted)
        assert response.status_code != 403

    @pytest.mark.django_db
    def test_get_history_with_partial_permission_succeeds(self, make_request):
        request = make_request("get", "/__live-translations__/translations/history/", data={"msgid": "hello"})
        from live_translations.views import get_history

        response = get_history(request)
        assert response.status_code != 403
