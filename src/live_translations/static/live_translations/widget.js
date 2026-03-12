/**
 * django-live-translations — client-side widget
 * Vanilla JS, zero dependencies. Injected by middleware for superusers.
 *
 * State machine:
 *   inactive ──(Shift+T)──► active ──(click span)──► editing
 *      ▲                      │                         │
 *      └──────(Shift+T)───────┘                         │
 *      ▲                                                │
 *      └──────(save/cancel/Escape)──────────────────────┘
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

  // ─── State ───────────────────────────────────────────
  /** @type {"inactive"|"active"|"editing"} */
  var state = "inactive";
  /** @type {HTMLDialogElement|null} */
  var dialog = null;
  /** @type {HTMLElement|null} */
  var currentSpan = null;
  /** @type {string|null} - HTML attribute name when editing an attribute translation. */
  var currentAttrName = null;
  /** @type {boolean} */
  var historyOpen = false;

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
      '<div class="lt-dialog__fields"></div>' +
      '<div class="lt-dialog__history"></div>' +
      '<div class="lt-dialog__error"></div>' +
      '<div class="lt-dialog__actions">' +
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
    var label = "msgid: " + msgid;
    if (currentAttrName) {
      label += "  (attr: " + currentAttrName + ")";
    }
    dialog.querySelector(".lt-dialog__msgid").textContent = label;
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
   * Populate the dialog with per-language textarea fields, active toggles,
   * and .po default hints. Called after the translations API responds.
   * @param {TranslationData} data - Payload from `api.getTranslations`.
   * @returns {void}
   */
  function renderFields(data) {
    var container = dialog.querySelector(".lt-dialog__fields");
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

    container.innerHTML = "";

    var poDefaults = data.defaults || null;

    for (var i = 0; i < LANGUAGES.length; i++) {
      var lang = LANGUAGES[i];
      var entry = data.translations[lang] || { msgstr: "", fuzzy: false };

      var field = document.createElement("div");
      field.className = "lt-field";

      var label = document.createElement("label");
      label.className = "lt-field__label";
      label.textContent = langLabel(lang);
      label.setAttribute("for", "lt-input-" + lang);

      field.appendChild(label);

      // Active toggle — only visible when the value differs from .po default
      var poDefault = poDefaults ? (poDefaults[lang] || "") : "";
      var hasOverride = entry.msgstr !== poDefault;
      var isActive = hasOverride ? entry.is_active !== false : ACTIVE_BY_DEFAULT;

      var toggleWrap = document.createElement("label");
      toggleWrap.className = "lt-field__toggle";
      if (!hasOverride) toggleWrap.style.display = "none";

      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "lt-field__toggle-input";
      checkbox.id = "lt-active-" + lang;
      checkbox.checked = isActive;

      var slider = document.createElement("span");
      slider.className = "lt-field__toggle-slider";

      var toggleLabel = document.createElement("span");
      toggleLabel.className = "lt-field__toggle-label";
      toggleLabel.textContent = isActive ? "Active" : "Inactive";

      (function (lbl) {
        checkbox.addEventListener("change", function () {
          lbl.textContent = this.checked ? "Active" : "Inactive";
        });
      })(toggleLabel);

      var toggleHelp = document.createElement("span");
      toggleHelp.className = "lt-field__toggle-help";
      toggleHelp.textContent = "Inactive overrides are saved but won\u2019t take effect until activated.";

      toggleWrap.appendChild(checkbox);
      toggleWrap.appendChild(slider);
      toggleWrap.appendChild(toggleLabel);
      toggleWrap.appendChild(toggleHelp);

      var textarea = document.createElement("textarea");
      textarea.className = "lt-field__input";
      textarea.id = "lt-input-" + lang;
      textarea.name = lang;
      textarea.value = entry.msgstr;
      textarea.rows = 3;
      if (entry.fuzzy) {
        textarea.classList.add("lt-field__input--fuzzy");
      }

      // Show/hide toggle + auto-resize on input
      (function (ta, toggle, defaultVal, cb, defaultActive) {
        function syncToggle() {
          var differs = ta.value !== defaultVal;
          toggle.style.display = differs ? "" : "none";
          if (!differs) {
            cb.checked = defaultActive;
          }
        }
        ta.addEventListener("input", function () {
          this.style.height = "auto";
          this.style.height = this.scrollHeight + "px";
          syncToggle();
        });
        // Expose for the revert button
        ta._ltSyncToggle = syncToggle;
      })(textarea, toggleWrap, poDefault, checkbox, ACTIVE_BY_DEFAULT);

      // Show .po default with revert button if available
      if (poDefaults && poDefaults[lang]) {
        var poRow = document.createElement("div");
        poRow.className = "lt-field__po-row";

        var poHint = document.createElement("div");
        poHint.className = "lt-field__po-default";
        poHint.textContent = poDefaults[lang];
        poHint.title = ".po file default";

        var revertBtn = document.createElement("button");
        revertBtn.type = "button";
        revertBtn.className = "lt-btn--revert";
        revertBtn.textContent = "Revert";
        revertBtn.title = "Revert to .po default";
        (function (ta, defaultValue) {
          revertBtn.addEventListener("click", function () {
            ta.value = defaultValue;
            ta.style.height = "auto";
            ta.style.height = ta.scrollHeight + "px";
            if (ta._ltSyncToggle) ta._ltSyncToggle();
            ta.focus();
          });
        })(textarea, poDefaults[lang]);

        poRow.appendChild(poHint);
        poRow.appendChild(revertBtn);
        field.appendChild(poRow);
      }

      field.appendChild(textarea);
      field.appendChild(toggleWrap);
      container.appendChild(field);
    }

    // Focus first textarea
    var first = container.querySelector("textarea");
    if (first) first.focus();
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
   * Collect values from all language fields and POST them to the save endpoint.
   * On success the page is reloaded so Django re-renders server-side translations.
   * @returns {void}
   */
  function handleSave() {
    var saveBtn = dialog.querySelector(".lt-btn--save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    showDialogError(null);

    // Read msgid/context from either span data attrs or the stored attr info
    var attrData = currentAttrName ? _getAttrInfo(currentSpan, currentAttrName) : null;
    var msgid = attrData ? attrData.m : currentSpan.dataset.ltMsgid;
    var context = attrData ? attrData.c : (currentSpan.dataset.ltContext || "");

    var translations = {};
    var activeFlags = {};
    for (var i = 0; i < LANGUAGES.length; i++) {
      var lang = LANGUAGES[i];
      var input = dialog.querySelector("#lt-input-" + lang);
      var toggle = dialog.querySelector("#lt-active-" + lang);
      if (input) {
        translations[lang] = input.value;
        activeFlags[lang] = toggle ? toggle.checked : ACTIVE_BY_DEFAULT;
      }
    }

    api
      .saveTranslations(msgid, context, translations, activeFlags)
      .then(function () {
        // Full page reload so Django re-renders all translations server-side.
        // Inline DOM update can't handle %(var)s interpolation from blocktrans,
        // plural forms, or other template-level processing.
        window.location.reload();
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
   * Switch the dialog chrome to show the translation editor (fields + save/cancel).
   * @returns {void}
   */
  function _showEditView() {
    if (!dialog) return;
    dialog.querySelector(".lt-dialog__title").textContent = "Edit Translation";
    var btn = dialog.querySelector(".lt-btn--history");
    btn.innerHTML = dialog._ltIconHistory;
    btn.title = "View edit history";

    dialog.querySelector(".lt-dialog__fields").style.display = "";
    dialog.querySelector(".lt-dialog__actions").style.display = "";
    dialog.querySelector(".lt-dialog__history").style.display = "none";
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
        window.location.reload();
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
    if (state === "editing") {
      state = "active";
    }
  }

  // ─── Edit Mode Toggle ───────────────────────────────

  /**
   * Enter translation edit mode: add the body class that highlights translatable
   * elements and show a toast notification.
   * @returns {void}
   */
  function activateEditMode() {
    state = "active";
    document.body.classList.add("lt-edit-mode");
    showToast(
      "Translation edit mode ON \u2014 click any highlighted text",
      "info"
    );
  }

  /**
   * Leave translation edit mode: close any open modal, remove the body class,
   * and show a toast notification.
   * @returns {void}
   */
  function deactivateEditMode() {
    closeModal();
    state = "inactive";
    document.body.classList.remove("lt-edit-mode");
    showToast("Translation edit mode OFF", "info");
  }

  // ─── Keyboard Handler ───────────────────────────────

  document.addEventListener("keydown", function (e) {
    // Shift+T toggles edit mode (but not when typing in inputs)
    if (e.key === "T" && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
      var tag = document.activeElement ? document.activeElement.tagName : "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        return;
      }

      e.preventDefault();
      if (state === "inactive") {
        activateEditMode();
      } else {
        deactivateEditMode();
      }
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
        openModal(span);
        return;
      }

      // Check for attribute-translatable element
      var attrEl = e.target.closest("[data-lt-attrs]");
      if (attrEl) {
        e.preventDefault();
        e.stopPropagation();

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
})();
