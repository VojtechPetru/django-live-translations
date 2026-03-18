"""API views — thin HTTP adapters that delegate to services."""

import functools
import json
import logging
import typing as t

import django.http
import django.views.decorators.csrf
import django.views.decorators.http

from live_translations import conf, services
from live_translations.types import LanguageCode, MsgKey

__all__ = [
    "bulk_activate",
    "delete_translation",
    "get_history",
    "get_translations",
    "require_translation_permission",
    "save_translations",
]

logger = logging.getLogger(__name__)


def require_translation_permission[F: t.Callable[..., django.http.JsonResponse]](view: F) -> F:
    """Decorator that returns 403 if the user lacks the configured translation permission."""

    @functools.wraps(view)
    def wrapper(request: django.http.HttpRequest, *args: object, **kwargs: object) -> django.http.JsonResponse:
        checker = conf.get_permission_checker()
        if not checker(request):
            return django.http.JsonResponse({"error": "Forbidden"}, status=403)
        return view(request, *args, **kwargs)

    return t.cast("F", wrapper)


@require_translation_permission
@django.views.decorators.http.require_GET
def get_translations(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """GET /__live-translations__/translations/?msgid=hero-title&context="""
    key = MsgKey(
        msgid=request.GET.get("msgid", ""),
        context=request.GET.get("context", ""),
    )

    try:
        result = services.get_translations(key=key)
    except ValueError as e:
        return django.http.JsonResponse({"error": str(e)}, status=400)
    except Exception:
        logger.exception("Failed to fetch translations for msgid='%s'", key.msgid)
        return django.http.JsonResponse({"error": "Backend error"}, status=500)

    return django.http.JsonResponse(result)


@require_translation_permission
@django.views.decorators.csrf.csrf_protect
@django.views.decorators.http.require_POST
def save_translations(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """POST /__live-translations__/translations/save/"""
    try:
        body: dict[str, t.Any] = json.loads(request.body)
    except json.JSONDecodeError:
        return django.http.JsonResponse({"error": "Invalid JSON"}, status=400)

    key = MsgKey(msgid=body.get("msgid", ""), context=body.get("context", ""))
    translations: dict[LanguageCode, str] = body.get("translations", {})
    active_flags: dict[LanguageCode, bool] = body.get("active_flags", {})
    page_language: LanguageCode = body.get("page_language", "")

    try:
        result = services.save_translations(
            key=key,
            translations=translations,
            active_flags=active_flags,
            page_language=page_language,
            is_preview=conf.is_preview_request(request),
        )
    except ValueError as e:
        return django.http.JsonResponse({"error": str(e)}, status=400)
    except services.PlaceholderValidationError as e:
        return django.http.JsonResponse({"error": "Placeholder mismatch", "details": e.details}, status=400)
    except FileNotFoundError as e:
        return django.http.JsonResponse({"error": str(e)}, status=404)
    except Exception:
        logger.exception("Failed to save translations for msgid='%s'", key.msgid)
        return django.http.JsonResponse({"error": "Backend error"}, status=500)

    return django.http.JsonResponse(result)


@require_translation_permission
@django.views.decorators.http.require_GET
def get_history(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """GET /__live-translations__/translations/history/?msgid=hero-title&context=&limit=50"""
    msgid = request.GET.get("msgid", "")
    if not msgid:
        return django.http.JsonResponse({"error": "msgid is required"}, status=400)

    key = MsgKey(msgid=msgid, context=request.GET.get("context", ""))

    try:
        limit = min(int(request.GET.get("limit", "50")), 200)
    except (ValueError, TypeError):
        limit = 50

    return django.http.JsonResponse(services.get_history(key=key, limit=limit))


@require_translation_permission
@django.views.decorators.csrf.csrf_protect
@django.views.decorators.http.require_POST
def delete_translation(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """POST /__live-translations__/translations/delete/"""
    try:
        body: dict[str, t.Any] = json.loads(request.body)
    except json.JSONDecodeError:
        return django.http.JsonResponse({"error": "Invalid JSON"}, status=400)

    key = MsgKey(msgid=body.get("msgid", ""), context=body.get("context", ""))
    languages_param: list[LanguageCode] = body.get("languages", [])
    language: LanguageCode = body.get("language", "")
    page_language: LanguageCode = body.get("page_language", "")

    if not key.msgid:
        return django.http.JsonResponse({"error": "msgid is required"}, status=400)

    # Normalize language/languages into a single list
    resolved_languages: list[LanguageCode] | None = None
    if languages_param:
        resolved_languages = languages_param
    elif language:
        resolved_languages = [language]

    result = services.delete_translations(
        key=key,
        languages=resolved_languages,
        page_language=page_language,
        is_preview=conf.is_preview_request(request),
    )
    return django.http.JsonResponse(result)


@require_translation_permission
@django.views.decorators.csrf.csrf_protect
@django.views.decorators.http.require_POST
def bulk_activate(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """POST /__live-translations__/translations/bulk-activate/"""
    try:
        body: dict[str, t.Any] = json.loads(request.body)
    except json.JSONDecodeError:
        return django.http.JsonResponse({"error": "Invalid JSON"}, status=400)

    language: LanguageCode = body.get("language", "")
    if not language or not isinstance(language, str):
        return django.http.JsonResponse({"error": "language is required"}, status=400)

    msgid_list: list[dict[str, str]] = body.get("msgids", [])
    if not msgid_list:
        return django.http.JsonResponse({"error": "msgids list is required"}, status=400)

    for item in msgid_list:
        if not isinstance(item, dict) or "msgid" not in item:
            return django.http.JsonResponse({"error": "Each item must have a 'msgid' key"}, status=400)

    keys = [MsgKey(msgid=item["msgid"], context=item.get("context", "")) for item in msgid_list]
    result = services.bulk_activate(language=language, keys=keys)
    return django.http.JsonResponse(result)
