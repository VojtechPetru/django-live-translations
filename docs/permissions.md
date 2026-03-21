---
title: Permissions
description: Control who can edit translations and which languages they can access
---

# Permissions

Access to the editing UI is controlled by a single permission callable. By default, only authenticated superusers can see and use the widget.

For users who don't pass the check, the package has no visible effect and near-zero performance overhead.

## Default behavior

The built-in check allows access for authenticated superusers:

```python
def default_permission_check(request):
    return (
        hasattr(request, "user")
        and request.user.is_authenticated
        and request.user.is_superuser
    )
```

## Custom permission check

Set `PERMISSION_CHECK` to a dotted path or callable:

```python title="settings.py"
LIVE_TRANSLATIONS = {
    "PERMISSION_CHECK": "myapp.permissions.can_edit_translations",
}
```

### Staff members

```python title="myapp/permissions.py"
import django.http


def can_edit_translations(request: django.http.HttpRequest) -> bool:
    return (
        hasattr(request, "user")
        and request.user.is_authenticated
        and request.user.is_staff
    )
```

### Group-based access

```python title="myapp/permissions.py"
import django.http


def can_edit_translations(request: django.http.HttpRequest) -> bool:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False
    return request.user.groups.filter(name="Translators").exists()
```

### Django permission

```python title="myapp/permissions.py"
import django.http


def can_edit_translations(request: django.http.HttpRequest) -> bool:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False
    return request.user.has_perm("live_translations.change_translationentry")
```

## Per-language permissions

The permission callable can return a **set of language codes** instead of a boolean. This restricts which languages a user can edit while still allowing them to view all languages.

| Return value | Effect |
|---|---|
| `True` | Full access to all languages |
| `False` | No access (widget not injected) |
| `set[str]` | Edit access only for those languages |
| Empty `set()` | Treated as no access |

### Example: restrict by user profile

```python title="myapp/permissions.py"
import django.http


def can_edit_translations(request: django.http.HttpRequest) -> bool | set[str]:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False

    if request.user.is_superuser:
        return True

    if request.user.is_staff:
        return set(request.user.profile.allowed_languages)

    return False
```

### Example: team-based language access

```python title="myapp/permissions.py"
import django.http

TEAM_LANGUAGES = {
    "translators-eu": {"de", "fr", "es", "it"},
    "translators-asia": {"ja", "ko", "zh"},
}


def can_edit_translations(request: django.http.HttpRequest) -> bool | set[str]:
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False

    languages: set[str] = set()
    for group in request.user.groups.values_list("name", flat=True):
        languages |= TEAM_LANGUAGES.get(group, set())

    return languages or False
```

### What users see with partial access

When a user has access to some languages but not others:

- All language tabs are visible, but restricted tabs have reduced opacity
- Textareas for restricted languages are disabled
- The active/inactive toggle is hidden for restricted languages
- The "Delete Override" and "Restore" buttons are hidden for restricted languages
- Save skips restricted languages automatically

### Server-side enforcement

Per-language permissions are enforced on the server for all write operations (save, delete, activate). The frontend restrictions are a convenience. The API rejects unauthorized language writes regardless of what the client sends.
