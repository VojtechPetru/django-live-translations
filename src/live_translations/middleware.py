"""Middleware that activates live translations for superusers.

Responsibilities:
1. Dispatch API requests (``/__live-translations__/*``) to view functions.
2. Set ``lt_active`` contextvar so template nodes and gettext know when to emit markers.
3. Resolve text-safe markers into ``<span>`` wrappers (text) or ``data-lt-attrs`` (attributes).
4. Inject JS/CSS assets into HTML responses for active users.
"""

import typing as t

import django.http
import django.middleware.csrf
import django.templatetags.static
import django.utils.html

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
        token = strings.lt_active.set(is_active)
        try:
            response = self.get_response(request)
        finally:
            strings.lt_active.reset(token)

        if not is_active:
            return response

        # Only inject into non-streaming HTML responses
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type or response.streaming:  # type: ignore[union-attr]
            return response

        self._inject_assets(request, response)
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

    def _inject_assets(
        self,
        request: django.http.HttpRequest,
        response: django.http.HttpResponse,
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

        snippet = (
            f'<link rel="stylesheet" href="{css_url}">'
            "<script>"
            f"window.__LT_CONFIG__={{apiBase:'{conf.API_PREFIX}',"
            f"languages:[{languages_json}],"
            f"csrfToken:'{csrf_token}',"
            f"activeByDefault:{active_by_default}}};"
            "</script>"
            f'<script src="{js_url}"></script>'
        )

        response.content = (
            content[:body_close_idx] + snippet + content[body_close_idx:]
        ).encode(response.charset)

        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)
