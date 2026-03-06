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

    saveTranslations: function (msgid, context, translations) {
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
        }),
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

  function openModal(span) {
    createDialog();
    currentSpan = span;
    state = "editing";

    var msgid = span.dataset.ltMsgid;
    var context = span.dataset.ltContext || "";

    // Show loading state
    dialog.querySelector(".lt-dialog__fields").innerHTML = "";
    dialog.querySelector(".lt-dialog__loading").style.display = "block";
    dialog.querySelector(".lt-dialog__msgid").textContent = "msgid: " + msgid;
    dialog.querySelector(".lt-btn--save").disabled = true;

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

      var textarea = document.createElement("textarea");
      textarea.className = "lt-field__input";
      textarea.id = "lt-input-" + lang;
      textarea.name = lang;
      textarea.value = entry.msgstr;
      textarea.rows = 3;
      if (entry.fuzzy) {
        textarea.classList.add("lt-field__input--fuzzy");
      }

      // Auto-resize textarea on input
      textarea.addEventListener("input", function () {
        this.style.height = "auto";
        this.style.height = this.scrollHeight + "px";
      });

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
            ta.focus();
          });
        })(textarea, poDefaults[lang]);

        poRow.appendChild(poHint);
        poRow.appendChild(revertBtn);
        field.appendChild(poRow);
      }

      field.appendChild(textarea);
      container.appendChild(field);
    }

    // Focus first textarea
    var first = container.querySelector("textarea");
    if (first) first.focus();
  }

  function handleSave() {
    var saveBtn = dialog.querySelector(".lt-btn--save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    var msgid = currentSpan.dataset.ltMsgid;
    var context = currentSpan.dataset.ltContext || "";

    var translations = {};
    for (var i = 0; i < LANGUAGES.length; i++) {
      var lang = LANGUAGES[i];
      var input = dialog.querySelector("#lt-input-" + lang);
      if (input) {
        translations[lang] = input.value;
      }
    }

    api
      .saveTranslations(msgid, context, translations)
      .then(function (result) {
        // In-place update: replace the span's text with current language translation
        if (result.current_language_msgstr) {
          currentSpan.textContent = result.current_language_msgstr;
        }
        closeModal();
        showToast("Translation saved");
      })
      .catch(function (err) {
        showToast("Save failed: " + err.message, "error");
      })
      .finally(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = "Save";
      });
  }

  function closeModal() {
    if (dialog && dialog.open) {
      dialog.close();
    }
    currentSpan = null;
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

      var span = e.target.closest(".lt-translatable");
      if (!span) return;

      e.preventDefault();
      e.stopPropagation();
      openModal(span);
    },
    true
  ); // Use capture phase to intercept before other handlers
})();
