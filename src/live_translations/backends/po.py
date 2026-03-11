"""PO file backend — reads/writes .po files on disk using polib."""

import logging
import os
import typing as t
from pathlib import Path

import django.utils.translation.reloader
import polib

from live_translations.backends import base

logger = logging.getLogger(__name__)


class POFileBackend(base.TranslationBackend):
    """Default backend that reads/writes locale/*.po files."""

    def __init__(
        self,
        locale_dir: str,
        domain: str,
        cache_alias: str = "default",
    ) -> None:
        super().__init__(locale_dir, domain, cache_alias)
        # Mtime-based cache: {path: (mtime, POFile)}
        self._po_cache: dict[str, tuple[float, polib.POFile]] = {}

    def _po_path(self, language: str) -> str:
        return os.path.join(
            self.locale_dir, language, "LC_MESSAGES", f"{self.domain}.po"
        )

    def _mo_path(self, language: str) -> str:
        return os.path.join(
            self.locale_dir, language, "LC_MESSAGES", f"{self.domain}.mo"
        )

    def _load_po(self, language: str) -> polib.POFile:
        path = self._po_path(language)
        try:
            mtime = os.path.getmtime(path)
        except OSError as err:
            raise FileNotFoundError(f"PO file not found: {path}") from err

        cached = self._po_cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        po = polib.pofile(path)
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
        languages: list[str],
        context: str = "",
    ) -> dict[str, base.TranslationEntry]:
        result: dict[str, base.TranslationEntry] = {}
        for lang in languages:
            try:
                po = self._load_po(lang)
                entry = self._find_entry(po, msgid, context)
                result[lang] = base.TranslationEntry(
                    language=lang,
                    msgid=msgid,
                    msgstr=entry.msgstr if entry else "",
                    context=context,
                    fuzzy="fuzzy" in (entry.flags if entry else []),
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
    def save_translations(
        self,
        msgid: str,
        translations: dict[str, str],
        context: str = "",
        active_flags: dict[str, bool] | None = None,
    ) -> None:
        mo_path: str | None = None
        for lang, msgstr in translations.items():
            po = self._load_po(lang)
            entry = self._find_entry(po, msgid, context)
            if entry is None:
                entry = polib.POEntry(
                    msgid=msgid,
                    msgstr=msgstr,
                    msgctxt=context if context else None,
                )
                po.append(entry)
            else:
                entry.msgstr = msgstr
                if "fuzzy" in entry.flags:
                    entry.flags.remove("fuzzy")
            po.save()
            mo_path = self._mo_path(lang)
            po.save_as_mofile(mo_path)
            # Invalidate mtime cache — file was just written
            self._po_cache.pop(self._po_path(lang), None)

        if mo_path is not None:
            django.utils.translation.reloader.translation_file_changed(
                sender=None, file_path=Path(mo_path)
            )

    @t.override
    def get_hint(
        self,
        msgid: str,
        context: str = "",
    ) -> str:
        """Read the translator comment (#. line) from the first .po file that has the entry."""
        # Use configured languages (already known) instead of scanning the filesystem.
        from live_translations import conf

        for lang in conf.get_settings().languages:
            try:
                po = self._load_po(lang)
            except (FileNotFoundError, OSError):
                continue
            entry = self._find_entry(po, msgid, context)
            if entry and entry.comment:
                return entry.comment
        return ""
