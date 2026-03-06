"""Database backend — reads/writes translations from Django's database.

Stores translation overrides in a DB table. Falls back to .po file values
for translations that haven't been overridden. Caches all overrides per
language for fast gettext lookups.
"""

import logging
import typing as t

from django.core.cache import cache
from django.utils.translation import trans_real

from .base import TranslationBackend, TranslationEntry

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = "lt:overrides"
CACHE_TIMEOUT = 60 * 60  # 1 hour — invalidated explicitly on save


def _cache_key(language: str) -> str:
    return f"{CACHE_KEY_PREFIX}:{language}"


class DatabaseBackend(TranslationBackend):
    """Backend that stores overrides in the database, falls back to .po files.

    Translation resolution order:
    1. Database override (cached)
    2. .po file value (via polib, read-only)
    """

    def _get_po_backend(self) -> t.Any:
        """Lazy-import and cache POFileBackend for .po file access."""
        if not hasattr(self, "_po_backend"):
            from .po import POFileBackend

            self._po_backend = POFileBackend(locale_dir=self.locale_dir, domain=self.domain)
        return self._po_backend

    def get_cached_overrides(self, language: str) -> dict[str, str]:
        """Get all DB overrides for a language as {(msgid, context): msgstr}.

        The cache key format is: "msgid\\x00context" -> msgstr.
        Using null byte as separator since it can't appear in msgid/context.
        """
        key = _cache_key(language)
        cached: dict[str, str] | None = cache.get(key)
        if cached is not None:
            return cached

        from ..models import TranslationEntry as DBEntry

        overrides: dict[str, str] = {}
        for entry in DBEntry.objects.for_language(language).values_list("msgid", "context", "msgstr"):
            cache_entry_key = f"{entry[0]}\x00{entry[1]}"
            overrides[cache_entry_key] = entry[2]
        cache.set(key, overrides, CACHE_TIMEOUT)
        return overrides

    @t.override
    def lookup_override(self, language: str, msgid: str, context: str = "") -> str | None:
        """Look up a single override from the cache. Returns None if not overridden."""
        overrides = self.get_cached_overrides(language)
        key = f"{msgid}\x00{context}"
        return overrides.get(key)

    @t.override
    def invalidate_cache(self, languages: list[str] | None = None) -> None:
        """Clear cached overrides. If languages is None, clear all configured languages."""
        if languages is None:
            from ..conf import get_conf

            languages = get_conf().languages

        keys = [_cache_key(lang) for lang in languages]
        cache.delete_many(keys)

    @t.override
    def get_translations(
        self,
        msgid: str,
        languages: list[str],
        context: str = "",
    ) -> dict[str, TranslationEntry]:
        """Fetch translations for a msgid, merging DB overrides with .po defaults."""
        po_backend = self._get_po_backend()
        po_entries = po_backend.get_translations(msgid=msgid, languages=languages, context=context)

        result: dict[str, TranslationEntry] = {}
        for lang in languages:
            po_entry = po_entries.get(lang)
            po_msgstr = po_entry.msgstr if po_entry else ""
            po_fuzzy = po_entry.fuzzy if po_entry else False

            db_override = self.lookup_override(lang, msgid, context)

            result[lang] = TranslationEntry(
                language=lang,
                msgid=msgid,
                msgstr=db_override if db_override is not None else po_msgstr,
                context=context,
                fuzzy=po_fuzzy if db_override is None else False,
            )

        return result

    @t.override
    def get_defaults(self, msgid: str, languages: list[str], context: str = "") -> dict[str, str]:
        """Get .po file translations (read-only) for display as defaults."""
        po_backend = self._get_po_backend()
        po_entries = po_backend.get_translations(msgid=msgid, languages=languages, context=context)
        return {lang: entry.msgstr for lang, entry in po_entries.items()}

    @t.override
    def get_hint(self, msgid: str, context: str = "") -> str:
        """Delegate to POFileBackend for translator comments."""
        return self._get_po_backend().get_hint(msgid, context)

    @t.override
    def save_translations(
        self,
        msgid: str,
        translations: dict[str, str],
        context: str = "",
    ) -> None:
        """Save translation overrides to the database.

        If the submitted value matches the .po file default, any existing
        DB override is deleted instead of created/updated — no point storing
        a redundant record.
        """
        from ..models import TranslationEntry as DBEntry

        po_defaults = self.get_defaults(msgid, list(translations.keys()), context)
        languages_changed: list[str] = []

        for lang, msgstr in translations.items():
            if msgstr == po_defaults.get(lang, ""):
                # Matches .po default — remove any existing override
                DBEntry.objects.for_msgid(msgid, context).for_language(lang).delete()
            else:
                DBEntry.objects.update_or_create(
                    language=lang,
                    msgid=msgid,
                    context=context,
                    defaults={"msgstr": msgstr},
                )
            languages_changed.append(lang)

        self.invalidate_cache(languages_changed)
        self.reload()

    @t.override
    def reload(self) -> None:
        """Flush Django's in-memory gettext catalogs."""
        if hasattr(trans_real, "_translations"):
            trans_real._translations = {}  # type: ignore[attr-defined]
        else:
            logger.warning("trans_real._translations not found — translations may not reload until server restart")
