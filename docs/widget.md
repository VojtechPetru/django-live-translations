# Frontend Widget

The frontend widget is a vanilla JavaScript application (~2500 lines, zero dependencies) that provides the inline translation editing experience. It's automatically injected into HTML responses for authorized users.

## Edit mode

Toggle edit mode with `Ctrl+Shift+E` (configurable via [`SHORTCUT_EDIT`](configuration.md#shortcut_edit--shortcut_preview)).

When active, all translatable strings on the page are highlighted with blue dashed outlines. Click any highlighted string to open the translation editor.

<!-- TODO: replace with actual screenshot -->
![Edit mode with highlighted strings](assets/screenshots/edit-mode.png)

### How strings are detected

The widget walks the DOM looking for invisible zero-width character (ZWC) markers that were appended to translated strings by the server-side gettext patch. Each marker encodes a string-table ID that maps back to the original `msgid` and context.

The widget strips the markers, wraps the text in `<lt-t>` custom elements (inert inline wrappers), and uses these elements as click targets for editing.

## Modal editor

Clicking a translatable string opens a modal dialog with tabbed editing for all configured languages.

<!-- TODO: replace with actual screenshot -->
![Translation modal editor](assets/screenshots/modal-editor.png)

The modal includes:

- **Language tabs** -- one tab per configured language, showing the current translation
- **Message ID** -- the original `msgid` displayed for reference, with a copy button
- **Default value** -- the `.po` file baseline (database backend), shown as read-only
- **Translator hint** -- extracted from `.po` file comments (`#.` lines), if available
- **Placeholder validation** -- warns if `%(name)s` or `{name}` placeholders don't match between the original and translation
- **Active toggle** -- per-language checkbox to control whether the translation is immediately active
- **Save** -- persists changes and updates the page in real-time
- **Delete override** -- reverts to the `.po` file default (removes the DB or pending override)

## Preview mode

Toggle preview mode with `Ctrl+Shift+P` (configurable via [`SHORTCUT_PREVIEW`](configuration.md#shortcut_edit--shortcut_preview)).

Preview mode shows inactive translations overlaid on the page with amber outlines, allowing you to review pending changes before activating them.

<!-- TODO: replace with actual screenshot -->
![Preview mode with inactive translations](assets/screenshots/preview-mode.png)

## Bulk activation

In preview mode, you can select multiple inactive translations and activate them all at once:

1. Enter preview mode (`Ctrl+Shift+P`)
2. `Shift+Click` on inactive translations to select them (amber outlines turn to selection indicators)
3. A floating action bar appears with the count and an "Activate" button
4. Click "Activate" to make all selected translations live

<!-- TODO: replace with actual screenshot -->
![Bulk activation selection](assets/screenshots/bulk-activate.png)

## Edit history

The modal editor includes a history panel that shows all previous edits for the current string, with word-level inline diffs and the ability to restore any previous value.

<!-- TODO: replace with actual screenshot -->
![Edit history with word-level diffs](assets/screenshots/edit-history.png)

Each history entry shows:

- Timestamp and user who made the change
- Action type (create, update, delete, activate, deactivate)
- Word-level diff highlighting additions and deletions
- "Restore" button to revert to that value

## Hint bar

A draggable hint bar is displayed at the bottom of the page showing the available keyboard shortcuts. Its position is persisted to `localStorage` so it stays where you put it across page navigations.

<!-- TODO: replace with actual screenshot -->
![Shortcut hint bar](assets/screenshots/hint-bar.png)

## Toast notifications

Save, delete, and activation actions show brief toast notifications confirming the operation. Toasts appear at the bottom of the viewport and auto-dismiss.

## Keyboard shortcuts

| Shortcut | Action | Configurable |
|----------|--------|-------------|
| `Ctrl+Shift+E` | Toggle edit mode | `SHORTCUT_EDIT` |
| `Ctrl+Shift+P` | Toggle preview mode | `SHORTCUT_PREVIEW` |
| `Escape` | Close modal / exit edit mode | No |
| `Shift+Click` | Select element for bulk activation (preview mode) | No |

## Technical details

- The widget uses the `<lt-t>` custom HTML element as an inert inline wrapper (no shadow DOM, no styling side effects)
- State machine: `inactive` -> `active` -> `editing`
- All styles are prefixed with `.lt-` to avoid conflicts
- The widget communicates with the server via JSON endpoints under `/__live-translations__/`
- DOM updates after save are applied immediately without page reload
- Attribute translations (e.g. `placeholder`, `title`) are also detected and editable
