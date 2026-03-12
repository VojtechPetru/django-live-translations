"""Middleware that activates live translations for superusers.

Responsibilities:
1. Dispatch API requests (``/__live-translations__/*``) to view functions.
2. Set ``lt_active`` contextvar so template nodes and gettext know when to emit markers.
3. Resolve text-safe markers into ``<span>`` wrappers (text) or ``data-lt-attrs`` (attributes).
4. Inject JS/CSS assets into HTML responses for active users.
"""

import json
import typing as t

import django.http
import django.middleware.csrf
import django.templatetags.static
import django.utils.html
import django.utils.translation

from live_translations import conf, resolver, strings

_resolver = resolver.MarkerResolver(
    marker_re=strings.MARKER_RE,
    marker_start=strings.MARKER_START,
    b64_decode=strings._b64d,
    html_escape=django.utils.html.escape,
)

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
            raw_user
            if raw_user and getattr(raw_user, "is_authenticated", False)
            else None
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
        is_preview = is_active and request.COOKIES.get("lt_preview") == "1"
        preview_overrides: dict[tuple[str, str], str] | None = None
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
            return response

        # Only inject into non-streaming HTML responses
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type or response.streaming:  # type: ignore[union-attr]
            return response

        self._inject_assets(request, response, preview_entries=preview_overrides)
        return response

    @staticmethod
    def _dispatch_api(
        request: django.http.HttpRequest,
        view_name: str,
    ) -> django.http.HttpResponse:
        from live_translations import views

        view: t.Callable[[django.http.HttpRequest], django.http.HttpResponse] = getattr(
            views, view_name
        )
        return view(request)

    @staticmethod
    def _load_preview_overrides() -> dict[tuple[str, str], str]:
        """Load inactive DB translations for the current language into a preview dict."""
        from live_translations import models

        language = django.utils.translation.get_language() or ""
        if not language:
            return {}

        overrides: dict[tuple[str, str], str] = {}
        try:
            for msgid, ctx, msgstr in (
                models.TranslationEntry.objects.filter(
                    language=language, is_active=False
                )
                .exclude(msgstr="")
                .values_list("msgid", "context", "msgstr")
            ):
                overrides[(msgid, ctx)] = msgstr
        except Exception:
            pass
        return overrides

    def _inject_assets(
        self,
        request: django.http.HttpRequest,
        response: django.http.HttpResponse,
        *,
        preview_entries: dict[tuple[str, str], str] | None = None,
    ) -> None:
        content = response.content.decode(response.charset)

        # Resolve text-safe markers -> <span> (text) or plain text + data-lt-attrs (attributes)
        if strings.MARKER_START in content:
            content = _resolver.resolve(content)

        body_close_idx = content.rfind("</body>")
        if body_close_idx == -1:
            return

        settings = conf.get_settings()
        languages_json = ",".join(f'"{lang}"' for lang in settings.languages)
        csrf_token = django.middleware.csrf.get_token(request)

        css_url = django.templatetags.static.static("live_translations/widget.css")
        js_url = django.templatetags.static.static("live_translations/widget.js")

        active_by_default = (
            "true" if settings.translation_active_by_default else "false"
        )

        preview_config = ""
        if preview_entries:
            entries_json = json.dumps(
                [{"m": m, "c": c} for (m, c) in preview_entries],
                separators=(",", ":"),
            )
            preview_config = f",preview:true,previewEntries:{entries_json}"

        snippet = (
            f'<link rel="stylesheet" href="{css_url}">'
            "<script>"
            f"window.__LT_CONFIG__={{apiBase:'{conf.API_PREFIX}',"
            f"languages:[{languages_json}],"
            f"csrfToken:'{csrf_token}',"
            f"activeByDefault:{active_by_default}{preview_config}}};"
            "</script>"
            f'<script src="{js_url}"></script>'
        )

        response.content = (
            content[:body_close_idx] + snippet + content[body_close_idx:]
        ).encode(response.charset)

        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)
