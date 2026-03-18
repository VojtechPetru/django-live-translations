# Frontend Widget

The frontend widget is automatically injected into HTML responses for authorized users. It provides the inline translation editing experience with zero frontend dependencies.

## Edit mode

Toggle edit mode with `Ctrl+Shift+E` (configurable via [`SHORTCUT_EDIT`](configuration.md#shortcut_edit--shortcut_preview)).

When active, all translatable strings on the page are highlighted with blue dashed outlines. Click any highlighted string to open the translation editor.

<!-- TODO: replace with actual screenshot -->
![Edit mode with highlighted strings](assets/screenshots/edit-mode.png){ loading=lazy }
/// caption
Translatable strings highlighted with blue dashed outlines
///

## Modal editor

Clicking a translatable string opens a modal dialog with tabbed editing for all configured languages.

<!-- TODO: replace with actual screenshot -->
![Translation modal editor](assets/screenshots/modal-editor.png){ loading=lazy }
/// caption
Multi-language translation editor modal
///

The modal includes:

- **Language tabs** - one tab per configured language, showing the current translation
- **Message ID** - the original `msgid` displayed for reference, with a copy button
- **Default value** - the `.po` file baseline (database backend), shown as read-only
- **Translator hint** - extracted from `.po` file comments (`#.` lines), if available
- **Placeholder validation** - warns if `%(name)s` or `{name}` placeholders don't match between the original and translation
- **Active toggle** - per-language checkbox to control whether the translation is immediately active
- **Save** - persists changes and updates the page in real-time
- **Delete override** - reverts to the `.po` file default (removes the DB or pending override)

## Preview mode

Toggle preview mode with `Ctrl+Shift+P` (configurable via [`SHORTCUT_PREVIEW`](configuration.md#shortcut_edit--shortcut_preview)).

Preview mode shows inactive translations overlaid on the page with amber outlines, allowing you to review pending changes before activating them.

<!-- TODO: replace with actual screenshot -->
![Preview mode with inactive translations](assets/screenshots/preview-mode.png){ loading=lazy }
/// caption
Inactive translations shown with amber outlines in preview mode
///

## Bulk activation

In preview mode, you can select multiple inactive translations and activate them all at once:

1. Enter preview mode (`Ctrl+Shift+P`)
2. `Shift+Click` on inactive translations to select them (amber outlines turn to selection indicators)
3. A floating action bar appears with the count and an "Activate" button
4. Click "Activate" to make all selected translations live

<!-- TODO: replace with actual screenshot -->
![Bulk activation selection](assets/screenshots/bulk-activate.png){ loading=lazy }
/// caption
Selecting multiple translations for bulk activation
///

## Edit history

The modal editor includes a history panel that shows all previous edits for the current string, with word-level inline diffs and the ability to restore any previous value.

<!-- TODO: replace with actual screenshot -->
![Edit history with word-level diffs](assets/screenshots/edit-history.png){ loading=lazy }
/// caption
Edit history with word-level diffs and restore option
///

Each history entry shows:

- Timestamp and user who made the change
- Action type (create, update, delete, activate, deactivate)
- Word-level diff highlighting additions and deletions
- "Restore" button to revert to that value

## Hint bar

A draggable hint bar is displayed at the bottom of the page showing the available keyboard shortcuts. Its position is persisted to `localStorage` so it stays where you put it across page navigations.

<!-- TODO: replace with actual screenshot -->
![Shortcut hint bar](assets/screenshots/hint-bar.png){ loading=lazy }
/// caption
Draggable hint bar showing available keyboard shortcuts
///

## Language switcher

When multiple languages are configured, the hint bar includes a language switcher dropdown. Click the current language indicator to open the menu.

![Language switcher with draft badge](assets/screenshots/language-switcher.png){ loading=lazy }
/// caption
Language switcher dropdown with a draft language marked
///

The switcher shows all configured languages. [Draft languages](configuration.md#draft-languages) are marked with an amber "Draft" badge.

**Switching behavior:**

- **Draft languages** - sets a cookie and reloads the page. The middleware overrides Django's active language so the page renders in the draft locale.
- **Published languages** - navigates to the language-prefixed URL (e.g. `/de/about/`) if `i18n_patterns` is detected, or sets the `django_language` cookie and reloads.

## Keyboard shortcuts

| Shortcut | Action | Configurable |
|----------|--------|-------------|
| `Ctrl+Shift+E` | Toggle edit mode | `SHORTCUT_EDIT` |
| `Ctrl+Shift+P` | Toggle preview mode | `SHORTCUT_PREVIEW` |
| `Escape` | Close modal / exit edit mode | No |
| `Shift+Click` | Select element for bulk activation (preview mode) | No |
