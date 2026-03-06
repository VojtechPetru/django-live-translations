"""Middleware that activates live translations for superusers.

Responsibilities:
1. Set _lt_active contextvar and request._live_translations_active flag.
2. Inject JS/CSS assets into HTML responses for active users.
"""

import typing as t

from django.http import HttpRequest, HttpResponse  # noqa: TC002
from django.middleware.csrf import get_token

from .conf import get_conf, get_permission_checker
from .strings import lt_active


class LiveTranslationsMiddleware:
    """Inject live translation assets for authorized users."""

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip admin URLs entirely
        if request.path.startswith("/admin/"):
            return self.get_response(request)

        checker = get_permission_checker()
        is_active = checker(request)
        request._live_translations_active = is_active  # type: ignore[attr-defined]

        if is_active:
            token = lt_active.set(True)
            try:
                response = self.get_response(request)
            finally:
                lt_active.reset(token)
        else:
            response = self.get_response(request)

        if not is_active:
            return response

        # Only inject into non-streaming HTML responses
        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type or response.streaming:  # type: ignore[union-attr]
            return response

        self._inject_assets(request, response)
        return response

    def _inject_assets(self, request: HttpRequest, response: HttpResponse) -> None:
        content = response.content.decode(response.charset)

        body_close_idx = content.rfind("</body>")
        if body_close_idx == -1:
            return

        conf = get_conf()
        api_base = conf.url_prefix
        languages_json = ",".join(f'"{lang}"' for lang in conf.languages)
        csrf_token = get_token(request)

        snippet = (
            '<link rel="stylesheet" href="/static/live_translations/widget.css">'
            "<script>"
            f"window.__LT_CONFIG__={{apiBase:'{api_base}',"
            f"languages:[{languages_json}],"
            f"csrfToken:'{csrf_token}'}};"
            "</script>"
            '<script src="/static/live_translations/widget.js"></script>'
        )

        response.content = (content[:body_close_idx] + snippet + content[body_close_idx:]).encode(response.charset)

        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)
