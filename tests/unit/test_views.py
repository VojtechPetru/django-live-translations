"""Tests for view error paths (live_translations.views)."""

import json
import unittest.mock

from live_translations import services
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


def _allow_permission():
    return unittest.mock.patch(
        "live_translations.conf.get_permission_checker",
        return_value=lambda request: True,
    )


# ---------------------------------------------------------------------------
# save_translations
# ---------------------------------------------------------------------------


class TestSaveTranslationsView:
    def test_invalid_json_400(self, make_request):
        request = make_request("post", _SAVE_PATH, raw_body=b"not json")
        with _allow_permission():
            response = save_translations(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"

    def test_value_error_400(self, make_request):
        request = make_request("post", _SAVE_PATH, data={"msgid": "", "translations": {}})
        with (
            _allow_permission(),
            unittest.mock.patch(
                "live_translations.services.save_translations",
                side_effect=ValueError("msgid is required"),
            ),
        ):
            response = save_translations(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "msgid is required"

    def test_placeholder_error_400(self, make_request):
        details = {"en": ["missing %s"]}
        request = make_request("post", _SAVE_PATH, data={"msgid": "Hello %s", "translations": {"en": "Hi"}})
        with (
            _allow_permission(),
            unittest.mock.patch(
                "live_translations.services.save_translations",
                side_effect=services.PlaceholderValidationError(details),
            ),
        ):
            response = save_translations(request)
        assert response.status_code == 400
        body = json.loads(response.content)
        assert body["error"] == "Placeholder mismatch"
        assert body["details"] == details

    def test_file_not_found_404(self, make_request):
        request = make_request("post", _SAVE_PATH, data={"msgid": "hello", "translations": {"en": "Hi"}})
        with (
            _allow_permission(),
            unittest.mock.patch(
                "live_translations.services.save_translations",
                side_effect=FileNotFoundError("PO file not found"),
            ),
        ):
            response = save_translations(request)
        assert response.status_code == 404
        assert json.loads(response.content)["error"] == "PO file not found"

    def test_backend_error_500(self, make_request):
        request = make_request("post", _SAVE_PATH, data={"msgid": "hello", "translations": {"en": "Hi"}})
        with (
            _allow_permission(),
            unittest.mock.patch(
                "live_translations.services.save_translations",
                side_effect=RuntimeError("unexpected"),
            ),
        ):
            response = save_translations(request)
        assert response.status_code == 500
        assert json.loads(response.content)["error"] == "Backend error"


# ---------------------------------------------------------------------------
# get_translations
# ---------------------------------------------------------------------------


class TestGetTranslationsView:
    def test_value_error_400(self, make_request):
        request = make_request("get", _GET_PATH, data={"msgid": ""})
        with (
            _allow_permission(),
            unittest.mock.patch(
                "live_translations.services.get_translations",
                side_effect=ValueError("msgid is required"),
            ),
        ):
            response = get_translations(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "msgid is required"

    def test_backend_error_500(self, make_request):
        request = make_request("get", _GET_PATH, data={"msgid": "hello"})
        with (
            _allow_permission(),
            unittest.mock.patch(
                "live_translations.services.get_translations",
                side_effect=RuntimeError("boom"),
            ),
        ):
            response = get_translations(request)
        assert response.status_code == 500
        assert json.loads(response.content)["error"] == "Backend error"


# ---------------------------------------------------------------------------
# delete_translation
# ---------------------------------------------------------------------------


class TestDeleteTranslationView:
    def test_invalid_json_400(self, make_request):
        request = make_request("post", _DELETE_PATH, raw_body=b"not json")
        with _allow_permission():
            response = delete_translation(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"


# ---------------------------------------------------------------------------
# bulk_activate
# ---------------------------------------------------------------------------


class TestBulkActivateView:
    def test_invalid_json_400(self, make_request):
        request = make_request("post", _BULK_PATH, raw_body=b"not json")
        with _allow_permission():
            response = bulk_activate(request)
        assert response.status_code == 400
        assert json.loads(response.content)["error"] == "Invalid JSON"

    def test_invalid_msgid_item_400(self, make_request):
        request = make_request("post", _BULK_PATH, data={"language": "en", "msgids": [{"no_msgid": "x"}]})
        with _allow_permission():
            response = bulk_activate(request)
        assert response.status_code == 400
        assert "msgid" in json.loads(response.content)["error"]

    def test_non_dict_item_400(self, make_request):
        request = make_request("post", _BULK_PATH, data={"language": "en", "msgids": ["just-a-string"]})
        with _allow_permission():
            response = bulk_activate(request)
        assert response.status_code == 400
        assert "msgid" in json.loads(response.content)["error"]
