import dataclasses
import functools
import typing as t
from pathlib import Path

import django.conf
import django.http
import django.utils.module_loading

if t.TYPE_CHECKING:
    from live_translations.backends.base import TranslationBackend

PermissionCheck: t.TypeAlias = t.Callable[[django.http.HttpRequest], bool]

API_PREFIX = "/__live-translations__"


def _to_dotted_path(value: str | type) -> str:
    """Convert a class or callable to its dotted import path, or pass through strings."""
    if isinstance(value, str):
        return value
    return f"{value.__module__}.{value.__qualname__}"


class LiveTranslationsSettings(t.TypedDict, total=False):
    """Type hint for the ``LIVE_TRANSLATIONS`` dict in Django settings.

    All keys are optional — sensible defaults are derived from Django's own
    settings (``LANGUAGES``, ``LOCALE_PATHS``, ``BASE_DIR``).

    Usage in ``settings.py``::

        if typing.TYPE_CHECKING:
            from live_translations import LiveTranslationsSettings

        LIVE_TRANSLATIONS: "LiveTranslationsSettings" = {
            "BACKEND": "live_translations.backends.db.DatabaseBackend",
            "LANGUAGES": ["en", "cs", "de"],
            "CACHE": "translations",
        }
    """

    BACKEND: "str | type[TranslationBackend]"
    """Translation storage backend — dotted path or class.
    Default: ``POFileBackend`` (reads/writes ``.po`` files on disk)."""

    CACHE: str
    """Django cache alias used for cross-process invalidation of translation
    overrides. Only relevant for ``DatabaseBackend``. Default: ``"default"``."""

    DOMAIN: str
    """Gettext domain — the basename of ``.po``/``.mo`` files
    (e.g. ``"django"`` resolves to ``django.po``). Default: ``"django"``."""

    LANGUAGES: list[str]
    """Language codes available for live editing. Falls back to the codes
    in ``settings.LANGUAGES``. Set explicitly to expose only a subset."""

    LOCALE_DIR: str | Path
    """Path to the locale directory containing ``{lang}/LC_MESSAGES/`` subdirs.
    Falls back to ``settings.LOCALE_PATHS[0]``, then ``settings.BASE_DIR / "locale"``."""

    PERMISSION_CHECK: str | PermissionCheck
    """Callable ``(HttpRequest) -> bool`` that gates access to the editing UI.
    Dotted path or function reference. Default: authenticated superusers only."""

    TRANSLATION_ACTIVE_BY_DEFAULT: bool
    """Whether new translation overrides saved from the frontend widget are
    immediately active. When ``False`` (default), overrides require explicit
    activation via Django admin before they take effect."""

    SHORTCUT_EDIT: str
    """Keyboard shortcut to toggle edit mode.  Expressed as a ``+``-separated
    combo of modifier names (``ctrl``, ``shift``, ``alt``, ``meta``) and a
    single key character.  Case-insensitive.  Default: ``"ctrl+shift+e"``."""

    SHORTCUT_PREVIEW: str
    """Keyboard shortcut to toggle preview mode (inactive overrides).
    Same format as ``SHORTCUT_EDIT``.  Default: ``"ctrl+shift+p"``."""


_DEFAULTS: LiveTranslationsSettings = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
    "CACHE": "default",
    "DOMAIN": "django",
    "PERMISSION_CHECK": "live_translations.conf.default_permission_check",
}


@dataclasses.dataclass(frozen=True, slots=True)
class LiveTranslationsConf:
    """Resolved configuration for live_translations."""

    languages: list[str] = dataclasses.field(default_factory=list)
    backend: str = _DEFAULTS["BACKEND"]  # type: ignore[assignment]
    cache: str = _DEFAULTS["CACHE"]
    locale_dir: str = ""
    domain: str = _DEFAULTS["DOMAIN"]
    permission_check: str = _DEFAULTS["PERMISSION_CHECK"]  # type: ignore[assignment]
    translation_active_by_default: bool = False
    shortcut_edit: str = "ctrl+shift+e"
    shortcut_preview: str = "ctrl+shift+p"


def default_permission_check(request: django.http.HttpRequest) -> bool:
    """Default: only authenticated superusers see the live translation UI."""
    return bool(
        hasattr(request, "user")
        and request.user.is_authenticated
        and request.user.is_superuser
    )


@functools.cache
def get_settings() -> LiveTranslationsConf:
    """Read LIVE_TRANSLATIONS from Django settings and merge with defaults (cached)."""
    raw: LiveTranslationsSettings = getattr(
        django.conf.settings, "LIVE_TRANSLATIONS", {}
    )

    languages: list[str] = raw.get("LANGUAGES", [])
    if not languages:
        # If languages not set in the plugin settings, fallback to settings.LANGUAGES.
        # If settings.LANGUAGES is also not set, fallback to settings.LANGUAGE_CODE.
        languages = [
            code for code, _name in getattr(django.conf.settings, "LANGUAGES", [])
        ]
        if not languages and django.conf.settings.LANGUAGE_CODE:
            languages = [django.conf.settings.LANGUAGE_CODE]

    locale_dir_raw = raw.get("LOCALE_DIR", "")
    locale_dir = (
        str(locale_dir_raw) if isinstance(locale_dir_raw, Path) else locale_dir_raw
    )
    if not locale_dir:
        locale_paths: list[str] = getattr(django.conf.settings, "LOCALE_PATHS", [])
        if locale_paths:
            locale_dir = str(locale_paths[0])
        else:
            import os

            base = getattr(django.conf.settings, "BASE_DIR", "")
            locale_dir = os.path.join(str(base), "locale")

    return LiveTranslationsConf(
        languages=languages,
        backend=_to_dotted_path(raw.get("BACKEND", _DEFAULTS["BACKEND"])),
        cache=raw.get("CACHE", _DEFAULTS["CACHE"]),
        locale_dir=locale_dir,
        domain=raw.get("DOMAIN", _DEFAULTS["DOMAIN"]),
        permission_check=_to_dotted_path(
            raw.get("PERMISSION_CHECK", _DEFAULTS["PERMISSION_CHECK"])
        ),
        translation_active_by_default=raw.get("TRANSLATION_ACTIVE_BY_DEFAULT", False),
        shortcut_edit=raw.get("SHORTCUT_EDIT", "ctrl+shift+e"),
        shortcut_preview=raw.get("SHORTCUT_PREVIEW", "ctrl+shift+p"),
    )


@functools.cache
def get_permission_checker() -> PermissionCheck:
    """Import and return the configured permission check callable (cached)."""
    settings = get_settings()
    return django.utils.module_loading.import_string(settings.permission_check)  # type: ignore[return-value]


@functools.cache
def get_backend_instance() -> "TranslationBackend":
    """Get or create the configured translation backend (cached singleton)."""
    settings = get_settings()
    cls: type[TranslationBackend] = django.utils.module_loading.import_string(
        settings.backend
    )
    return cls(
        locale_dir=settings.locale_dir,
        domain=settings.domain,
        cache_alias=settings.cache,
    )
