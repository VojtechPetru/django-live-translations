"""API views for fetching and saving translations."""

import json
import logging
import re
import typing as t

import django.http
import django.views.decorators.csrf
import django.views.decorators.http

from live_translations import conf, history, models

logger = logging.getLogger(__name__)


_PLACEHOLDER_RE = re.compile(
    r"%(?:\([a-zA-Z_]\w*\))?[diouxXeEfFgGcrsab%]|\{[a-zA-Z_]\w*\}"
)


def _extract_placeholders(text: str) -> set[str]:
    """Extract printf-style %(name)s and {name} placeholders from text."""
    return set(_PLACEHOLDER_RE.findall(text))


def _validate_placeholders(
    msgid: str,
    translations: dict[str, str],
) -> dict[str, list[str]] | None:
    """Return per-language error details if any translation has mismatched placeholders, else None."""
    expected = _extract_placeholders(msgid)
    if not expected:
        return None

    errors: dict[str, list[str]] = {}
    for lang, msgstr in translations.items():
        if not msgstr:
            continue
        actual = _extract_placeholders(msgstr)
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            parts: list[str] = []
            if missing:
                parts.append(f"missing {', '.join(sorted(missing))}")
            if extra:
                parts.append(f"unexpected {', '.join(sorted(extra))}")
            errors[lang] = parts

    return errors or None


def _check_permission(
    request: django.http.HttpRequest,
) -> django.http.JsonResponse | None:
    """Return a 403 JsonResponse if the user lacks permission, else None."""
    checker = conf.get_permission_checker()
    if not checker(request):
        return django.http.JsonResponse({"error": "Forbidden"}, status=403)
    return None


@django.views.decorators.http.require_GET
def get_translations(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """Fetch translations for a msgid across all configured languages.

    GET /__live-translations__/translations/?msgid=hero-title&context=
    """
    forbidden = _check_permission(request)
    if forbidden:
        return forbidden

    msgid = request.GET.get("msgid", "")
    context = request.GET.get("context", "")

    if not msgid:
        return django.http.JsonResponse({"error": "msgid is required"}, status=400)

    settings = conf.get_settings()
    backend = conf.get_backend_instance()

    try:
        entries = backend.get_translations(
            msgid=msgid,
            languages=settings.languages,
            context=context,
        )
    except Exception:
        logger.exception("Failed to fetch translations for msgid='%s'", msgid)
        return django.http.JsonResponse({"error": "Backend error"}, status=500)

    hint = backend.get_hint(msgid=msgid, context=context)

    return django.http.JsonResponse(
        {
            "msgid": msgid,
            "context": context,
            "translations": {
                lang: {
                    "msgstr": entry.msgstr,
                    "fuzzy": entry.fuzzy,
                    "is_active": entry.is_active,
                }
                for lang, entry in entries.items()
            },
            "defaults": backend.get_defaults(
                msgid=msgid, languages=settings.languages, context=context
            ),
            "hint": hint,
        }
    )


@django.views.decorators.csrf.csrf_protect
@django.views.decorators.http.require_POST
def save_translations(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """Save translations for a msgid.

    POST /__live-translations__/translations/save/
    Body: {"msgid": "...", "context": "", "translations": {"cs": "...", "en": "..."}}
    """
    import django.utils.translation

    forbidden = _check_permission(request)
    if forbidden:
        return forbidden

    try:
        body: dict[str, t.Any] = json.loads(request.body)
    except json.JSONDecodeError:
        return django.http.JsonResponse({"error": "Invalid JSON"}, status=400)

    msgid: str = body.get("msgid", "")
    context: str = body.get("context", "")
    translations: dict[str, str] = body.get("translations", {})
    active_flags: dict[str, bool] = body.get("active_flags", {})

    if not msgid:
        return django.http.JsonResponse({"error": "msgid is required"}, status=400)
    if not translations:
        return django.http.JsonResponse(
            {"error": "translations dict is required"}, status=400
        )

    # Validate language codes
    settings = conf.get_settings()
    allowed = set(settings.languages)
    invalid = set(translations.keys()) - allowed
    if invalid:
        return django.http.JsonResponse(
            {"error": f"Invalid language codes: {', '.join(sorted(invalid))}"},
            status=400,
        )

    placeholder_errors = _validate_placeholders(msgid, translations)
    if placeholder_errors:
        return django.http.JsonResponse(
            {"error": "Placeholder mismatch", "details": placeholder_errors}, status=400
        )

    backend = conf.get_backend_instance()

    try:
        backend.save_translations(
            msgid=msgid,
            translations=translations,
            context=context,
            active_flags=active_flags,
        )
    except FileNotFoundError as e:
        return django.http.JsonResponse({"error": str(e)}, status=404)
    except Exception:
        logger.exception("Failed to save translations for msgid='%s'", msgid)
        return django.http.JsonResponse({"error": "Backend error"}, status=500)

    # Return the current language's translation for in-place update
    current_lang = django.utils.translation.get_language() or settings.languages[0]
    current_msgstr = translations.get(current_lang, "")

    return django.http.JsonResponse(
        {
            "ok": True,
            "current_language_msgstr": current_msgstr,
        }
    )


if t.TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser


def _format_user(user: "AbstractBaseUser | None") -> str:
    """Format a user object for display. Returns 'System' for None."""
    if user is None:
        return "System"
    name = getattr(user, "get_full_name", lambda: "")()
    if name:
        return name
    username_field = getattr(user, "USERNAME_FIELD", None)
    if not username_field:
        logger.warning("User does not have a USERNAME_FIELD attribute set.")
        return "Unknown"
    return str(getattr(user, username_field))


@django.views.decorators.http.require_GET
def get_history(request: django.http.HttpRequest) -> django.http.JsonResponse:
    """Fetch edit history for a msgid across all languages.

    GET /__live-translations__/translations/history/?msgid=hero-title&context=&limit=50
    """
    forbidden = _check_permission(request)
    if forbidden:
        return forbidden

    msgid = request.GET.get("msgid", "")
    context = request.GET.get("context", "")

    if not msgid:
        return django.http.JsonResponse({"error": "msgid is required"}, status=400)

    try:
        limit = min(int(request.GET.get("limit", "50")), 200)
    except (ValueError, TypeError):
        limit = 50

    entries = (
        models.TranslationHistory.objects.filter(msgid=msgid, context=context)
        .select_related("user")
        .order_by("-created_at")[:limit]
    )

    results = []
    for entry in entries:
        item: dict[str, t.Any] = {
            "id": entry.pk,
            "language": entry.language,
            "action": entry.action,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
            "user": _format_user(entry.user),
            "created_at": entry.created_at.isoformat(),
        }
        if entry.action not in (
            models.TranslationHistory.Action.ACTIVATE,
            models.TranslationHistory.Action.DEACTIVATE,
        ):
            item["diff"] = history.compute_diff(entry.old_value, entry.new_value)
        results.append(item)

    return django.http.JsonResponse({"history": results})
