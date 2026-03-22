---
title: Import & Export
description: Export and import translation overrides as CSV or PO files from the Django admin
---

# Import & Export

Export translation overrides to CSV or PO files, and import them back. Useful for bulk editing in a spreadsheet, sharing translations between environments, or migrating between backends.

All import/export operations are available from the TranslationEntry admin page.

## Exporting

From the translation overrides list in Django admin, click the **Export** button in the top-right toolbar.

### Format

Choose between two export formats:

=== "CSV"

    A flat CSV file with columns: `language`, `msgid`, `context`, `msgid_plural`, `form_index`, `msgstr`, `is_active`. Plural translations expand into multiple rows (one per form), while singular translations use a single row.

    CSV exports support two scopes:

    - **Overrides only**: exports entries from the database (your customizations)
    - **All**: merges `.po` file defaults with database overrides, so you get a complete picture of every translation

=== "PO"

    Standard gettext `.po` files.

    - When a single language is selected, you get one `.po` file
    - When "All languages" is selected, you get a `.zip` archive containing one `.po` file per language

    PO exports always include `.po` file defaults merged with database overrides.

### Language filter

Select a specific language to export, or choose "All languages" to export everything.

### Bulk action export

You can also export specific entries using the bulk actions dropdown. Select entries in the list view, then choose **Export selected as CSV** or **Export selected as PO (zip)** from the action menu.

??? info "Technical details"
    CSV bulk export writes only the selected entries, without merging `.po` defaults. PO bulk export creates a zip with one `.po` file per language found in the selection.

## Importing

Click the **Import** button in the toolbar to open the import form.

### Supported file types

| File type | Extension | Language handling |
|-----------|-----------|-------------------|
| CSV       | `.csv`    | Language per row (`language` column) |
| PO        | `.po`     | Single language per file (select in form or auto-detect from PO metadata) |
| ZIP       | `.zip`    | Multiple `.po` files, language derived from filename (e.g., `en.po`, `cs.po`) |

### CSV format

The CSV file must have a header row. Required columns: `language`, `msgid`, `msgstr`. Optional columns: `context`, `msgid_plural`, `form_index`, `is_active`.

For singular translations, each entry is one row with `msgid_plural` and `form_index` left empty. For plural translations, each form gets its own row with `form_index` set to the form number (0, 1, 2, ...).

=== "Table view"

    | language | msgid | context | msgid_plural | form_index | msgstr | is_active |
    |----------|-------|---------|--------------|:----------:|--------|:---------:|
    | en | hello | | | | Hello | true |
    | en | cart | | cart.plural | 0 | %(n)s item | true |
    | en | cart | | cart.plural | 1 | %(n)s items | true |
    | cs | hello | | | | Ahoj | false |
    | cs | cart | | cart.plural | 0 | %(n)s kus | true |
    | cs | cart | | cart.plural | 1 | %(n)s kusy | true |
    | cs | cart | | cart.plural | 2 | %(n)s kusů | true |

=== "Raw CSV"

    ```csv title="translations.csv"
    language,msgid,context,msgid_plural,form_index,msgstr,is_active
    en,hello,,,,Hello,true
    en,cart,,cart.plural,0,%(n)s item,true
    en,cart,,cart.plural,1,%(n)s items,true
    cs,hello,,,,Ahoj,false
    cs,cart,,cart.plural,0,%(n)s kus,true
    cs,cart,,cart.plural,1,%(n)s kusy,true
    cs,cart,,cart.plural,2,%(n)s kusů,true
    ```

When `is_active` is omitted, entries default to active. Values `false`, `0`, and `no` (case-insensitive) are treated as inactive.

### Dry run

Check **Dry run** before importing to preview what would change without writing to the database. The dry run report shows:

- How many entries would be created or updated
- Which entries are already up to date (unchanged)
- A detailed table of each change, showing old and new values side by side
- Any validation errors (empty msgid, missing language)

Review the preview, then re-upload the same file without dry run to apply the changes.

### Import behavior

Imports use upsert logic. Rows are grouped by `(language, msgid, context, msgid_plural)` and each group becomes one translation entry:

- If no matching entry exists, a new one is created
- If a matching entry exists, its translation and `is_active` fields are updated
- All changes happen in a single database transaction
- [Edit history](admin.md#translation-history) is recorded for the import

## Round-trip workflow

Export, edit externally, and re-import. The export and import formats are designed to round-trip without losing state.

### CSV round-trip

1. Export as CSV (with "All" scope if you want defaults included)
2. Edit translations in a spreadsheet
3. Import the modified CSV

The `is_active` column preserves activation state through the round-trip.

### PO round-trip

PO exports encode the active/inactive state so that re-importing restores it exactly:

- **Active overrides** are written as regular PO entries with the override in `msgstr`
- **Inactive overrides** are written with the `.po` default in `msgstr`, the override stored in a special `ltpending:` translator comment, and the `fuzzy` flag set

=== "Active override in PO"

    ```po
    msgid "Hello"
    msgstr "Hello World"
    ```

=== "Inactive override in PO"

    ```po
    #, fuzzy
    # ltpending:SGVsbG8gV29ybGQ=
    msgid "Hello"
    msgstr "Ahoj"
    ```

    `msgstr` contains the `.po` default. The `ltpending:` comment holds the inactive override (base64-encoded). On import, the override is restored as inactive.

??? info "Technical details"
    When importing a `.po` file, entries with an `ltpending:` comment are imported with the pending value as `msgstr` and `is_active=False`. For entries without `ltpending:`, the `fuzzy` flag determines activation: fuzzy entries are imported as inactive, non-fuzzy as active. This means standard PO workflows (marking entries as fuzzy for review) also work as expected.
