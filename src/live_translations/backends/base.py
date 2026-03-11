"""Abstract base class for translation storage backends."""

import abc
import dataclasses
import typing as t

if t.TYPE_CHECKING:
    import django.core.checks


@dataclasses.dataclass(frozen=True, slots=True)
class TranslationEntry:
    """One translation of a msgid in a single language."""

    language: str
    msgid: str
    msgstr: str
    context: str  # "" if no msgctxt
    fuzzy: bool = False


class TranslationBackend(abc.ABC):
    """Protocol for translation storage backends.

    Subclass and implement get_translations / save_translations to support
    a new storage mechanism (database, API, etc.).
    """

    def __init__(
        self,
        locale_dir: str,
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
        languages: list[str],
        context: str = "",
    ) -> dict[str, TranslationEntry]:
        """Fetch translations for a msgid across multiple languages.

        Returns dict mapping language code to TranslationEntry.
        Missing entries should still appear with empty msgstr.
        """
        ...

    @abc.abstractmethod
    def save_translations(
        self,
        msgid: str,
        translations: dict[str, str],
        context: str = "",
    ) -> None:
        """Save translations for a msgid.

        Args:
            msgid: The message identifier.
            translations: Dict mapping language code to new msgstr.
            context: Gettext context (empty string if none).

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

    def get_defaults(
        self,
        msgid: str,
        languages: list[str],
        context: str = "",
    ) -> dict[str, str]:
        """Get baseline default translations for display alongside overrides.

        Returns empty dict by default. DatabaseBackend overrides this to read from .po files.
        """
        return {}

    def get_hint(
        self,
        msgid: str,
        context: str = "",
    ) -> str:
        """Get the translator comment (#. line) for a msgid from .po files.

        Returns empty string if no comment exists. POFileBackend reads from .po,
        DatabaseBackend delegates to POFileBackend.
        """
        return ""

    def check(self) -> "list[django.core.checks.CheckMessage]":
        """Return Django system check errors/warnings for this backend's configuration.

        Override in subclasses to add backend-specific checks.
        """
        return []
