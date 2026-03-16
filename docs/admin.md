# Django Admin

django-live-translations registers a `TranslationEntryAdmin` in Django's admin site, providing a management interface for translation overrides stored in the database.

!!! note
    The admin interface is primarily useful with the [Database backend](backends.md#database-backend). With the PO file backend, translation overrides live in `.po` files and are not stored in the database.

## List view

The admin list displays all translation overrides with the following columns:

- **Message ID** - truncated to 60 characters
- **Language** - language code
- **Translation** - the override value, truncated to 80 characters
- **Context** - gettext message context (if any)
- **Is Active** - whether the override is currently applied
- **Updated At** - last modification timestamp

### Filtering and search

- **Filters**: language, context, active status
- **Search**: searches across msgid, msgstr, and context fields
- **Ordering**: by msgid and language (default)

## Detail view

The edit form is organized into two fieldsets:

**Translation:**

- `.po` default (read-only) - shows the baseline value from the `.po` file for comparison
- Translation (`msgstr`) - the override value
- Is Active - toggle whether this override is applied

**Identification:**

- Language
- Message ID (`msgid`)
- Context

## Bulk actions

Two custom actions are available in the list view:

### Activate selected translations

Sets `is_active = True` for all selected entries. Useful for making a batch of reviewed translations live at once.

### Deactivate selected translations

Sets `is_active = False` for all selected entries. Useful for temporarily disabling translations without deleting them.

Both actions trigger the backend's catalog version bump, so changes propagate across processes immediately.

## django-unfold support

If [django-unfold](https://github.com/unfoldadmin/django-unfold) is installed, the admin automatically uses unfold's `ModelAdmin` for a modern admin UI. No configuration needed.
