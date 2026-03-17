import dataclasses
import functools
import pathlib
import typing as t

import django.conf
import django.http
import django.utils.module_loading

from live_translations.types import LanguageCode

if t.TYPE_CHECKING:
    from live_translations.backends.base import TranslationBackend

__all__ = [
    "API_PREFIX",
    "LiveTranslationsConf",
    "LiveTranslationsSettings",
    "PermissionCheck",
    "default_permission_check",
    "get_backend_instance",
    "get_permission_checker",
    "get_settings",
    "is_preview_request",
]

type PermissionCheck = t.Callable[[django.http.HttpRequest], bool]

API_PREFIX = "/__live-translations__"

_DEFAULT_BACKEND = "live_translations.backends.po.POFileBackend"
_DEFAULT_CACHE = "default"
_DEFAULT_GETTEXT_DOMAIN = "django"
_DEFAULT_PERMISSION_CHECK = "live_translations.conf.default_permission_check"
_DEFAULT_SHORTCUT_EDIT = "ctrl+shift+e"
_DEFAULT_SHORTCUT_PREVIEW = "ctrl+shift+p"


def _to_dotted_path(value: str | type | t.Callable[..., t.Any]) -> str:
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
            from live_translations.conf import LiveTranslationsSettings

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

    GETTEXT_DOMAIN: str
    """Gettext domain used to locate ``.po`` and ``.mo`` files.

    The value is the basename of the catalog files inside each
    ``{lang}/LC_MESSAGES/`` directory.  For example, ``"django"`` (the
    default) resolves to ``django.po`` / ``django.mo``, while
    ``"djangojs"`` targets ``djangojs.po`` / ``djangojs.mo``.

    Most projects only use the default ``"django"`` domain.  Set this if
    your translatable strings live in a different gettext domain (e.g.
    ``"djangojs"`` for JavaScript catalogs).  Default: ``"django"``."""

    LANGUAGES: list[LanguageCode]
    """Language codes available for live editing. Falls back to the codes
    in ``settings.LANGUAGES``. Set explicitly to expose only a subset."""

    LOCALE_DIR: str | pathlib.Path
    """Path to the locale directory containing ``{lang}/LC_MESSAGES/`` subdirs.
    Falls back to ``settings.LOCALE_PATHS[0]``, then ``settings.BASE_DIR / "locale"``."""

    PERMISSION_CHECK: str | PermissionCheck
    """Callable ``(HttpRequest) -> bool`` that gates access to the editing UI.
    Dotted path or function reference. Default: authenticated superusers only."""

    TRANSLATION_ACTIVE_BY_DEFAULT: bool
    """Whether new translation overrides saved from the frontend widget are
    immediately active. When ``False`` (default), overrides require explicit
    activation before they take effect."""

    SHORTCUT_EDIT: str
    """Keyboard shortcut to toggle edit mode.  Expressed as a ``+``-separated
    combo of modifier names (``ctrl``, ``shift``, ``alt``, ``meta``) and a
    single key character.  Case-insensitive.  Default: ``"ctrl+shift+e"``."""

    SHORTCUT_PREVIEW: str
    """Keyboard shortcut to toggle preview mode (inactive overrides).
    Same format as ``SHORTCUT_EDIT``.  Default: ``"ctrl+shift+p"``."""


@dataclasses.dataclass(frozen=True, slots=True)
class LiveTranslationsConf:
    """Resolved configuration for live_translations."""

    languages: list[LanguageCode] = dataclasses.field(default_factory=list)
    backend: str = _DEFAULT_BACKEND
    cache: str = _DEFAULT_CACHE
    locale_dir: pathlib.Path = pathlib.Path()
    gettext_domain: str = _DEFAULT_GETTEXT_DOMAIN
    permission_check: str = _DEFAULT_PERMISSION_CHECK
    translation_active_by_default: bool = False
    shortcut_edit: str = _DEFAULT_SHORTCUT_EDIT
    shortcut_preview: str = _DEFAULT_SHORTCUT_PREVIEW


def default_permission_check(request: django.http.HttpRequest) -> bool:
    """Default: only authenticated superusers see the live translation UI."""
    return bool(
        hasattr(request, "user") and request.user.is_authenticated and request.user.is_superuser  # type: ignore[missing-attribute]
    )


@functools.cache
def get_settings() -> LiveTranslationsConf:
    """Read LIVE_TRANSLATIONS from Django settings and merge with defaults (cached)."""
    raw: LiveTranslationsSettings = getattr(django.conf.settings, "LIVE_TRANSLATIONS", {})  # type: ignore[bad-assignment]

    languages: list[str] = raw.get("LANGUAGES", [])
    if not languages:
        # If languages not set in the plugin settings, fallback to settings.LANGUAGES.
        # If settings.LANGUAGES is also not set, fallback to settings.LANGUAGE_CODE.
        languages = [code for code, _name in getattr(django.conf.settings, "LANGUAGES", [])]
        if not languages and django.conf.settings.LANGUAGE_CODE:
            languages = [django.conf.settings.LANGUAGE_CODE]

    locale_dir_raw = raw.get("LOCALE_DIR", "")
    if locale_dir_raw:
        locale_dir = pathlib.Path(locale_dir_raw)
    else:
        locale_paths: list[str] = getattr(django.conf.settings, "LOCALE_PATHS", [])
        if locale_paths:
            locale_dir = pathlib.Path(locale_paths[0])
        else:
            base = getattr(django.conf.settings, "BASE_DIR", "")
            locale_dir = pathlib.Path(str(base)) / "locale"

    return LiveTranslationsConf(
        languages=languages,
        backend=_to_dotted_path(raw.get("BACKEND", _DEFAULT_BACKEND)),
        cache=raw.get("CACHE", _DEFAULT_CACHE),
        locale_dir=locale_dir,
        gettext_domain=raw.get("GETTEXT_DOMAIN", _DEFAULT_GETTEXT_DOMAIN),
        permission_check=_to_dotted_path(raw.get("PERMISSION_CHECK", _DEFAULT_PERMISSION_CHECK)),
        translation_active_by_default=raw.get("TRANSLATION_ACTIVE_BY_DEFAULT", False),
        shortcut_edit=raw.get("SHORTCUT_EDIT", _DEFAULT_SHORTCUT_EDIT),
        shortcut_preview=raw.get("SHORTCUT_PREVIEW", _DEFAULT_SHORTCUT_PREVIEW),
    )


@functools.cache
def get_permission_checker() -> PermissionCheck:
    """Import and return the configured permission check callable (cached)."""
    settings = get_settings()
    return t.cast("PermissionCheck", django.utils.module_loading.import_string(settings.permission_check))


def is_preview_request(request: django.http.HttpRequest) -> bool:
    return request.COOKIES.get("lt_preview") == "1"


@functools.cache
def get_backend_instance() -> "TranslationBackend":
    """Get or create the configured translation backend (cached singleton)."""
    settings = get_settings()
    cls: type[TranslationBackend] = django.utils.module_loading.import_string(settings.backend)
    return cls(
        locale_dir=settings.locale_dir,
        domain=settings.gettext_domain,
        cache_alias=settings.cache,
    )
