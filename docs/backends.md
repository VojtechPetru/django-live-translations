# Backends

django-live-translations uses a backend system to abstract translation storage. Two backends are included out of the box, and you can implement your own by subclassing the abstract base class.

## PO file backend (default)

```python
LIVE_TRANSLATIONS = {
    "BACKEND": "live_translations.backends.po.POFileBackend",
}
```

The `POFileBackend` reads and writes `.po`/`.mo` files directly on disk. This is the default backend and requires no additional setup beyond having a locale directory with `.po` files.

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

!!! warning "Best suited for local development"
    The PO backend writes directly to `.po`/`.mo` files on disk. If used on a deployed server, any translation edits will be **lost on the next deployment** when the codebase (including `.po` files) is replaced. Use the [Database backend](#database-backend) for production environments.

### Trade-offs

**Pros:**

- No database or cache infrastructure required
- Zero setup - works out of the box
- Changes are written to `.po` files, which you can commit to version control

**Cons:**

- **Edits are lost on redeployment** - the next deploy overwrites `.po` files with what's in the repo
- Writes to the filesystem (won't work on read-only deployments like containers)
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
