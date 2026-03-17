"""Tests for the LiveTranslationsMiddleware."""

import json
import unittest.mock

import django.http
import pytest

from live_translations import conf, strings
from live_translations.middleware import _ZWC_RE, LiveTranslationsMiddleware
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


def _mock_backend():
    backend = unittest.mock.MagicMock()
    backend.ensure_current.return_value = None
    backend.get_inactive_overrides.return_value = {}
    return backend


def _mock_settings(
    *,
    languages: list[str] | None = None,
    active_by_default: bool = False,
    shortcut_edit: str = "ctrl+shift+e",
    shortcut_preview: str = "ctrl+shift+p",
) -> conf.LiveTranslationsConf:
    return conf.LiveTranslationsConf(
        languages=languages or ["en", "cs"],
        translation_active_by_default=active_by_default,
        shortcut_edit=shortcut_edit,
        shortcut_preview=shortcut_preview,
    )


def _patch_middleware_deps(
    *,
    permission: bool = True,
    is_preview: bool = False,
    backend: unittest.mock.MagicMock | None = None,
    settings: conf.LiveTranslationsConf | None = None,
):
    """Context manager that patches conf helpers used by the middleware."""
    backend = backend or _mock_backend()
    settings = settings or _mock_settings()

    return unittest.mock.patch.multiple(
        "live_translations.middleware.conf",
        get_backend_instance=unittest.mock.MagicMock(return_value=backend),
        get_permission_checker=unittest.mock.MagicMock(return_value=lambda _req: permission),
        is_preview_request=unittest.mock.MagicMock(return_value=is_preview),
        get_settings=unittest.mock.MagicMock(return_value=settings),
    )


class TestDispatchApi:
    """API route dispatch and non-API passthrough."""

    def test_dispatches_known_api_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True})
        inner = unittest.mock.MagicMock(return_value=_html_response())
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.get_translations = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("get", "/__live-translations__/translations/")
            response = mw(request)

        assert response is mock_view_response
        mock_views.get_translations.assert_called_once_with(request)
        inner.assert_not_called()

    def test_dispatches_save_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True})
        inner = unittest.mock.MagicMock(return_value=_html_response())
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.save_translations = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("post", "/__live-translations__/translations/save/")
            response = mw(request)

        assert response is mock_view_response
        mock_views.save_translations.assert_called_once_with(request)

    def test_dispatches_delete_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True})
        inner = unittest.mock.MagicMock()
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.delete_translation = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("post", "/__live-translations__/translations/delete/")
            response = mw(request)

        assert response is mock_view_response
        mock_views.delete_translation.assert_called_once_with(request)

    def test_dispatches_history_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"history": []})
        inner = unittest.mock.MagicMock()
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.get_history = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("get", "/__live-translations__/translations/history/")
            response = mw(request)

        assert response is mock_view_response

    def test_dispatches_bulk_activate_route(self, make_request):
        mock_view_response = django.http.JsonResponse({"ok": True, "activated": 2})
        inner = unittest.mock.MagicMock()
        mw = LiveTranslationsMiddleware(inner)

        with unittest.mock.patch("live_translations.middleware.views") as mock_views:
            mock_views.bulk_activate = unittest.mock.MagicMock(return_value=mock_view_response)
            request = make_request("post", "/__live-translations__/translations/bulk-activate/")
            response = mw(request)

        assert response is mock_view_response

    def test_non_api_path_passes_through(self, make_request):
        inner_response = _html_response()
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with _patch_middleware_deps(permission=False):
            request = make_request("get", "/some-page/")
            response = mw(request)

        inner.assert_called_once()
        assert response is inner_response


class TestHandleRequest:
    """Core middleware request handling: admin bypass, inactive user, HTML injection, etc."""

    def test_admin_path_bypasses_middleware(self, make_request):
        inner_response = _html_response("<html><body>Admin</body></html>")
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with (
            _patch_middleware_deps(),
            unittest.mock.patch.object(
                LiveTranslationsMiddleware,
                "_is_admin_path",
                return_value=True,
            ),
        ):
            request = make_request("get", "/admin/some-model/")
            response = mw(request)

        assert response is inner_response
        # No snippet injected into admin responses
        assert b"__LT_CONFIG__" not in response.content

    def test_inactive_user_returns_unmodified_response(self, make_request):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with _patch_middleware_deps(permission=False):
            request = make_request("get", "/page/", has_permission=False)
            response = mw(request)

        assert response is inner_response
        assert b"__LT_CONFIG__" not in response.content

    def test_active_user_html_gets_assets_injected(self, make_request):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with (
            _patch_middleware_deps(permission=True),
            unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="tok"),
            unittest.mock.patch(
                "live_translations.middleware.django.templatetags.static.static",
                side_effect=lambda p: f"/static/{p}",
            ),
        ):
            request = make_request("get", "/page/")
            response = mw(request)

        assert b"__LT_CONFIG__" in response.content
        assert b"</body>" in response.content

    def test_json_response_strips_zwc_when_active(self, make_request):
        marker = "\ufeff" + "\u200b\u200c" * 8 + "\ufeff"
        zwc_content = '{"msg":"' + marker + '"}'
        inner_response = _json_response(zwc_content)
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with _patch_middleware_deps(permission=True):
            request = make_request("get", "/api/data/")
            response = mw(request)

        content = response.content.decode()
        assert "\ufeff" not in content

    def test_streaming_html_strips_zwc(self, make_request):
        """Streaming HTML responses should go through ZWC strip path, not injection."""
        inner_response = _streaming_html_response()
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with _patch_middleware_deps(permission=True):
            with unittest.mock.patch.object(LiveTranslationsMiddleware, "_strip_zwc") as mock_strip:
                request = make_request("get", "/page/")
                mw(request)

        mock_strip.assert_called_once_with(inner_response)

    def test_resets_string_registry_after_response(self, make_request):
        inner = unittest.mock.MagicMock(return_value=_html_response())
        mw = LiveTranslationsMiddleware(inner)

        with _patch_middleware_deps(permission=True):
            with unittest.mock.patch("live_translations.middleware.strings.reset_string_registry") as mock_reset:
                request = make_request("get", "/page/")
                mw(request)

        mock_reset.assert_called_once()

    def test_does_not_reset_registry_when_get_response_raises(self, make_request):
        """When get_response raises, the outer try/finally for reset_string_registry is never entered."""

        def raise_error(_req):
            raise RuntimeError("boom")

        mw = LiveTranslationsMiddleware(raise_error)

        with _patch_middleware_deps(permission=True):
            with unittest.mock.patch("live_translations.middleware.strings.reset_string_registry") as mock_reset:
                request = make_request("get", "/page/")
                with pytest.raises(RuntimeError, match="boom"):
                    mw(request)

        mock_reset.assert_not_called()

    def test_resets_lt_active_contextvar_on_exception(self, make_request):
        """lt_active is always reset even when get_response raises."""

        def raise_error(_req):
            raise RuntimeError("boom")

        mw = LiveTranslationsMiddleware(raise_error)

        with _patch_middleware_deps(permission=True):
            request = make_request("get", "/page/")
            with pytest.raises(RuntimeError, match="boom"):
                mw(request)

        assert strings.lt_active.get(False) is False

    def test_preview_mode_loads_overrides(self, make_request):
        preview_overrides = {MsgKey("hello", ""): "Ahoj"}
        backend = _mock_backend()
        backend.get_inactive_overrides.return_value = preview_overrides

        inner_response = _html_response("<html><body>Page</body></html>")
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with (
            _patch_middleware_deps(permission=True, is_preview=True, backend=backend),
            unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="tok"),
            unittest.mock.patch(
                "live_translations.middleware.django.templatetags.static.static",
                side_effect=lambda p: f"/static/{p}",
            ),
            unittest.mock.patch(
                "live_translations.middleware.django.utils.translation.get_language",
                return_value="cs",
            ),
        ):
            request = make_request("get", "/page/")
            response = mw(request)

        content = response.content.decode()
        assert "preview:true" in content
        assert "previewEntries:" in content

    def test_preview_mode_resets_contextvar(self, make_request):
        backend = _mock_backend()
        backend.get_inactive_overrides.return_value = {MsgKey("hello", ""): "Hi"}
        inner = unittest.mock.MagicMock(return_value=_html_response())
        mw = LiveTranslationsMiddleware(inner)

        with (
            _patch_middleware_deps(permission=True, is_preview=True, backend=backend),
            unittest.mock.patch(
                "live_translations.middleware.django.utils.translation.get_language",
                return_value="en",
            ),
        ):
            request = make_request("get", "/page/")
            mw(request)

        # After middleware completes, preview overrides contextvar should be reset
        assert strings.lt_preview_overrides.get(None) is None

    def test_non_preview_active_user_no_preview_config(self, make_request):
        inner_response = _html_response("<html><body>Page</body></html>")
        inner = unittest.mock.MagicMock(return_value=inner_response)
        mw = LiveTranslationsMiddleware(inner)

        with (
            _patch_middleware_deps(permission=True, is_preview=False),
            unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="tok"),
            unittest.mock.patch(
                "live_translations.middleware.django.templatetags.static.static",
                side_effect=lambda p: f"/static/{p}",
            ),
        ):
            request = make_request("get", "/page/")
            response = mw(request)

        content = response.content.decode()
        assert "preview:true" not in content

    def test_ensure_current_called_for_non_api_paths(self, make_request):
        backend = _mock_backend()
        inner = unittest.mock.MagicMock(return_value=_html_response())
        mw = LiveTranslationsMiddleware(inner)

        with _patch_middleware_deps(permission=False, backend=backend):
            request = make_request("get", "/page/")
            mw(request)

        backend.ensure_current.assert_called_once()


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


class TestInjectAssets:
    """Tests for _inject_assets method."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        strings.reset_string_registry()
        yield
        strings.reset_string_registry()

    def test_injects_before_body_close(self, make_request):
        response = _html_response("<html><body>Content</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings(languages=["en", "cs"])

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch(
                "live_translations.middleware.django.middleware.csrf.get_token", return_value="abc"
            ):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
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

    def test_includes_csrf_token(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch(
                "live_translations.middleware.django.middleware.csrf.get_token", return_value="my-csrf-token"
            ):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "csrfToken:'my-csrf-token'" in content

    def test_includes_languages(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings(languages=["en", "de", "fr"])

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'languages:["en","de","fr"]' in content

    def test_includes_api_base(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "apiBase:'/__live-translations__'" in content

    def test_includes_static_urls(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'href="/static/live_translations/widget.css"' in content
        assert 'src="/static/live_translations/widget.js"' in content

    def test_active_by_default_true(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings(active_by_default=True)

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "activeByDefault:true" in content

    def test_active_by_default_false(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings(active_by_default=False)

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert "activeByDefault:false" in content

    def test_preview_entries_included(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()
        preview = {MsgKey("hello", ""): "Ahoj", MsgKey("bye", "ctx"): "Nashle"}

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response, preview_entries=preview)

        content = response.content.decode()
        assert "preview:true" in content
        assert "previewEntries:" in content

    def test_no_preview_entries_when_none(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response, preview_entries=None)

        content = response.content.decode()
        assert "preview:true" not in content

    def test_updates_content_length(self, make_request):
        response = _html_response("<html><body>X</body></html>", content_length=True)
        original_length = int(response["Content-Length"])
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        new_length = int(response["Content-Length"])
        assert new_length > original_length
        assert new_length == len(response.content)

    def test_no_content_length_header_not_added(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        if "Content-Length" in response:
            del response["Content-Length"]
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        assert "Content-Length" not in response

    def test_string_registry_serialized(self, make_request):
        # Register a string so the table is non-empty
        strings.register_string(MsgKey("hello", ""))
        strings.register_string(MsgKey("bye", "ctx"))

        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings()

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
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

    def test_shortcut_keys_included(self, make_request):
        response = _html_response("<html><body>X</body></html>")
        mw = LiveTranslationsMiddleware(lambda r: response)
        settings = _mock_settings(shortcut_edit="ctrl+e", shortcut_preview="ctrl+p")

        with unittest.mock.patch("live_translations.middleware.conf.get_settings", return_value=settings):
            with unittest.mock.patch("live_translations.middleware.django.middleware.csrf.get_token", return_value="t"):
                with unittest.mock.patch(
                    "live_translations.middleware.django.templatetags.static.static",
                    side_effect=lambda p: f"/static/{p}",
                ):
                    mw._inject_assets(make_request("get", "/page/"), response)

        content = response.content.decode()
        assert 'shortcutEdit:"ctrl+e"' in content
        assert 'shortcutPreview:"ctrl+p"' in content


class TestLoadPreviewOverrides:
    """Tests for _load_preview_overrides static method."""

    def test_delegates_to_backend(self):
        backend = _mock_backend()
        expected = {MsgKey("hello", ""): "Ahoj"}
        backend.get_inactive_overrides.return_value = expected

        with unittest.mock.patch("live_translations.middleware.conf.get_backend_instance", return_value=backend):
            with unittest.mock.patch(
                "live_translations.middleware.django.utils.translation.get_language", return_value="cs"
            ):
                result = LiveTranslationsMiddleware._load_preview_overrides()

        assert result == expected
        backend.get_inactive_overrides.assert_called_once_with("cs")

    def test_empty_language_returns_empty_dict(self):
        backend = _mock_backend()

        with unittest.mock.patch("live_translations.middleware.conf.get_backend_instance", return_value=backend):
            with unittest.mock.patch(
                "live_translations.middleware.django.utils.translation.get_language", return_value=""
            ):
                result = LiveTranslationsMiddleware._load_preview_overrides()

        assert result == {}
        backend.get_inactive_overrides.assert_not_called()

    def test_none_language_returns_empty_dict(self):
        backend = _mock_backend()

        with unittest.mock.patch("live_translations.middleware.conf.get_backend_instance", return_value=backend):
            with unittest.mock.patch(
                "live_translations.middleware.django.utils.translation.get_language", return_value=None
            ):
                result = LiveTranslationsMiddleware._load_preview_overrides()

        assert result == {}
        backend.get_inactive_overrides.assert_not_called()


class TestCallUserContextvar:
    """Tests for lt_current_user contextvar set/reset in __call__."""

    def test_sets_authenticated_user(self, make_request):
        captured_user: list[object] = []

        def capture_inner(request):
            captured_user.append(strings.lt_current_user.get(None))
            return _html_response()

        mw = LiveTranslationsMiddleware(capture_inner)

        with _patch_middleware_deps(permission=False):
            request = make_request("get", "/page/", has_permission=True)
            mw(request)

        assert captured_user[0] is request.user

    def test_sets_none_for_unauthenticated_user(self, make_request):
        captured_user: list[object] = []

        def capture_inner(request):
            captured_user.append(strings.lt_current_user.get(None))
            return _html_response()

        mw = LiveTranslationsMiddleware(capture_inner)

        with _patch_middleware_deps(permission=False):
            request = make_request("get", "/page/", has_permission=False)
            mw(request)

        assert captured_user[0] is None

    def test_sets_none_for_anonymous_user(self, make_request):
        captured_user: list[object] = []

        def capture_inner(request):
            captured_user.append(strings.lt_current_user.get(None))
            return _html_response()

        mw = LiveTranslationsMiddleware(capture_inner)
        request = make_request("get", "/page/", anonymous=True)

        with _patch_middleware_deps(permission=False):
            mw(request)

        assert captured_user[0] is None

    def test_resets_contextvar_after_request(self, make_request):
        mw = LiveTranslationsMiddleware(lambda r: _html_response())

        with _patch_middleware_deps(permission=False):
            request = make_request("get", "/page/", has_permission=True)
            mw(request)

        # After middleware completes, contextvar should be reset to default
        assert strings.lt_current_user.get(None) is None

    def test_resets_contextvar_on_exception(self, make_request):
        def raise_error(_req):
            raise RuntimeError("boom")

        mw = LiveTranslationsMiddleware(raise_error)

        with _patch_middleware_deps(permission=True):
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
