"""PO file backend — reads/writes .po files on disk using polib."""

import logging
import os
import typing as t

import polib
from django.utils.translation import trans_real

from .base import TranslationBackend, TranslationEntry

logger = logging.getLogger(__name__)


class POFileBackend(TranslationBackend):
    """Default backend that reads/writes locale/*.po files."""

    def __init__(self, locale_dir: str, domain: str) -> None:
        super().__init__(locale_dir, domain)
        # Mtime-based cache: {path: (mtime, POFile)}
        self._po_cache: dict[str, tuple[float, polib.POFile]] = {}

    def _po_path(self, language: str) -> str:
        return os.path.join(self.locale_dir, language, "LC_MESSAGES", f"{self.domain}.po")

    def _mo_path(self, language: str) -> str:
        return os.path.join(self.locale_dir, language, "LC_MESSAGES", f"{self.domain}.mo")

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

    def _find_entry(self, po: polib.POFile, msgid: str, context: str) -> polib.POEntry | None:
        return po.find(msgid, msgctxt=context or False)

    @t.override
    def get_translations(
        self,
        msgid: str,
        languages: list[str],
        context: str = "",
    ) -> dict[str, TranslationEntry]:
        result: dict[str, TranslationEntry] = {}
        for lang in languages:
            try:
                po = self._load_po(lang)
                entry = self._find_entry(po, msgid, context)
                result[lang] = TranslationEntry(
                    language=lang,
                    msgid=msgid,
                    msgstr=entry.msgstr if entry else "",
                    context=context,
                    fuzzy="fuzzy" in (entry.flags if entry else []),
                )
            except FileNotFoundError:
                logger.warning("PO file not found for language '%s'", lang)
                result[lang] = TranslationEntry(
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
    ) -> None:
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
            po.save_as_mofile(self._mo_path(lang))
            # Invalidate mtime cache — file was just written
            self._po_cache.pop(self._po_path(lang), None)

        self.reload()

    @t.override
    def get_hint(self, msgid: str, context: str = "") -> str:
        """Read the translator comment (#. line) from the first .po file that has the entry."""
        # Use configured languages (already known) instead of scanning the filesystem.
        from ..conf import get_conf

        for lang in get_conf().languages:
            try:
                po = self._load_po(lang)
            except FileNotFoundError, OSError:
                continue
            entry = self._find_entry(po, msgid, context)
            if entry and entry.comment:
                return entry.comment
        return ""

    @t.override
    def reload(self) -> None:
        """Flush Django's in-memory gettext catalogs."""
        if hasattr(trans_real, "_translations"):
            trans_real._translations = {}  # type: ignore[attr-defined]
        else:
            logger.warning("trans_real._translations not found — translations may not reload until server restart")
