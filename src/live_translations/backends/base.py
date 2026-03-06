"""Abstract base class for translation storage backends."""

import abc
import dataclasses


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

    Subclass and implement get_translations / save_translations / reload
    to support a new storage mechanism (database, API, etc.).
    """

    def __init__(self, locale_dir: str, domain: str) -> None:
        self.locale_dir = locale_dir
        self.domain = domain

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

        Must persist changes AND reload so they take effect.
        """
        ...

    @abc.abstractmethod
    def reload(self) -> None:
        """Flush Django's gettext translation caches.

        Called after saving so updated translations become visible
        without a server restart.
        """
        ...

    def invalidate_cache(self, languages: list[str] | None = None) -> None:  # noqa: B027
        """Intentional no-op for backends without caching. Overridden by DatabaseBackend."""

    def get_defaults(self, msgid: str, languages: list[str], context: str = "") -> dict[str, str]:
        """Get baseline default translations for display alongside overrides.

        Returns empty dict by default. DatabaseBackend overrides this to read from .po files.
        """
        return {}

    def lookup_override(self, language: str, msgid: str, context: str = "") -> str | None:
        """Look up a translation override for a single msgid.

        Returns None if no override exists. DatabaseBackend overrides this to check the DB cache.
        """
        return None

    def get_hint(self, msgid: str, context: str = "") -> str:
        """Get the translator comment (#. line) for a msgid from .po files.

        Returns empty string if no comment exists. POFileBackend reads from .po,
        DatabaseBackend delegates to POFileBackend.
        """
        return ""
