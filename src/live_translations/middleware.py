"""Middleware that activates live translations for superusers.

Responsibilities:
1. Dispatch API requests (``/__live-translations__/*``) to view functions.
2. Set ``lt_active`` contextvar so patched gettext appends ZWC markers.
3. Inject the string table + JS/CSS assets into HTML responses.
4. Strip ZWC markers from non-HTML responses (JSON APIs, etc.).
"""

import html as html_mod
import json
import re
import typing as t

import django.http
import django.middleware.csrf
import django.templatetags.static
import django.urls
import django.utils.translation

from live_translations import conf, plurals, strings, views
from live_translations.types import ClientConfig, LanguageCode, OverrideMap, PreviewItem, StringTable, StringTableEntry

__all__ = ["LiveTranslationsMiddleware"]

_ZWC_RE: t.Final[re.Pattern[str]] = re.compile(r"\uFEFF[\u200B\u200C]{16}\uFEFF")


def _json_attr(obj: t.Any) -> str:
    """Serialize *obj* to compact JSON and HTML-escape for use in an attribute value."""
    return html_mod.escape(json.dumps(obj, separators=(",", ":")), quote=True)


_ATTR_CONFIG: t.Final[str] = "data-lt-config"
_ATTR_STRINGS: t.Final[str] = "data-lt-strings"

_DRAFT_LANG_COOKIE: t.Final[str] = "lt_lang"
_DRAFT_LANG_ATTR: t.Final[str] = "_lt_draft_lang"

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

        # Skip admin URLs entirely (use resolver so it works regardless of
        # URL prefix, e.g. when admin is inside i18n_patterns).
        if self._is_admin_path(request.path):
            return self.get_response(request)

        settings = conf.get_settings()
        checker = conf.get_permission_checker()
        permission_result = checker(request)
        editable = conf.resolve_editable_languages(permission_result, settings.languages)
        is_active = editable is not None

        # Draft language override via lt_lang cookie (draft languages only).
        # We store it on the request but DON'T activate yet — activating before
        # get_response() would break i18n_patterns URL resolution (Django's
        # LocalePrefixPattern uses get_language() to match the URL prefix).
        # Actual activation happens in process_view(), after URL resolution.
        draft_lang: str | None = None
        if is_active:
            lt_lang = request.COOKIES.get(_DRAFT_LANG_COOKIE, "")
            if lt_lang and conf.is_draft_language(lt_lang):
                draft_lang = lt_lang
                setattr(request, _DRAFT_LANG_ATTR, lt_lang)

        # Preview mode: load inactive overrides for the target language
        is_preview = is_active and conf.is_preview_request(request)
        preview_overrides: OverrideMap | None = None
        preview_token = None
        if is_preview:
            preview_overrides = self._load_preview_overrides(language=draft_lang)
            preview_token = strings.lt_preview_overrides.set(preview_overrides)

        token = strings.lt_active.set(is_active)
        try:
            response = self.get_response(request)
        finally:
            strings.lt_active.reset(token)
            if preview_token is not None:
                strings.lt_preview_overrides.reset(preview_token)

        try:
            if not is_active:
                # Clear stale draft language cookie for non-permitted users
                if request.COOKIES.get(_DRAFT_LANG_COOKIE):
                    response.delete_cookie(_DRAFT_LANG_COOKIE, path="/")
                return response

            # Only inject into non-streaming HTML responses
            content_type = response.get("Content-Type", "")
            if "text/html" not in content_type or response.streaming:  # type: ignore[union-attr]
                self._strip_zwc(response)
                return response

            self._inject_assets(request, response, preview_entries=preview_overrides, editable_languages=editable)
            return response
        finally:
            strings.reset_string_registry()

    def process_view(
        self,
        request: django.http.HttpRequest,
        view_func: t.Callable[..., django.http.HttpResponse],
        view_args: tuple[t.Any, ...],
        view_kwargs: dict[str, t.Any],
    ) -> None:
        """
        Activate the draft language after URL resolution (so i18n_patterns works).
        https://docs.djangoproject.com/en/6.0/topics/http/middleware/#process-view
        """
        draft_lang: str | None = getattr(request, _DRAFT_LANG_ATTR, None)
        if draft_lang:
            django.utils.translation.activate(draft_lang)
            request.LANGUAGE_CODE = draft_lang  # type: ignore[attr-defined]

    @staticmethod
    def _is_admin_path(path: str) -> bool:
        """Return True if *path* resolves to the Django admin app."""
        try:
            match = django.urls.resolve(path)
        except Exception:  # noqa: BLE001
            return False
        return getattr(match, "app_name", None) == "admin"

    @staticmethod
    def _dispatch_api(
        request: django.http.HttpRequest,
        view_name: str,
    ) -> django.http.HttpResponse:
        view: t.Callable[[django.http.HttpRequest], django.http.HttpResponse] = getattr(views, view_name)
        return view(request)

    @staticmethod
    def _load_preview_overrides(*, language: str | None = None) -> OverrideMap:
        """Load inactive translations for the given (or current) language."""
        lang = language or django.utils.translation.get_language() or ""
        if not lang:
            return {}
        return conf.get_backend_instance().get_inactive_overrides(lang)

    @staticmethod
    def _strip_zwc(response: django.http.HttpResponse) -> None:
        """Strip ZWC end markers and start flags from non-HTML responses."""
        if response.streaming:  # type: ignore[union-attr]
            return
        content = response.content.decode(response.charset)
        if strings.ZWC_BOUNDARY not in content:
            return
        content = _ZWC_RE.sub("", content)
        content = content.replace(strings.ZWC_BOUNDARY, "")  # strip position-0 start flags
        content = content.replace(strings.WJ, "")  # strip position-1 start flags
        response.content = content.encode(response.charset)
        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)

    @staticmethod
    def _build_string_table() -> StringTable:
        """Serialize the per-request string registry into a client-side string table."""
        registry = strings.get_string_registry()
        table: StringTable = {}
        for i, key in enumerate(registry):
            entry: StringTableEntry = {"m": key.msgid, "c": key.context}
            if key.msgid_plural:
                entry["p"] = key.msgid_plural
            table[i] = entry
        return table

    def _build_string_table_tag(self) -> str:
        """Build a ``<template data-lt-strings="...">`` tag for the current request's strings.

        Returns an empty string when no translations were registered.
        """
        table = self._build_string_table()
        if not table:
            return ""
        return f'<template {_ATTR_STRINGS}="{_json_attr(table)}"></template>'

    def _inject_assets(
        self,
        request: django.http.HttpRequest,
        response: django.http.HttpResponse,
        *,
        preview_entries: OverrideMap | None = None,
        editable_languages: set[LanguageCode] | None = None,
    ) -> None:
        content = response.content.decode(response.charset)

        body_close_idx = content.rfind("</body>")
        if body_close_idx == -1:
            # Partial HTML response (no </body>) — inject only the string table
            # so client-side JS can resolve ZWC markers after dynamic content swaps.
            tag = self._build_string_table_tag()
            if tag:
                response.content = (content + tag).encode(response.charset)
                if "Content-Length" in response:
                    response["Content-Length"] = len(response.content)
            return

        settings = conf.get_settings()
        current_language = django.utils.translation.get_language() or ""
        csrf_token = django.middleware.csrf.get_token(request)

        config: ClientConfig = {
            "apiBase": conf.API_PREFIX,
            "languages": list(settings.languages),
            "draftLanguages": list(settings.draft_languages),
            "currentLanguage": current_language,
            "csrfToken": csrf_token,
            "activeByDefault": settings.translation_active_by_default,
            "shortcutEdit": settings.shortcut_edit,
            "shortcutPreview": settings.shortcut_preview,
            "nplurals": conf.get_nplurals(),
            "pluralHints": {
                lang: [list(h) for h in lang_hints] for lang, lang_hints in plurals.get_plural_hints().items()
            },
        }

        if editable_languages is not None and editable_languages != set(settings.languages):
            config["editableLanguages"] = [lang for lang in settings.languages if lang in editable_languages]

        if preview_entries is not None:
            config["preview"] = True
            preview_items: list[PreviewItem] = []
            for key in preview_entries:
                item = PreviewItem(m=key.msgid, c=key.context)
                if key.msgid_plural:
                    item["p"] = key.msgid_plural
                preview_items.append(item)
            config["previewEntries"] = preview_items

        # Build single <template> with config and (optionally) strings
        template_attrs = f'{_ATTR_CONFIG}="{_json_attr(config)}"'
        table = self._build_string_table()
        if table:
            template_attrs += f' {_ATTR_STRINGS}="{_json_attr(table)}"'

        css_url = django.templatetags.static.static("live_translations/widget.css")
        js_url = django.templatetags.static.static("live_translations/widget.js")
        snippet = (
            f'<link rel="stylesheet" href="{css_url}">'
            f"<template {template_attrs}></template>"
            f'<script src="{js_url}"></script>'
        )

        response.content = (content[:body_close_idx] + snippet + content[body_close_idx:]).encode(response.charset)

        if "Content-Length" in response:
            response["Content-Length"] = len(response.content)
