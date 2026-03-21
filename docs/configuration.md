---
title: Configuration
description: All available settings for django-live-translations
---

# Configuration

All settings live in the `LIVE_TRANSLATIONS` dictionary in your Django settings. Every key is optional.

```python title="settings.py"
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
    "LANGUAGES": ["en", "cs", "de"],
    "LOCALE_DIR": BASE_DIR / "locale",
}
```

!!! tip "Type checking"
    Use the `LiveTranslationsSettings` TypedDict for autocomplete and type safety:

    ```python title="settings.py"
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from live_translations.conf import LiveTranslationsSettings

    LIVE_TRANSLATIONS: "LiveTranslationsSettings" = {
        "BACKEND": "live_translations.backends.db.DatabaseBackend",
        "CACHE": "translations",
    }
    ```

## Settings reference

`BACKEND`
:   Translation storage backend. Dotted import path or class reference.

    Default: `"live_translations.backends.po.POFileBackend"`

    See [Backends](backends.md) for setup and comparison.

`CACHE`
:   Django cache alias for cross-process invalidation. Only used by the [database backend](backends.md#database-backend).

    Default: `"default"`

    The cache must be shared across processes (Redis, Memcached, etc.). `LocMemCache` and `DummyCache` will not work in production.

`GETTEXT_DOMAIN`
:   Gettext domain, the basename of `.po`/`.mo` catalog files. For example, `"django"` resolves to `django.po`/`django.mo`, while `"djangojs"` targets `djangojs.po`/`djangojs.mo`.

    Default: `"django"`

`LANGUAGES`
:   Language codes available for editing. When not set, derived from Django's `settings.LANGUAGES`.

    Default: codes from `settings.LANGUAGES`

    ```python title="settings.py"
    LIVE_TRANSLATIONS = {
        "LANGUAGES": ["en", "cs"],  # only English and Czech
    }
    ```

    Languages listed here but absent from Django's `settings.LANGUAGES` become [draft languages](#draft-languages).

`LOCALE_DIR`
:   Path to the locale directory containing `{lang}/LC_MESSAGES/` subdirectories.

    Resolution order:

    1. `LIVE_TRANSLATIONS["LOCALE_DIR"]` (if set)
    2. `settings.LOCALE_PATHS[0]` (if defined)
    3. `settings.BASE_DIR / "locale"` (fallback)

`PERMISSION_CHECK`
:   Callable that controls access to the editing UI. Receives an `HttpRequest`, returns `True` (full access), `False` (no access), or a `set[str]` of language codes for per-language access.

    Default: authenticated superusers only

    Accepts a dotted import path or function reference. See [Permissions](permissions.md) for examples.

`TRANSLATION_ACTIVE_BY_DEFAULT`
:   Whether newly saved translations are immediately active.

    Default: `False`

    When `False`, overrides require explicit activation before they take effect. Set to `True` if you want saves to go live immediately.

`SHORTCUT_EDIT`
:   Keyboard shortcut to toggle edit mode. Format: `+`-separated modifiers and key (case-insensitive).

    Default: `"ctrl+shift+e"`

    Available modifiers: `ctrl`, `shift`, `alt`, `meta`.

`SHORTCUT_PREVIEW`
:   Keyboard shortcut to toggle preview mode. Same format as `SHORTCUT_EDIT`.

    Default: `"ctrl+shift+p"`

## Draft languages

Any language code listed in `LANGUAGES` that is not present in Django's `settings.LANGUAGES` is treated as a **draft language**. This lets you prepare translations for a new locale before publishing it to users.

```python title="settings.py"
LANGUAGES = [
    ("en", "English"),
    ("cs", "Czech"),
]

LIVE_TRANSLATIONS = {
    "LANGUAGES": ["en", "cs", "de"],  # (1)!
}
```

1. `"de"` is a draft language because it's not in `LANGUAGES`.

Draft language behavior:

- Visible in the editor modal and language switcher, marked with a "Draft" badge
- Translations are **always saved as active**. The active/inactive toggle is hidden because the entire language is unpublished, so "inactive" has no meaning. This also ensures translations survive `makemessages`, which preserves `msgstr` values but may strip custom comments.
- Switching to a draft language sets a middleware cookie (`lt_lang`) that overrides Django's active language for that session, without changing the URL
- Invisible to users who don't pass the permission check

When the language is ready, add it to Django's `LANGUAGES` and it becomes a published language automatically.

## System checks

django-live-translations runs Django system checks on startup to catch configuration issues early.

| Check ID | Level | Condition |
|----------|-------|-----------|
| `live_translations.E001` | Error | No languages configured anywhere |
| `live_translations.W001` | Warning | `django.contrib.staticfiles` missing from `INSTALLED_APPS` |
| `live_translations.W002` | Warning | Cache alias not defined in `CACHES` (DB backend) |
| `live_translations.W003` | Warning | Cache alias uses `DummyCache` (DB backend) |
| `live_translations.W004` | Warning | Unrecognized keys in `LIVE_TRANSLATIONS` |

Run checks manually:

```bash
python manage.py check live_translations
```

See [Troubleshooting](troubleshooting.md) for more on resolving these.
