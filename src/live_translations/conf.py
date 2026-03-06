import dataclasses
import typing as t

from django.conf import settings
from django.utils.module_loading import import_string

_DEFAULTS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
    "DOMAIN": "django",
    "PERMISSION_CHECK": "live_translations.conf.default_permission_check",
    "URL_PREFIX": "/__live-translations__",
}


@dataclasses.dataclass(frozen=True, slots=True)
class LiveTranslationsConf:
    """Resolved configuration for live_translations."""

    languages: list[str] = dataclasses.field(default_factory=list)
    backend: str = _DEFAULTS["BACKEND"]
    locale_dir: str = ""
    domain: str = _DEFAULTS["DOMAIN"]
    permission_check: str = _DEFAULTS["PERMISSION_CHECK"]
    url_prefix: str = _DEFAULTS["URL_PREFIX"]


def default_permission_check(request: t.Any) -> bool:
    """Default: only authenticated superusers see the live translation UI."""
    return bool(hasattr(request, "user") and request.user.is_authenticated and request.user.is_superuser)


_conf_instance: LiveTranslationsConf | None = None


def get_conf() -> LiveTranslationsConf:
    """Read LIVE_TRANSLATIONS from Django settings and merge with defaults (cached)."""
    global _conf_instance
    if _conf_instance is not None:
        return _conf_instance

    raw: dict[str, t.Any] = getattr(settings, "LIVE_TRANSLATIONS", {})

    languages: list[str] = raw.get("LANGUAGES", [])
    if not languages:
        languages = [code for code, _name in getattr(settings, "LANGUAGES", [])]

    locale_dir: str = raw.get("LOCALE_DIR", "")
    if not locale_dir:
        import os

        base = getattr(settings, "BASE_DIR", "")
        locale_dir = os.path.join(str(base), "locale")

    _conf_instance = LiveTranslationsConf(
        languages=languages,
        backend=raw.get("BACKEND", _DEFAULTS["BACKEND"]),
        locale_dir=locale_dir,
        domain=raw.get("DOMAIN", _DEFAULTS["DOMAIN"]),
        permission_check=raw.get("PERMISSION_CHECK", _DEFAULTS["PERMISSION_CHECK"]),
        url_prefix=raw.get("URL_PREFIX", _DEFAULTS["URL_PREFIX"]),
    )
    return _conf_instance


_permission_checker: t.Callable[..., bool] | None = None


def get_permission_checker() -> t.Callable[..., bool]:
    """Import and return the configured permission check callable (cached)."""
    global _permission_checker
    if _permission_checker is not None:
        return _permission_checker
    conf = get_conf()
    _permission_checker = import_string(conf.permission_check)
    return _permission_checker  # type: ignore[return-value]


_backend_instance: t.Any = None


def get_backend_instance() -> t.Any:
    """Get or create the configured translation backend (cached singleton)."""
    global _backend_instance
    if _backend_instance is None:
        conf = get_conf()
        cls = import_string(conf.backend)
        _backend_instance = cls(locale_dir=conf.locale_dir, domain=conf.domain)
    return _backend_instance


def reset_all() -> None:
    """Reset all cached singletons (for testing)."""
    global _conf_instance, _permission_checker, _backend_instance
    _conf_instance = None
    _permission_checker = None
    _backend_instance = None


# Keep backwards-compatible alias
reset_backend_instance = reset_all
