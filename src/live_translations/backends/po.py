"""PO file backend — reads/writes .po files on disk using polib."""

import base64
import logging
import typing as t
import pathlib

import django.utils.translation.reloader
import polib

from live_translations import conf, history
from live_translations.backends import base
from live_translations.types import LanguageCode, MsgKey, OverrideMap

__all__ = ["LT_PENDING_PREFIX", "POFileBackend"]

logger = logging.getLogger(__name__)

LT_PENDING_PREFIX = "ltpending:"


def _get_pending(entry: polib.POEntry) -> str | None:
    """Extract the pending msgstr from the translator comment, or None."""
    if not entry.comment:
        return None
    lines = entry.comment.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(LT_PENDING_PREFIX):
            # Collect this line + all continuation lines (polib may wrap long base64)
            raw = line[len(LT_PENDING_PREFIX) :]
            for cont in lines[i + 1 :]:
                raw += cont
            try:
                return base64.b64decode(raw).decode()
            except (ValueError, UnicodeDecodeError):
                return raw
    return None


def _set_pending(entry: polib.POEntry, value: str) -> None:
    """Store a pending msgstr as base64 in the translator comment.

    Uses ``ltpending:`` prefix (no hyphen) because polib wraps long comment
    lines via textwrap which breaks at hyphens. A hyphenated prefix like
    ``lt-pending:`` gets split into ``lt-`` / ``pending:`` on separate lines.
    Base64 encoding avoids spaces/hyphens in the value itself.
    """
    _clear_pending(entry)
    encoded = base64.b64encode(value.encode()).decode()
    pending_line = f"{LT_PENDING_PREFIX}{encoded}"
    entry.comment = (
        f"{entry.comment}\n{pending_line}" if entry.comment else pending_line
    )


def _clear_pending(entry: polib.POEntry) -> None:
    """Remove the pending msgstr (and any continuation lines) from the comment."""
    if not entry.comment:
        return
    lines = entry.comment.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(LT_PENDING_PREFIX):
            entry.comment = "\n".join(lines[:i]).strip()
            return


def _clean_comment(comment: str) -> str:
    """Return the comment with pending data stripped."""
    lines = comment.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(LT_PENDING_PREFIX):
            return "\n".join(lines[:i]).strip()
    return comment.strip()


class POFileBackend(base.TranslationBackend):
    """Default backend that reads/writes locale/*.po files."""

    def __init__(
        self,
        locale_dir: pathlib.Path,
        domain: str,
        cache_alias: str = "default",
    ) -> None:
        super().__init__(locale_dir, domain, cache_alias)
        # Mtime-based cache: {path: (mtime, POFile)}
        self._po_cache: dict[pathlib.Path, tuple[float, polib.POFile]] = {}

    def _po_path(self, language: str) -> pathlib.Path:
        return self.locale_dir / language / "LC_MESSAGES" / f"{self.domain}.po"

    def _mo_path(self, language: str) -> pathlib.Path:
        return self.locale_dir / language / "LC_MESSAGES" / f"{self.domain}.mo"

    def _load_po(self, language: str) -> polib.POFile:
        path = self._po_path(language)
        try:
            mtime = path.stat().st_mtime
        except OSError as err:
            raise FileNotFoundError(f"PO file not found: {path}") from err

        cached = self._po_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        po = polib.pofile(str(path))
        self._po_cache[path] = (mtime, po)
        return po

    def _find_entry(
        self,
        po: polib.POFile,
        msgid: str,
        context: str,
    ) -> polib.POEntry | None:
        return po.find(msgid, msgctxt=context or False)

    @t.override
    def get_translations(
        self,
        msgid: str,
        languages: list[LanguageCode],
        context: str = "",
    ) -> dict[LanguageCode, base.TranslationEntry]:
        result: dict[str, base.TranslationEntry] = {}
        for lang in languages:
            try:
                po = self._load_po(lang)
                entry = self._find_entry(po, msgid, context)
                if entry is None:
                    result[lang] = base.TranslationEntry(
                        language=lang,
                        msgid=msgid,
                        msgstr="",
                        context=context,
                    )
                    continue
                pending = _get_pending(entry)
                is_active = pending is None
                result[lang] = base.TranslationEntry(
                    language=lang,
                    msgid=msgid,
                    msgstr=pending if pending is not None else entry.msgstr,
                    context=context,
                    fuzzy="fuzzy" in entry.flags,
                    is_active=is_active,
                )
            except FileNotFoundError:
                logger.warning("PO file not found for language '%s'", lang)
                result[lang] = base.TranslationEntry(
                    language=lang,
                    msgid=msgid,
                    msgstr="",
                    context=context,
                )
        return result

    @t.override
    def get_inactive_overrides(self, language: LanguageCode) -> OverrideMap:
        overrides: OverrideMap = {}
        try:
            po = self._load_po(language)
        except FileNotFoundError:
            return overrides
        for entry in po:
            pending = _get_pending(entry)
            if pending:
                overrides[MsgKey(entry.msgid, entry.msgctxt or "")] = pending
        return overrides

    @t.override
    def save_translations(
        self,
        msgid: str,
        translations: dict[LanguageCode, str],
        context: str = "",
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        fallback_active = conf.get_settings().translation_active_by_default

        mo_path: pathlib.Path | None = None
        old_entries: dict[str, str] = {}
        old_active_states: dict[str, bool] = {}
        new_active_states: dict[str, bool] = {}
        for lang, msgstr in translations.items():
            po = self._load_po(lang)
            entry = self._find_entry(po, msgid, context)

            is_active = (
                active_flags.get(lang, fallback_active)
                if active_flags
                else fallback_active
            )
            new_active_states[lang] = is_active

            if entry is not None:
                pending = _get_pending(entry)
                old_entries[lang] = pending if pending is not None else entry.msgstr
                old_active_states[lang] = pending is None

            if entry is None:
                entry = polib.POEntry(
                    msgid=msgid,
                    msgstr="" if not is_active else msgstr,
                    msgctxt=context if context else None,
                )
                if not is_active:
                    _set_pending(entry, msgstr)
                po.append(entry)
            elif is_active:
                entry.msgstr = msgstr
                _clear_pending(entry)
                if "fuzzy" in entry.flags:
                    entry.flags.remove("fuzzy")
            else:
                # Inactive: keep current msgstr in .po/.mo, store new value as pending
                _set_pending(entry, msgstr)
                if "fuzzy" in entry.flags:
                    entry.flags.remove("fuzzy")

            po.save()
            mo_path = self._mo_path(lang)
            po.save_as_mofile(str(mo_path))
            # Invalidate mtime cache — file was just written
            self._po_cache.pop(self._po_path(lang), None)

        history.record_text_changes(
            msgid=msgid,
            context=context,
            old_entries=old_entries,
            new_entries=translations,
        )
        history.record_active_changes(
            msgid=msgid,
            context=context,
            old_states=old_active_states,
            new_states=new_active_states,
        )

        if mo_path is not None:
            django.utils.translation.reloader.translation_file_changed(
                sender=None, file_path=pathlib.Path(mo_path)
            )

    @t.override
    def get_hint(self, msgid: str, context: str = "") -> str:
        return _clean_comment(super().get_hint(msgid, context))
