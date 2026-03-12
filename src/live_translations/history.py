"""Utilities for recording translation edit history and computing diffs."""

import difflib
import re

import django.db.models

from live_translations import models, strings


def _get_user() -> django.db.models.Model | None:
    """Read the current user from the contextvar, returning None for anonymous."""
    user = strings.lt_current_user.get(None)
    if user is not None and not getattr(user, "is_authenticated", False):
        return None
    return user


def record_change(
    *,
    language: str,
    msgid: str,
    context: str,
    action: str,
    old_value: str = "",
    new_value: str = "",
) -> models.TranslationHistory:
    """Create a single TranslationHistory entry, reading user from contextvar."""
    return models.TranslationHistory.objects.create(
        language=language,
        msgid=msgid,
        context=context,
        action=action,
        old_value=old_value,
        new_value=new_value,
        user=_get_user(),
    )


def record_bulk_action(
    *,
    entries: list[tuple[str, str, str]],
    action: str,
    old_value: str,
    new_value: str,
) -> None:
    """Bulk-create history entries for admin actions (activate/deactivate/delete).

    ``entries`` is a list of (language, msgid, context) tuples, materialized
    before the bulk update so the queryset is not re-evaluated.
    """
    if not entries:
        return
    user = _get_user()
    models.TranslationHistory.objects.bulk_create(
        [
            models.TranslationHistory(
                language=lang,
                msgid=mid,
                context=ctx,
                action=action,
                old_value=old_value,
                new_value=new_value,
                user=user,
            )
            for lang, mid, ctx in entries
        ]
    )


_WORD_RE = re.compile(r"\S+|\s+")


def compute_diff(old_text: str, new_text: str) -> list[dict[str, str]]:
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
    segments: list[dict[str, str]] = []

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
