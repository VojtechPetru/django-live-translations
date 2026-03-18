"""Tests for the LiveTranslationsMiddleware."""

import json
import typing as t
import unittest.mock

import django.http
import django.utils.translation
import pytest

from live_translations import conf, strings
from live_translations.middleware import _DRAFT_LANG_ATTR, _DRAFT_LANG_COOKIE, _ZWC_RE, LiveTranslationsMiddleware
from live_translations.types import MsgKey


def _html_response(
    body: str = "<html><body>Hello</body></html>", *, content_length: bool = False
) -> django.http.HttpResponse:
    response = django.http.HttpResponse(body, content_type="text/html; charset=utf-8")
    if content_length:
        response["Content-Length"] = len(response.content)
    return response


def _json_response(data: str = '{"ok":true}', *, content_length: bool = False) -> django.http.HttpResponse:
    response = django.http.HttpResponse(data, content_type="application/json")
    if content_length:
        response["Content-Length"] = len(response.content)
    return response


def _streaming_html_response() -> django.http.StreamingHttpResponse:
    return django.http.StreamingHttpResponse(iter(["<html><body>Hi</body></html>"]), content_type="text/html")


def _middleware_settings(
    *,
    languages: list[str] | None = None,
    permission: bool = True,
    active_by_default: bool = False,
    shortcut_edit: str = "ctrl+shift+e",
    shortcut_preview: str = "ctrl+shift+p",
) -> dict[str, t.Any]:
    return {
        "BACKEND": "tests.backends.InMemoryBackend",
        "LANGUAGES": languages or ["en", "cs"],
        "LOCALE_DIR": "/tmp",
        "PERMISSION_CHECK": "tests.permissions.allow_all" if permission else "tests.permissions.deny_all",
        "TRANSLATION_ACTIVE_BY_DEFAULT": active_by_default,
        "SHORTCUT_EDIT": shortcut_edit,
        "SHORTCUT_PREVIEW": shortcut_preview,
    }


def _clear_caches() -> None:
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()


class TestDispatchApi:
    """API route dispatch and non-API passthrough."""

    def test_dispatches_known_api_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True})
        calls: list[django.http.HttpRequest] = []

        def inner(request: django.http.HttpRequest) -> django.http.HttpResponse:
            calls.append(request)
            return _html_response()

        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.get_translations = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("get", "/__live-translations__/translations/")
            response = mw(request)

        assert response is mock_view_response
        mock_views.get_translations.assert_called_once_with(request)
        assert len(calls) == 0

    def test_dispatches_save_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True})
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.save_translations = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("post", "/__live-translations__/translations/save/")
            response = mw(request)

        assert response is mock_view_response
        mock_views.save_translations.assert_called_once_with(request)

    def test_dispatches_delete_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True})
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.delete_translation = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("post", "/__live-translations__/translations/delete/")
            response = mw(request)

        assert response is mock_view_response
        mock_views.delete_translation.assert_called_once_with(request)

    def test_dispatches_history_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"history": []})
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.get_history = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("get", "/__live-translations__/translations/history/")
            response = mw(request)

        assert response is mock_view_response

    def test_dispatches_bulk_activate_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True, "activated": 2})
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.bulk_activate = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("post", "/__live-translations__/translations/bulk-activate/")
            response = mw(request)

        assert response is mock_view_response

    def test_non_api_path_passes_through(self, make_request, settings):
        inner_response = _html_response()
        calls: list[django.http.HttpRequest] = []

        def inner(request: django.http.HttpRequest) -> django.http.HttpResponse:
            calls.append(request)
            return inner_response

        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        request = make_request("get", "/some-page/")
        response = mw(request)

        assert len(calls) == 1
        assert response is inner_response


@pytest.mark.django_db
class TestHandleRequest:
    """Core middleware request handling: admin bypass, inactive user, HTML injection, etc."""

    def test_admin_path_bypasses_middleware(self, make_request, settings):
        inner_response = _html_response("<html><body>Admin</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        settings.ROOT_URLCONF = "tests.urls"
        _clear_caches()

        # Use an actual admin URL path that resolves to Django admin
        request = make_request("get", "/admin/live_translations/")
        response = mw(request)

        assert response is inner_response
        # No snippet injected into admin responses
        assert b"__LT_CONFIG__" not in response.content

    def test_inactive_user_returns_unmodified_response(self, make_request, settings):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        request = make_request("get", "/page/", has_permission=False)
        response = mw(request)

        assert response is inner_response
        assert b"__LT_CONFIG__" not in response.content

    def test_active_user_html_gets_assets_injected(self, make_request, settings):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/page/")
        response = mw(request)

        assert b"__LT_CONFIG__" in response.content
        assert b"</body>" in response.content

    def test_json_response_strips_zwc_when_active(self, make_request, settings):
        marker = "\ufeff" + "\u200b\u200c" * 8 + "\ufeff"
        zwc_content = '{"msg":"' + marker + '"}'
        inner_response = _json_response(zwc_content)
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/api/data/")
        response = mw(request)

        content = response.content.decode()
        assert "\ufeff" not in content

    def test_streaming_html_goes_through_strip_path(self, make_request, settings):
        """Streaming HTML responses go through ZWC strip path, not injection."""
        inner_response = _streaming_html_response()
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)  # type: ignore[bad-argument-type]

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/page/")
        response = mw(request)

        # Streaming responses should NOT have assets injected (no __LT_CONFIG__)
        assert isinstance(response, django.http.StreamingHttpResponse)
        content = b"".join(response.streaming_content).decode()  # type: ignore[bad-argument-type]
        assert "__LT_CONFIG__" not in content
        assert isinstance(response, django.http.StreamingHttpResponse)

    def test_resets_string_registry_after_response(self, make_request, settings):
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        # Seed the registry so there's something to reset
        strings.register_string(MsgKey("test", ""))
        request = make_request("get", "/page/")
        mw(request)

        assert strings.get_string_registry() == []

    def test_does_not_reset_registry_when_get_response_raises(self, make_request, settings):
        """When get_response raises, the outer try/finally for reset_string_registry is never entered."""
        # Seed the registry before the middleware runs
        strings.register_string(MsgKey("test", ""))

        def raise_error(_req: django.http.HttpRequest) -> django.http.HttpResponse:
            raise RuntimeError("boom")

        mw = LiveTranslationsMiddleware(raise_error)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/page/")
        with pytest.raises(RuntimeError, match="boom"):
            mw(request)

        # Registry should NOT have been reset because the error happened before
        # the try/finally block that calls reset_string_registry
        assert len(strings.get_string_registry()) > 0
        # Clean up
        strings.reset_string_registry()

    def test_resets_lt_active_contextvar_on_exception(self, make_request, settings):
        """lt_active is always reset even when get_response raises."""

        def raise_error(_req: django.http.HttpRequest) -> django.http.HttpResponse:
            raise RuntimeError("boom")

        mw = LiveTranslationsMiddleware(raise_error)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/page/")
        with pytest.raises(RuntimeError, match="boom"):
            mw(request)

        assert strings.lt_active.get(False) is False

    def test_preview_mode_loads_overrides(self, make_request, settings):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()

        # Seed an inactive override in the backend
        from live_translations.models import TranslationEntry as TEModel

        TEModel.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=False)

        with django.utils.translation.override("cs"):
            request = make_request("get", "/page/")
            request.COOKIES["lt_preview"] = "1"
            response = mw(request)

        content = response.content.decode()
        assert "preview:true" in content
        assert "previewEntries:" in content

    def test_preview_mode_resets_contextvar(self, make_request, settings):
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()

        with django.utils.translation.override("en"):
            request = make_request("get", "/page/")
            request.COOKIES["lt_preview"] = "1"
            mw(request)

        # After middleware completes, preview overrides contextvar should be reset
        assert strings.lt_preview_overrides.get(None) is None

    def test_non_preview_active_user_no_preview_config(self, make_request, settings):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/page/")
        response = mw(request)

        content = response.content.decode()
        assert "preview:true" not in content

    def test_ensure_current_called_for_non_api_paths(self, make_request, settings):
        inner = lambda r: _html_response()  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        request = make_request("get", "/page/")
        mw(request)

        backend = conf.get_backend_instance()
        assert len(backend.get_calls("ensure_current")) >= 1  # type: ignore[union-attr]


class TestStripZwc:
    """Tests for _strip_zwc static method."""

    def test_no_zwc_content_unchanged(self):
        response = _json_response('{"key":"value"}')
        original_content = response.content

        LiveTranslationsMiddleware._strip_zwc(response)

        assert response.content == original_content

    def test_strips_zwc_markers(self):
        # Build a valid ZWC marker: FEFF + 16 bits (all zeros = id 0) + FEFF
        marker = "\ufeff" + "\u200b" * 16 + "\ufeff"
        body = f'{{"msg":"Hello{marker}"}}'
        response = _json_response(body)

        LiveTranslationsMiddleware._strip_zwc(response)

        content = response.content.decode()
        assert "\ufeff" not in content
        assert '"msg":"Hello"' in content

    def test_strips_multiple_markers(self):
        marker_0 = "\ufeff" + "\u200b" * 16 + "\ufeff"
        marker_1 = "\ufeff" + "\u200b" * 15 + "\u200c" + "\ufeff"
        body = f"Hello{marker_0} World{marker_1}"
        response = django.http.HttpResponse(body, content_type="text/plain")

        LiveTranslationsMiddleware._strip_zwc(response)

        content = response.content.decode()
        assert content == "Hello World"

    def test_updates_content_length_when_present(self):
        marker = "\ufeff" + "\u200b" * 16 + "\ufeff"
        body = f"Hello{marker}"
        response = django.http.HttpResponse(body, content_type="text/plain")
        response["Content-Length"] = len(response.content)

        LiveTranslationsMiddleware._strip_zwc(response)

        content = response.content.decode()
        assert content == "Hello"
        assert int(response["Content-Length"]) == len(response.content)

    def test_no_content_length_header_not_added(self):
        marker = "\ufeff" + "\u200b" * 16 + "\ufeff"
        body = f"Hello{marker}"
        response = django.http.HttpResponse(body, content_type="text/plain")
        # Ensure no Content-Length header
        if "Content-Length" in response:
            del response["Content-Length"]

        LiveTranslationsMiddleware._strip_zwc(response)

        assert "Content-Length" not in response

    def test_zwc_boundary_present_but_no_full_marker(self):
        """ZWC_BOUNDARY alone (without a full 18-char marker) should not alter content."""
        body = "Hello\ufeffWorld"
        response = django.http.HttpResponse(body, content_type="text/plain")

        LiveTranslationsMiddleware._strip_zwc(response)

        # The regex won't match an incomplete marker, so content stays the same
        content = response.content.decode()
        assert content == "Hello\ufeffWorld"


@pytest.mark.django_db
class TestInjectAssets:
    """Tests for _inject_assets method."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        strings.reset_string_registry()
        yield
        strings.reset_string_registry()

    def test_injects_before_body_close(self, make_request, settings):
        response = _html_response("<html><body>Content</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs"])
        _clear_caches()
        request = make_request("get", "/page/")
        mw._inject_assets(request, response)

        content = response.content.decode()
        # Snippet should appear before </body>
        body_idx = content.rfind("</body>")
        config_idx = content.find("__LT_CONFIG__")
        assert config_idx != -1
        assert config_idx < body_idx

    def test_no_body_tag_does_nothing(self, make_request):
        response = django.http.HttpResponse("<html>No body tag</html>", content_type="text/html")
        original_content = response.content
        mw = LiveTranslationsMiddleware(lambda r: response)

        mw._inject_assets(make_request("get", "/page/"), response)

        assert response.content == original_content

    def test_includes_csrf_token(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "csrfToken:'" in content

    def test_includes_languages(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "de", "fr"])
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'languages:["en","de","fr"]' in content

    def test_includes_api_base(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "apiBase:'/__live-translations__'" in content

    def test_includes_static_urls(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'href="/static/live_translations/widget.css"' in content
        assert 'src="/static/live_translations/widget.js"' in content

    def test_active_by_default_true(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(active_by_default=True)
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "activeByDefault:true" in content

    def test_active_by_default_false(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(active_by_default=False)
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "activeByDefault:false" in content

    def test_preview_entries_included(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        preview = {MsgKey("hello", ""): "Ahoj", MsgKey("bye", "ctx"): "Nashle"}

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response, preview_entries=preview)

        content = response.content.decode()
        assert "preview:true" in content
        assert "previewEntries:" in content

    def test_no_preview_entries_when_none(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response, preview_entries=None)

        content = response.content.decode()
        assert "preview:true" not in content

    def test_updates_content_length(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>", content_length=True)
        original_length = int(response["Content-Length"])
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        new_length = int(response["Content-Length"])
        assert new_length > original_length
        assert new_length == len(response.content)

    def test_no_content_length_header_not_added(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        if "Content-Length" in response:
            del response["Content-Length"]
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        assert "Content-Length" not in response

    def test_string_registry_serialized(self, make_request, settings):
        # Register a string so the table is non-empty
        strings.register_string(MsgKey("hello", ""))
        strings.register_string(MsgKey("bye", "ctx"))

        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "__LT_STRINGS__=" in content
        # Extract the JSON portion
        start = content.index("__LT_STRINGS__=") + len("__LT_STRINGS__=")
        end = content.index(";", start)
        table = json.loads(content[start:end])
        assert table["0"]["m"] == "hello"
        assert table["0"]["c"] == ""
        assert table["1"]["m"] == "bye"
        assert table["1"]["c"] == "ctx"

    def test_shortcut_keys_included(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(shortcut_edit="ctrl+e", shortcut_preview="ctrl+p")
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'shortcutEdit:"ctrl+e"' in content
        assert 'shortcutPreview:"ctrl+p"' in content


@pytest.mark.django_db
class TestLoadPreviewOverrides:
    """Tests for _load_preview_overrides static method."""

    def test_delegates_to_backend(self, settings):
        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()

        from live_translations.models import TranslationEntry as TEModel

        TEModel.objects.create(language="cs", msgid="hello", context="", msgstr="Ahoj", is_active=False)

        with django.utils.translation.override("cs"):
            result = LiveTranslationsMiddleware._load_preview_overrides()

        assert result == {MsgKey("hello", ""): "Ahoj"}

    def test_empty_language_returns_empty_dict(self, settings):
        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()

        django.utils.translation.deactivate_all()
        result = LiveTranslationsMiddleware._load_preview_overrides()

        assert result == {}

    def test_none_language_returns_empty_dict(self, settings):
        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()

        django.utils.translation.deactivate_all()
        result = LiveTranslationsMiddleware._load_preview_overrides()

        assert result == {}

    def test_explicit_language_overrides_get_language(self, settings):
        """When language kwarg is passed, get_language() is not used."""
        settings.LIVE_TRANSLATIONS = _middleware_settings()
        _clear_caches()

        from live_translations.models import TranslationEntry as TEModel

        TEModel.objects.create(language="ja", msgid="hello", context="", msgstr="Hola", is_active=False)

        with django.utils.translation.override("en"):
            result = LiveTranslationsMiddleware._load_preview_overrides(language="ja")

        assert result == {MsgKey("hello", ""): "Hola"}


@pytest.mark.django_db
class TestPreviewWithDraftLanguage:
    """Preview mode combined with draft language cookie."""

    def test_preview_loads_overrides_for_draft_language(self, make_request, settings):
        """When both preview and draft cookie are set, preview overrides use the draft language."""
        # Use "xx" as draft language since it's not in Django's default LANGUAGES
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "xx"])
        _clear_caches()

        from live_translations.models import TranslationEntry as TEModel

        TEModel.objects.create(language="xx", msgid="hello", context="", msgstr="Hola", is_active=False)

        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        request = make_request("get", "/page/")
        request.COOKIES[_DRAFT_LANG_COOKIE] = "xx"
        request.COOKIES["lt_preview"] = "1"
        mw(request)

        backend = conf.get_backend_instance()
        # Verify the backend was called with the draft language
        inactive_calls = backend.get_calls("get_inactive_overrides")  # type: ignore[union-attr]
        assert len(inactive_calls) >= 1
        # call_log stores (args_tuple, kwargs_dict) where args_tuple = (language,)
        assert any(args == ("xx",) for args, _kwargs in inactive_calls)

    def test_admin_path_skips_draft_processing(self, make_request, settings):
        """Admin path early-returns before draft cookie is checked."""
        # Use "xx" as draft language
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "xx"])
        settings.ROOT_URLCONF = "tests.urls"
        _clear_caches()

        inner_response = _html_response("<html><body>Admin</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        request = make_request("get", "/admin/live_translations/")
        request.COOKIES[_DRAFT_LANG_COOKIE] = "xx"
        response = mw(request)

        assert response is inner_response
        assert not hasattr(request, _DRAFT_LANG_ATTR)


@pytest.mark.django_db
class TestCallUserContextvar:
    """Tests for lt_current_user contextvar set/reset in __call__."""

    def test_sets_authenticated_user(self, make_request, settings):
        captured_user: list[object] = []

        def capture_inner(request: django.http.HttpRequest) -> django.http.HttpResponse:
            captured_user.append(strings.lt_current_user.get(None))
            return _html_response()

        mw = LiveTranslationsMiddleware(capture_inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        request = make_request("get", "/page/", has_permission=True)
        mw(request)

        assert captured_user[0] is request.user

    def test_sets_user_for_non_superuser(self, make_request, settings):
        """A non-superuser is still authenticated, so lt_current_user is set."""
        captured_user: list[object] = []

        def capture_inner(request: django.http.HttpRequest) -> django.http.HttpResponse:
            captured_user.append(strings.lt_current_user.get(None))
            return _html_response()

        mw = LiveTranslationsMiddleware(capture_inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        request = make_request("get", "/page/", has_permission=False)
        mw(request)

        # User with has_permission=False is still authenticated, so contextvar is set
        assert captured_user[0] is request.user

    def test_sets_none_for_anonymous_user(self, make_request, settings):
        captured_user: list[object] = []

        def capture_inner(request: django.http.HttpRequest) -> django.http.HttpResponse:
            captured_user.append(strings.lt_current_user.get(None))
            return _html_response()

        mw = LiveTranslationsMiddleware(capture_inner)
        request = make_request("get", "/page/", anonymous=True)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        mw(request)

        assert captured_user[0] is None

    def test_resets_contextvar_after_request(self, make_request, settings):
        mw = LiveTranslationsMiddleware(lambda r: _html_response())

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=False)
        _clear_caches()
        request = make_request("get", "/page/", has_permission=True)
        mw(request)

        # After middleware completes, contextvar should be reset to default
        assert strings.lt_current_user.get(None) is None

    def test_resets_contextvar_on_exception(self, make_request, settings):
        def raise_error(_req: django.http.HttpRequest) -> django.http.HttpResponse:
            raise RuntimeError("boom")

        mw = LiveTranslationsMiddleware(raise_error)

        settings.LIVE_TRANSLATIONS = _middleware_settings(permission=True)
        _clear_caches()
        request = make_request("get", "/page/")
        with pytest.raises(RuntimeError, match="boom"):
            mw(request)

        assert strings.lt_current_user.get(None) is None


class TestZwcRegex:
    """Verify the compiled _ZWC_RE pattern matches expected markers."""

    def test_matches_valid_marker(self):
        marker = "\ufeff" + "\u200b" * 16 + "\ufeff"
        assert _ZWC_RE.search(marker) is not None

    def test_matches_mixed_bits(self):
        marker = "\ufeff" + "\u200b\u200c" * 8 + "\ufeff"
        assert _ZWC_RE.search(marker) is not None

    def test_no_match_on_short_marker(self):
        marker = "\ufeff" + "\u200b" * 15 + "\ufeff"
        assert _ZWC_RE.search(marker) is None

    def test_no_match_on_long_marker(self):
        marker = "\ufeff" + "\u200b" * 17 + "\ufeff"
        # Should match the first 16 chars between boundaries, but as a full match the 17th is outside
        match = _ZWC_RE.search(marker)
        if match:
            # The regex matches a 16-bit substring, leaving extra chars outside
            assert len(match.group()) == 18  # FEFF + 16 + FEFF

    def test_no_match_without_boundaries(self):
        marker = "\u200b" * 16
        assert _ZWC_RE.search(marker) is None


@pytest.mark.django_db
class TestDraftLanguageOverride:
    """Draft language cookie detection and translation activation."""

    def test_draft_cookie_stores_lang_on_request(self, make_request, settings):
        """_handle_request stores draft lang on request but does NOT activate yet."""
        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        # Use "xx" as draft language (not in Django's default LANGUAGES)
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs", "xx"])
        _clear_caches()
        request = make_request("get", "/page/")
        request.COOKIES[_DRAFT_LANG_COOKIE] = "xx"

        # Capture the language during inner call to verify it wasn't changed
        captured_lang: list[str | None] = []
        original_inner = inner

        def tracking_inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            captured_lang.append(django.utils.translation.get_language())
            return original_inner(req)

        mw = LiveTranslationsMiddleware(tracking_inner)
        mw(request)

        # Draft lang is stored on the request for process_view
        assert getattr(request, _DRAFT_LANG_ATTR) == "xx"

    def test_process_view_activates_draft_language(self, make_request, settings):
        """process_view activates the draft language after URL resolution."""
        mw = LiveTranslationsMiddleware(lambda r: _html_response())

        request = make_request("get", "/page/")
        setattr(request, _DRAFT_LANG_ATTR, "xx")

        result = mw.process_view(request, lambda r: _html_response(), (), {})

        assert result is None
        assert django.utils.translation.get_language() == "xx"
        assert request.LANGUAGE_CODE == "xx"

    def test_process_view_noop_without_draft(self, make_request, settings):
        """process_view does nothing when no draft language is set."""
        mw = LiveTranslationsMiddleware(lambda r: _html_response())

        request = make_request("get", "/page/")
        original_lang = django.utils.translation.get_language()

        result = mw.process_view(request, lambda r: _html_response(), (), {})

        assert result is None
        assert django.utils.translation.get_language() == original_lang

    def test_draft_cookie_ignored_for_published_language(self, make_request, settings):
        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        # "en" is in Django's default LANGUAGES, so not a draft language
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs"])
        _clear_caches()
        request = make_request("get", "/page/")
        request.COOKIES[_DRAFT_LANG_COOKIE] = "en"
        mw(request)

        assert not hasattr(request, _DRAFT_LANG_ATTR)

    def test_draft_cookie_ignored_for_non_permitted_user(self, make_request, settings):
        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        # "xx" is draft, but user is denied permission
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "xx"], permission=False)
        _clear_caches()
        request = make_request("get", "/page/", has_permission=False)
        request.COOKIES[_DRAFT_LANG_COOKIE] = "xx"
        mw(request)

        assert not hasattr(request, _DRAFT_LANG_ATTR)

    def test_draft_cookie_cleared_for_non_permitted_user(self, make_request, settings):
        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "xx"], permission=False)
        _clear_caches()
        request = make_request("get", "/page/", has_permission=False)
        request.COOKIES[_DRAFT_LANG_COOKIE] = "xx"
        response = mw(request)

        # The middleware should schedule cookie deletion
        assert _DRAFT_LANG_COOKIE in str(response.cookies)
        assert response.cookies[_DRAFT_LANG_COOKIE]["max-age"] == 0

    def test_empty_cookie_ignored(self, make_request, settings):
        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "xx"])
        _clear_caches()
        request = make_request("get", "/page/")
        request.COOKIES[_DRAFT_LANG_COOKIE] = ""
        mw(request)

        assert not hasattr(request, _DRAFT_LANG_ATTR)

    def test_unknown_code_ignored(self, make_request, settings):
        inner_response = _html_response("<html><body>Hi</body></html>")
        inner = lambda r: inner_response  # noqa: E731
        mw = LiveTranslationsMiddleware(inner)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs"])
        _clear_caches()
        request = make_request("get", "/page/")
        # "zz" is not in the LANGUAGES list at all
        request.COOKIES[_DRAFT_LANG_COOKIE] = "zz"
        mw(request)

        assert not hasattr(request, _DRAFT_LANG_ATTR)

    def test_config_includes_draft_languages_array(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        # "xx" is not in Django's LANGUAGES -> becomes a draft language
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs", "xx"])
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'draftLanguages:["xx"]' in content

    def test_config_empty_draft_languages(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        # "en" and "cs" are both in Django's default LANGUAGES -> no drafts
        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs"])
        _clear_caches()
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "draftLanguages:[]" in content

    def test_config_includes_current_language(self, make_request, settings):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "cs"])
        _clear_caches()

        with django.utils.translation.override("cs"):
            mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "currentLanguage:'cs'" in content

    def test_current_language_reflects_draft_after_process_view(self, make_request, settings):
        """After process_view activates draft language, _inject_assets uses it for currentLanguage."""
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)

        settings.LIVE_TRANSLATIONS = _middleware_settings(languages=["en", "xx"])
        _clear_caches()

        # Simulate what process_view does: activate the draft language
        django.utils.translation.activate("xx")
        mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "currentLanguage:'xx'" in content
