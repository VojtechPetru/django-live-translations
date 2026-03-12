"""Database backend — reads/writes translations from Django's database.

Stores translation overrides in a DB table. Falls back to .po file values
for translations that haven't been overridden. Uses catalog injection to
make overrides visible to Django's gettext machinery.
"""

import logging
import typing as t
import uuid
from pathlib import Path

import django.core.cache
import django.db.utils
import django.utils.translation
import django.utils.translation.trans_real
import django.utils.translation.reloader

from live_translations.backends import base

if t.TYPE_CHECKING:
    import django.core.checks

    from live_translations.backends import po as _po_mod

logger = logging.getLogger(__name__)

_UNSET: object = object()
_DUMMY_MO = Path("_.mo")

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
        locale_dir: str,
        domain: str,
        cache_alias: str = "default",
    ) -> None:
        super().__init__(locale_dir, domain, cache_alias)
        self._local_version: object = _UNSET  # sentinel, always mismatches initially

    @t.override
    def check(self) -> "list[django.core.checks.CheckMessage]":
        import django.conf
        import django.core.checks

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

    def _get_po_backend(self) -> "_po_mod.POFileBackend":
        """Lazy-import and cache POFileBackend for .po file access."""
        if not hasattr(self, "_po_backend"):
            from live_translations.backends import po

            self._po_backend = po.POFileBackend(
                locale_dir=self.locale_dir,
                domain=self.domain,
                cache_alias=self.cache_alias,
            )
        return self._po_backend

    @t.override
    def ensure_current(self) -> None:
        """Check shared version counter; clear + re-inject if stale."""
        remote = django.core.cache.caches[self.cache_alias].get(CATALOG_VERSION_KEY)
        if remote == self._local_version:
            return
        # Save the active language before clearing — translation_file_changed()
        # replaces trans_real._active with a fresh Local(), wiping the language
        # that LocaleMiddleware already activated for this request.
        current_lang = django.utils.translation.get_language()
        django.utils.translation.reloader.translation_file_changed(
            sender=None, file_path=_DUMMY_MO
        )
        self.inject_overrides()
        self._local_version = remote
        # Re-activate the language so this request proceeds in the correct locale.
        if current_lang:
            django.utils.translation.activate(current_lang)

    @t.override
    def bump_catalog_version(self) -> None:
        """Set a new version in shared cache, signaling all processes."""
        django.core.cache.caches[self.cache_alias].set(
            CATALOG_VERSION_KEY, uuid.uuid4().hex, CATALOG_VERSION_TIMEOUT
        )

    @t.override
    def inject_overrides(self) -> None:
        """Query all DB overrides and inject into Django's translation catalogs."""
        from live_translations import models

        try:
            rows = models.TranslationEntry.objects.active().values_list(
                "language", "msgid", "context", "msgstr"
            )
        except (django.db.utils.OperationalError, django.db.utils.ProgrammingError):
            # Table doesn't exist yet (before migrations).
            return

        by_lang: dict[str, list[tuple[str, str, str]]] = {}
        for language, msgid, context, msgstr in rows:
            by_lang.setdefault(language, []).append((msgid, context, msgstr))

        for lang, entries in by_lang.items():
            try:
                trans_obj: "django.utils.translation.trans_real.DjangoTranslation" = (
                    django.utils.translation.trans_real.translation(lang)
                )
            except Exception:
                continue
            catalog: django.utils.translation.trans_real.TranslationCatalog | None = (
                trans_obj._catalog  # type: ignore[assignment]
            )
            if catalog is None:
                continue
            for msgid, context, msgstr in entries:
                key = f"{context}\x04{msgid}" if context else msgid
                catalog[key] = msgstr

    @t.override
    def get_translations(
        self,
        msgid: str,
        languages: list[str],
        context: str = "",
    ) -> dict[str, base.TranslationEntry]:
        """Fetch translations for a msgid, merging DB overrides with .po defaults."""
        from live_translations import models

        po_backend = self._get_po_backend()
        po_entries = po_backend.get_translations(
            msgid=msgid,
            languages=languages,
            context=context,
        )

        # Query DB overrides for this specific msgid
        db_overrides: dict[str, tuple[str, bool]] = {}
        try:
            for row in (
                models.TranslationEntry.objects.for_msgid(msgid, context)
                .filter(language__in=languages)
                .values_list("language", "msgstr", "is_active")
            ):
                db_overrides[row[0]] = (row[1], row[2])
        except (django.db.utils.OperationalError, django.db.utils.ProgrammingError):
            pass

        result: dict[str, base.TranslationEntry] = {}
        for lang in languages:
            po_entry = po_entries.get(lang)
            po_msgstr = po_entry.msgstr if po_entry else ""
            po_fuzzy = po_entry.fuzzy if po_entry else False

            db_entry = db_overrides.get(lang)

            result[lang] = base.TranslationEntry(
                language=lang,
                msgid=msgid,
                msgstr=db_entry[0] if db_entry is not None else po_msgstr,
                context=context,
                fuzzy=po_fuzzy if db_entry is None else False,
                is_active=db_entry[1] if db_entry is not None else True,
                has_override=db_entry is not None,
            )

        return result

    @t.override
    def get_defaults(
        self,
        msgid: str,
        languages: list[str],
        context: str = "",
    ) -> dict[str, str]:
        """Get .po file translations (read-only) for display as defaults."""
        po_backend = self._get_po_backend()
        po_entries = po_backend.get_translations(
            msgid=msgid,
            languages=languages,
            context=context,
        )
        return {lang: entry.msgstr for lang, entry in po_entries.items()}

    @t.override
    def get_hint(
        self,
        msgid: str,
        context: str = "",
    ) -> str:
        """Delegate to POFileBackend for translator comments."""
        return self._get_po_backend().get_hint(msgid, context)

    @t.override
    def save_translations(
        self,
        msgid: str,
        translations: dict[str, str],
        context: str = "",
        active_flags: dict[str, bool] | None = None,
    ) -> None:
        """Save translation overrides to the database."""
        from live_translations import conf as lt_conf
        from live_translations import history, models

        fallback_active = lt_conf.get_settings().translation_active_by_default
        po_defaults = self.get_defaults(msgid, list(translations.keys()), context)

        # Snapshot existing DB values (text + active state) for history tracking
        existing: dict[str, tuple[str, bool]] = {}
        for row in (
            models.TranslationEntry.objects.for_msgid(msgid, context)
            .filter(language__in=translations.keys())
            .values_list("language", "msgstr", "is_active")
        ):
            existing[row[0]] = (row[1], row[2])

        for lang, msgstr in translations.items():
            old_entry = existing.get(lang)
            old_msgstr = old_entry[0] if old_entry else ""
            old_is_active = old_entry[1] if old_entry else False

            is_active = (
                active_flags.get(lang, fallback_active)
                if active_flags
                else fallback_active
            )

            models.TranslationEntry.objects.update_or_create(
                language=lang,
                msgid=msgid,
                context=context,
                defaults={"msgstr": msgstr, "is_active": is_active},
            )
            # Track text changes
            if not old_msgstr:
                history.record_change(
                    language=lang,
                    msgid=msgid,
                    context=context,
                    action=models.TranslationHistory.Action.CREATE,
                    old_value=po_defaults.get(lang, ""),
                    new_value=msgstr,
                )
            elif old_msgstr != msgstr:
                history.record_change(
                    language=lang,
                    msgid=msgid,
                    context=context,
                    action=models.TranslationHistory.Action.UPDATE,
                    old_value=old_msgstr,
                    new_value=msgstr,
                )
            # Track active state changes (only for pre-existing entries)
            if old_entry is not None and old_is_active != is_active:
                history.record_change(
                    language=lang,
                    msgid=msgid,
                    context=context,
                    action=(
                        models.TranslationHistory.Action.ACTIVATE
                        if is_active
                        else models.TranslationHistory.Action.DEACTIVATE
                    ),
                    old_value="active" if old_is_active else "inactive",
                    new_value="active" if is_active else "inactive",
                )

        self.bump_catalog_version()
