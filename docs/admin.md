---
title: Django Admin
description: Managing translation overrides from the Django admin panel
---

# Django Admin

django-live-translations registers two models in Django's admin: `TranslationEntry` for managing overrides and `TranslationHistory` as a read-only audit log.

!!! note
    The admin interface is most useful with the [database backend](backends.md#database-backend). With the PO backend, overrides live in `.po` files and these tables remain empty.

## Translation entries

The list view shows all overrides with columns for message ID, language, translation, context, active status, and last updated timestamp.

**Filters**: language, context, active status, modified by (user)

**Search**: across msgid, msgstr, and context fields

### Detail view

The edit form has two fieldsets:

- **Translation**: PO file default (read-only), the override value, and active toggle
- **Identification**: language, message ID, and context

The PO default lets you compare your override against the baseline `.po` file value.

### Bulk actions

Two actions are available on selected entries:

- **Activate selected translations**: sets `is_active = True` and triggers cache invalidation
- **Deactivate selected translations**: sets `is_active = False` and triggers cache invalidation

## Translation history

A read-only audit log of all changes. Shows timestamp, action type, language, message ID, context, and user.

No entries can be added, edited, or deleted through the admin. The history is append-only.

## django-unfold support

If [django-unfold](https://github.com/unfoldadmin/django-unfold) is installed, the admin automatically uses its `ModelAdmin` base class for a modern UI. No configuration needed.
