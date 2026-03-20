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

## Per-language permissions

The permission checker can return a **set of language codes** instead of a boolean to restrict which languages a user may edit. Users can still *view* all languages, but write operations (save, delete, activate) are blocked for languages outside the returned set.

### Return type

| Return value | Effect |
|---|---|
| `True` | Full access — user can edit all configured languages |
| `False` | No access — widget is not injected |
| `set[str]` | Partial access — user can only edit the languages in the set |
| Empty `set()` | Treated as `False` — no access |

### Example: restrict by user profile

```python
# myapp/permissions.py
from django.http import HttpRequest


def can_edit_translations(request: HttpRequest) -> bool | set[str]:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False

    # Superusers can edit everything
    if request.user.is_superuser:
        return True

    # Staff can only edit their assigned languages
    if request.user.is_staff:
        return set(request.user.profile.allowed_languages)

    return False
```

### Example: team-based language access

```python
# myapp/permissions.py
from django.http import HttpRequest

TEAM_LANGUAGES = {
    "translators-eu": {"de", "fr", "es", "it"},
    "translators-asia": {"ja", "ko", "zh"},
}


def can_edit_translations(request: HttpRequest) -> bool | set[str]:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False

    languages: set[str] = set()
    for group in request.user.groups.values_list("name", flat=True):
        languages |= TEAM_LANGUAGES.get(group, set())

    return languages or False
```

### Frontend behavior

When a user has partial language permissions:

- All language tabs are visible, but non-editable tabs have reduced opacity
- Textareas for non-editable languages are disabled
- The active/inactive toggle is hidden for non-editable languages
- The "Delete Override" button is hidden for non-editable languages
- The "Restore" button in history is hidden for non-editable languages
- Save skips non-editable languages automatically

### Backend enforcement

Per-language permissions are enforced server-side on all write endpoints. Frontend restrictions are a convenience — the API rejects unauthorized language writes regardless.

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

Write endpoints (`save`, `delete`, `bulk-activate`) additionally enforce per-language permissions when the checker returns a set. Read endpoints (`translations`, `history`) are not language-restricted — users with any level of access can view all languages.
