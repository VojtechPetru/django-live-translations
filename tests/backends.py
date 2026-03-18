"""Test backends for use in unit tests via Django settings DI.

These are real ``TranslationBackend`` implementations (not mocks) that store
translations in the ORM but avoid external dependencies like PO files
and shared caches.
"""

import pathlib
import typing as t

import django.core.checks
import django.db.utils

from live_translations import conf, history, models
from live_translations.backends.base import TranslationBackend, TranslationEntry
from live_translations.types import DbOverride, LanguageCode, MsgKey, OverrideMap

__all__ = [
    "CheckCrashBackend",
    "CheckWarningBackend",
    "FileNotFoundBackend",
    "GetErrorBackend",
    "SaveErrorBackend",
    "TestBackend",
]


class TestBackend(TranslationBackend):
    """Simplified ``DatabaseBackend`` for testing -- no PO files, no shared cache.

    Like ``DatabaseBackend``, overrides are stored in the ``TranslationEntry``
    ORM table.  The differences:

    * **Defaults/hints** come from in-memory dicts (seeded via
      :meth:`seed_default` / :meth:`seed_hint`) instead of ``.po`` files.
    * **Version sync** is a plain ``self._version`` counter instead of a
      shared cache key.
    * **Catalog injection** (``ensure_current`` / ``inject_overrides``) is
      a no-op -- Django's gettext catalogs are not patched.
    """

    def __init__(
        self,
        locale_dir: pathlib.Path = pathlib.Path("/tmp"),  # noqa: S108
        domain: str = "django",
        cache_alias: str = "default",
    ) -> None:
        super().__init__(locale_dir, domain, cache_alias)
        # In-memory stores for defaults/hints (no PO file dependency)
        self._defaults: dict[tuple[LanguageCode, str, str], str] = {}
        self._hints: dict[tuple[str, str], str] = {}
        # Simple version counter (no cache dependency)
        self._version: int = 0
        self.call_log: list[tuple[str, tuple[t.Any, ...], dict[str, t.Any]]] = []
        """Append-only log of ``(method_name, args, kwargs)`` for every backend call.

        Use :meth:`get_calls` to filter by method name.  Replaces
        ``mock.assert_called_*`` patterns without pulling in ``unittest.mock``.
        """

    # -- Test helper methods --------------------------------------------------

    def seed_default(
        self,
        language: LanguageCode,
        msgid: str,
        msgstr: str,
        *,
        context: str = "",
    ) -> None:
        """Pre-load a PO-file-like default translation."""
        self._defaults[(language, msgid, context)] = msgstr

    def seed_hint(self, msgid: str, hint: str, *, context: str = "") -> None:
        """Pre-load a translator hint/comment."""
        self._hints[(msgid, context)] = hint

    def clear(self) -> None:
        """Reset all seeded data and call log."""
        self._defaults.clear()
        self._hints.clear()
        self._version = 0
        self.call_log.clear()

    def get_calls(self, method_name: str) -> list[tuple[tuple[t.Any, ...], dict[str, t.Any]]]:
        """Get call log entries for a specific method."""
        return [(args, kwargs) for name, args, kwargs in self.call_log if name == method_name]

    # -- TranslationBackend abstract implementations --------------------------

    @t.override
    def get_translations(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, TranslationEntry]:
        self.call_log.append(("get_translations", (key, languages), {}))

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

        result: dict[LanguageCode, TranslationEntry] = {}
        for lang in languages:
            default_msgstr = self._defaults.get((lang, key.msgid, key.context), "")
            db_entry = db_overrides.get(lang)

            result[lang] = TranslationEntry(
                language=lang,
                msgid=key.msgid,
                msgstr=db_entry.msgstr if db_entry is not None else default_msgstr,
                context=key.context,
                fuzzy=False,
                is_active=db_entry.is_active if db_entry is not None else True,
                has_override=db_entry is not None,
            )

        return result

    @t.override
    def save_translations(
        self,
        key: MsgKey,
        translations: dict[LanguageCode, str],
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        self.call_log.append(("save_translations", (key, translations), {"active_flags": active_flags}))

        fallback_active = conf.get_settings().translation_active_by_default
        po_defaults = self.get_defaults(key, list(translations.keys()))

        # Snapshot existing DB values for history tracking
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

            # Skip phantom entries (same logic as DatabaseBackend)
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

    # -- Hook overrides -------------------------------------------------------

    @t.override
    def ensure_current(self) -> None:
        self.call_log.append(("ensure_current", (), {}))

    @t.override
    def inject_overrides(self) -> None:
        self.call_log.append(("inject_overrides", (), {}))

    @t.override
    def bump_catalog_version(self) -> None:
        self.call_log.append(("bump_catalog_version", (), {}))
        self._version += 1

    @t.override
    def bulk_activate(
        self,
        language: LanguageCode,
        msgids: list[MsgKey],
    ) -> list[MsgKey]:
        self.call_log.append(("bulk_activate", (language, msgids), {}))

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
        self.call_log.append(("get_inactive_overrides", (language,), {}))
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
    def get_defaults(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, str]:
        self.call_log.append(("get_defaults", (key, languages), {}))
        result: dict[LanguageCode, str] = {}
        for lang in languages:
            val = self._defaults.get((lang, key.msgid, key.context))
            if val is not None:
                result[lang] = val
        return result

    @t.override
    def get_hint(self, key: MsgKey) -> str:
        self.call_log.append(("get_hint", (key,), {}))
        return self._hints.get((key.msgid, key.context), "")

    @t.override
    def check(self) -> list[django.core.checks.CheckMessage]:
        self.call_log.append(("check", (), {}))
        return []


# ---------------------------------------------------------------------------
# Specialised error backends for view error-path tests
# ---------------------------------------------------------------------------


class SaveErrorBackend(TestBackend):
    """Backend whose ``save_translations`` always raises ``RuntimeError``."""

    @t.override
    def save_translations(
        self,
        key: MsgKey,
        translations: dict[LanguageCode, str],
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        raise RuntimeError("unexpected backend error")


class FileNotFoundBackend(TestBackend):
    """Backend whose ``save_translations`` always raises ``FileNotFoundError``."""

    @t.override
    def save_translations(
        self,
        key: MsgKey,
        translations: dict[LanguageCode, str],
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        raise FileNotFoundError("PO file not found")


class GetErrorBackend(TestBackend):
    """Backend whose ``get_translations`` always raises ``RuntimeError``."""

    @t.override
    def get_translations(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, TranslationEntry]:
        raise RuntimeError("unexpected backend error")


# ---------------------------------------------------------------------------
# Specialised check backends for system-check tests
# ---------------------------------------------------------------------------


class CheckWarningBackend(TestBackend):
    """Backend whose ``check()`` returns a Warning."""

    @t.override
    def check(self) -> list[django.core.checks.CheckMessage]:
        return [
            django.core.checks.Warning(
                "test warning from backend",
                id="live_translations.W999",
            )
        ]


class CheckCrashBackend(TestBackend):
    """Backend whose ``check()`` raises ``RuntimeError``."""

    @t.override
    def check(self) -> list[django.core.checks.CheckMessage]:
        raise RuntimeError("backend check exploded")
