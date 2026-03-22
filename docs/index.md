---
title: django-live-translations
description: In-browser translation editing for Django
---

# django-live-translations

Edit translations directly on any page of your Django site. Toggle edit mode with a keyboard shortcut, click any translatable string, save your changes, and see them appear instantly.

<video controls autoplay loop muted playsinline width="100%">
  <source src="assets/screenshots/demo.mp4" type="video/mp4">
</video>

## What it does

django-live-translations hooks into Django's gettext system and adds an editing layer on top. Authorized users see a widget that lets them modify translations in-place, while regular users see no difference at all.

It works with all standard Django translation APIs:

- `{% translate %}` and `{% blocktranslate %}` template tags, including `{% blocktranslate count %}`
- `gettext()`, `pgettext()`, `ngettext()`, `npgettext()`, and their lazy variants

## Features

- **Inline editing** with a multi-language modal editor
- **Live updates** after saving, no page reload needed
- **Preview mode** to review inactive translations before going live
- **Bulk activation** of multiple pending translations at once
- **Edit history** with word-level diffs and one-click restore
- **Draft language support** for preparing translations before publishing
- **Placeholder validation** catches missing `%(name)s` or `{name}` format strings
- **HTML validation** warns about unclosed or mismatched tags
- **Two storage backends**: PO files (default) or database with cache sync
- **Per-language permissions** to restrict who can edit which languages
- **Django admin integration** for managing translation overrides
- **Zero frontend dependencies**, vanilla JS, no build step

## Quick install

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

```python title="settings.py"
INSTALLED_APPS = [
    # ...
    "live_translations",
]

MIDDLEWARE = [
    # ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "live_translations.middleware.LiveTranslationsMiddleware",  # (1)!
]
```

1. Must come **after** `AuthenticationMiddleware`.

Log in as a superuser and press ++ctrl+shift+e++ to start editing.

## Requirements

Python 3.12+ and Django 4.2+.

## Next steps

- [Getting started](getting-started.md) for the full setup walkthrough
- [Configuration](configuration.md) for all available settings
- [Backends](backends.md) to choose between PO files and database storage
