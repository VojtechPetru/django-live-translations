"""API views for fetching and saving translations."""

import json
import logging
import typing as t

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from .conf import get_backend_instance, get_conf, get_permission_checker

logger = logging.getLogger(__name__)


def _check_permission(request: HttpRequest) -> JsonResponse | None:
    """Return a 403 JsonResponse if the user lacks permission, else None."""
    checker = get_permission_checker()
    if not checker(request):
        return JsonResponse({"error": "Forbidden"}, status=403)
    return None


@require_GET
def get_translations(request: HttpRequest) -> JsonResponse:
    """Fetch translations for a msgid across all configured languages.

    GET /__live-translations__/translations/?msgid=hero-title&context=
    """
    forbidden = _check_permission(request)
    if forbidden:
        return forbidden

    msgid = request.GET.get("msgid", "")
    context = request.GET.get("context", "")

    if not msgid:
        return JsonResponse({"error": "msgid is required"}, status=400)

    conf = get_conf()
    backend = get_backend_instance()

    try:
        entries = backend.get_translations(
            msgid=msgid,
            languages=conf.languages,
            context=context,
        )
    except Exception:
        logger.exception("Failed to fetch translations for msgid='%s'", msgid)
        return JsonResponse({"error": "Backend error"}, status=500)

    hint = backend.get_hint(msgid=msgid, context=context)

    return JsonResponse(
        {
            "msgid": msgid,
            "context": context,
            "translations": {lang: {"msgstr": entry.msgstr, "fuzzy": entry.fuzzy} for lang, entry in entries.items()},
            "defaults": backend.get_defaults(msgid=msgid, languages=conf.languages, context=context),
            "hint": hint,
        }
    )


@csrf_protect
@require_POST
def save_translations(request: HttpRequest) -> JsonResponse:
    """Save translations for a msgid.

    POST /__live-translations__/translations/save/
    Body: {"msgid": "...", "context": "", "translations": {"cs": "...", "en": "..."}}
    """
    forbidden = _check_permission(request)
    if forbidden:
        return forbidden

    try:
        body: dict[str, t.Any] = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    msgid: str = body.get("msgid", "")
    context: str = body.get("context", "")
    translations: dict[str, str] = body.get("translations", {})

    if not msgid:
        return JsonResponse({"error": "msgid is required"}, status=400)
    if not translations:
        return JsonResponse({"error": "translations dict is required"}, status=400)

    # Validate language codes
    conf = get_conf()
    allowed = set(conf.languages)
    invalid = set(translations.keys()) - allowed
    if invalid:
        return JsonResponse(
            {"error": f"Invalid language codes: {', '.join(sorted(invalid))}"},
            status=400,
        )

    backend = get_backend_instance()

    try:
        backend.save_translations(
            msgid=msgid,
            translations=translations,
            context=context,
        )
    except FileNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except Exception:
        logger.exception("Failed to save translations for msgid='%s'", msgid)
        return JsonResponse({"error": "Backend error"}, status=500)

    # Return the current language's translation for in-place update
    from django.utils.translation import get_language

    current_lang = get_language() or conf.languages[0]
    current_msgstr = translations.get(current_lang, "")

    return JsonResponse(
        {
            "ok": True,
            "current_language_msgstr": current_msgstr,
        }
    )
