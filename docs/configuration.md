# Configuration

All configuration is done through the `LIVE_TRANSLATIONS` dictionary in your Django settings. Every key is optional - sensible defaults are derived from Django's own settings.

```python
# settings.py
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
    "LANGUAGES": ["en", "cs", "de"],  # optional, defaults to settings.LANGUAGES
    "LOCALE_DIR": BASE_DIR / "locale",  # optional, defaults to LOCALE_PATHS[0]
}
```

!!! tip "Type checking"
    Use the `LiveTranslationsSettings` TypedDict to get autocomplete and type checking for your configuration:

    ```python
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from live_translations.conf import LiveTranslationsSettings

    LIVE_TRANSLATIONS: "LiveTranslationsSettings" = {
        "BACKEND": "live_translations.backends.db.DatabaseBackend",
        "CACHE": "translations",
    }
    ```

## Settings reference

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `BACKEND` | `str \| type` | `"live_translations.backends.po.POFileBackend"` | Translation storage backend. Dotted import path or class reference. |
| `CACHE` | `str` | `"default"` | Django cache alias for cross-process invalidation. Only used by `DatabaseBackend`. |
| `GETTEXT_DOMAIN` | `str` | `"django"` | Gettext domain — the basename of `.po`/`.mo` catalog files (e.g. `"django"` resolves to `django.po`/`django.mo`, `"djangojs"` to `djangojs.po`/`djangojs.mo`). |
| `LANGUAGES` | `list[str]` | From `settings.LANGUAGES` | Language codes available for editing. Set explicitly to expose only a subset. |
| `LOCALE_DIR` | `str \| Path` | `LOCALE_PATHS[0]` or `BASE_DIR/locale` | Path to the locale directory containing `{lang}/LC_MESSAGES/` subdirectories. |
| `PERMISSION_CHECK` | `str \| Callable` | Superuser check | Callable `(HttpRequest) -> bool` that controls access to the editing UI. Accepts a dotted path or function reference. |
| `TRANSLATION_ACTIVE_BY_DEFAULT` | `bool` | `False` | Whether newly saved translations are immediately active. When `False`, overrides require explicit activation. |
| `SHORTCUT_EDIT` | `str` | `"ctrl+shift+e"` | Keyboard shortcut to toggle edit mode. Format: `+`-separated modifiers and key. |
| `SHORTCUT_PREVIEW` | `str` | `"ctrl+shift+p"` | Keyboard shortcut to toggle preview mode. Same format as `SHORTCUT_EDIT`. |

## Settings details

### `BACKEND`

Choose between the two built-in backends:

```python
# PO file backend (default) - reads/writes .po files directly
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
}

# Database backend - stores overrides in the DB
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.db.DatabaseBackend",
}
```

See [Backends](backends.md) for a detailed comparison.

### `CACHE`

Only relevant when using the `DatabaseBackend`. The cache is used to synchronize translation overrides across multiple processes (e.g. gunicorn workers).

```python
CACHES = {
    "translations": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/1",
    }
}

LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.db.DatabaseBackend",
    "CACHE": "translations",
}
```

!!! warning
    The cache must be shared across processes (e.g. gunicorn workers). Use Redis, Memcached, or a similar multi-process cache backend. `LocMemCache` and `DummyCache` won't work in production.

### `LANGUAGES`

By default, languages are derived from Django's `settings.LANGUAGES`. Set this explicitly to limit which languages appear in the editor:

```python
LIVE_TRANSLATIONS = {
    "LANGUAGES": ["en", "cs"],  # only English and Czech
}
```

#### Draft languages

Any language listed in `LANGUAGES` that is **not** present in Django's `settings.LANGUAGES` is automatically treated as a **draft language**. Draft languages are fully editable by translators but are not served to regular users.

This lets you prepare translations for a new locale before publishing it:

```python
# settings.py
LANGUAGES = [
    ("en", "English"),
    ("cs", "Czech"),
]

LIVE_TRANSLATIONS = {
    "LANGUAGES": ["en", "cs", "de"],  # "de" is a draft language
}
```

Draft languages:

- Appear in the [language switcher](widget.md#language-switcher) in the hint bar with a "Draft" badge
- Are fully editable from the translation modal (also marked with a "Draft" badge)
- **Are always saved as active** - the active/inactive toggle is hidden. Since the entire language is unpublished, there is no need for a separate "inactive" state. This also ensures translations survive `makemessages` (which preserves `msgstr` values but may strip internal comments used for inactive overrides)
- Are switched via a middleware cookie override (`lt_lang`) - the page renders in the draft language without URL changes
- Are invisible to users who don't pass the `PERMISSION_CHECK`

Once ready, add the language to Django's `LANGUAGES` setting and it becomes a published language automatically.

### `LOCALE_DIR`

The directory containing your `{lang}/LC_MESSAGES/` subdirectories. Resolution order:

1. `LIVE_TRANSLATIONS["LOCALE_DIR"]` (if set)
2. `settings.LOCALE_PATHS[0]` (if defined)
3. `settings.BASE_DIR / "locale"` (fallback)

### `PERMISSION_CHECK`

Override the default superuser check with a custom callable. See [Permissions](permissions.md) for detailed examples.

```python
LIVE_TRANSLATIONS = {
    "PERMISSION_CHECK": "myapp.permissions.can_edit_translations",
}
```

### `SHORTCUT_EDIT` / `SHORTCUT_PREVIEW`

Customize keyboard shortcuts using `+`-separated modifier names and a key character (case-insensitive):

```python
LIVE_TRANSLATIONS = {
    "SHORTCUT_EDIT": "ctrl+shift+t",
    "SHORTCUT_PREVIEW": "ctrl+shift+r",
}
```

Available modifiers: `ctrl`, `shift`, `alt`, `meta`.

## System checks

django-live-translations registers Django system checks that run on startup:

| Check ID | Level | Condition |
|----------|-------|-----------|
| `live_translations.E001` | Error | `LANGUAGES` is empty and `settings.LANGUAGES` is not set |
| `live_translations.W001` | Warning | `django.contrib.staticfiles` is not in `INSTALLED_APPS` |
| `live_translations.W002` | Warning | Cache alias (for DB backend) is not defined in `CACHES` |
| `live_translations.W003` | Warning | Cache alias uses `DummyCache` (for DB backend) |
| `live_translations.W004` | Warning | Unknown keys in `LIVE_TRANSLATIONS` dictionary |

Run checks manually with:

```bash
python manage.py check live_translations
```
