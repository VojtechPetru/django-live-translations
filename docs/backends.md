# Backends

django-live-translations uses a backend system to abstract translation storage. Two backends are included out of the box, and you can implement your own by subclassing the abstract base class.

## PO file backend (default)

```python
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
}
```

The `POFileBackend` reads and writes `.po`/`.mo` files directly on disk. This is the default backend and requires no additional setup beyond having a locale directory with `.po` files.

### How it works

- **Active translations** are written directly into the `.po` file's `msgstr` field, and the `.mo` file is recompiled
- **Inactive translations** (when `TRANSLATION_ACTIVE_BY_DEFAULT` is `False`) are stored as base64-encoded values in the `.po` file's translator comment, using a `ltpending:` prefix
- After saving, Django's translation file change signal is triggered to reload catalogs

### File structure

```
locale/
  en/
    LC_MESSAGES/
      django.po    # read/written by POFileBackend
      django.mo    # recompiled on every save
  cs/
    LC_MESSAGES/
      django.po
      django.mo
```

### Trade-offs

**Pros:**

- No database required
- Changes are version-controlled alongside your code
- Works with any deployment strategy

**Cons:**

- Writes to the filesystem (may not work on read-only deployments)
- No built-in cross-process synchronization
- Requires `.po` files to exist for each language

## Database backend

```python
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.db.DatabaseBackend",
    "CACHE": "default",
}
```

The `DatabaseBackend` stores translation overrides in the database and falls back to `.po` files for defaults. It uses Django's cache framework for cross-process synchronization.

### Setup

1. Set the backend in your settings:

    ```python
    LIVE_TRANSLATIONS = {
        "BACKEND": "live_translations.backends.db.DatabaseBackend",
        "CACHE": "translations",  # must match a CACHES entry
    }
    ```

2. Ensure you have a proper cache backend configured:

    ```python
    CACHES = {
        "translations": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:6379/1",
        }
    }
    ```

3. Run migrations:

    ```bash
    python manage.py migrate
    ```

### How it works

**Translation resolution order:**

1. Database override (injected into Django's translation catalog)
2. `.po` file value (via standard gettext catalog)

When a translation is saved:

1. The override is written to the `TranslationEntry` table
2. A new catalog version UUID is set in the shared cache
3. On subsequent requests, each process checks the version -- if stale, it clears its local translation cache and re-injects all DB overrides

**Catalog injection** works by writing directly into Django's internal `DjangoTranslation._catalog` objects, so overrides are immediately visible to `gettext()` without restarting the application.

### Trade-offs

**Pros:**

- Works on read-only filesystems (containers, serverless)
- Built-in cross-process synchronization via cache
- Overrides are independent of `.po` files
- Full edit history with the `TranslationHistory` model

**Cons:**

- Requires database and cache infrastructure
- Overrides are not version-controlled (unless you export them)

## Comparison

| Feature | PO Backend | Database Backend |
|---------|-----------|-----------------|
| Storage | `.po`/`.mo` files | Database table |
| Cross-process sync | Via filesystem | Via cache (Redis, Memcached) |
| Read-only filesystem | No | Yes |
| Version control | Yes (files in repo) | No |
| Requires migrations | No | Yes |
| Edit history | Yes | Yes |
| `.po` file fallback | N/A | Yes |
| Inactive translations | Comment-based (`ltpending:`) | `is_active` field |

## Custom backends

To implement a custom backend, subclass `TranslationBackend` and implement the two required abstract methods:

```python
from live_translations.backends.base import TranslationBackend, TranslationEntry
from live_translations.types import LanguageCode, MsgKey


class MyCustomBackend(TranslationBackend):
    def get_translations(
        self,
        key: MsgKey,
        languages: list[LanguageCode],
    ) -> dict[LanguageCode, TranslationEntry]:
        """Fetch translations for a msgid across multiple languages."""
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

### Optional methods to override

| Method | Purpose |
|--------|---------|
| `ensure_current()` | Check if local overrides are stale and refresh if needed |
| `inject_overrides()` | Inject overrides into Django's translation catalogs |
| `bump_catalog_version()` | Signal other processes that overrides changed |
| `bulk_activate(language, msgids)` | Activate multiple pending translations |
| `get_inactive_overrides(language)` | Return inactive translations for preview mode |
| `get_defaults(key, languages)` | Get baseline `.po` file values for display |
| `get_hint(key)` | Get translator comments from `.po` files |
| `check()` | Return Django system check messages |

Register your backend in settings:

```python
LIVE_TRANSLATIONS = {
    "BACKEND": "myapp.backends.MyCustomBackend",
}
```
