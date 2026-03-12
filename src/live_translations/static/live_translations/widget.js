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

  // ─── Config (injected by middleware) ─────────────────
  var CONFIG = window.__LT_CONFIG__ || {};
  var API_BASE = CONFIG.apiBase || "/__live-translations__";
  var LANGUAGES = CONFIG.languages || [];
  var CSRF_TOKEN = CONFIG.csrfToken || "";
  var ACTIVE_BY_DEFAULT = CONFIG.activeByDefault !== undefined ? CONFIG.activeByDefault : false;

  // ─── Language display names & flags ──────────────────
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

  function langLabel(code) {
    var meta = LANG_META[code];
    if (meta) return meta.flag + "  " + meta.name;
    return code.toUpperCase();
  }

  // ─── State ───────────────────────────────────────────
  var state = "inactive"; // "inactive" | "active" | "editing"
  var dialog = null;
  var currentSpan = null;
  var currentAttrName = null; // Set when editing an attribute translation
  var historyOpen = false;

  // ─── API Client ──────────────────────────────────────

  var api = {
    getTranslations: function (msgid, context) {
      var params = new URLSearchParams({ msgid: msgid, context: context });
      return fetch(API_BASE + "/translations/?" + params, {
        credentials: "same-origin",
      }).then(function (resp) {
        if (!resp.ok) throw new Error("GET failed: " + resp.status);
        return resp.json();
      });
    },

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

  var _historyData = [];        // cached entries from last fetch
  var _historyLangFilter = "";  // "" = all, "en" = specific language

  function _getMsgidAndContext() {
    var attrData = currentAttrName ? _getAttrInfo(currentSpan, currentAttrName) : null;
    return {
      msgid: attrData ? attrData.m : currentSpan.dataset.ltMsgid,
      context: attrData ? attrData.c : (currentSpan.dataset.ltContext || ""),
    };
  }

  function toggleHistory() {
    if (historyOpen) {
      _showEditView();
    } else {
      _showHistoryView();
    }
    historyOpen = !historyOpen;
  }

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

  // ── Action labels (used for tooltips) ──
  var _ACTION_LABELS = {
    create: "Created",
    update: "Updated",
    "delete": "Deleted",
    activate: "Activated",
    deactivate: "Deactivated",
  };

  // ── Action icons (inline SVG, colored via currentColor) ──
  var _ACTION_ICONS = {
    create: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M8 3v10M3 8h10"/></svg>',
    update: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 11v2.5H5L13 5.5 10.5 3 2.5 11z"/><path d="M9 4.5l2.5 2.5"/></svg>',
    "delete": '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 4.5h10"/><path d="M6.5 4.5V3a.5.5 0 01.5-.5h2a.5.5 0 01.5.5v1.5"/><path d="M5 4.5V13a1 1 0 001 1h4a1 1 0 001-1V4.5"/></svg>',
    activate: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="12" height="6" rx="3"/><circle cx="11" cy="8" r="2" fill="currentColor"/></svg>',
    deactivate: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="12" height="6" rx="3"/><circle cx="5" cy="8" r="2"/></svg>',
  };

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

  function activateEditMode() {
    state = "active";
    document.body.classList.add("lt-edit-mode");
    showToast(
      "Translation edit mode ON \u2014 click any highlighted text",
      "info"
    );
  }

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

  function _showAttrPicker(element, attrs) {
    // Simple: open modal for first attr, with a note about others.
    // A full picker UI can be added later.
    openModal(element, attrs[0]);
  }
})();
