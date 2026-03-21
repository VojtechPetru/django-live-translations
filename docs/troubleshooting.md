---
title: Troubleshooting
description: Common issues and how to resolve them
---

# Troubleshooting

## System checks

django-live-translations runs Django system checks on startup. Run them manually with:

```bash
python manage.py check live_translations
```

### `live_translations.E001`: No languages configured

**Cause**: `LIVE_TRANSLATIONS["LANGUAGES"]` is empty and Django's `settings.LANGUAGES` is not set either.

**Fix**: set at least one language in your config:

```python title="settings.py"
LIVE_TRANSLATIONS = {
    "LANGUAGES": ["en"],
}
```

Or ensure Django's `LANGUAGES` setting is defined.

### `live_translations.W001`: staticfiles missing

**Cause**: `django.contrib.staticfiles` is not in `INSTALLED_APPS`.

**Fix**: add it. The widget needs it to serve CSS and JavaScript:

```python title="settings.py"
INSTALLED_APPS = [
    # ...
    "django.contrib.staticfiles",
    "live_translations",
]
```

### `live_translations.W002`: Cache alias not defined

**Cause**: you're using the database backend but the configured `CACHE` alias doesn't exist in `CACHES`.

**Fix**: add the cache backend:

```python title="settings.py"
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

### `live_translations.W003`: DummyCache in use

**Cause**: the configured cache alias uses `DummyCache`, which doesn't actually cache anything.

**Fix**: use a real cache backend (Redis, Memcached) for the database backend. `DummyCache` prevents cross-process synchronization.

### `live_translations.W004`: Unknown settings keys

**Cause**: `LIVE_TRANSLATIONS` contains keys that aren't recognized. Usually a typo.

**Fix**: check the key name against the [configuration reference](configuration.md#settings-reference).

## Common issues

### Edit mode shortcut does nothing

- Verify you're logged in as a superuser (or a user who passes your custom `PERMISSION_CHECK`)
- Check the browser console for JavaScript errors
- Confirm `django.contrib.staticfiles` is in `INSTALLED_APPS`
- Make sure the middleware is placed **after** `AuthenticationMiddleware`
- If you changed `SHORTCUT_EDIT`, verify the format is correct (e.g. `"ctrl+shift+e"`)

### Translations not updating after save

- **PO backend**: the `.mo` file should recompile automatically on save. Check that the `.po` file is writable.
- **Database backend**: verify your cache is working. `LocMemCache` won't synchronize across processes. Check that `ensure_current()` can read from the cache.

### Zero-width characters appearing in output

If invisible characters appear in JSON responses, email subjects, or other non-HTML output:

- Ensure `LiveTranslationsMiddleware` is positioned correctly. It strips markers from non-HTML responses, but only if it runs.
- Position it after any middleware that might cache or intercept response content.
- Template fragment caching for authorized users can preserve markers. Consider using `{% cache %}` only for unauthenticated content, or disable the widget for cached views.

### Translations lost after deployment

This happens with the PO backend because deployment replaces `.po` files on disk. Switch to the [database backend](backends.md#database-backend) for production.

### History not appearing

Edit history requires the `TranslationHistory` database table. Run migrations:

```bash
python manage.py migrate live_translations
```

If the table doesn't exist, history is silently skipped (no errors, but no records either).

### Permission check not working

- The callable must accept a single `HttpRequest` argument
- It must return `True`, `False`, or a `set[str]` of language codes
- If using a dotted path, verify the module is importable
- Check that the middleware is after `AuthenticationMiddleware` so `request.user` exists
