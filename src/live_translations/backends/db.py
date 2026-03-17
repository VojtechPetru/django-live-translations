"""Database backend — reads/writes translations from Django's database.

Stores translation overrides in a DB table. Falls back to .po file values
for translations that haven't been overridden. Uses catalog injection to
make overrides visible to Django's gettext machinery.
"""

import logging
import pathlib
import typing as t
import uuid

import django.conf
import django.core.cache
import django.core.checks
import django.db.utils
import django.utils.translation
import django.utils.translation.reloader
import django.utils.translation.trans_real

from live_translations import conf, history, models
from live_translations.backends import base, po
from live_translations.types import DbOverride, LanguageCode, MsgKey, OverrideMap

__all__ = ["CATALOG_VERSION_KEY", "CATALOG_VERSION_TIMEOUT", "DatabaseBackend"]

logger = logging.getLogger(__name__)

_UNSET: object = object()
_DUMMY_MO = pathlib.Path("_.mo")

CATALOG_VERSION_KEY = "lt:catalog_version"
CATALOG_VERSION_TIMEOUT = 60 * 60 * 24 * 30  # 30 days


class DatabaseBackend(base.TranslationBackend):
    """Backend that stores overrides in the database, falls back to .po files.

    Translation resolution order:
    1. Database override (injected into Django's translation catalog)
    2. .po file value (via standard gettext catalog)
    """

    def __init__(
        self,
        locale_dir: pathlib.Path,
        domain: str,
        cache_alias: str = "default",
    ) -> None:
        super().__init__(locale_dir, domain, cache_alias)
        self._local_version: object = _UNSET  # sentinel, always mismatches initially

    @t.override
    def check(self) -> list[django.core.checks.CheckMessage]:
        errors: list[django.core.checks.CheckMessage] = []

        cache_conf = django.conf.settings.CACHES.get(self.cache_alias)
        if cache_conf is None:
            errors.append(
                django.core.checks.Warning(
                    f"Cache alias '{self.cache_alias}' is not defined in CACHES.",
                    hint=(
                        "The database translation backend requires a cache alias "
                        "defined in Django's CACHES setting. Add an entry for "
                        f"'{self.cache_alias}' or change LIVE_TRANSLATIONS['CACHE']."
                    ),
                    id="live_translations.W002",
                )
            )
        elif cache_conf.get("BACKEND") == "django.core.cache.backends.dummy.DummyCache":
            errors.append(
                django.core.checks.Warning(
                    f"Cache alias '{self.cache_alias}' uses DummyCache.",
                    hint=(
                        "The database translation backend uses Django's cache framework "
                        "to synchronise translation overrides across processes. "
                        "DummyCache discards all writes, so changes saved in the admin "
                        "will not propagate. Use a real cache backend such as Redis, "
                        "Memcached, or LocMemCache (single-process only)."
                    ),
                    id="live_translations.W003",
                )
            )

        return errors

    def _get_po_backend(self) -> po.POFileBackend:
        """Lazy-import and cache POFileBackend for .po file access."""
        if not hasattr(self, "_po_backend"):
            self._po_backend = po.POFileBackend(
                locale_dir=self.locale_dir,
                domain=self.domain,
                cache_alias=self.cache_alias,
            )
        return self._po_backend

    @t.override
    def ensure_current(self) -> None:
        """Check the shared version counter; clear and re-inject if stale."""
        remote = django.core.cache.caches[self.cache_alias].get(CATALOG_VERSION_KEY)
        if remote == self._local_version:
            return
        # Save the active language before clearing — translation_file_changed()
        # replaces trans_real._active with a fresh Local(), wiping the language
        # that LocaleMiddleware already activated for this request.
        current_lang = django.utils.translation.get_language()
        django.utils.translation.reloader.translation_file_changed(sender=None, file_path=_DUMMY_MO)
        self.inject_overrides()
        self._local_version = remote
        # Re-activate the language so this request proceeds in the correct locale.
        if current_lang:
            django.utils.translation.activate(current_lang)

    @t.override
    def bump_catalog_version(self) -> None:
        """Set a new version in shared cache, signaling all processes."""
        django.core.cache.caches[self.cache_alias].set(CATALOG_VERSION_KEY, uuid.uuid4().hex, CATALOG_VERSION_TIMEOUT)

    @t.override
    def bulk_activate(
        self,
        language: LanguageCode,
        msgids: list[MsgKey],
    ) -> list[MsgKey]:
        import django.db.models

        q = django.db.models.Q()
        for key in msgids:
            q |= django.db.models.Q(msgid=key.msgid, context=key.context)

        qs = models.TranslationEntry.objects.qs.for_languages([language]).active(active=False).filter(q)

        activated = [MsgKey(msgid, ctx) for msgid, ctx in qs.values_list("msgid", "context")]
        qs.update(is_active=True)

        if activated:
            self.bump_catalog_version()

        return activated

    @t.override
    def get_inactive_overrides(self, language: LanguageCode) -> OverrideMap:
        overrides: OverrideMap = {}
        try:
            for msgid, ctx, msgstr in (
                models.TranslationEntry.objects.qs.for_languages([language])
                .active(active=False)
                .exclude(msgstr="")
                .values_list("msgid", "context", "msgstr")
            ):
                overrides[MsgKey(msgid, ctx)] = msgstr
        except (django.db.utils.OperationalError, django.db.utils.ProgrammingError):
            pass
        return overrides

    @t.override
    def inject_overrides(self) -> None:
        """Query all DB overrides and inject into Django's translation catalogs."""
        try:
            rows = models.TranslationEntry.objects.qs.active().values_list("language", "msgid", "context", "msgstr")
        except (django.db.utils.OperationalError, django.db.utils.ProgrammingError):
            # Table doesn't exist yet (before migrations).
            return

        by_lang: dict[str, list[tuple[str, str, str]]] = {}
        for language, msgid, context, msgstr in rows:
            by_lang.setdefault(language, []).append((msgid, context, msgstr))

        for lang, entries in by_lang.items():
            try:
                trans_obj: django.utils.translation.trans_real.DjangoTranslation = (
                    django.utils.translation.trans_real.translation(lang)
                )
            except Exception:  # noqa: BLE001, S112
                continue
            catalog: django.utils.translation.trans_real.TranslationCatalog | None = trans_obj._catalog  # type: ignore[assignment]
            if catalog is None:
                continue
            for msgid, context, msgstr in entries:
                key = f"{context}\x04{msgid}" if context else msgid
                catalog[key] = msgstr

    @t.override
    def get_translations(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, base.TranslationEntry]:
        """Fetch translations for a msgid, merging DB overrides with .po defaults."""
        po_backend = self._get_po_backend()
        po_entries = po_backend.get_translations(key, languages)

        # Query DB overrides for this specific msgid
        db_overrides: dict[LanguageCode, DbOverride] = {}
        try:
            for row in (
                models.TranslationEntry.objects.qs.for_key(key)
                .for_languages(languages)
                .values_list("language", "msgstr", "is_active")
            ):
                db_overrides[row[0]] = DbOverride(row[1], row[2])
        except (django.db.utils.OperationalError, django.db.utils.ProgrammingError):
            pass

        result: dict[LanguageCode, base.TranslationEntry] = {}
        for lang in languages:
            po_entry = po_entries.get(lang)
            po_msgstr = po_entry.msgstr if po_entry else ""
            po_fuzzy = po_entry.fuzzy if po_entry else False

            db_entry = db_overrides.get(lang)

            result[lang] = base.TranslationEntry(
                language=lang,
                msgid=key.msgid,
                msgstr=db_entry.msgstr if db_entry is not None else po_msgstr,
                context=key.context,
                fuzzy=po_fuzzy if db_entry is None else False,
                is_active=db_entry.is_active if db_entry is not None else True,
                has_override=db_entry is not None,
            )

        return result

    @t.override
    def get_defaults(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, str]:
        """Get .po file translations (read-only) for display as defaults."""
        po_backend = self._get_po_backend()
        po_entries = po_backend.get_translations(key, languages)
        return {lang: entry.msgstr for lang, entry in po_entries.items()}

    @t.override
    def save_translations(
        self,
        key: MsgKey,
        translations: dict[LanguageCode, str],
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        """Save translation overrides to the database."""
        fallback_active = conf.get_settings().translation_active_by_default
        po_defaults = self.get_defaults(key, list(translations.keys()))

        # Snapshot existing DB values (text + active state) for history tracking
        existing: dict[LanguageCode, DbOverride] = {}
        for row in (
            models.TranslationEntry.objects.qs.for_key(key)
            .filter(language__in=translations.keys())
            .values_list("language", "msgstr", "is_active")
        ):
            row: tuple[LanguageCode, str, bool]
            existing[row[0]] = DbOverride(row[1], row[2])

        old_text_values: dict[LanguageCode, str] = {}
        old_active_states: dict[LanguageCode, bool] = {}
        new_active_states: dict[LanguageCode, bool] = {}
        for lang, msgstr in translations.items():
            old_entry = existing.get(lang)
            is_active = active_flags.get(lang, fallback_active) if active_flags else fallback_active

            # Skip creating a new DB row when nothing changed from the .po default.
            # This prevents phantom entries for languages the caller didn't intend to edit.
            if old_entry is None and msgstr == po_defaults.get(lang, "") and is_active == fallback_active:
                continue

            old_text_values[lang] = old_entry.msgstr if old_entry else ""
            new_active_states[lang] = is_active
            if old_entry is not None:
                old_active_states[lang] = old_entry.is_active

            models.TranslationEntry.objects.update_or_create(
                language=lang,
                msgid=key.msgid,
                context=key.context,
                defaults={"msgstr": msgstr, "is_active": is_active},
            )

        history.record_text_changes(
            key=key,
            old_entries=old_text_values,
            new_entries=translations,
            defaults=po_defaults,
        )
        history.record_active_changes(
            key=key,
            old_states=old_active_states,
            new_states=new_active_states,
        )
        self.bump_catalog_version()
