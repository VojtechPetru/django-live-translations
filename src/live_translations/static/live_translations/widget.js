/**
 * django-live-translations — client-side widget
 * Vanilla JS, zero dependencies. Injected by middleware for superusers.
 *
 * State machine:
 *   inactive ──(shortcut)──► active ──(click span)──► editing
 *      ▲                       ▲│                        │
 *      └──────(shortcut)───────┘│                        │
 *                                └──(save/cancel/Esc)────┘
 *
 *   Save triggers a page reload; edit mode is persisted to
 *   sessionStorage and restored on the next load.
 *
 * Preview mode (shortcut → page reload):
 *   Server renders inactive translations. Elements with inactive overrides
 *   get amber borders. Shift+click selects them for bulk activation.
 */
(function () {
  "use strict";

  /**
   * @typedef {Object} LTConfig
   * @property {string}   [apiBase]          - URL prefix for the translation API endpoints.
   * @property {string[]} [languages]        - Language codes enabled for editing (e.g. ["en","cs","de"]).
   * @property {string}   [csrfToken]        - Django CSRF token injected by middleware.
   * @property {boolean}  [activeByDefault]  - Whether new overrides are active immediately.
   */

  /**
   * @typedef {Object} LangMeta
   * @property {string} flag - Emoji flag for the language.
   * @property {string} name - English display name.
   */

  /**
   * Attribute translation descriptor embedded in `data-lt-attrs` JSON.
   * @typedef {Object} AttrInfo
   * @property {string} a - HTML attribute name (e.g. "title", "placeholder").
   * @property {string} m - The gettext msgid.
   * @property {string} c - The gettext context (empty string if none).
   */

  /**
   * Single language entry returned by the translations API.
   * @typedef {Object} TranslationEntry
   * @property {string}  msgstr    - Current translated string.
   * @property {boolean} fuzzy     - Whether the .po entry is marked fuzzy.
   * @property {boolean} is_active - Whether the DB override is active.
   */

  /**
   * Response payload from `GET /translations/`.
   * @typedef {Object} TranslationData
   * @property {Object<string, TranslationEntry>} translations - Keyed by language code.
   * @property {Object<string, string>|null}       defaults     - .po file defaults keyed by language code.
   * @property {string|null}                        hint         - Optional translator hint from the .po file.
   */

  /**
   * Single diff segment within a history entry.
   * @typedef {Object} DiffSegment
   * @property {"equal"|"insert"|"delete"} type - Diff operation type.
   * @property {string}                     text - Text content of this segment.
   */

  /**
   * Single entry from the edit history API.
   * @typedef {Object} HistoryEntry
   * @property {number}         id         - Database primary key.
   * @property {string}         language   - Language code this change applies to.
   * @property {"create"|"update"|"delete"|"activate"|"deactivate"} action - Type of change.
   * @property {string}         created_at - ISO 8601 timestamp.
   * @property {string|null}    user       - Username of the editor, or null.
   * @property {string|null}    old_value  - Previous msgstr (null for creates).
   * @property {string|null}    new_value  - New msgstr (null for deletes).
   * @property {DiffSegment[]}  diff       - Token-level diff between old and new values.
   */

  // ─── Config (injected by middleware) ─────────────────
  /** @type {LTConfig} */
  var CONFIG = window.__LT_CONFIG__ || {};
  /** @type {string} */
  var API_BASE = CONFIG.apiBase || "/__live-translations__";
  /** @type {string[]} */
  var LANGUAGES = CONFIG.languages || [];
  /** @type {string} */
  var CSRF_TOKEN = CONFIG.csrfToken || "";
  /** @type {boolean} */
  var ACTIVE_BY_DEFAULT = CONFIG.activeByDefault !== undefined ? CONFIG.activeByDefault : false;
  /** @type {string} */
  var SHORTCUT_EDIT = CONFIG.shortcutEdit || "ctrl+shift+e";
  /** @type {string} */
  var SHORTCUT_PREVIEW = CONFIG.shortcutPreview || "ctrl+shift+p";
  /** @type {boolean} */
  var PREVIEW = CONFIG.preview || false;
  /** @type {Array<{m:string, c:string}>} */
  var PREVIEW_ENTRIES = CONFIG.previewEntries || [];

  // ─── Shortcut Parsing ────────────────────────────────

  /**
   * Parse a shortcut string like "ctrl+shift+e" into a descriptor object.
   * @param {string} combo - "+"-separated modifier+key string (case-insensitive).
   * @returns {{ctrl: boolean, shift: boolean, alt: boolean, meta: boolean, key: string}}
   */
  function _parseShortcut(combo) {
    var parts = combo.toLowerCase().split("+");
    var key = parts[parts.length - 1];
    return {
      ctrl: parts.indexOf("ctrl") !== -1,
      shift: parts.indexOf("shift") !== -1,
      alt: parts.indexOf("alt") !== -1,
      meta: parts.indexOf("meta") !== -1,
      key: key,
    };
  }

  /**
   * Test whether a KeyboardEvent matches a parsed shortcut descriptor.
   * @param {KeyboardEvent} e - The keyboard event.
   * @param {{ctrl: boolean, shift: boolean, alt: boolean, meta: boolean, key: string}} sc
   * @returns {boolean}
   */
  function _matchShortcut(e, sc) {
    return (
      e.key.toLowerCase() === sc.key &&
      e.ctrlKey === sc.ctrl &&
      e.shiftKey === sc.shift &&
      e.altKey === sc.alt &&
      e.metaKey === sc.meta
    );
  }

  /**
   * Format a shortcut descriptor as a human-readable label (e.g. "Ctrl + Shift + E").
   * Uses platform-aware symbols on macOS (⌘/⌃/⌥/⇧).
   * @param {{ctrl: boolean, shift: boolean, alt: boolean, meta: boolean, key: string}} sc
   * @returns {string}
   */
  function _formatShortcut(sc) {
    var isMac = navigator.platform ? navigator.platform.indexOf("Mac") !== -1 : false;
    var parts = [];
    if (sc.ctrl) parts.push(isMac ? "\u2303" : "Ctrl");
    if (sc.shift) parts.push(isMac ? "\u21E7" : "Shift");
    if (sc.alt) parts.push(isMac ? "\u2325" : "Alt");
    if (sc.meta) parts.push(isMac ? "\u2318" : "Meta");
    parts.push(sc.key.toUpperCase());
    return parts.join(isMac ? "" : " + ");
  }

  var SC_EDIT = _parseShortcut(SHORTCUT_EDIT);
  var SC_PREVIEW = _parseShortcut(SHORTCUT_PREVIEW);

  // ─── Language display names & flags ──────────────────
  /** @type {Object<string, LangMeta>} */
  var LANG_META = {
    cs: { flag: "\uD83C\uDDE8\uD83C\uDDFF", name: "Czech" },
    en: { flag: "\uD83C\uDDEC\uD83C\uDDE7", name: "English" },
    de: { flag: "\uD83C\uDDE9\uD83C\uDDEA", name: "German" },
    pl: { flag: "\uD83C\uDDF5\uD83C\uDDF1", name: "Polish" },
    sk: { flag: "\uD83C\uDDF8\uD83C\uDDF0", name: "Slovak" },
    fr: { flag: "\uD83C\uDDEB\uD83C\uDDF7", name: "French" },
    es: { flag: "\uD83C\uDDEA\uD83C\uDDF8", name: "Spanish" },
    it: { flag: "\uD83C\uDDEE\uD83C\uDDF9", name: "Italian" },
    pt: { flag: "\uD83C\uDDF5\uD83C\uDDF9", name: "Portuguese" },
    nl: { flag: "\uD83C\uDDF3\uD83C\uDDF1", name: "Dutch" },
    ru: { flag: "\uD83C\uDDF7\uD83C\uDDFA", name: "Russian" },
    uk: { flag: "\uD83C\uDDFA\uD83C\uDDE6", name: "Ukrainian" },
    ja: { flag: "\uD83C\uDDEF\uD83C\uDDF5", name: "Japanese" },
    zh: { flag: "\uD83C\uDDE8\uD83C\uDDF3", name: "Chinese" },
    ko: { flag: "\uD83C\uDDF0\uD83C\uDDF7", name: "Korean" },
  };

  /**
   * @param {string} code - ISO 639-1 language code.
   * @returns {string} Emoji flag + English name, or uppercased code if unknown.
   */
  function langLabel(code) {
    var meta = LANG_META[code];
    if (meta) return meta.flag + "  " + meta.name;
    return code.toUpperCase();
  }

  // ─── Clipboard Copy Helper ───────────────────────────

  /** @type {string} */
  var ICON_COPY_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/>' +
    '<path d="M10.5 5.5V3.5a1.5 1.5 0 0 0-1.5-1.5H3.5A1.5 1.5 0 0 0 2 3.5V9a1.5 1.5 0 0 0 1.5 1.5h2"/></svg>';
  /** @type {string} */
  var ICON_CHECK_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M3.5 8.5l3 3 6-7"/></svg>';
  /** @type {string} */
  var ICON_CHECKBOX_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="2" y="2" width="12" height="12" rx="2"/></svg>';
  /** @type {string} */
  var ICON_CHECKBOX_CHECKED_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="2" y="2" width="12" height="12" rx="2" fill="currentColor" fill-opacity="0.15"/>' +
    '<path d="M5 8l2.5 2.5L11 6"/></svg>';

  /**
   * Make a container element copyable: clicking anywhere on it copies text to
   * the clipboard, swaps the icon to a checkmark, and adds a `--copied` CSS
   * modifier class for visual feedback.
   *
   * @param {HTMLElement}        container   - The clickable wrapper element.
   * @param {HTMLElement}        iconEl      - Element whose innerHTML is swapped (copy ↔ check).
   * @param {function(): string} getText     - Returns the string to copy.
   * @param {string}             copiedClass - CSS class toggled during feedback (e.g. "foo--copied").
   * @param {number}             [duration]  - Feedback duration in ms (default 1500).
   * @returns {void}
   */
  function _makeCopyable(container, iconEl, getText, copiedClass, duration) {
    var ms = duration || 1500;
    iconEl.innerHTML = ICON_COPY_SVG;
    container.style.cursor = "pointer";
    container.addEventListener("click", function () {
      var text = getText();
      if (!text || container.classList.contains(copiedClass)) return;
      navigator.clipboard.writeText(text).then(function () {
        container.classList.add(copiedClass);
        iconEl.innerHTML = ICON_CHECK_SVG;
        setTimeout(function () {
          container.classList.remove(copiedClass);
          iconEl.innerHTML = ICON_COPY_SVG;
        }, ms);
      });
    });
  }

  // ─── State ───────────────────────────────────────────
  /** @type {"inactive"|"active"|"editing"} */
  var state = "inactive";
  /** @type {string} */
  var _EDIT_MODE_KEY = "lt_edit_mode";

  /**
   * Persist edit-mode flag to sessionStorage and reload the page.
   * Edit mode is restored on the next page load via DOMContentLoaded.
   * @returns {void}
   */
  function _reloadPage() {
    if (state === "active" || state === "editing") {
      try { sessionStorage.setItem(_EDIT_MODE_KEY, "1"); } catch (e) { /* quota / private */ }
    }
    window.location.reload();
  }
  /** @type {HTMLDialogElement|null} */
  var dialog = null;
  /** @type {HTMLElement|null} */
  var currentSpan = null;
  /** @type {string|null} - HTML attribute name when editing an attribute translation. */
  var currentAttrName = null;
  /** @type {boolean} */
  var historyOpen = false;

  // ─── Editor State (tabbed editing) ───────────────────
  /** @type {TranslationData|null} - Cached API data for the current edit session. */
  var _editData = null;
  /** @type {string} - Currently selected language tab for editing. */
  var _editLang = "";
  /** @type {Object<string, string>} - Accumulated edited text values keyed by language. */
  var _editedValues = {};
  /** @type {Object<string, boolean>} - Accumulated active flags keyed by language. */
  var _editedActiveFlags = {};
  /** @type {Object<string, string>} - Snapshot of initial text values from API (for dirty detection). */
  var _originalValues = {};
  /** @type {Object<string, boolean>} - Snapshot of initial active flags from API (for dirty detection). */
  var _originalActiveFlags = {};
  /** @type {Object<string, boolean>} - Languages marked for override deletion (submitted on Save). */
  var _deletionsMarked = {};

  // ─── API Client ──────────────────────────────────────

  var api = {
    /**
     * Fetch all language translations for a single msgid.
     * @param {string} msgid  - The gettext message identifier.
     * @param {string} context - The gettext context (empty string if none).
     * @returns {Promise<TranslationData>}
     */
    getTranslations: function (msgid, context) {
      var params = new URLSearchParams({ msgid: msgid, context: context });
      return fetch(API_BASE + "/translations/?" + params, {
        credentials: "same-origin",
        cache: "no-store",
      }).then(function (resp) {
        if (!resp.ok) throw new Error("GET failed: " + resp.status);
        return resp.json();
      });
    },

    /**
     * Persist translation overrides to the database.
     * @param {string}                msgid        - The gettext message identifier.
     * @param {string}                context      - The gettext context.
     * @param {Object<string,string>} translations - Map of language code to msgstr value.
     * @param {Object<string,boolean>} activeFlags - Map of language code to active/inactive flag.
     * @returns {Promise<Object>} Server confirmation payload.
     */
    saveTranslations: function (msgid, context, translations, activeFlags) {
      return fetch(API_BASE + "/translations/save/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRF_TOKEN,
        },
        body: JSON.stringify({
          msgid: msgid,
          context: context,
          translations: translations,
          active_flags: activeFlags || {},
        }),
      }).then(function (resp) {
        if (!resp.ok) {
          return resp
            .json()
            .catch(function () {
              return {};
            })
            .then(function (err) {
              var e = new Error(err.error || "POST failed: " + resp.status);
              e.details = err.details || null;
              throw e;
            });
        }
        return resp.json();
      });
    },

    /**
     * Fetch the edit history for a msgid/context pair.
     * @param {string} msgid   - The gettext message identifier.
     * @param {string} context - The gettext context.
     * @returns {Promise<{history: HistoryEntry[]}>}
     */
    getHistory: function (msgid, context) {
      var params = new URLSearchParams({ msgid: msgid, context: context });
      return fetch(API_BASE + "/translations/history/?" + params, {
        credentials: "same-origin",
      }).then(function (resp) {
        if (!resp.ok) throw new Error("GET failed: " + resp.status);
        return resp.json();
      });
    },

    /**
     * Delete DB override(s) for a msgid/context.
     * @param {string}   msgid     - The gettext message identifier.
     * @param {string}   context   - The gettext context.
     * @param {string[]} languages - Language codes to delete.
     * @returns {Promise<{ok:boolean, deleted:number}>}
     */
    deleteTranslation: function (msgid, context, languages) {
      var payload = { msgid: msgid, context: context };
      if (languages && languages.length) payload.languages = languages;
      return fetch(API_BASE + "/translations/delete/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRF_TOKEN,
        },
        body: JSON.stringify(payload),
      }).then(function (resp) {
        if (!resp.ok) {
          return resp
            .json()
            .catch(function () {
              return {};
            })
            .then(function (err) {
              throw new Error(err.error || "POST failed: " + resp.status);
            });
        }
        return resp.json();
      });
    },

    /**
     * Bulk-activate translations for the given msgid/context pairs for a single language.
     * @param {Array<{msgid:string, context:string}>} msgids - Entries to activate.
     * @param {string} language - Language code to activate for.
     * @returns {Promise<{ok:boolean, activated:number}>}
     */
    bulkActivate: function (msgids, language) {
      return fetch(API_BASE + "/translations/bulk-activate/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRF_TOKEN,
        },
        body: JSON.stringify({ msgids: msgids, language: language }),
      }).then(function (resp) {
        if (!resp.ok) {
          return resp
            .json()
            .catch(function () {
              return {};
            })
            .then(function (err) {
              throw new Error(err.error || "POST failed: " + resp.status);
            });
        }
        return resp.json();
      });
    },
  };

  // ─── Toast ───────────────────────────────────────────

  /**
   * @param {string} message - Text to display.
   * @param {"success"|"error"|"info"} [type="success"] - Visual style of the toast.
   * @returns {void}
   */
  function showToast(message, type) {
    type = type || "success";
    var existing = document.querySelector(".lt-toast");
    if (existing) existing.remove();

    var toast = document.createElement("div");
    toast.className = "lt-toast lt-toast--" + type;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Trigger reflow for animation
    void toast.offsetHeight;
    toast.classList.add("lt-toast--visible");

    setTimeout(function () {
      toast.classList.remove("lt-toast--visible");
      setTimeout(function () {
        toast.remove();
      }, 300);
    }, 3000);
  }

  // ─── Modal ───────────────────────────────────────────

  /**
   * Lazily create the shared `<dialog>` element and attach its event listeners.
   * Subsequent calls are no-ops; the dialog is reused across all edit sessions.
   * @returns {void}
   */
  function createDialog() {
    if (dialog) return;

    dialog = document.createElement("dialog");
    dialog.className = "lt-dialog";
    var ICON_HISTORY =
      '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M8 3.5V8L10.5 10.5M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0Z" ' +
      'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var ICON_BACK =
      '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M10 12L6 8L10 4" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var ICON_CLOSE =
      '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>';

    dialog.innerHTML =
      '<div class="lt-dialog__form">' +
      '<div class="lt-dialog__header">' +
      '<h2 class="lt-dialog__title">Edit Translation</h2>' +
      '<div class="lt-dialog__header-actions">' +
      '<button type="button" class="lt-btn lt-btn--history" aria-label="History" title="View edit history">' +
      ICON_HISTORY +
      "</button>" +
      '<button type="button" class="lt-dialog__close" aria-label="Close">' +
      ICON_CLOSE +
      "</button>" +
      "</div>" +
      "</div>" +
      '<div class="lt-dialog__msgid"></div>' +
      '<div class="lt-dialog__hint"></div>' +
      '<div class="lt-editor__tabs"></div>' +
      '<div class="lt-dialog__fields"></div>' +
      '<div class="lt-dialog__history"></div>' +
      '<div class="lt-dialog__error"></div>' +
      '<div class="lt-dialog__actions">' +
      '<button type="button" class="lt-btn lt-btn--delete-override" style="display:none">Delete Override</button>' +
      '<button type="button" class="lt-btn lt-btn--cancel">Cancel</button>' +
      '<button type="button" class="lt-btn lt-btn--save">Save</button>' +
      "</div>" +
      '<div class="lt-dialog__loading">Loading translations...</div>' +
      "</div>";

    // Store icon templates on the dialog for toggling
    dialog._ltIconHistory = ICON_HISTORY;
    dialog._ltIconBack = ICON_BACK;

    document.body.appendChild(dialog);

    // Event listeners
    dialog
      .querySelector(".lt-dialog__close")
      .addEventListener("click", closeModal);
    dialog
      .querySelector(".lt-btn--cancel")
      .addEventListener("click", closeModal);
    dialog
      .querySelector(".lt-btn--save")
      .addEventListener("click", handleSave);
    dialog
      .querySelector(".lt-btn--delete-override")
      .addEventListener("click", handleDeleteOverride);
    dialog
      .querySelector(".lt-btn--history")
      .addEventListener("click", toggleHistory);

    // Native <dialog> close event (Escape key)
    dialog.addEventListener("close", function () {
      if (state === "editing") {
        state = "active";
      }
    });

    // Backdrop click closes
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog) {
        closeModal();
      }
    });
  }

  /**
   * Open the translation editor for a translatable element.
   *
   * For inline text spans (`<span class="lt-translatable">`), `attrInfo` is
   * omitted and the msgid/context are read from the element's `data-lt-msgid`
   * and `data-lt-context` attributes. For attribute translations (e.g. `title`),
   * the caller passes the {@link AttrInfo} descriptor from `data-lt-attrs`.
   *
   * @param {HTMLElement}   element   - The DOM element that was clicked.
   * @param {AttrInfo}      [attrInfo] - Attribute descriptor; omit for inline text.
   * @returns {void}
   */
  function openModal(element, attrInfo) {
    createDialog();
    currentSpan = element;
    currentAttrName = attrInfo ? attrInfo.a : null;
    state = "editing";
    historyOpen = false;
    _showEditView();

    var msgid = attrInfo ? attrInfo.m : element.dataset.ltMsgid;
    var context = attrInfo ? attrInfo.c : (element.dataset.ltContext || "");

    // Show loading state
    dialog.querySelector(".lt-dialog__fields").innerHTML = "";
    dialog.querySelector(".lt-dialog__loading").style.display = "block";
    var msgidEl = dialog.querySelector(".lt-dialog__msgid");
    msgidEl.dataset.msgid = msgid;
    msgidEl.innerHTML = "";

    var msgidLabel = document.createElement("span");
    msgidLabel.className = "lt-dialog__msgid-label";
    msgidLabel.textContent = currentAttrName ? "msgid · " + currentAttrName : "msgid";

    var msgidText = document.createElement("span");
    msgidText.className = "lt-dialog__msgid-text";
    msgidText.textContent = msgid;

    var copyIcon = document.createElement("span");
    copyIcon.className = "lt-dialog__msgid-icon";
    copyIcon.title = "Copy msgid";

    msgidEl.appendChild(msgidLabel);
    msgidEl.appendChild(msgidText);
    msgidEl.appendChild(copyIcon);
    _makeCopyable(
      msgidEl,
      copyIcon,
      function () { return msgidEl.dataset.msgid || ""; },
      "lt-dialog__msgid--copied"
    );
    dialog.querySelector(".lt-btn--save").disabled = true;
    showDialogError(null);

    dialog.showModal();

    api
      .getTranslations(msgid, context)
      .then(function (data) {
        renderFields(data);
      })
      .catch(function (err) {
        showToast("Failed to load translations: " + err.message, "error");
        closeModal();
      });
  }

  /**
   * Populate the dialog with tabbed language editing.
   * Called after the translations API responds.
   * @param {TranslationData} data - Payload from `api.getTranslations`.
   * @returns {void}
   */
  function renderFields(data) {
    dialog.querySelector(".lt-dialog__loading").style.display = "none";
    dialog.querySelector(".lt-btn--save").disabled = false;

    // Show translator hint if available
    var hintEl = dialog.querySelector(".lt-dialog__hint");
    if (data.hint) {
      hintEl.textContent = data.hint;
      hintEl.style.display = "block";
    } else {
      hintEl.textContent = "";
      hintEl.style.display = "none";
    }

    // Store data for tab switching
    _editData = data;
    _editedValues = {};
    _editedActiveFlags = {};
    _originalValues = {};
    _originalActiveFlags = {};

    var poDefaults = data.defaults || {};

    // Initialize values from API data
    for (var i = 0; i < LANGUAGES.length; i++) {
      var lang = LANGUAGES[i];
      var entry = data.translations[lang] || { msgstr: "", fuzzy: false };
      _editedValues[lang] = entry.msgstr;
      var hasOverride = !!entry.has_override;
      _editedActiveFlags[lang] = hasOverride ? entry.is_active !== false : ACTIVE_BY_DEFAULT;
      _originalValues[lang] = entry.msgstr;
      _originalActiveFlags[lang] = _editedActiveFlags[lang];
    }

    // Default edit language: current page language if configured, else first
    var pageLang = (document.documentElement.lang || "").toLowerCase();
    _editLang = LANGUAGES.indexOf(pageLang) !== -1 ? pageLang : LANGUAGES[0];

    _renderEditorTabs();
    _renderEditorPanels();
  }

  /**
   * Render the language tab bar above the editor panels.
   * Hidden when only one language is configured.
   * @returns {void}
   */
  function _renderEditorTabs() {
    var tabBar = dialog.querySelector(".lt-editor__tabs");
    tabBar.innerHTML = "";

    if (LANGUAGES.length <= 1) {
      tabBar.style.display = "none";
      return;
    }

    tabBar.style.display = "";

    for (var i = 0; i < LANGUAGES.length; i++) {
      (function (lang) {
        var meta = LANG_META[lang];
        var entry = (_editData && _editData.translations[lang]) || {};
        var pill = document.createElement("button");
        pill.type = "button";
        pill.className = "lt-editor__tab" + (_editLang === lang ? " lt-editor__tab--active" : "");
        if (entry.has_override && entry.is_active === false) {
          pill.classList.add("lt-editor__tab--inactive-override");
        }
        pill.textContent = meta ? meta.flag + "  " + meta.name : lang.toUpperCase();
        pill.dataset.lang = lang;
        pill.addEventListener("click", function () {
          if (_editLang === lang) return;
          _switchEditLang(lang);
        });
        tabBar.appendChild(pill);
      })(LANGUAGES[i]);
    }
  }

  /**
   * Switch the active edit language tab.
   * Persists current edits, swaps languages, and re-renders the editor.
   * @param {string} newLang - Language code to switch to.
   * @returns {void}
   */
  function _switchEditLang(newLang) {
    _persistCurrentEdit();
    _editLang = newLang;

    // Update tab active states without full re-render
    var tabs = dialog.querySelectorAll(".lt-editor__tab");
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].dataset.lang === newLang) {
        tabs[i].classList.add("lt-editor__tab--active");
      } else {
        tabs[i].classList.remove("lt-editor__tab--active");
      }
    }

    _renderEditorPanels();
    _updateTabDirtyDots();
  }

  /**
   * Save current textarea value and toggle state to the accumulated edit stores.
   * Called before tab switches and before save.
   * @returns {void}
   */
  function _persistCurrentEdit() {
    if (!_editLang || !dialog) return;
    var textarea = dialog.querySelector("#lt-input-" + _editLang);
    if (textarea) {
      _editedValues[_editLang] = textarea.value;
    }
    var toggle = dialog.querySelector("#lt-active-" + _editLang);
    if (toggle) {
      _editedActiveFlags[_editLang] = toggle.checked;
    }
  }

  /**
   * Check whether a language has unsaved changes relative to the API snapshot.
   * @param {string} lang - Language code.
   * @returns {boolean}
   */
  function _isLangDirty(lang) {
    if (_deletionsMarked[lang]) return true;
    if (_editedValues[lang] !== _originalValues[lang]) return true;
    if (_editedActiveFlags[lang] !== _originalActiveFlags[lang]) return true;
    return false;
  }

  /**
   * Update the dirty-dot and inactive-override indicators on each language tab.
   * Reads the current textarea/toggle for `_editLang` live (without persisting).
   * @returns {void}
   */
  function _updateTabDirtyDots() {
    if (!dialog || LANGUAGES.length <= 1) return;
    var tabs = dialog.querySelectorAll(".lt-editor__tab");
    for (var i = 0; i < tabs.length; i++) {
      var lang = tabs[i].dataset.lang;
      var markedForDelete = !!_deletionsMarked[lang];
      var dirty;
      var activeNow;
      if (lang === _editLang) {
        // Read live from DOM for the active tab
        var ta = dialog.querySelector("#lt-input-" + lang);
        var cb = dialog.querySelector("#lt-active-" + lang);
        dirty = markedForDelete ||
                (ta && ta.value !== _originalValues[lang]) ||
                (cb && cb.checked !== _originalActiveFlags[lang]);
        activeNow = cb ? cb.checked : _editedActiveFlags[lang];
      } else {
        dirty = _isLangDirty(lang);
        activeNow = _editedActiveFlags[lang] !== undefined ? _editedActiveFlags[lang] : ACTIVE_BY_DEFAULT;
      }
      if (dirty) {
        tabs[i].classList.add("lt-editor__tab--dirty");
      } else {
        tabs[i].classList.remove("lt-editor__tab--dirty");
      }
      // Red dot: marked for deletion (supersedes amber dot)
      if (markedForDelete) {
        tabs[i].classList.add("lt-editor__tab--marked-delete");
        tabs[i].classList.remove("lt-editor__tab--inactive-override");
      } else {
        tabs[i].classList.remove("lt-editor__tab--marked-delete");
        // Amber dot: override exists on server but current active state is off
        var entry = (_editData && _editData.translations[lang]) || {};
        if (entry.has_override && !activeNow) {
          tabs[i].classList.add("lt-editor__tab--inactive-override");
        } else {
          tabs[i].classList.remove("lt-editor__tab--inactive-override");
        }
      }
    }
  }

  /**
   * Render the editor content area for the currently selected language.
   * @returns {void}
   */
  function _renderEditorPanels() {
    var container = dialog.querySelector(".lt-dialog__fields");
    container.innerHTML = "";

    var wrapper = document.createElement("div");
    wrapper.className = "lt-editor__single";
    _renderEditPanel(wrapper);
    container.appendChild(wrapper);

    // Focus and auto-resize textarea
    var ta = container.querySelector("textarea");
    if (ta) {
      ta.focus();
      ta.style.height = "auto";
      ta.style.height = ta.scrollHeight + "px";
    }
    _syncDeleteOverride();
  }

  /**
   * Render the edit panel for the currently selected language.
   * Contains .po default hint, textarea, and active toggle.
   * Textarea is disabled when the language is marked for deletion.
   * @param {HTMLElement} container - Parent element to render into.
   * @returns {void}
   */
  function _renderEditPanel(container) {
    container.innerHTML = "";
    var lang = _editLang;
    var entry = (_editData.translations[lang]) || { msgstr: "", fuzzy: false };
    var poDefaults = _editData.defaults || {};
    var poDefault = poDefaults[lang] || "";
    var hasOverride = !!entry.has_override;
    var markedForDelete = !!_deletionsMarked[lang];

    // Show language label in single-language mode (no tabs to indicate it)
    if (LANGUAGES.length <= 1) {
      var langLabelEl = document.createElement("label");
      langLabelEl.className = "lt-field__label";
      langLabelEl.textContent = langLabel(lang);
      langLabelEl.setAttribute("for", "lt-input-" + lang);
      container.appendChild(langLabelEl);
    }

    // .po default hint (click to copy)
    if (poDefault) {
      var poWrap = document.createElement("div");
      poWrap.className = "lt-field__po-wrap";

      var poHeader = document.createElement("div");
      poHeader.className = "lt-field__po-header";

      var poLabel = document.createElement("span");
      poLabel.className = "lt-field__po-label";
      poLabel.textContent = "Default";

      var poCopyIcon = document.createElement("span");
      poCopyIcon.className = "lt-field__po-copy";
      poCopyIcon.title = "Copy default";

      poHeader.appendChild(poLabel);
      poHeader.appendChild(poCopyIcon);

      var poText = document.createElement("div");
      poText.className = "lt-field__po-default";
      poText.textContent = poDefault;

      poWrap.appendChild(poHeader);
      poWrap.appendChild(poText);
      container.appendChild(poWrap);

      _makeCopyable(
        poWrap,
        poCopyIcon,
        function () { return poDefault; },
        "lt-field__po-wrap--copied"
      );
    }

    // Textarea
    var textarea = document.createElement("textarea");
    textarea.className = "lt-field__input";
    textarea.id = "lt-input-" + lang;
    textarea.name = lang;
    textarea.value = _editedValues[lang] || "";
    textarea.rows = 3;
    if (entry.fuzzy) {
      textarea.classList.add("lt-field__input--fuzzy");
    }
    if (markedForDelete) {
      textarea.disabled = true;
      textarea.classList.add("lt-field__input--marked-delete");
    }

    // Active toggle
    var isActive = _editedActiveFlags[lang];
    var currentVal = _editedValues[lang] || "";

    var toggleWrap = document.createElement("label");
    toggleWrap.className = "lt-field__toggle";
    if (markedForDelete || (!hasOverride && currentVal === poDefault)) {
      toggleWrap.style.display = "none";
    }

    var checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "lt-field__toggle-input";
    checkbox.id = "lt-active-" + lang;
    checkbox.checked = isActive;

    var slider = document.createElement("span");
    slider.className = "lt-field__toggle-slider";

    var toggleLabelEl = document.createElement("span");
    toggleLabelEl.className = "lt-field__toggle-label";
    toggleLabelEl.textContent = isActive ? "Active" : "Inactive";

    checkbox.addEventListener("change", function () {
      toggleLabelEl.textContent = checkbox.checked ? "Active" : "Inactive";
      _updateTabDirtyDots();
    });

    toggleWrap.title = "Inactive overrides are saved but won\u2019t take effect until activated.";
    toggleWrap.appendChild(checkbox);
    toggleWrap.appendChild(slider);
    toggleWrap.appendChild(toggleLabelEl);

    // Show/hide toggle + auto-resize on input
    (function (ta, toggle, defaultVal, cb, defaultActive, hadOverride) {
      function syncToggle() {
        var differs = ta.value !== defaultVal;
        toggle.style.display = (differs || hadOverride) ? "" : "none";
        if (!differs && !hadOverride) {
          cb.checked = defaultActive;
        }
      }
      ta.addEventListener("input", function () {
        this.style.height = "auto";
        this.style.height = this.scrollHeight + "px";
        syncToggle();
        _updateTabDirtyDots();
      });
    })(textarea, toggleWrap, poDefault, checkbox, ACTIVE_BY_DEFAULT, hasOverride);

    container.appendChild(textarea);
    container.appendChild(toggleWrap);
  }

  /**
   * Display or clear the inline error banner inside the dialog.
   *
   * When `details` is provided, the error is rendered as per-language lines
   * (e.g. missing `%(key)s` placeholders). Otherwise `message` is shown as plain text.
   *
   * @param {string|null}                     message - Error message, or null to clear.
   * @param {Object<string, string[]>|null}   [details] - Per-language error arrays from the server.
   * @returns {void}
   */
  function showDialogError(message, details) {
    var errorEl = dialog.querySelector(".lt-dialog__error");
    if (!message) {
      errorEl.innerHTML = "";
      errorEl.style.display = "none";
      return;
    }
    errorEl.innerHTML = "";
    if (details) {
      // Structured per-language errors: {lang: ["missing %(key)s", ...]}
      for (var lang in details) {
        var line = document.createElement("div");
        var meta = LANG_META[lang];
        var label = meta ? meta.flag + " " + meta.name : lang.toUpperCase();
        line.textContent = label + ": " + details[lang].join(", ");
        errorEl.appendChild(line);
      }
    } else {
      errorEl.textContent = message;
    }
    errorEl.style.display = "block";
  }

  /**
   * Show or hide the "Delete Override" footer button and sync its checkbox state.
   * Visible whenever an override exists on the server for the current language.
   * The button acts as a toggle: clicking marks/unmarks the language for deletion.
   * @returns {void}
   */
  function _syncDeleteOverride() {
    if (!dialog) return;
    var btn = dialog.querySelector(".lt-btn--delete-override");
    if (!btn || !_editData) return;
    var lang = _editLang;
    var entry = (_editData.translations[lang]) || {};

    if (!entry.has_override) {
      btn.style.display = "none";
      return;
    }

    btn.style.display = "";
    var marked = !!_deletionsMarked[lang];

    if (marked) {
      btn.innerHTML = ICON_CHECKBOX_CHECKED_SVG + " Delete Override";
      btn.classList.add("lt-btn--delete-override--checked");
    } else {
      btn.innerHTML = ICON_CHECKBOX_SVG + " Delete Override";
      btn.classList.remove("lt-btn--delete-override--checked");
    }
  }

  /**
   * Toggle the current language's "marked for deletion" flag.
   * Actual deletion happens on Save (all marked languages at once).
   * @returns {void}
   */
  function handleDeleteOverride() {
    _persistCurrentEdit();
    var lang = _editLang;
    if (_deletionsMarked[lang]) {
      delete _deletionsMarked[lang];
    } else {
      _deletionsMarked[lang] = true;
    }
    _renderEditorPanels();
    _updateTabDirtyDots();
  }

  function handleSave() {
    var saveBtn = dialog.querySelector(".lt-btn--save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    showDialogError(null);

    // Capture whatever is in the current textarea/toggle before sending
    _persistCurrentEdit();

    var attrData = currentAttrName ? _getAttrInfo(currentSpan, currentAttrName) : null;
    var msgid = attrData ? attrData.m : currentSpan.dataset.ltMsgid;
    var context = attrData ? attrData.c : (currentSpan.dataset.ltContext || "");

    // Separate languages into save vs delete groups
    var translations = {};
    var activeFlags = {};
    var activeFlagChanged = false;
    var langsToDelete = [];
    for (var i = 0; i < LANGUAGES.length; i++) {
      var lang = LANGUAGES[i];
      if (_deletionsMarked[lang]) {
        langsToDelete.push(lang);
        continue;
      }
      translations[lang] = _editedValues[lang] !== undefined ? _editedValues[lang] : "";
      activeFlags[lang] = _editedActiveFlags[lang] !== undefined ? _editedActiveFlags[lang] : ACTIVE_BY_DEFAULT;
      if (activeFlags[lang] !== (_originalActiveFlags[lang] !== undefined ? _originalActiveFlags[lang] : ACTIVE_BY_DEFAULT)) {
        activeFlagChanged = true;
      }
    }

    // Build parallel work: save non-deleted languages + delete marked ones
    var work = [];
    if (Object.keys(translations).length > 0) {
      work.push(api.saveTranslations(msgid, context, translations, activeFlags));
    }
    if (langsToDelete.length > 0) {
      work.push(api.deleteTranslation(msgid, context, langsToDelete));
    }

    if (work.length === 0) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
      closeModal();
      return;
    }

    Promise.all(work)
      .then(function () {
        var needsReload = activeFlagChanged || langsToDelete.length > 0;
        if (!needsReload) {
          for (var i = 0; i < LANGUAGES.length; i++) {
            var lang = LANGUAGES[i];
            if (_deletionsMarked[lang]) continue;
            var textChanged = translations[lang] !== (_originalValues[lang] || "");
            if (textChanged && (activeFlags[lang] || PREVIEW)) {
              needsReload = true;
              break;
            }
          }
        }
        if (needsReload) {
          _reloadPage();
        } else {
          saveBtn.disabled = false;
          saveBtn.textContent = "Save";
          closeModal();
        }
      })
      .catch(function (err) {
        showDialogError(err.message, err.details || null);
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
      });
  }

  /**
   * Look up a single attribute descriptor from the element's `data-lt-attrs` JSON array.
   * @param {HTMLElement} element  - Element carrying `data-lt-attrs`.
   * @param {string}      attrName - Attribute name to find (e.g. "title").
   * @returns {AttrInfo|null} The matching descriptor, or null if not found.
   */
  function _getAttrInfo(element, attrName) {
    try {
      var attrs = JSON.parse(element.dataset.ltAttrs || "[]");
      for (var i = 0; i < attrs.length; i++) {
        if (attrs[i].a === attrName) return attrs[i];
      }
    } catch (e) { /* ignore parse errors */ }
    return null;
  }

  // ─── History Panel ──────────────────────────────────

  /** @type {HistoryEntry[]} - Cached entries from the last history fetch. */
  var _historyData = [];
  /** @type {string} - Active language filter ("" = show all languages). */
  var _historyLangFilter = "";

  /**
   * Read the msgid and context for the element currently being edited,
   * accounting for both inline text spans and attribute translations.
   * @returns {{msgid: string, context: string}}
   */
  function _getMsgidAndContext() {
    var attrData = currentAttrName ? _getAttrInfo(currentSpan, currentAttrName) : null;
    return {
      msgid: attrData ? attrData.m : currentSpan.dataset.ltMsgid,
      context: attrData ? attrData.c : (currentSpan.dataset.ltContext || ""),
    };
  }

  /**
   * Toggle the dialog between the edit form and the history timeline.
   * @returns {void}
   */
  function toggleHistory() {
    if (historyOpen) {
      _showEditView();
    } else {
      _showHistoryView();
    }
    historyOpen = !historyOpen;
  }

  /**
   * Switch the dialog chrome to show the translation editor (tabs + fields + save/cancel).
   * @returns {void}
   */
  function _showEditView() {
    if (!dialog) return;
    dialog.querySelector(".lt-dialog__title").textContent = "Edit Translation";
    var btn = dialog.querySelector(".lt-btn--history");
    btn.innerHTML = dialog._ltIconHistory;
    btn.title = "View edit history";

    var tabBar = dialog.querySelector(".lt-editor__tabs");
    if (tabBar) tabBar.style.display = LANGUAGES.length > 1 ? "" : "none";

    dialog.querySelector(".lt-dialog__fields").style.display = "";
    dialog.querySelector(".lt-dialog__actions").style.display = "";
    dialog.querySelector(".lt-dialog__history").style.display = "none";

    // Restore hint visibility
    if (_editData && _editData.hint) {
      dialog.querySelector(".lt-dialog__hint").style.display = "block";
    }
  }

  /**
   * Switch the dialog chrome to show the history timeline, fetching data from the API.
   * @returns {void}
   */
  function _showHistoryView() {
    if (!dialog) return;
    dialog.querySelector(".lt-dialog__title").textContent = "Edit History";
    var btn = dialog.querySelector(".lt-btn--history");
    btn.innerHTML = dialog._ltIconBack;
    btn.title = "Back to editing";

    // Persist current edits before switching views
    _persistCurrentEdit();

    var tabBar = dialog.querySelector(".lt-editor__tabs");
    if (tabBar) tabBar.style.display = "none";

    dialog.querySelector(".lt-dialog__fields").style.display = "none";
    dialog.querySelector(".lt-dialog__hint").style.display = "none";
    dialog.querySelector(".lt-dialog__actions").style.display = "none";
    dialog.querySelector(".lt-dialog__error").style.display = "none";

    var historyEl = dialog.querySelector(".lt-dialog__history");
    historyEl.style.display = "block";
    historyEl.innerHTML =
      '<div class="lt-history__loading">Loading history\u2026</div>';

    _historyLangFilter = "";
    _historyData = [];

    var info = _getMsgidAndContext();
    api
      .getHistory(info.msgid, info.context)
      .then(function (data) {
        _historyData = data.history || [];
        _renderHistoryPanel(historyEl);
      })
      .catch(function () {
        historyEl.innerHTML =
          '<div class="lt-history__empty">Failed to load history.</div>';
      });
  }

  /** @type {Object<string, string>} - Human-readable labels for history action types. */
  var _ACTION_LABELS = {
    create: "Created",
    update: "Updated",
    "delete": "Deleted",
    activate: "Activated",
    deactivate: "Deactivated",
  };

  /** @type {Object<string, string>} - Inline SVG markup for each history action type. */
  var _ACTION_ICONS = {
    create: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8 3v10M3 8h10"/></svg>',
    update: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 11v2.5H5L13 5.5 10.5 3 2.5 11z"/><path d="M9 4.5l2.5 2.5"/></svg>',
    "delete": '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10"/><path d="M6.5 4.5V3a.5.5 0 01.5-.5h2a.5.5 0 01.5.5v1.5"/><path d="M5 4.5V13a1 1 0 001 1h4a1 1 0 001-1V4.5"/></svg>',
    activate: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="12" height="6" rx="3"/><circle cx="11" cy="8" r="2" fill="currentColor"/></svg>',
    deactivate: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="12" height="6" rx="3"/><circle cx="5" cy="8" r="2"/></svg>',
  };

  /**
   * Render the history timeline into the given container.
   *
   * Builds language filter pills (when multiple languages have history),
   * applies the current `_historyLangFilter`, and renders a chronological
   * list of history entries with diff views and restore controls.
   * Re-called when the user changes the language filter.
   *
   * @param {HTMLElement} container - The `.lt-dialog__history` element to populate.
   * @returns {void}
   */
  function _renderHistoryPanel(container) {
    container.innerHTML = "";

    if (!_historyData || _historyData.length === 0) {
      container.innerHTML =
        '<div class="lt-history__empty">No edit history yet.</div>';
      return;
    }

    // ── Language filter pills ──
    var langs = [];
    var langSet = {};
    for (var k = 0; k < _historyData.length; k++) {
      var l = _historyData[k].language;
      if (!langSet[l]) {
        langSet[l] = true;
        langs.push(l);
      }
    }
    langs.sort();

    if (langs.length > 1) {
      var filterBar = document.createElement("div");
      filterBar.className = "lt-history__filters";

      var allPill = document.createElement("button");
      allPill.type = "button";
      allPill.className = "lt-history__filter-pill" + (!_historyLangFilter ? " lt-history__filter-pill--active" : "");
      allPill.textContent = "All";
      allPill.addEventListener("click", function () {
        _historyLangFilter = "";
        _renderHistoryPanel(container);
      });
      filterBar.appendChild(allPill);

      for (var p = 0; p < langs.length; p++) {
        (function (code) {
          var meta = LANG_META[code];
          var pill = document.createElement("button");
          pill.type = "button";
          pill.className = "lt-history__filter-pill" + (_historyLangFilter === code ? " lt-history__filter-pill--active" : "");
          pill.textContent = meta ? meta.flag + " " + meta.name : code.toUpperCase();
          pill.addEventListener("click", function () {
            _historyLangFilter = code;
            _renderHistoryPanel(container);
          });
          filterBar.appendChild(pill);
        })(langs[p]);
      }
      container.appendChild(filterBar);
    }

    // ── Filter entries ──
    var filtered = _historyLangFilter
      ? _historyData.filter(function (e) { return e.language === _historyLangFilter; })
      : _historyData;

    if (filtered.length === 0) {
      var emptyMsg = document.createElement("div");
      emptyMsg.className = "lt-history__empty";
      emptyMsg.textContent = "No history for this language.";
      container.appendChild(emptyMsg);
      return;
    }

    // ── Timeline ──
    var timeline = document.createElement("div");
    timeline.className = "lt-history__timeline";

    // Track the newest (current) entry per language to hide its Restore button
    var newestPerLang = {};
    for (var n = 0; n < filtered.length; n++) {
      if (!newestPerLang[filtered[n].language]) {
        newestPerLang[filtered[n].language] = filtered[n].id;
      }
    }

    for (var i = 0; i < filtered.length; i++) {
      var entry = filtered[i];
      var item = document.createElement("div");
      item.className = "lt-history__entry lt-history__entry--" + entry.action;

      var header = document.createElement("div");
      header.className = "lt-history__entry-header";

      // Action icon (colored container — replaces text label)
      var iconEl = document.createElement("span");
      iconEl.className = "lt-history__icon lt-history__icon--" + entry.action;
      iconEl.innerHTML = _ACTION_ICONS[entry.action] || "";
      iconEl.title = _ACTION_LABELS[entry.action] || entry.action;
      header.appendChild(iconEl);

      // Flag (only when showing all languages)
      var hasFlag = false;
      if (!_historyLangFilter) {
        var langMeta = LANG_META[entry.language];
        if (langMeta) {
          var flag = document.createElement("span");
          flag.className = "lt-history__flag";
          flag.textContent = langMeta.flag;
          header.appendChild(flag);
          hasFlag = true;
        }
      }

      // Separator between flag and time (only when flag is visible)
      if (hasFlag) {
        var sep1 = document.createElement("span");
        sep1.className = "lt-history__sep";
        sep1.textContent = "\u00b7";
        header.appendChild(sep1);
      }

      var time = document.createElement("span");
      time.className = "lt-history__time";
      time.textContent = _formatTime(entry.created_at);
      time.title = new Date(entry.created_at).toLocaleString();
      header.appendChild(time);

      // User
      if (entry.user && entry.user !== "System") {
        var sep2 = document.createElement("span");
        sep2.className = "lt-history__sep";
        sep2.textContent = "\u00b7";
        header.appendChild(sep2);

        var user = document.createElement("span");
        user.className = "lt-history__user";
        user.textContent = entry.user;
        header.appendChild(user);
      }

      item.appendChild(header);

      // ── Content block ──
      var isStateChange = entry.action === "activate" || entry.action === "deactivate";

      if (isStateChange) {
        var statusEl = document.createElement("div");
        statusEl.className = "lt-history__status lt-history__status--" + entry.action;
        var dot = document.createElement("span");
        dot.className = "lt-history__status-dot";
        var statusText = document.createElement("span");
        statusText.textContent = entry.action === "activate"
          ? "Translation enabled"
          : "Translation disabled";
        statusEl.appendChild(dot);
        statusEl.appendChild(statusText);
        item.appendChild(statusEl);
      } else {
        // Build diff view
        var diffView = null;
        if (entry.diff && entry.diff.length > 0) {
          diffView = document.createElement("div");
          diffView.className = "lt-history__diff";
          for (var j = 0; j < entry.diff.length; j++) {
            var seg = entry.diff[j];
            var segSpan = document.createElement("span");
            segSpan.className = "lt-diff lt-diff--" + seg.type;
            segSpan.textContent = seg.text;
            diffView.appendChild(segSpan);
          }
        } else if (entry.action === "create" && entry.new_value) {
          diffView = document.createElement("div");
          diffView.className = "lt-history__diff";
          var cSpan = document.createElement("span");
          cSpan.className = "lt-diff lt-diff--insert";
          cSpan.textContent = entry.new_value;
          diffView.appendChild(cSpan);
        } else if (entry.action === "delete" && entry.old_value) {
          diffView = document.createElement("div");
          diffView.className = "lt-history__diff";
          var dSpan = document.createElement("span");
          dSpan.className = "lt-diff lt-diff--delete";
          dSpan.textContent = entry.old_value;
          diffView.appendChild(dSpan);
        }

        if (diffView) {
          var hasValues = entry.old_value || entry.new_value;
          if (hasValues) {
            // Toggle tabs: Diff / Value
            var tabs = document.createElement("div");
            tabs.className = "lt-history__content-tabs";

            var tDiff = document.createElement("button");
            tDiff.type = "button";
            tDiff.className = "lt-history__content-tab lt-history__content-tab--active";
            tDiff.textContent = "Diff";
            tabs.appendChild(tDiff);

            var tVal = document.createElement("button");
            tVal.type = "button";
            tVal.className = "lt-history__content-tab";
            tVal.textContent = "Value";
            tabs.appendChild(tVal);

            item.appendChild(tabs);
            item.appendChild(diffView);

            // Value view (hidden by default)
            var valView = document.createElement("div");
            valView.className = "lt-history__values";
            valView.style.display = "none";
            _buildValueSections(valView, entry);
            item.appendChild(valView);

            // Toggle handlers (IIFE for var-scoped closure)
            (function (dt, vt, dv, vv) {
              dt.addEventListener("click", function () {
                dt.classList.add("lt-history__content-tab--active");
                vt.classList.remove("lt-history__content-tab--active");
                dv.style.display = "";
                vv.style.display = "none";
              });
              vt.addEventListener("click", function () {
                vt.classList.add("lt-history__content-tab--active");
                dt.classList.remove("lt-history__content-tab--active");
                vv.style.display = "";
                dv.style.display = "none";
              });
            })(tDiff, tVal, diffView, valView);
          } else {
            item.appendChild(diffView);
          }
        }
      }

      // ── Restore button (text changes only, skip current state per language) ──
      var isCurrent = newestPerLang[entry.language] === entry.id;
      if (!isStateChange && !isCurrent) {
        _appendRestoreControl(header, item, entry);
      }

      timeline.appendChild(item);
    }

    container.appendChild(timeline);
  }

  /**
   * Append a "Restore" button and confirmation panel to a history entry.
   *
   * Clicking "Restore" reveals two options: "Restore & activate" and
   * "Restore as inactive", each of which calls `_executeRestore`.
   * The restore value is `new_value` for create/update actions and
   * `old_value` for delete actions (i.e. the state after the event).
   *
   * @param {HTMLElement}  header - The entry's header row (button is appended here).
   * @param {HTMLElement}  item   - The entry's root element (confirmation panel appended here).
   * @param {HistoryEntry} entry  - The history entry data.
   * @returns {void}
   */
  function _appendRestoreControl(header, item, entry) {
    // Determine the value to restore:
    // CREATE/UPDATE → new_value (the state after this event)
    // DELETE → old_value (restore what was removed)
    var restoreValue = entry.action === "delete" ? entry.old_value : entry.new_value;

    // Restore button sits in the header row, right-aligned (like Revert in edit view).
    // When no lang tag precedes it, it needs margin-left:auto to push right.
    var restoreBtn = document.createElement("button");
    restoreBtn.type = "button";
    restoreBtn.className = "lt-history__restore-btn";
    restoreBtn.style.marginLeft = "auto";
    restoreBtn.textContent = "Restore";
    header.appendChild(restoreBtn);

    // Confirmation panel (hidden initially, appended to the item below header)
    var confirm = document.createElement("div");
    confirm.className = "lt-history__restore-confirm";
    confirm.style.display = "none";

    var confirmActions = document.createElement("div");
    confirmActions.className = "lt-history__restore-actions";

    var activateBtn = document.createElement("button");
    activateBtn.type = "button";
    activateBtn.className = "lt-history__restore-activate";
    activateBtn.textContent = "Restore & activate";

    var inactiveBtn = document.createElement("button");
    inactiveBtn.type = "button";
    inactiveBtn.className = "lt-history__restore-inactive";
    inactiveBtn.textContent = "Restore as inactive";

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "lt-history__restore-cancel";
    cancelBtn.textContent = "Cancel";

    confirmActions.appendChild(activateBtn);
    confirmActions.appendChild(inactiveBtn);
    confirmActions.appendChild(cancelBtn);
    confirm.appendChild(confirmActions);

    item.appendChild(confirm);

    restoreBtn.addEventListener("click", function () {
      restoreBtn.style.display = "none";
      confirm.style.display = "block";
    });

    cancelBtn.addEventListener("click", function () {
      confirm.style.display = "none";
      restoreBtn.style.display = "";
    });

    activateBtn.addEventListener("click", function () {
      _executeRestore(entry.language, restoreValue, true, confirm);
    });

    inactiveBtn.addEventListener("click", function () {
      _executeRestore(entry.language, restoreValue, false, confirm);
    });
  }

  /**
   * Save a single-language translation restore and reload the page on success.
   * @param {string}      language  - Language code to restore.
   * @param {string}      value     - The msgstr value to restore.
   * @param {boolean}     activate  - Whether the restored value should be active.
   * @param {HTMLElement} confirmEl - The confirmation panel (buttons are disabled during request).
   * @returns {void}
   */
  function _executeRestore(language, value, activate, confirmEl) {
    // Disable buttons during request
    var buttons = confirmEl.querySelectorAll("button");
    for (var b = 0; b < buttons.length; b++) buttons[b].disabled = true;

    var info = _getMsgidAndContext();
    var translations = {};
    translations[language] = value;
    var activeFlags = {};
    activeFlags[language] = activate;

    api
      .saveTranslations(info.msgid, info.context, translations, activeFlags)
      .then(function () {
        _reloadPage();
      })
      .catch(function (err) {
        // Re-enable buttons on error
        for (var b = 0; b < buttons.length; b++) buttons[b].disabled = false;
        showToast("Restore failed: " + err.message, "error");
      });
  }

  /**
   * Render "Before" / "After" value sections for the history Value tab.
   * @param {HTMLElement}  container - Parent element to append sections into.
   * @param {HistoryEntry} entry     - The history entry with `old_value` and/or `new_value`.
   * @returns {void}
   */
  function _buildValueSections(container, entry) {
    if (entry.old_value) {
      var sec1 = document.createElement("div");
      sec1.className = "lt-history__value-section";
      var lbl1 = document.createElement("div");
      lbl1.className = "lt-history__value-label";
      lbl1.textContent = "Before";
      var txt1 = document.createElement("div");
      txt1.className = "lt-history__value-text";
      txt1.textContent = entry.old_value;
      sec1.appendChild(lbl1);
      sec1.appendChild(txt1);
      container.appendChild(sec1);
    }
    if (entry.new_value) {
      var sec2 = document.createElement("div");
      sec2.className = "lt-history__value-section";
      var lbl2 = document.createElement("div");
      lbl2.className = "lt-history__value-label";
      lbl2.textContent = "After";
      var txt2 = document.createElement("div");
      txt2.className = "lt-history__value-text";
      txt2.textContent = entry.new_value;
      sec2.appendChild(lbl2);
      sec2.appendChild(txt2);
      container.appendChild(sec2);
    }
  }

  /**
   * Format an ISO 8601 timestamp as a human-friendly relative time string
   * (e.g. "just now", "5m ago", "3d ago") or a locale date for older entries.
   * @param {string} isoString - ISO 8601 date string from the API.
   * @returns {string}
   */
  function _formatTime(isoString) {
    var date = new Date(isoString);
    var now = new Date();
    var diffMs = now - date;
    var diffSec = Math.floor(diffMs / 1000);
    var diffMins = Math.floor(diffMs / 60000);
    var diffHours = Math.floor(diffMs / 3600000);
    var diffDays = Math.floor(diffMs / 86400000);

    if (diffSec < 10) return "just now";
    if (diffSec < 60) return diffSec + "s ago";
    if (diffMins < 60) return diffMins + "m ago";
    if (diffHours < 24) return diffHours + "h ago";
    if (diffDays < 7) return diffDays + "d ago";
    if (diffDays < 30) return Math.floor(diffDays / 7) + "w ago";
    return date.toLocaleDateString();
  }

  /**
   * Close the dialog and reset editing state back to "active" mode.
   * @returns {void}
   */
  function closeModal() {
    if (dialog && dialog.open) {
      dialog.close();
    }
    currentSpan = null;
    currentAttrName = null;
    historyOpen = false;
    _editData = null;
    _editLang = "";
    _editedValues = {};
    _editedActiveFlags = {};
    _originalValues = {};
    _originalActiveFlags = {};
    _deletionsMarked = {};
    if (dialog) {
      var delBtn = dialog.querySelector(".lt-btn--delete-override");
      if (delBtn) {
        delBtn.style.display = "none";
        delBtn.classList.remove("lt-btn--delete-override--checked");
      }
    }
    if (state === "editing") {
      state = "active";
    }
  }

  // ─── Preview Mode: Multi-select & Action Bar ────────

  /** @type {HTMLElement[]} */
  var selectedElements = [];
  /** @type {HTMLElement|null} */
  var actionBar = null;
  /** @type {boolean} */
  var actionBarConfirming = false;

  /**
   * Toggle an element's selection state for bulk activation.
   * @param {HTMLElement} el - The element to toggle.
   * @returns {void}
   */
  function _toggleSelected(el) {
    var idx = selectedElements.indexOf(el);
    if (idx !== -1) {
      selectedElements.splice(idx, 1);
      el.classList.remove("lt-selected");
    } else {
      selectedElements.push(el);
      el.classList.add("lt-selected");
    }
    _updateActionBar();
  }

  /**
   * Clear all selected elements.
   * @returns {void}
   */
  function _clearSelection() {
    for (var i = 0; i < selectedElements.length; i++) {
      selectedElements[i].classList.remove("lt-selected");
    }
    selectedElements = [];
    _updateActionBar();
  }

  /**
   * Create the floating action bar element (called once on preview init).
   * @returns {void}
   */
  function _createActionBar() {
    if (actionBar) return;
    actionBar = document.createElement("div");
    actionBar.className = "lt-action-bar";
    document.body.appendChild(actionBar);
    _renderActionBarDefault();
  }

  /**
   * Render the action bar in its default state (count + activate + clear).
   * @returns {void}
   */
  function _renderActionBarDefault() {
    if (!actionBar) return;
    actionBarConfirming = false;
    var count = selectedElements.length;
    actionBar.innerHTML =
      '<span class="lt-action-bar__count">' + count + " selected</span>" +
      '<button type="button" class="lt-action-bar__activate">Activate</button>' +
      '<button type="button" class="lt-action-bar__clear">Clear</button>';
    actionBar.querySelector(".lt-action-bar__activate").addEventListener("click", _showActivateConfirm);
    actionBar.querySelector(".lt-action-bar__clear").addEventListener("click", _clearSelection);
  }

  /**
   * Show/hide the action bar based on selection count.
   * @returns {void}
   */
  function _updateActionBar() {
    if (!actionBar) return;
    var count = selectedElements.length;
    if (count === 0) {
      actionBar.classList.remove("lt-action-bar--visible");
      actionBarConfirming = false;
      _renderActionBarDefault();
      return;
    }
    actionBar.classList.add("lt-action-bar--visible");
    if (!actionBarConfirming) {
      _renderActionBarDefault();
    }
  }

  /**
   * Switch the action bar to confirmation state with a warning.
   * @returns {void}
   */
  function _showActivateConfirm() {
    actionBarConfirming = true;
    var count = selectedElements.length;
    var lang = (document.documentElement.lang || "").toLowerCase() || "unknown";
    actionBar.innerHTML =
      '<span class="lt-action-bar__warning">' +
      "This will activate " + count + " translation(s) for language \"" + lang + "\". Continue?" +
      "</span>" +
      '<button type="button" class="lt-action-bar__confirm">Confirm</button>' +
      '<button type="button" class="lt-action-bar__cancel">Cancel</button>';
    actionBar.querySelector(".lt-action-bar__confirm").addEventListener("click", _executeBulkActivate);
    actionBar.querySelector(".lt-action-bar__cancel").addEventListener("click", function () {
      _renderActionBarDefault();
    });
  }

  /**
   * Collect selected msgid/context pairs and POST to the bulk-activate endpoint.
   * @returns {void}
   */
  function _executeBulkActivate() {
    var confirmBtn = actionBar.querySelector(".lt-action-bar__confirm");
    if (confirmBtn) confirmBtn.disabled = true;

    var msgids = [];
    var seen = {};

    for (var i = 0; i < selectedElements.length; i++) {
      var el = selectedElements[i];

      if (el.dataset.ltMsgid) {
        // Inline text span
        var msgid = el.dataset.ltMsgid;
        var context = el.dataset.ltContext || "";
        var key = msgid + "\x00" + context;
        if (!seen[key]) {
          seen[key] = true;
          msgids.push({ msgid: msgid, context: context });
        }
      } else if (el.dataset.ltAttrs) {
        // Attribute element — collect all preview entries
        try {
          var attrs = JSON.parse(el.dataset.ltAttrs);
          for (var j = 0; j < attrs.length; j++) {
            var aKey = attrs[j].m + "\x00" + (attrs[j].c || "");
            if (!seen[aKey]) {
              seen[aKey] = true;
              msgids.push({ msgid: attrs[j].m, context: attrs[j].c || "" });
            }
          }
        } catch (e) { /* ignore */ }
      }
    }

    if (msgids.length === 0) {
      showToast("No translations to activate", "error");
      _renderActionBarDefault();
      return;
    }

    var lang = (document.documentElement.lang || "").toLowerCase();

    api
      .bulkActivate(msgids, lang)
      .then(function (data) {
        showToast(data.activated + " translation(s) activated", "success");
        _reloadPage();
      })
      .catch(function (err) {
        showToast("Bulk activate failed: " + err.message, "error");
        if (confirmBtn) confirmBtn.disabled = false;
      });
  }

  /**
   * Initialize preview mode: mark elements with inactive overrides and create the action bar.
   * Called once on DOMContentLoaded when PREVIEW is true.
   * @returns {void}
   */
  function _initPreviewMode() {
    // Build lookup from config
    var lookup = {};
    for (var i = 0; i < PREVIEW_ENTRIES.length; i++) {
      var e = PREVIEW_ENTRIES[i];
      lookup[e.m + "\x00" + (e.c || "")] = true;
    }

    // Mark inline text spans
    var spans = document.querySelectorAll(".lt-translatable");
    for (var s = 0; s < spans.length; s++) {
      var sp = spans[s];
      var spKey = (sp.dataset.ltMsgid || "") + "\x00" + (sp.dataset.ltContext || "");
      if (lookup[spKey]) {
        sp.classList.add("lt-preview");
      }
    }

    // Mark attribute-translatable elements
    var attrEls = document.querySelectorAll("[data-lt-attrs]");
    for (var a = 0; a < attrEls.length; a++) {
      try {
        var attrs = JSON.parse(attrEls[a].dataset.ltAttrs || "[]");
        for (var j = 0; j < attrs.length; j++) {
          var aKey = (attrs[j].m || "") + "\x00" + (attrs[j].c || "");
          if (lookup[aKey]) {
            attrEls[a].classList.add("lt-preview");
            break;
          }
        }
      } catch (e) { /* ignore parse errors */ }
    }

    _createActionBar();
  }

  // ─── Edit Mode Toggle ───────────────────────────────

  /**
   * Enter translation edit mode: add the body class that highlights translatable
   * elements.
   * @returns {void}
   */
  function activateEditMode() {
    state = "active";
    document.body.classList.add("lt-edit-mode");
    _updateHintActiveState();
  }

  /**
   * Leave translation edit mode: close any open modal, remove the body class.
   * @returns {void}
   */
  function deactivateEditMode() {
    closeModal();
    _clearSelection();
    state = "inactive";
    document.body.classList.remove("lt-edit-mode");
    _updateHintActiveState();
  }

  // ─── Keyboard Handler ───────────────────────────────

  document.addEventListener("keydown", function (e) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    var inInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

    // Toggle edit mode
    if (_matchShortcut(e, SC_EDIT)) {
      if (inInput) return;
      e.preventDefault();
      if (state === "inactive") {
        activateEditMode();
      } else {
        deactivateEditMode();
      }
    }

    // Toggle preview mode (cookie + reload)
    if (_matchShortcut(e, SC_PREVIEW)) {
      if (inInput) return;
      e.preventDefault();
      if (document.cookie.indexOf("lt_preview=1") !== -1) {
        document.cookie = "lt_preview=; path=/; max-age=0";
      } else {
        document.cookie = "lt_preview=1; path=/; max-age=86400; SameSite=Lax";
      }
      window.location.reload();
    }
  });

  // ─── Click Handler (delegated) ──────────────────────

  document.addEventListener(
    "click",
    function (e) {
      if (state !== "active") return;

      // Check for inline text span first
      var span = e.target.closest(".lt-translatable");
      if (span) {
        e.preventDefault();
        e.stopPropagation();

        // Shift+click on preview elements toggles selection
        if (e.shiftKey && PREVIEW && span.classList.contains("lt-preview")) {
          _toggleSelected(span);
          window.getSelection().removeAllRanges();
          return;
        }

        openModal(span);
        return;
      }

      // Check for attribute-translatable element
      var attrEl = e.target.closest("[data-lt-attrs]");
      if (attrEl) {
        e.preventDefault();
        e.stopPropagation();

        // Shift+click on preview elements toggles selection
        if (e.shiftKey && PREVIEW && attrEl.classList.contains("lt-preview")) {
          _toggleSelected(attrEl);
          window.getSelection().removeAllRanges();
          return;
        }

        var attrs;
        try {
          attrs = JSON.parse(attrEl.dataset.ltAttrs);
        } catch (err) {
          return;
        }
        if (!attrs || !attrs.length) return;

        if (attrs.length === 1) {
          // Single translated attribute — open directly
          openModal(attrEl, attrs[0]);
        } else {
          // Multiple translated attributes — show picker
          _showAttrPicker(attrEl, attrs);
        }
      }
    },
    true
  ); // Use capture phase to intercept before other handlers

  // ─── Attribute Picker (for elements with multiple translated attrs) ──

  /**
   * Handle elements with multiple translated attributes (e.g. both `title` and
   * `placeholder`). Currently opens the editor for the first attribute only;
   * a multi-attribute picker UI is planned for a future release.
   * @param {HTMLElement} element - The element carrying `data-lt-attrs`.
   * @param {AttrInfo[]}  attrs   - Parsed array of attribute descriptors.
   * @returns {void}
   */
  function _showAttrPicker(element, attrs) {
    openModal(element, attrs[0]);
  }

  // ─── Edit Mode Restore After Reload ──────────────────

  document.addEventListener("DOMContentLoaded", function () {
    try {
      if (sessionStorage.getItem(_EDIT_MODE_KEY)) {
        sessionStorage.removeItem(_EDIT_MODE_KEY);
        if (state === "inactive") {
          activateEditMode();
        }
      }
    } catch (e) { /* private browsing / quota */ }
  });

  // ─── Preview Mode Auto-Activation ───────────────────

  if (PREVIEW) {
    document.addEventListener("DOMContentLoaded", function () {
      activateEditMode();
      _initPreviewMode();
    });
  }

  // ─── Shortcut Hint (sticky bar) ──────────────────────

  /** @type {string} */
  var _HINT_POS_KEY = "lt_hint_pos";
  /** @type {HTMLElement|null} */
  var _hintBar = null;
  /** @type {boolean} - True while a drag gesture is in progress (past threshold). */
  var _hintDidDrag = false;

  /**
   * Show a persistent shortcut hint bar at the bottom of the viewport.
   * The entire bar is draggable. Edit/Preview are clickable toggle buttons.
   * Position is remembered in localStorage.
   * @returns {void}
   */
  function _showShortcutHint() {
    var bar = document.createElement("div");
    bar.className = "lt-hint";

    // Brand label
    var brand = document.createElement("span");
    brand.className = "lt-hint__brand";
    brand.textContent = "Live Translations";
    bar.appendChild(brand);

    // Separator after brand
    var sep0 = document.createElement("span");
    sep0.className = "lt-hint__sep";
    bar.appendChild(sep0);

    // Edit mode button
    var editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "lt-hint__action";
    editBtn.dataset.mode = "edit";
    editBtn.title = "Toggle inline translation editor";
    editBtn.innerHTML =
      '<kbd class="lt-hint__kbd">' + _formatShortcut(SC_EDIT) + "</kbd>" +
      '<span class="lt-hint__label">Edit</span>';
    editBtn.addEventListener("click", function () {
      if (_hintDidDrag) return;
      if (state === "inactive") {
        activateEditMode();
      } else {
        deactivateEditMode();
      }
    });
    bar.appendChild(editBtn);

    // Preview mode button
    var previewBtn = document.createElement("button");
    previewBtn.type = "button";
    previewBtn.className = "lt-hint__action";
    previewBtn.dataset.mode = "preview";
    previewBtn.title = "Preview translations from the database";
    previewBtn.innerHTML =
      '<kbd class="lt-hint__kbd">' + _formatShortcut(SC_PREVIEW) + "</kbd>" +
      '<span class="lt-hint__label">Preview</span>';
    previewBtn.addEventListener("click", function () {
      if (_hintDidDrag) return;
      if (document.cookie.indexOf("lt_preview=1") !== -1) {
        document.cookie = "lt_preview=; path=/; max-age=0";
      } else {
        document.cookie = "lt_preview=1; path=/; max-age=86400; SameSite=Lax";
      }
      window.location.reload();
    });
    bar.appendChild(previewBtn);

    // Preview tip (visible only in preview mode)
    var tip = document.createElement("span");
    tip.className = "lt-hint__tip";
    tip.title = "Hold Shift and click translated text to select multiple entries";
    tip.innerHTML = '<kbd class="lt-hint__kbd">Shift</kbd><span class="lt-hint__label">click to select</span>';
    bar.appendChild(tip);

    document.body.appendChild(bar);
    _hintBar = bar;

    // Restore saved position or use default centered bottom
    var savedPos = null;
    try {
      var raw = localStorage.getItem(_HINT_POS_KEY);
      if (raw) savedPos = JSON.parse(raw);
    } catch (e) { /* ignore */ }

    if (savedPos && typeof savedPos.x === "number" && typeof savedPos.y === "number") {
      var x = Math.max(0, Math.min(window.innerWidth - bar.offsetWidth, savedPos.x));
      var y = Math.max(0, Math.min(window.innerHeight - bar.offsetHeight, savedPos.y));
      bar.style.left = x + "px";
      bar.style.top = y + "px";
      bar.classList.add("lt-hint--positioned");
    }

    _updateHintActiveState();
    _initHintDrag(bar);

    void bar.offsetHeight;
    bar.classList.add("lt-hint--visible");
  }

  /** @type {number} - Pixel threshold to distinguish click from drag. */
  var _DRAG_THRESHOLD = 3;

  /**
   * Make the entire hint bar draggable.
   * Uses a movement threshold to distinguish clicks from drags — button
   * click handlers check `_hintDidDrag` and bail if a drag just occurred.
   * @param {HTMLElement} bar - The hint bar element.
   * @returns {void}
   */
  function _initHintDrag(bar) {
    var dragState = null;

    bar.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return;
      // Don't prevent default — let clicks reach buttons if no drag happens

      var rect = bar.getBoundingClientRect();
      dragState = {
        mouseX: e.clientX,
        mouseY: e.clientY,
        barX: rect.left,
        barY: rect.top,
        moved: false,
      };
      _hintDidDrag = false;
    });

    document.addEventListener("mousemove", function (e) {
      if (!dragState) return;

      var dx = e.clientX - dragState.mouseX;
      var dy = e.clientY - dragState.mouseY;

      // Only start dragging after passing the threshold
      if (!dragState.moved) {
        if (Math.abs(dx) < _DRAG_THRESHOLD && Math.abs(dy) < _DRAG_THRESHOLD) return;
        dragState.moved = true;
        _hintDidDrag = true;

        // Switch from center-anchored to explicit positioning on first drag
        if (!bar.classList.contains("lt-hint--positioned")) {
          bar.style.left = dragState.barX + "px";
          bar.style.top = dragState.barY + "px";
          bar.classList.add("lt-hint--positioned");
        }

        bar.classList.add("lt-hint--dragging");
      }

      var newX = dragState.barX + dx;
      var newY = dragState.barY + dy;
      var maxX = window.innerWidth - bar.offsetWidth;
      var maxY = window.innerHeight - bar.offsetHeight;
      bar.style.left = Math.max(0, Math.min(maxX, newX)) + "px";
      bar.style.top = Math.max(0, Math.min(maxY, newY)) + "px";
    });

    document.addEventListener("mouseup", function () {
      if (!dragState) return;
      var wasDrag = dragState.moved;
      dragState = null;
      bar.classList.remove("lt-hint--dragging");

      if (wasDrag) {
        // Persist position
        try {
          localStorage.setItem(_HINT_POS_KEY, JSON.stringify({
            x: parseInt(bar.style.left, 10),
            y: parseInt(bar.style.top, 10),
          }));
        } catch (e) { /* ignore */ }

        // Reset drag flag after a tick so the click event (which fires after
        // mouseup) still sees _hintDidDrag=true and is suppressed
        setTimeout(function () { _hintDidDrag = false; }, 0);
      }
    });
  }

  /**
   * Update the hint bar to highlight the currently active mode.
   * @returns {void}
   */
  function _updateHintActiveState() {
    if (!_hintBar) return;
    var editEl = _hintBar.querySelector('[data-mode="edit"]');
    var previewEl = _hintBar.querySelector('[data-mode="preview"]');
    var tipEl = _hintBar.querySelector(".lt-hint__tip");
    if (editEl) {
      if (state === "active" || state === "editing") {
        editEl.classList.add("lt-hint__action--active");
      } else {
        editEl.classList.remove("lt-hint__action--active");
      }
    }
    if (previewEl) {
      if (PREVIEW) {
        previewEl.classList.add("lt-hint__action--active");
      } else {
        previewEl.classList.remove("lt-hint__action--active");
      }
    }
    if (tipEl) {
      if (PREVIEW) {
        tipEl.classList.add("lt-hint__tip--visible");
      } else {
        tipEl.classList.remove("lt-hint__tip--visible");
      }
    }
  }

  _showShortcutHint();
})();
