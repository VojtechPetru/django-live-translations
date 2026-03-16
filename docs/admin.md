# Django Admin

django-live-translations registers a `TranslationEntryAdmin` in Django's admin site, providing a management interface for translation overrides stored in the database.

!!! note
    The admin interface is primarily useful with the [Database backend](backends.md#database-backend). With the PO file backend, translation overrides live in `.po` files and are not stored in the database.

## List view

The admin list displays all translation overrides with the following columns:

- **Message ID** -- truncated to 60 characters
- **Language** -- language code
- **Translation** -- the override value, truncated to 80 characters
- **Context** -- gettext message context (if any)
- **Is Active** -- whether the override is currently applied
- **Updated At** -- last modification timestamp

<!-- TODO: replace with actual screenshot -->
![Admin list view](assets/screenshots/admin-list.png)

### Filtering and search

- **Filters**: language, context, active status
- **Search**: searches across msgid, msgstr, and context fields
- **Ordering**: by msgid and language (default)

## Detail view

The edit form is organized into two fieldsets:

**Translation:**

- `.po` default (read-only) -- shows the baseline value from the `.po` file for comparison
- Translation (`msgstr`) -- the override value
- Is Active -- toggle whether this override is applied

**Identification:**

- Language
- Message ID (`msgid`)
- Context

## Bulk actions

Two custom actions are available in the list view:

<!-- TODO: replace with actual screenshot -->
![Bulk actions dropdown](assets/screenshots/admin-actions.png)

### Activate selected translations

Sets `is_active = True` for all selected entries. Useful for making a batch of reviewed translations live at once.

### Deactivate selected translations

Sets `is_active = False` for all selected entries. Useful for temporarily disabling translations without deleting them.

Both actions trigger the backend's catalog version bump, so changes propagate across processes immediately.

## django-unfold support

The admin class automatically detects if [django-unfold](https://github.com/unfoldadmin/django-unfold) is installed and inherits from `unfold.admin.ModelAdmin` instead of Django's default `ModelAdmin`. This provides a modern admin UI with no additional configuration needed.

```python
# Automatic detection -- no configuration required
# If unfold is installed, TranslationEntryAdmin uses unfold's ModelAdmin
# If not, it falls back to django.contrib.admin.ModelAdmin
```

## How saves work

Admin saves go through the service layer (`services.save_translations`), which:

1. Validates placeholder consistency between msgid and msgstr
2. Persists the override to the database
3. Records edit history (create/update action, old/new values)
4. Bumps the catalog version in the shared cache

Deletes similarly go through `services.delete_translations`, ensuring history is recorded and the cache is invalidated.
