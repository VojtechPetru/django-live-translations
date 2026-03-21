---
title: Backends
description: Choose between PO file and database storage for translation overrides
---

# Backends

django-live-translations stores translation overrides through a pluggable backend system. Two backends ship out of the box.

## PO file backend

```python title="settings.py"
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",  # (1)!
}
```

1. This is the default. You can omit `BACKEND` entirely.

Reads and writes `.po` files directly on disk, then recompiles the `.mo` file on every save. No database or cache required.

Expected file structure:

```
locale/
  en/LC_MESSAGES/
    django.po
    django.mo
  cs/LC_MESSAGES/
    django.po
    django.mo
```

!!! warning "Best for local development"
    The PO backend writes directly to disk. On deployed servers, edits are lost on the next deployment when `.po` files are replaced. Use the [database backend](#database-backend) for production.

??? info "How inactive translations work in PO files"
    When `TRANSLATION_ACTIVE_BY_DEFAULT` is `False`, inactive translations are encoded as base64 in the entry's translator comment:

    ```
    # ltpending:SGVsbG8gV29ybGQ=
    msgid "Hello"
    msgstr "original translation"
    ```

    The `ltpending:` prefix marks the comment as a pending override. When activated, the pending value replaces `msgstr` and the comment is removed. These comments are stripped from the translator hint displayed in the editor.

## Database backend

```python title="settings.py"
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.db.DatabaseBackend",
    "CACHE": "translations",  # (1)!
}
```

1. Must match an entry in your `CACHES` setting.

Stores translation overrides in the database (`TranslationEntry` model) and falls back to `.po` files for defaults. Uses Django's cache framework to synchronize overrides across processes.

### Setup

1. Configure a shared cache backend:

    ```python title="settings.py"
    CACHES = {
        "translations": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/1",
        }
    }
    ```

2. Run migrations:

    ```bash
    python manage.py migrate
    ```

!!! warning
    The cache must be shared across all processes (e.g. gunicorn workers). Redis or Memcached work well. `LocMemCache` and `DummyCache` will not synchronize.

??? info "How cross-process sync works"
    When a translation is saved, a UUID version is written to the cache. On each request, the middleware calls `ensure_current()`, which compares the local version against the cache. If stale, the process clears its translation catalogs and re-injects all DB overrides. There's a brief window (one request cycle) where other processes may serve stale translations.

## Comparison

| | PO backend | Database backend |
|---|---|---|
| Storage | `.po`/`.mo` files on disk | Database table |
| Cross-process sync | Via filesystem | Via cache |
| Read-only filesystem | No | Yes |
| Survives redeployment | No | Yes |
| Requires migrations | No | Yes |
| Requires cache | No | Yes |
| Version controllable | Yes (commit `.po` files) | Via [export](import-export.md) |
| Inactive translations | Base64 in `.po` comments | `is_active` field |
| Edit history | Yes (needs DB) | Yes |

**Use the PO backend** for local development and small projects where you commit translations to your repo.

**Use the database backend** for production deployments, especially with containers, read-only filesystems, or multiple server processes.

## Custom backends

Subclass `TranslationBackend` and implement the two required methods:

```python title="myapp/backends.py"
from live_translations.backends.base import TranslationBackend, TranslationEntry
from live_translations.types import LanguageCode, MsgKey


class MyBackend(TranslationBackend):
    def get_translations(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, TranslationEntry]:
        """Fetch translations for a msgid across languages."""
        ...

    def save_translations(
        self,
        key: MsgKey,
        translations: dict[LanguageCode, str],
        active_flags: dict[LanguageCode, bool] | None = None,
    ) -> None:
        """Save translations for a msgid."""
        ...
```

Optional methods to override:

| Method | Purpose |
|--------|---------|
| `ensure_current()` | Check freshness and refresh if stale |
| `inject_overrides()` | Write overrides into Django's translation catalogs |
| `bump_catalog_version()` | Signal other processes that overrides changed |
| `bulk_activate(language, msgids)` | Activate multiple pending translations |
| `get_inactive_overrides(language)` | Return inactive translations for preview mode |
| `get_defaults(key, languages)` | Get baseline `.po` file values |
| `get_hint(key)` | Get translator comments from `.po` files |
| `check()` | Return Django system check messages |

Register your backend:

```python title="settings.py"
LIVE_TRANSLATIONS = {
    "BACKEND": "myapp.backends.MyBackend",
}
```
