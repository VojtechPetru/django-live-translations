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
    dialog.innerHTML =
      '<div class="lt-dialog__form">' +
      '<div class="lt-dialog__header">' +
      '<h2 class="lt-dialog__title">Edit Translation</h2>' +
      '<button type="button" class="lt-dialog__close" aria-label="Close">&times;</button>' +
      "</div>" +
      '<div class="lt-dialog__msgid"></div>' +
      '<div class="lt-dialog__hint"></div>' +
      '<div class="lt-dialog__fields"></div>' +
      '<div class="lt-dialog__error"></div>' +
      '<div class="lt-dialog__actions">' +
      '<button type="button" class="lt-btn lt-btn--cancel">Cancel</button>' +
      '<button type="button" class="lt-btn lt-btn--save">Save</button>' +
      "</div>" +
      '<div class="lt-dialog__loading">Loading translations...</div>' +
      "</div>";
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

  function closeModal() {
    if (dialog && dialog.open) {
      dialog.close();
    }
    currentSpan = null;
    currentAttrName = null;
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
