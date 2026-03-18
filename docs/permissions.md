# Permissions

django-live-translations controls access to the editing UI through a configurable permission check. By default, only authenticated superusers can see and use the translation editing widget.

## Default behavior

The default permission check allows access for authenticated superusers only:

```python
def default_permission_check(request: HttpRequest) -> bool:
    return (
        hasattr(request, "user")
        and request.user.is_authenticated
        and request.user.is_superuser
    )
```

For all other users, the package has no visible effect and near-zero performance overhead.

## Custom permission check

Override the default by setting `PERMISSION_CHECK` to a dotted path or callable:

### Staff members only

```python
# myapp/permissions.py
from django.http import HttpRequest


def can_edit_translations(request: HttpRequest) -> bool:
    return (
        hasattr(request, "user")
        and request.user.is_authenticated
        and request.user.is_staff
    )
```

```python
# settings.py
LIVE_TRANSLATIONS = {
    "PERMISSION_CHECK": "myapp.permissions.can_edit_translations",
}
```

### Group-based access

```python
# myapp/permissions.py
from django.http import HttpRequest


def can_edit_translations(request: HttpRequest) -> bool:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False
    return request.user.groups.filter(name="Translators").exists()
```

### Permission-based access

```python
# myapp/permissions.py
from django.http import HttpRequest


def can_edit_translations(request: HttpRequest) -> bool:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False
    return request.user.has_perm("live_translations.change_translationentry")
```

## Preview mode

Preview mode allows authorized users to see inactive translations overlaid on the page without activating them. This is useful for reviewing translations before making them live.

- Toggle with `Ctrl+Shift+P` (configurable via `SHORTCUT_PREVIEW`)
- Inactive translations are shown with amber outlines
- Preview mode uses the `lt_preview` cookie to persist the state

Preview mode is gated by the same permission check as edit mode - only users who pass the `PERMISSION_CHECK` can use it.

## API endpoint protection

All API endpoints under `/__live-translations__/` are protected by the same permission check. Unauthorized requests receive a `403 Forbidden` response. The endpoints are:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/__live-translations__/translations/` | GET | Fetch translations for a msgid |
| `/__live-translations__/translations/save/` | POST | Save translation changes |
| `/__live-translations__/translations/delete/` | POST | Delete a translation override |
| `/__live-translations__/translations/history/` | GET | Fetch edit history |
| `/__live-translations__/translations/bulk-activate/` | POST | Activate multiple translations |

No URL configuration is needed - these are handled automatically by the middleware.
