"""Middleware that activates live translations for superusers.

Responsibilities:
1. Dispatch API requests (``/__live-translations__/*``) to view functions.
2. Set ``lt_active`` contextvar so patched gettext appends ZWC markers.
3. Inject the string table + JS/CSS assets into HTML responses.
4. Strip ZWC markers from non-HTML responses (JSON APIs, etc.).
"""

import json
import re
import typing as t

import django.http
import django.middleware.csrf
import django.templatetags.static
import django.utils.translation

from live_translations import conf, strings, views
from live_translations.types import OverrideMap, StringTable

__all__ = ["LiveTranslationsMiddleware"]

_ZWC_RE: t.Final[re.Pattern[str]] = re.compile(r"\uFEFF[\u200B\u200C]{16}\uFEFF")

_API_ROUTES: dict[str, str] = {
    f"{conf.API_PREFIX}/translations/": "get_translations",
    f"{conf.API_PREFIX}/translations/save/": "save_translations",
    f"{conf.API_PREFIX}/translations/delete/": "delete_translation",
    f"{conf.API_PREFIX}/translations/history/": "get_history",
    f"{conf.API_PREFIX}/translations/bulk-activate/": "bulk_activate",
}


class LiveTranslationsMiddleware:
    """Inject live translation assets for authorized users."""

    def __init__(
        self,
        get_response: t.Callable[[django.http.HttpRequest], django.http.HttpResponse],
    ) -> None:
        self.get_response = get_response

    def __call__(
        self,
        request: django.http.HttpRequest,
    ) -> django.http.HttpResponse:
        # Set current user for history tracking (available to all code paths
        # including API dispatch and admin saves).
        raw_user = getattr(request, "user", None)
        user_token = strings.lt_current_user.set(
            raw_user if raw_user and getattr(raw_user, "is_authenticated", False) else None
        )
        try:
            return self._handle_request(request)
        finally:
            strings.lt_current_user.reset(user_token)

    def _handle_request(
        self,
        request: django.http.HttpRequest,
    ) -> django.http.HttpResponse:
        # Dispatch API requests before any other processing
        view_name = _API_ROUTES.get(request.path)
        if view_name is not None:
            return self._dispatch_api(request, view_name)

        conf.get_backend_instance().ensure_current()

        # Skip admin URLs entirely
        if request.path.startswith("/admin/"):
            return self.get_response(request)

        checker = conf.get_permission_checker()
        is_active = checker(request)

        # Preview mode: load inactive overrides for the current language
        is_preview = is_active and conf.is_preview_request(request)
        preview_overrides: OverrideMap | None = None
        preview_token = None
        if is_preview:
            preview_overrides = self._load_preview_overrides()
            preview_token = strings.lt_preview_overrides.set(preview_overrides)

        token = strings.lt_active.set(is_active)
        try:
            response = self.get_response(request)
        finally:
            strings.lt_active.reset(token)
            if preview_token is not None:
                strings.lt_preview_overrides.reset(preview_token)

        if not is_active:
            strings.reset_string_registry()
            return response

        # Only inject into non-streaming HTML responses
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type or response.streaming:  # type: ignore[union-attr]
            self._strip_zwc(response)
            strings.reset_string_registry()
            return response

        self._inject_assets(request, response, preview_entries=preview_overrides)
        strings.reset_string_registry()
        return response

    @staticmethod
    def _dispatch_api(
        request: django.http.HttpRequest,
        view_name: str,
    ) -> django.http.HttpResponse:
        view: t.Callable[[django.http.HttpRequest], django.http.HttpResponse] = getattr(views, view_name)
        return view(request)

    @staticmethod
    def _load_preview_overrides() -> OverrideMap:
        """Load inactive translations for the current language into a preview dict."""
        language = django.utils.translation.get_language() or ""
        if not language:
            return {}
        return conf.get_backend_instance().get_inactive_overrides(language)

    @staticmethod
    def _strip_zwc(response: django.http.HttpResponse) -> None:
        """Strip ZWC markers from non-HTML responses."""
        content = response.content.decode(response.charset)
        if strings.ZWC_BOUNDARY not in content:
            return
        content = _ZWC_RE.sub("", content)
        response.content = content.encode(response.charset)
        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)

    def _inject_assets(
        self,
        request: django.http.HttpRequest,
        response: django.http.HttpResponse,
        *,
        preview_entries: OverrideMap | None = None,
    ) -> None:
        content = response.content.decode(response.charset)

        body_close_idx = content.rfind("</body>")
        if body_close_idx == -1:
            return

        settings = conf.get_settings()
        languages_json = ",".join(f'"{lang}"' for lang in settings.languages)
        csrf_token = django.middleware.csrf.get_token(request)

        css_url = django.templatetags.static.static("live_translations/widget.css")
        js_url = django.templatetags.static.static("live_translations/widget.js")

        active_by_default = "true" if settings.translation_active_by_default else "false"

        preview_config = ""
        if preview_entries is not None:
            entries_json = json.dumps(
                [{"m": m, "c": c} for (m, c) in preview_entries],
                separators=(",", ":"),
            )
            preview_config = f",preview:true,previewEntries:{entries_json}"

        shortcut_edit_js = json.dumps(settings.shortcut_edit)
        shortcut_preview_js = json.dumps(settings.shortcut_preview)

        # Serialize the per-request string registry for client-side marker resolution
        registry = strings.get_string_registry()
        table: StringTable = {i: {"m": key.msgid, "c": key.context} for i, key in enumerate(registry)}
        strings_json = json.dumps(table, separators=(",", ":"))

        snippet = (
            f'<link rel="stylesheet" href="{css_url}">'
            "<script>"
            f"window.__LT_CONFIG__={{apiBase:'{conf.API_PREFIX}',"
            f"languages:[{languages_json}],"
            f"csrfToken:'{csrf_token}',"
            f"activeByDefault:{active_by_default},"
            f"shortcutEdit:{shortcut_edit_js},"
            f"shortcutPreview:{shortcut_preview_js}"
            f"{preview_config}}};"
            f"window.__LT_STRINGS__={strings_json};"
            "</script>"
            f'<script src="{js_url}"></script>'
        )

        response.content = (content[:body_close_idx] + snippet + content[body_close_idx:]).encode(response.charset)

        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)
