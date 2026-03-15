"""Abstract base class for translation storage backends."""

import abc
import dataclasses
import typing as t
import pathlib

import polib

from live_translations import conf
from live_translations.types import LanguageCode, OverrideMap

if t.TYPE_CHECKING:
    import django.core.checks

__all__ = ["TranslationBackend", "TranslationEntry"]


@dataclasses.dataclass(frozen=True, slots=True)
class TranslationEntry:
    """One translation of a msgid in a single language."""

    language: LanguageCode
    msgid: str
    msgstr: str
    context: str  # "" if no msgctxt
    fuzzy: bool = False
    is_active: bool = True
    has_override: bool = False


class TranslationBackend(abc.ABC):
    """Protocol for translation storage backends.

    Subclass and implement get_translations / save_translations to support
    a new storage mechanism (database, API, etc.).
    """

    def __init__(
        self,
        locale_dir: pathlib.Path,
        domain: str,
        cache_alias: str = "default",
    ) -> None:
        self.locale_dir = locale_dir
        self.domain = domain
        self.cache_alias = cache_alias

    @abc.abstractmethod
    def get_translations(
        self,
        msgid: str,
        languages: list[LanguageCode],
        context: str = "",
    ) -> dict[LanguageCode, TranslationEntry]:
        """Fetch translations for a msgid across multiple languages.

        Returns dict mapping language code to TranslationEntry.
        Missing entries should still appear with empty msgstr.
        """
        ...

    @abc.abstractmethod
    def save_translations(
        self,
        msgid: str,
        translations: dict[LanguageCode, str],
        context: str = "",
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        """Save translations for a msgid.

        Args:
            msgid: The message identifier.
            translations: Dict mapping language code to new msgstr.
            context: Gettext context (empty string if none).
            active_flags: Optional dict mapping language code to is_active.
                When provided, sets the active state per language.
                When absent, uses the TRANSLATION_ACTIVE_BY_DEFAULT setting
                for new entries and preserves existing state on updates.

        Must persist changes AND signal that overrides changed.
        """
        ...

    def ensure_current(self) -> None:  # noqa: B027
        """Ensure the local process has current translation overrides.

        No-op for file-based backends. DatabaseBackend overrides this
        to check a shared version counter and re-inject if stale.
        """

    def inject_overrides(self) -> None:  # noqa: B027
        """Inject translation overrides into Django's translation catalogs.

        No-op for file-based backends. DatabaseBackend overrides this
        to query the DB and write into DjangoTranslation._catalog objects.
        """

    def bump_catalog_version(self) -> None:  # noqa: B027
        """Signal all processes that translation overrides have changed.

        No-op for file-based backends. DatabaseBackend overrides this
        to set a new version in Django's shared cache.
        """

    def get_inactive_overrides(self, language: LanguageCode) -> OverrideMap:
        """Return inactive translations for preview mode.

        Returns dict of (msgid, context) -> pending msgstr for the given language.
        """
        return {}

    def get_defaults(
        self,
        msgid: str,
        languages: list[LanguageCode],
        context: str = "",
    ) -> dict[LanguageCode, str]:
        """Get baseline default translations for display alongside overrides.

        Returns empty dict by default. DatabaseBackend overrides this to read from .po files.
        """
        return {}

    def get_hint(
        self,
        msgid: str,
        context: str = "",
    ) -> str:
        """Get the translator comment (#. line) for a msgid from .po files."""
        for lang in conf.get_settings().languages:
            path = self.locale_dir / lang / "LC_MESSAGES" / f"{self.domain}.po"
            try:
                po = polib.pofile(str(path))
            except (OSError, ValueError):
                continue
            entry = po.find(msgid, msgctxt=context or False)
            if entry and entry.comment:
                return entry.comment.strip()
        return ""

    def check(self) -> "list[django.core.checks.CheckMessage]":
        """Return Django system check errors/warnings for this backend's configuration.

        Override in subclasses to add backend-specific checks.
        """
        return []
