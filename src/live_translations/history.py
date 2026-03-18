"""Utilities for recording translation edit history and computing diffs."""

import contextlib
import difflib
import re
import typing as t

import django.db

from live_translations import models, strings
from live_translations.types import DiffSegment, LanguageCode, MsgKey

# Raised when the history table doesn't exist (migrations not applied).
# OperationalError on SQLite, ProgrammingError on PostgreSQL.
_MISSING_TABLE_ERRORS = (django.db.OperationalError, django.db.ProgrammingError)

if t.TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

__all__ = [
    "compute_diff",
    "get_user",
    "record_active_changes",
    "record_bulk_action",
    "record_change",
    "record_text_changes",
]


def get_user() -> "AbstractBaseUser | None":
    """Read the current user from the contextvar, returning None for anonymous."""
    user = strings.lt_current_user.get(None)
    if user is not None and not getattr(user, "is_authenticated", False):
        return None
    return user


def record_change(
    *,
    language: LanguageCode,
    key: MsgKey,
    action: models.TranslationHistory.Action,
    old_value: str = "",
    new_value: str = "",
) -> models.TranslationHistory | None:
    """Create a single TranslationHistory entry, reading user from contextvar.

    Returns None if the history table doesn't exist (migrations not applied).
    """
    with contextlib.suppress(*_MISSING_TABLE_ERRORS):
        return models.TranslationHistory.objects.create(
            language=language,
            msgid=key.msgid,
            context=key.context,
            action=action,
            old_value=old_value,
            new_value=new_value,
            user=get_user(),
        )
    return None


def record_text_changes(
    *,
    key: MsgKey,
    old_entries: dict[LanguageCode, str],
    new_entries: dict[LanguageCode, str],
    defaults: dict[LanguageCode, str] | None = None,
) -> None:
    """Record CREATE/UPDATE history for each language where the text changed.

    Args:
        old_entries: lang -> previous msgstr ("" means new/create).
        new_entries: lang -> new msgstr being saved.
        defaults: fallback old_value for CREATE actions (e.g. PO defaults).
    """
    for lang, new_msgstr in new_entries.items():
        old_msgstr = old_entries.get(lang, "")
        if not old_msgstr:
            record_change(
                language=lang,
                key=key,
                action=models.TranslationHistory.Action.CREATE,
                old_value=(defaults or {}).get(lang, ""),
                new_value=new_msgstr,
            )
        elif old_msgstr != new_msgstr:
            record_change(
                language=lang,
                key=key,
                action=models.TranslationHistory.Action.UPDATE,
                old_value=old_msgstr,
                new_value=new_msgstr,
            )


def record_active_changes(
    *,
    key: MsgKey,
    old_states: dict[LanguageCode, bool],
    new_states: dict[LanguageCode, bool],
) -> None:
    """Record ACTIVATE/DEACTIVATE history for each language where the active state changed.

    Only records changes for pre-existing entries (languages present in old_states).
    """
    for lang, new_active in new_states.items():
        old_active = old_states.get(lang)
        if old_active is not None and old_active != new_active:
            record_change(
                language=lang,
                key=key,
                action=(
                    models.TranslationHistory.Action.ACTIVATE
                    if new_active
                    else models.TranslationHistory.Action.DEACTIVATE
                ),
                old_value="active" if old_active else "inactive",
                new_value="active" if new_active else "inactive",
            )


def record_bulk_action(
    *,
    entries: list[tuple[LanguageCode, MsgKey]],
    action: models.TranslationHistory.Action,
    old_value: str,
    new_value: str,
) -> None:
    """Bulk-create history entries for admin actions (activate/deactivate/delete).

    ``entries`` is a list of (language, key) tuples, materialized
    before the bulk update so the queryset is not re-evaluated.
    """
    if not entries:
        return
    user = get_user()
    with contextlib.suppress(*_MISSING_TABLE_ERRORS):
        models.TranslationHistory.objects.bulk_create(
            [
                models.TranslationHistory(
                    language=lang,
                    msgid=key.msgid,
                    context=key.context,
                    action=action,
                    old_value=old_value,
                    new_value=new_value,
                    user=user,
                )
                for lang, key in entries
            ]
        )


_WORD_RE = re.compile(r"\S+|\s+")


def compute_diff(old_text: str, new_text: str) -> list[DiffSegment]:
    """Compute a word-level inline diff between two strings.

    Returns a list of segments suitable for JSON serialization:
    ``[{"type": "equal"|"insert"|"delete", "text": "..."}]``
    """
    if not old_text and not new_text:
        return []
    if not old_text:
        return [{"type": "insert", "text": new_text}]
    if not new_text:
        return [{"type": "delete", "text": old_text}]

    old_words = _WORD_RE.findall(old_text)
    new_words = _WORD_RE.findall(new_text)

    sm = difflib.SequenceMatcher(None, old_words, new_words)
    segments: list[DiffSegment] = []

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            segments.append({"type": "equal", "text": "".join(old_words[i1:i2])})
        elif op == "delete":
            segments.append({"type": "delete", "text": "".join(old_words[i1:i2])})
        elif op == "insert":
            segments.append({"type": "insert", "text": "".join(new_words[j1:j2])})
        elif op == "replace":
            segments.append({"type": "delete", "text": "".join(old_words[i1:i2])})
            segments.append({"type": "insert", "text": "".join(new_words[j1:j2])})

    return segments
