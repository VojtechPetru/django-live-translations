"""Service layer: all translation business logic lives here.

Views and admin are thin adapters that call these functions.
"""

import contextlib
import logging
import re
import typing as t

import django.db
import django.db.models
import django.db.transaction
import django.utils.translation

from live_translations import conf, history, models
from live_translations.types import (
    BulkActivateResult,
    DeleteResult,
    DisplayResult,
    HistoryItem,
    HistoryResult,
    LanguageCode,
    MsgKey,
    SaveResult,
    TranslationInfo,
    TranslationsResult,
)

if t.TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

__all__ = [
    "PlaceholderValidationError",
    "activate_entries",
    "bulk_activate",
    "compute_display",
    "deactivate_entries",
    "delete_entries",
    "delete_translations",
    "extract_placeholders",
    "format_user",
    "get_default",
    "get_history",
    "get_translations",
    "save_translations",
    "validate_placeholders",
]

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"%(?:\([a-zA-Z_]\w*\))?[diouxXeEfFgGcrsab%]|\{[a-zA-Z_]\w*\}")


class PlaceholderValidationError(Exception):
    def __init__(self, details: dict[LanguageCode, list[str]]) -> None:
        self.details = details


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def extract_placeholders(text: str) -> set[str]:
    """Extract printf-style %(name)s and {name} placeholders from text."""
    return set(_PLACEHOLDER_RE.findall(text))


def validate_placeholders(
    msgid: str,
    translations: dict[LanguageCode, str],
) -> dict[LanguageCode, list[str]] | None:
    """Return per-language error details if any translation has mismatched placeholders, else None."""
    expected = extract_placeholders(msgid)
    if not expected:
        return None

    errors: dict[LanguageCode, list[str]] = {}
    for lang, msgstr in translations.items():
        if not msgstr:
            continue
        actual = extract_placeholders(msgstr)
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


def format_user(user: "AbstractBaseUser | None") -> str:
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


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def get_translations(*, key: MsgKey) -> TranslationsResult:
    """Fetch translations for a msgid across all configured languages.

    Raises ValueError if msgid is empty.
    """
    if not key.msgid:
        raise ValueError("msgid is required")

    settings = conf.get_settings()
    backend = conf.get_backend_instance()

    entries = backend.get_translations(key, settings.languages)
    hint = backend.get_hint(key)

    return {
        "msgid": key.msgid,
        "context": key.context,
        "translations": {
            lang: TranslationInfo(
                msgstr=entry.msgstr,
                fuzzy=entry.fuzzy,
                is_active=entry.is_active,
                has_override=entry.has_override,
            )
            for lang, entry in entries.items()
        },
        "defaults": backend.get_defaults(key, settings.languages),
        "hint": hint,
    }


def save_translations(
    *,
    key: MsgKey,
    translations: dict[LanguageCode, str],
    active_flags: dict[LanguageCode, bool] | None = None,
    page_language: LanguageCode = "",
    is_preview: bool = False,
) -> SaveResult:
    """Validate and save translations, return JSON-ready dict.

    Raises ValueError, PlaceholderValidationError, FileNotFoundError.
    """
    if not key.msgid:
        raise ValueError("msgid is required")
    if not translations:
        raise ValueError("translations dict is required")

    settings = conf.get_settings()
    allowed = set(settings.languages)
    invalid = set(translations.keys()) - allowed
    if invalid:
        raise ValueError(f"Invalid language codes: {', '.join(sorted(invalid))}")

    placeholder_errors = validate_placeholders(key.msgid, translations)
    if placeholder_errors:
        raise PlaceholderValidationError(placeholder_errors)

    # Draft languages are always active — their translations go straight to
    # msgstr so they survive makemessages/msgmerge.  The whole language is
    # unpublished anyway, so "inactive" is meaningless.
    resolved_flags = dict(active_flags or {})
    draft_languages = settings.draft_languages
    for lang in translations:
        if lang in draft_languages:
            resolved_flags[lang] = True

    backend = conf.get_backend_instance()
    with django.db.transaction.atomic():
        backend.save_translations(
            key,
            translations=translations,
            active_flags=resolved_flags,
        )

    return {
        "ok": True,
        "display": compute_display(
            key=key,
            page_language=page_language,
            is_preview=is_preview,
        ),
    }


def delete_translations(
    *,
    key: MsgKey,
    languages: list[LanguageCode] | None = None,
    page_language: LanguageCode = "",
    is_preview: bool = False,
) -> DeleteResult:
    """Delete DB overrides for a msgid/context, return JSON-ready dict."""
    with django.db.transaction.atomic():
        qs = models.TranslationEntry.objects.qs.for_key(key)
        if languages:
            qs = qs.for_languages(languages)

        entries = list(qs.values_list("language", "msgstr"))
        deleted_count, _ = qs.delete()

        if deleted_count:
            for lang, old_value in entries:
                history.record_change(
                    language=lang,
                    key=key,
                    action=models.TranslationHistory.Action.DELETE,
                    old_value=old_value,
                    new_value="",
                )
            conf.get_backend_instance().bump_catalog_version()

    return {
        "ok": True,
        "deleted": deleted_count,
        "display": compute_display(
            key=key,
            page_language=page_language,
            is_preview=is_preview,
        ),
    }


@django.db.transaction.atomic
def delete_entries(*, queryset: django.db.models.QuerySet[models.TranslationEntry]) -> int:
    """Batch delete for admin's delete_queryset. Returns deleted count."""
    affected = list(queryset.values_list("language", "msgid", "context", "msgstr"))
    deleted_count, _ = queryset.delete()

    if deleted_count:
        # History table may not exist if migrations haven't been applied.
        with contextlib.suppress(django.db.OperationalError, django.db.ProgrammingError):
            user = history.get_user()
            models.TranslationHistory.objects.bulk_create(
                [
                    models.TranslationHistory(
                        language=lang,
                        msgid=mid,
                        context=ctx,
                        action=models.TranslationHistory.Action.DELETE,
                        old_value=msgstr,
                        new_value="",
                        user=user,
                    )
                    for lang, mid, ctx, msgstr in affected
                ]
            )
        conf.get_backend_instance().bump_catalog_version()

    return deleted_count


def get_history(*, key: MsgKey, limit: int = 50) -> HistoryResult:
    """Fetch edit history for a msgid, return JSON-ready dict."""
    # History table may not exist if migrations haven't been applied.
    entries: list[models.TranslationHistory] = []
    with contextlib.suppress(django.db.OperationalError, django.db.ProgrammingError):
        entries = list(
            models.TranslationHistory.objects.filter(msgid=key.msgid, context=key.context)
            .select_related("user")
            .order_by("-created_at")[:limit]
        )

    results: list[HistoryItem] = []
    for entry in entries:
        item: HistoryItem = {
            "id": entry.pk,
            "language": entry.language,
            "action": entry.action,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
            "user": format_user(entry.user),
            "created_at": entry.created_at.isoformat(),
        }
        if entry.action not in (
            models.TranslationHistory.Action.ACTIVATE,
            models.TranslationHistory.Action.DEACTIVATE,
        ):
            item["diff"] = history.compute_diff(entry.old_value, entry.new_value)
        results.append(item)

    return {"history": results}


@django.db.transaction.atomic
def bulk_activate(*, language: LanguageCode, keys: list[MsgKey]) -> BulkActivateResult:
    """Activate translations via backend, record history. Returns JSON-ready dict."""
    backend = conf.get_backend_instance()
    activated = backend.bulk_activate(language, keys)

    if activated:
        history.record_bulk_action(
            entries=[(language, key) for key in activated],
            action=models.TranslationHistory.Action.ACTIVATE,
            old_value="inactive",
            new_value="active",
        )

    return {"ok": True, "activated": len(activated)}


def activate_entries(*, queryset: django.db.models.QuerySet[models.TranslationEntry]) -> int:
    """Batch activate for admin action. Returns count of updated entries."""
    return _toggle_entries(queryset=queryset, activate=True)


def deactivate_entries(*, queryset: django.db.models.QuerySet[models.TranslationEntry]) -> int:
    """Batch deactivate for admin action. Returns count of updated entries."""
    return _toggle_entries(queryset=queryset, activate=False)


@django.db.transaction.atomic
def _toggle_entries(*, queryset: django.db.models.QuerySet[models.TranslationEntry], activate: bool) -> int:
    candidates = queryset.filter(is_active=not activate)
    affected = [(lang, MsgKey(mid, ctx)) for lang, mid, ctx in candidates.values_list("language", "msgid", "context")]
    updated = candidates.update(is_active=activate)
    if updated:
        history.record_bulk_action(
            entries=affected,
            action=models.TranslationHistory.Action.ACTIVATE
            if activate
            else models.TranslationHistory.Action.DEACTIVATE,
            old_value="inactive" if activate else "active",
            new_value="active" if activate else "inactive",
        )
        conf.get_backend_instance().bump_catalog_version()
    return updated


def compute_display(
    *,
    key: MsgKey,
    page_language: LanguageCode = "",
    is_preview: bool = False,
) -> DisplayResult:
    """Resolve visible text after mutation."""
    settings = conf.get_settings()
    current_lang: LanguageCode = page_language or django.utils.translation.get_language() or settings.languages[0]
    backend = conf.get_backend_instance()

    entries = backend.get_translations(key, [current_lang])
    entry = entries.get(current_lang)

    if entry and (entry.is_active or is_preview):
        display_text = entry.msgstr
    else:
        defaults = backend.get_defaults(key, [current_lang])
        display_text = defaults.get(current_lang, "")

    return {
        "text": display_text,
        "is_preview_entry": bool(is_preview and entry and not entry.is_active),
    }


def get_default(*, key: MsgKey, language: LanguageCode) -> str:
    """Get baseline default translation for a single language."""
    backend = conf.get_backend_instance()
    return backend.get_defaults(key, [language]).get(language, "")
