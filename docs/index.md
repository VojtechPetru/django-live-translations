# django-live-translations

**In-browser translation editing for Django superusers.**

django-live-translations lets authorized users edit translations directly on any page of your Django application. Toggle edit mode, click any translatable string, and save changes that take effect immediately - no deployment, no restarts, no context switching to `.po` file editors.

It works with all standard Django translation APIs:

- **Template tags** - `{% translate %}` (`{% trans %}`), `{% blocktranslate %}` (`{% blocktrans %}`) (non-plural)
- **Python calls** - `gettext()`, `pgettext()`, `gettext_lazy()`, `pgettext_lazy()`

Plural forms (`ngettext`, `{% blocktranslate count %}`) are not yet supported.

<!-- TODO: replace with actual screenshot -->
![Edit mode overview](assets/screenshots/edit-mode.png){ loading=lazy }
/// caption
Edit mode overview
///

## Features

- **Inline editing** - click any translatable string to open a multi-language editor modal
- **Live preview** - changes appear on the page instantly after saving
- **Preview mode** - review inactive translations before making them live
- **Edit history** - word-level diffs with one-click restore
- **Bulk activation** - select and activate multiple pending translations at once
- **Two storage backends** - PO files (default) or database with cache-based sync
- **Custom permissions** - control who can edit translations with a simple callable
- **Django admin integration** - manage translation overrides from the admin panel
- **Zero frontend dependencies** - vanilla JS widget, no build step required

## Quick start

=== "uv"

    ```bash
    uv add django-live-translations
    ```

=== "poetry"

    ```bash
    poetry add django-live-translations
    ```

=== "pip"

    ```bash
    pip install django-live-translations
    ```

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "live_translations",
]

MIDDLEWARE = [
    # ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "live_translations.middleware.LiveTranslationsMiddleware",
    # ...
]
```

Log in as a superuser and press `Ctrl+Shift+E` to activate edit mode.

## Learn more

| Topic | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Installation, setup, and first use |
| [Configuration](configuration.md) | All available settings |
| [Backends](backends.md) | PO file vs database storage |
| [Permissions](permissions.md) | Controlling access to the editing UI |
| [Frontend Widget](widget.md) | Keyboard shortcuts, modes, and features |
| [Django Admin](admin.md) | Admin panel integration |
