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
 *   Save updates the DOM in-place using server-computed display data.
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
   * @property {string}   [shortcutEdit]     - Keyboard shortcut for toggling edit mode.
   * @property {string}   [shortcutPreview]  - Keyboard shortcut for toggling preview mode.
   * @property {boolean}  [preview]          - Whether preview mode is active.
   * @property {Array<{m:string, c:string}>} [previewEntries] - Inactive override entries for preview.
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
   * @property {string}  msgstr       - Current translated string.
   * @property {boolean} fuzzy        - Whether the .po entry is marked fuzzy.
   * @property {boolean} is_active    - Whether the DB override is active.
   * @property {boolean} has_override - Whether a DB override exists.
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

  /**
   * Response payload from `POST /translations/save/`.
   * @typedef {Object} SaveResponse
   * @property {boolean} ok
   * @property {{text: string, is_preview_entry: boolean}} [display] - Updated display info.
   */

  /**
   * Response payload from `POST /translations/delete/`.
   * @typedef {Object} DeleteResponse
   * @property {boolean} ok
   * @property {number}  deleted - Number of overrides deleted.
   */

  /**
   * Response payload from `POST /translations/bulk-activate/`.
   * @typedef {Object} BulkActivateResponse
   * @property {boolean} ok
   * @property {number}  activated - Number of overrides activated.
   */

  /**
   * Error thrown by API methods when the server returns a non-OK response.
   * Extends the standard Error with optional structured per-language details.
   * @typedef {Error & {details?: Object<string, string[]>|null}} ApiError
   */

  /**
   * Drag state tracked during hint bar repositioning.
   * @typedef {Object} DragState
   * @property {number}  mouseX - Initial mouse X at drag start.
   * @property {number}  mouseY - Initial mouse Y at drag start.
   * @property {number}  barX   - Initial bar left offset at drag start.
   * @property {number}  barY   - Initial bar top offset at drag start.
   * @property {boolean} moved  - Whether the drag has passed the movement threshold.
   */

  /**
   * Persisted hint bar position in localStorage.
   * @typedef {Object} HintPosition
   * @property {number} x
   * @property {number} y
   */

  // ─── Config (injected by middleware) ─────────────────
  /** @type {LTConfig} */
  const CONFIG = window.__LT_CONFIG__ || {};
  /** @type {string} */
  const API_BASE = CONFIG.apiBase || "/__live-translations__";
  /** @type {string[]} */
  const LANGUAGES = CONFIG.languages || [];
  /** @type {string} */
  const CSRF_TOKEN = CONFIG.csrfToken || "";
  /** @type {boolean} */
  const ACTIVE_BY_DEFAULT = CONFIG.activeByDefault !== undefined ? CONFIG.activeByDefault : false;
  /** @type {string} */
  const SHORTCUT_EDIT = CONFIG.shortcutEdit || "ctrl+shift+e";
  /** @type {string} */
  const SHORTCUT_PREVIEW = CONFIG.shortcutPreview || "ctrl+shift+p";
  /** @type {boolean} */
  const PREVIEW = CONFIG.preview || false;
  /** @type {Array<{m:string, c:string}>} */
  let PREVIEW_ENTRIES = CONFIG.previewEntries || [];

  // ─── String Table & ZWC Marker Resolution ───────────

  /**
   * @typedef {{m: string, c: string}} StringTableEntry
   * Mirrors Python's StringTableEntry TypedDict.
   */

  /**
   * @typedef {Object<number, StringTableEntry>} StringTable
   * Maps string ID to {msgid, context}. Injected as window.__LT_STRINGS__.
   */

  /**
   * @typedef {Object} RegisteredNode
   * @property {Text}              node    - The text node containing translated content.
   * @property {string}            msgid   - The gettext message ID.
   * @property {string}            context - The gettext context (empty string if none).
   * @property {HTMLElement|null}  span    - Wrapping <lt-t> element (null only for OPTION/TITLE/SCRIPT/STYLE parents).
   */

  /** @type {RegExp} */
  const ZWC_RE = /\uFEFF[\u200B\u200C]{16}\uFEFF/g;

  /** @type {StringTable} */
  const STRING_TABLE = window.__LT_STRINGS__ || {};

  /** @type {RegisteredNode[]} */
  const registeredNodes = [];

  /**
   * Decode a ZWC marker string into a string-table ID.
   * @param {string} marker - 18-char ZWC sequence (FEFF + 16 bits + FEFF).
   * @returns {number} The decoded string ID (0-65535).
   */
  function decodeZWC(marker) {
    let n = 0;
    for (let i = 1; i <= 16; i++) {
      if (marker.charCodeAt(i) === 0x200C) n |= (1 << (16 - i));
    }
    return n;
  }

  /**
   * Walk the DOM, find ZWC markers in text nodes and attribute values,
   * strip them, and populate registeredNodes[].
   * @returns {void}
   */
  function resolveMarkers() {
    // Phase 1: Text nodes
    /** @type {Text[]} */
    const textNodes = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    /** @type {Node|null} */
    let wNode;
    while ((wNode = walker.nextNode()) !== null) {
      textNodes.push(/** @type {Text} */ (wNode));
    }

    for (let ti = 0; ti < textNodes.length; ti++) {
      let tn = textNodes[ti];
      const text = tn.textContent || "";
      ZWC_RE.lastIndex = 0;

      // Collect all marker matches in this text node
      /** @type {RegExpExecArray[]} */
      const matches = [];
      /** @type {RegExpExecArray|null} */
      let execMatch;
      while ((execMatch = ZWC_RE.exec(text)) !== null) {
        matches.push(execMatch);
      }
      if (!matches.length) continue;

      // Process markers right-to-left to preserve indices when splitting.
      // After each iteration we update `tn` to the content node to the LEFT
      // of the processed marker so the next (leftward) marker can be found.
      for (let mi = matches.length - 1; mi >= 0; mi--) {
        const m = matches[mi];
        const mIdx = /** @type {number} */ (m.index);
        const mLen = m[0].length;
        const id = decodeZWC(m[0]);
        const meta = STRING_TABLE[id];
        if (!meta) continue;

        // Guard: after earlier iterations the text node may have been split
        // or removed, making the original offset stale.
        const tnLen = (tn.textContent || "").length;
        if (mIdx + mLen > tnLen) continue;

        // Text AFTER the marker becomes a separate text node (tail)
        const afterStart = mIdx + mLen;
        if (afterStart < tnLen) {
          tn.splitText(afterStart);
        }

        // Text of the marker itself: remove it.
        // Now tn contains everything up to and including the marker.
        // Split before the marker to isolate it.
        if (mIdx > 0) {
          tn = /** @type {Text} */ (tn.splitText(mIdx));
        }

        // tn now starts with the marker. Remove the marker text from tn.
        tn.textContent = (tn.textContent || "").substring(mLen);

        // The text node BEFORE the marker (content text) is tn's previous sibling.
        // Since we append markers, the content is BEFORE the marker in the text.
        const contentNode = /** @type {Text|null} */ (tn.previousSibling);

        // Determine which text node contains the translatable content
        /** @type {Text|null} */
        let nodeToWrap = null;
        if (contentNode && contentNode.nodeType === Node.TEXT_NODE && (contentNode.textContent || "").length > 0) {
          nodeToWrap = /** @type {Text} */ (contentNode);
        } else if (tn.nodeType === Node.TEXT_NODE && (tn.textContent || "").length > 0) {
          // Marker was at position 0 or no previous content; use tn (text after marker)
          nodeToWrap = /** @type {Text} */ (tn);
        }

        if (nodeToWrap) {
          const wrapParent = nodeToWrap.parentNode;
          // Wrap in <lt-t> unless parent cannot contain child elements
          if (wrapParent && wrapParent.nodeName !== "OPTION" && wrapParent.nodeName !== "TITLE" && wrapParent.nodeName !== "SCRIPT" && wrapParent.nodeName !== "STYLE") {
            const ltEl = document.createElement("lt-t");
            ltEl.dataset.ltMsgid = meta.m;
            ltEl.dataset.ltContext = meta.c;
            wrapParent.insertBefore(ltEl, nodeToWrap);
            ltEl.appendChild(nodeToWrap);
            registeredNodes.push({ node: nodeToWrap, msgid: meta.m, context: meta.c, span: ltEl });
          } else {
            registeredNodes.push({ node: nodeToWrap, msgid: meta.m, context: meta.c, span: null });
          }
        }

        // Clean up empty text node left after marker removal
        if (tn !== nodeToWrap && tn.textContent === "" && tn.parentNode) {
          tn.parentNode.removeChild(tn);
        }

        // Update tn for the next (leftward) iteration.  contentNode holds
        // all text to the left of the just-processed marker, including any
        // remaining markers.  It may have been reparented into <lt-t> but
        // its textContent is unchanged so the earlier match indices stay valid.
        if (contentNode && contentNode.nodeType === Node.TEXT_NODE) {
          tn = /** @type {Text} */ (contentNode);
        }
      }
    }

    // Phase 2: Attribute values
    const allElements = document.querySelectorAll("*");
    for (let ei = 0; ei < allElements.length; ei++) {
      const el = /** @type {HTMLElement} */ (allElements[ei]);
      /** @type {AttrInfo[]} */
      const ltAttrs = [];
      const attrs = el.attributes;
      for (let ai = 0; ai < attrs.length; ai++) {
        const attr = attrs[ai];
        ZWC_RE.lastIndex = 0;
        const attrMatch = ZWC_RE.exec(attr.value);
        if (!attrMatch) continue;
        const attrId = decodeZWC(attrMatch[0]);
        const attrMeta = STRING_TABLE[attrId];
        if (!attrMeta) continue;
        // Strip ALL ZWC markers from the attribute value
        el.setAttribute(attr.name, attr.value.replace(ZWC_RE, ""));
        ltAttrs.push({ a: attr.name, m: attrMeta.m, c: attrMeta.c });
      }
      if (ltAttrs.length) {
        el.dataset.ltAttrs = JSON.stringify(ltAttrs);
      }
    }
  }



  // ─── Shared Helpers ──────────────────────────────────

  /**
   * Return the page's language code (lowercase), e.g. "en" or "cs".
   * @returns {string}
   */
  function _pageLang() {
    return (document.documentElement.lang || "").toLowerCase();
  }

  /**
   * Safely parse the `data-lt-attrs` JSON on an element.
   * @param {HTMLElement} el - Element with a `data-lt-attrs` attribute.
   * @returns {AttrInfo[]}
   */
  function _parseLtAttrs(el) {
    try { return JSON.parse(el.dataset.ltAttrs || "[]"); } catch { return []; }
  }

  /**
   * Build a dedup key from msgid + context (null-separated).
   * @param {string} msgid   - The gettext message identifier.
   * @param {string} context - The gettext context (empty string if none).
   * @returns {string}
   */
  function _entryKey(msgid, context) {
    return msgid + "\x00" + (context || "");
  }

  /**
   * Read an error JSON body from a failed API response and throw an Error.
   * @param {Response} resp - The fetch Response with a non-OK status.
   * @returns {Promise<never>}
   */
  async function _throwApiError(resp) {
    /** @type {Record<string, unknown>} */
    let errData;
    try { errData = await resp.json(); } catch { errData = {}; }
    throw new Error(/** @type {string} */ (errData.error) || "Request failed: " + resp.status);
  }

  // ─── Shortcut Parsing ────────────────────────────────

  /**
   * Parse a shortcut string like "ctrl+shift+e" into a descriptor object.
   * @param {string} combo - "+"-separated modifier+key string (case-insensitive).
   * @returns {{ctrl: boolean, shift: boolean, alt: boolean, meta: boolean, key: string}}
   */
  function _parseShortcut(combo) {
    const parts = combo.toLowerCase().split("+");
    const key = parts[parts.length - 1];
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
    const isMac = navigator.platform ? navigator.platform.indexOf("Mac") !== -1 : false;
    const parts = [];
    if (sc.ctrl) parts.push(isMac ? "\u2303" : "Ctrl");
    if (sc.shift) parts.push(isMac ? "\u21E7" : "Shift");
    if (sc.alt) parts.push(isMac ? "\u2325" : "Alt");
    if (sc.meta) parts.push(isMac ? "\u2318" : "Meta");
    parts.push(sc.key.toUpperCase());
    return parts.join(isMac ? "" : " + ");
  }

  const SC_EDIT = _parseShortcut(SHORTCUT_EDIT);
  const SC_PREVIEW = _parseShortcut(SHORTCUT_PREVIEW);

  // ─── Language display names & flags ──────────────────
  /** @type {Object<string, LangMeta>} */
  const LANG_META = {
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
    const meta = LANG_META[code];
    if (meta) return meta.flag + "  " + meta.name;
    return code.toUpperCase();
  }

  // ─── Clipboard Copy Helper ───────────────────────────

  /** @type {string} */
  const ICON_COPY_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/>' +
    '<path d="M10.5 5.5V3.5a1.5 1.5 0 0 0-1.5-1.5H3.5A1.5 1.5 0 0 0 2 3.5V9a1.5 1.5 0 0 0 1.5 1.5h2"/></svg>';
  /** @type {string} */
  const ICON_CHECK_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M3.5 8.5l3 3 6-7"/></svg>';
  /** @type {string} */
  const ICON_CHECKBOX_SVG =
    '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="2" y="2" width="12" height="12" rx="2"/></svg>';
  /** @type {string} */
  const ICON_CHECKBOX_CHECKED_SVG =
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
    const ms = duration || 1500;
    iconEl.innerHTML = ICON_COPY_SVG;
    container.style.cursor = "pointer";
    container.addEventListener("click", async function () {
      const text = getText();
      if (!text || container.classList.contains(copiedClass)) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        return;
      }
      container.classList.add(copiedClass);
      iconEl.innerHTML = ICON_CHECK_SVG;
      setTimeout(function () {
        container.classList.remove(copiedClass);
        iconEl.innerHTML = ICON_COPY_SVG;
      }, ms);
    });
  }

  // ─── State ───────────────────────────────────────────
  /** @type {"inactive"|"active"|"editing"} */
  let state = "inactive";
  /** @type {string} */
  const _EDIT_MODE_KEY = "lt_edit_mode";

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

  /**
   * Update all DOM elements matching a msgid/context with new display text.
   * Handles both inline text spans and attribute translations.
   * @param {string}  msgid          - The gettext msgid.
   * @param {string}  context        - The gettext context (empty string if none).
   * @param {string}  displayText    - The resolved text to display.
   * @param {boolean} isPreviewEntry - Whether this is an inactive preview entry.
   * @returns {void}
   */
  function _updateDomInPlace(msgid, context, displayText, isPreviewEntry) {
    // Update registered text nodes (and their wrapping spans if in edit mode)
    for (let ri = 0; ri < registeredNodes.length; ri++) {
      const entry = registeredNodes[ri];
      if (entry.msgid === msgid && entry.context === context) {
        entry.node.textContent = displayText;
        if (entry.span) {
          if (isPreviewEntry) {
            entry.span.classList.add("lt-preview");
          } else {
            entry.span.classList.remove("lt-preview", "lt-selected");
            const sidx = selectedElements.indexOf(entry.span);
            if (sidx !== -1) selectedElements.splice(sidx, 1);
          }
        }
      }
    }

    // Also update any inline text spans that may exist outside registeredNodes
    // (e.g., if wrapping was skipped for some elements)
    const spans = document.querySelectorAll("lt-t");
    for (let i = 0; i < spans.length; i++) {
      const sp = spans[i];
      if (sp.dataset.ltMsgid === msgid && (sp.dataset.ltContext || "") === context) {
        sp.textContent = displayText;
        if (isPreviewEntry) {
          sp.classList.add("lt-preview");
        } else {
          sp.classList.remove("lt-preview", "lt-selected");
          const idx = selectedElements.indexOf(sp);
          if (idx !== -1) selectedElements.splice(idx, 1);
        }
      }
    }

    // Update attribute translations
    const attrEls = document.querySelectorAll("[data-lt-attrs]");
    for (let j = 0; j < attrEls.length; j++) {
      const attrs = _parseLtAttrs(/** @type {HTMLElement} */ (attrEls[j]));
      for (let k = 0; k < attrs.length; k++) {
        if (attrs[k].m === msgid && (attrs[k].c || "") === context) {
          attrEls[j].setAttribute(attrs[k].a, displayText);
          if (isPreviewEntry) {
            attrEls[j].classList.add("lt-preview");
          } else {
            attrEls[j].classList.remove("lt-preview", "lt-selected");
            const aidx = selectedElements.indexOf(attrEls[j]);
            if (aidx !== -1) selectedElements.splice(aidx, 1);
          }
          break;
        }
      }
    }

    // Update PREVIEW_ENTRIES and action bar
    if (PREVIEW) {
      if (isPreviewEntry) {
        let found = false;
        for (let p = 0; p < PREVIEW_ENTRIES.length; p++) {
          if (PREVIEW_ENTRIES[p].m === msgid && (PREVIEW_ENTRIES[p].c || "") === context) {
            found = true;
            break;
          }
        }
        if (!found) PREVIEW_ENTRIES.push({m: msgid, c: context});
      } else {
        PREVIEW_ENTRIES = PREVIEW_ENTRIES.filter(function (e) {
          return !(e.m === msgid && (e.c || "") === context);
        });
      }
      _updateActionBar();
    }
  }

  /** @type {HTMLDialogElement|null} */
  let dialog = null;
  /** @type {HTMLElement|null} */
  let currentSpan = null;
  /** @type {string|null} - HTML attribute name when editing an attribute translation. */
  let currentAttrName = null;
  /** @type {boolean} */
  let historyOpen = false;
  /** @type {string} */
  let _iconHistory = "";
  /** @type {string} */
  let _iconBack = "";

  // ─── Editor State (tabbed editing) ───────────────────
  /** @type {TranslationData|null} - Cached API data for the current edit session. */
  let _editData = null;
  /** @type {string} - Currently selected language tab for editing. */
  let _editLang = "";
  /** @type {Object<string, string>} - Accumulated edited text values keyed by language. */
  let _editedValues = {};
  /** @type {Object<string, boolean>} - Accumulated active flags keyed by language. */
  let _editedActiveFlags = {};
  /** @type {Object<string, string>} - Snapshot of initial text values from API (for dirty detection). */
  let _originalValues = {};
  /** @type {Object<string, boolean>} - Snapshot of initial active flags from API (for dirty detection). */
  let _originalActiveFlags = {};
  /** @type {Object<string, boolean>} - Languages marked for override deletion (submitted on Save). */
  let _deletionsMarked = {};

  // ─── API Client ──────────────────────────────────────

  const api = {
    /**
     * Fetch all language translations for a single msgid.
     * @param {string} msgid  - The gettext message identifier.
     * @param {string} context - The gettext context (empty string if none).
     * @returns {Promise<TranslationData>}
     */
    getTranslations: async function (msgid, context) {
      const params = new URLSearchParams({ msgid: msgid, context: context });
      const resp = await fetch(API_BASE + "/translations/?" + params, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!resp.ok) throw new Error("GET failed: " + resp.status);
      return resp.json();
    },

    /**
     * Persist translation overrides to the database.
     * @param {string}                msgid        - The gettext message identifier.
     * @param {string}                context      - The gettext context.
     * @param {Object<string,string>} translations - Map of language code to msgstr value.
     * @param {Object<string,boolean>} activeFlags - Map of language code to active/inactive flag.
     * @returns {Promise<SaveResponse>}
     */
    saveTranslations: async function (msgid, context, translations, activeFlags) {
      const resp = await fetch(API_BASE + "/translations/save/", {
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
          page_language: _pageLang(),
        }),
      });
      if (!resp.ok) {
        /** @type {Record<string, unknown>} */
        let errData;
        try { errData = await resp.json(); } catch { errData = {}; }
        /** @type {ApiError} */
        const apiErr = Object.assign(
          new Error(/** @type {string} */ (errData.error) || "POST failed: " + resp.status),
          { details: /** @type {Object<string, string[]>|null} */ (errData.details) || null }
        );
        throw apiErr;
      }
      return /** @type {Promise<SaveResponse>} */ (resp.json());
    },

    /**
     * Fetch the edit history for a msgid/context pair.
     * @param {string} msgid   - The gettext message identifier.
     * @param {string} context - The gettext context.
     * @returns {Promise<{history: HistoryEntry[]}>}
     */
    getHistory: async function (msgid, context) {
      const params = new URLSearchParams({ msgid: msgid, context: context });
      const resp = await fetch(API_BASE + "/translations/history/?" + params, {
        credentials: "same-origin",
      });
      if (!resp.ok) throw new Error("GET failed: " + resp.status);
      return resp.json();
    },

    /**
     * Delete DB override(s) for a msgid/context.
     * @param {string}   msgid     - The gettext message identifier.
     * @param {string}   context   - The gettext context.
     * @param {string[]} languages - Language codes to delete.
     * @returns {Promise<DeleteResponse>}
     */
    deleteTranslation: async function (msgid, context, languages) {
      const payload = {
        msgid: msgid,
        context: context,
        page_language: _pageLang(),
      };
      if (languages && languages.length) payload.languages = languages;
      const resp = await fetch(API_BASE + "/translations/delete/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRF_TOKEN,
        },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) await _throwApiError(resp);
      return /** @type {Promise<DeleteResponse>} */ (resp.json());
    },

    /**
     * Bulk-activate translations for the given msgid/context pairs for a single language.
     * @param {Array<{msgid:string, context:string}>} msgids - Entries to activate.
     * @param {string} language - Language code to activate for.
     * @returns {Promise<BulkActivateResponse>}
     */
    bulkActivate: async function (msgids, language) {
      const resp = await fetch(API_BASE + "/translations/bulk-activate/", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": CSRF_TOKEN,
        },
        body: JSON.stringify({ msgids: msgids, language: language }),
      });
      if (!resp.ok) await _throwApiError(resp);
      return /** @type {Promise<BulkActivateResponse>} */ (resp.json());
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
    const existing = document.querySelector(".lt-toast");
    if (existing) existing.remove();

    const toast = document.createElement("div");
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
    const ICON_HISTORY =
      '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M8 3.5V8L10.5 10.5M14 8A6 6 0 1 1 2 8a6 6 0 0 1 12 0Z" ' +
      'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const ICON_BACK =
      '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M10 12L6 8L10 4" stroke="currentColor" stroke-width="1.5" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const ICON_CLOSE =
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

    // Store icon templates for toggling
    _iconHistory = ICON_HISTORY;
    _iconBack = ICON_BACK;

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
   * For inline text elements (`<lt-t>`), `attrInfo` is
   * omitted and the msgid/context are read from the element's `data-lt-msgid`
   * and `data-lt-context` attributes. For attribute translations (e.g. `title`),
   * the caller passes the {@link AttrInfo} descriptor from `data-lt-attrs`.
   *
   * @param {HTMLElement}   element   - The DOM element that was clicked.
   * @param {AttrInfo}      [attrInfo] - Attribute descriptor; omit for inline text.
   * @returns {Promise<void>}
   */
  async function openModal(element, attrInfo) {
    createDialog();
    currentSpan = element;
    currentAttrName = attrInfo ? attrInfo.a : null;
    state = "editing";
    historyOpen = false;
    _showEditView();

    const msgid = attrInfo ? attrInfo.m : element.dataset.ltMsgid;
    const context = attrInfo ? attrInfo.c : (element.dataset.ltContext || "");

    // Show loading state
    dialog.querySelector(".lt-dialog__fields").innerHTML = "";
    dialog.querySelector(".lt-dialog__loading").style.display = "block";
    const msgidEl = dialog.querySelector(".lt-dialog__msgid");
    msgidEl.dataset.msgid = msgid;
    msgidEl.innerHTML = "";

    const msgidLabel = document.createElement("span");
    msgidLabel.className = "lt-dialog__msgid-label";
    msgidLabel.textContent = currentAttrName ? "msgid · " + currentAttrName : "msgid";

    const msgidText = document.createElement("span");
    msgidText.className = "lt-dialog__msgid-text";
    msgidText.textContent = msgid;

    const copyIcon = document.createElement("span");
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

    try {
      const data = await api.getTranslations(msgid, context);
      renderFields(data);
    } catch (err) {
      showToast("Failed to load translations: " + err.message, "error");
      closeModal();
    }
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
    const hintEl = dialog.querySelector(".lt-dialog__hint");
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

    const poDefaults = data.defaults || {};

    // Initialize values from API data
    for (let i = 0; i < LANGUAGES.length; i++) {
      const lang = LANGUAGES[i];
      const entry = data.translations[lang] || { msgstr: "", fuzzy: false };
      _editedValues[lang] = entry.msgstr;
      const hasOverride = !!entry.has_override;
      _editedActiveFlags[lang] = hasOverride ? entry.is_active !== false : ACTIVE_BY_DEFAULT;
      _originalValues[lang] = entry.msgstr;
      _originalActiveFlags[lang] = _editedActiveFlags[lang];
    }

    // Default edit language: current page language if configured, else first
    const lang = _pageLang();
    _editLang = LANGUAGES.indexOf(lang) !== -1 ? lang : LANGUAGES[0];

    _renderEditorTabs();
    _renderEditorPanels();
  }

  /**
   * Render the language tab bar above the editor panels.
   * Hidden when only one language is configured.
   * @returns {void}
   */
  function _renderEditorTabs() {
    const tabBar = dialog.querySelector(".lt-editor__tabs");
    tabBar.innerHTML = "";

    if (LANGUAGES.length <= 1) {
      tabBar.style.display = "none";
      return;
    }

    tabBar.style.display = "";

    for (let i = 0; i < LANGUAGES.length; i++) {
      (function (lang) {
        const meta = LANG_META[lang];
        const entry = (_editData && _editData.translations[lang]) || {};
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "lt-editor__tab" + (_editLang === lang ? " lt-editor__tab--active" : "");

        // Leading dot (inactive override / marked for deletion)
        var leadDot = document.createElement("span");
        leadDot.className = "lt-editor__dot";
        leadDot.dataset.role = "status";
        if (entry.has_override && entry.is_active === false) {
          leadDot.classList.add("lt-editor__dot--inactive");
          leadDot.dataset.tip = "Inactive override";
        } else {
          leadDot.style.display = "none";
        }
        pill.appendChild(leadDot);

        // Label text
        var label = document.createTextNode(meta ? meta.flag + "  " + meta.name : lang.toUpperCase());
        pill.appendChild(label);

        // Trailing dot (unsaved changes)
        var trailDot = document.createElement("span");
        trailDot.className = "lt-editor__dot";
        trailDot.dataset.role = "dirty";
        trailDot.style.display = "none";
        pill.appendChild(trailDot);

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
    const tabs = dialog.querySelectorAll(".lt-editor__tab");
    for (let i = 0; i < tabs.length; i++) {
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
    const textarea = dialog.querySelector("#lt-input-" + _editLang);
    if (textarea) {
      _editedValues[_editLang] = textarea.value;
    }
    const toggle = dialog.querySelector("#lt-active-" + _editLang);
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
    const tabs = dialog.querySelectorAll(".lt-editor__tab");
    for (let i = 0; i < tabs.length; i++) {
      const lang = tabs[i].dataset.lang;
      const markedForDelete = !!_deletionsMarked[lang];
      let dirty;
      let activeNow;
      if (lang === _editLang) {
        // Read live from DOM for the active tab
        const ta = dialog.querySelector("#lt-input-" + lang);
        const cb = dialog.querySelector("#lt-active-" + lang);
        dirty = markedForDelete ||
                (ta && ta.value !== _originalValues[lang]) ||
                (cb && cb.checked !== _originalActiveFlags[lang]);
        activeNow = cb ? cb.checked : _editedActiveFlags[lang];
      } else {
        dirty = _isLangDirty(lang);
        activeNow = _editedActiveFlags[lang] !== undefined ? _editedActiveFlags[lang] : ACTIVE_BY_DEFAULT;
      }
      // Trailing dot: unsaved changes
      var trailDot = tabs[i].querySelector('[data-role="dirty"]');
      if (trailDot) {
        if (dirty) {
          trailDot.classList.add("lt-editor__dot--dirty");
          trailDot.dataset.tip = "Unsaved changes";
          trailDot.style.display = "";
        } else {
          trailDot.classList.remove("lt-editor__dot--dirty");
          delete trailDot.dataset.tip;
          trailDot.style.display = "none";
        }
      }
      // Leading dot: deletion (red) supersedes inactive override (amber)
      var leadDot = tabs[i].querySelector('[data-role="status"]');
      if (leadDot) {
        leadDot.classList.remove("lt-editor__dot--delete", "lt-editor__dot--inactive");
        if (markedForDelete) {
          leadDot.classList.add("lt-editor__dot--delete");
          leadDot.dataset.tip = "Marked for deletion";
          leadDot.style.display = "";
        } else {
          const entry = (_editData && _editData.translations[lang]) || {};
          if (entry.has_override && !activeNow) {
            leadDot.classList.add("lt-editor__dot--inactive");
            leadDot.dataset.tip = "Inactive override";
            leadDot.style.display = "";
          } else {
            delete leadDot.dataset.tip;
            leadDot.style.display = "none";
          }
        }
      }
    }
  }

  /**
   * Render the editor content area for the currently selected language.
   * @returns {void}
   */
  function _renderEditorPanels() {
    const container = dialog.querySelector(".lt-dialog__fields");
    container.innerHTML = "";

    const wrapper = document.createElement("div");
    wrapper.className = "lt-editor__single";
    _renderEditPanel(wrapper);
    container.appendChild(wrapper);

    // Focus and auto-resize textarea
    const ta = container.querySelector("textarea");
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
    const lang = _editLang;
    const entry = (_editData.translations[lang]) || { msgstr: "", fuzzy: false };
    const poDefaults = _editData.defaults || {};
    const poDefault = poDefaults[lang] || "";
    const hasOverride = !!entry.has_override;
    const markedForDelete = !!_deletionsMarked[lang];

    // Show language label in single-language mode (no tabs to indicate it)
    if (LANGUAGES.length <= 1) {
      const langLabelEl = document.createElement("label");
      langLabelEl.className = "lt-field__label";
      langLabelEl.textContent = langLabel(lang);
      langLabelEl.setAttribute("for", "lt-input-" + lang);
      container.appendChild(langLabelEl);
    }

    // .po default hint (click to copy)
    if (poDefault) {
      const poWrap = document.createElement("div");
      poWrap.className = "lt-field__po-wrap";

      const poHeader = document.createElement("div");
      poHeader.className = "lt-field__po-header";

      const poLabel = document.createElement("span");
      poLabel.className = "lt-field__po-label";
      poLabel.textContent = "Default";

      const poCopyIcon = document.createElement("span");
      poCopyIcon.className = "lt-field__po-copy";
      poCopyIcon.title = "Copy default";

      poHeader.appendChild(poLabel);
      poHeader.appendChild(poCopyIcon);

      const poText = document.createElement("div");
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
    const textarea = document.createElement("textarea");
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
    const isActive = _editedActiveFlags[lang];
    const currentVal = _editedValues[lang] || "";

    const toggleWrap = document.createElement("label");
    toggleWrap.className = "lt-field__toggle";
    if (markedForDelete) {
      toggleWrap.style.visibility = "hidden";
    } else if (!hasOverride && currentVal === poDefault) {
      toggleWrap.style.display = "none";
    }

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "lt-field__toggle-input";
    checkbox.id = "lt-active-" + lang;
    checkbox.checked = isActive;

    const slider = document.createElement("span");
    slider.className = "lt-field__toggle-slider";

    const toggleLabelEl = document.createElement("span");
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
        const differs = ta.value !== defaultVal;
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
    const errorEl = dialog.querySelector(".lt-dialog__error");
    if (!message) {
      errorEl.innerHTML = "";
      errorEl.style.display = "none";
      return;
    }
    errorEl.innerHTML = "";
    if (details) {
      // Structured per-language errors: {lang: ["missing %(key)s", ...]}
      for (const lang in details) {
        const line = document.createElement("div");
        const meta = LANG_META[lang];
        const label = meta ? meta.flag + " " + meta.name : lang.toUpperCase();
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
    const btn = dialog.querySelector(".lt-btn--delete-override");
    if (!btn || !_editData) return;
    const lang = _editLang;
    const entry = (_editData.translations[lang]) || {};

    if (!entry.has_override) {
      btn.style.display = "none";
      return;
    }

    btn.style.display = "";
    const marked = !!_deletionsMarked[lang];

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
    const lang = _editLang;
    if (_deletionsMarked[lang]) {
      delete _deletionsMarked[lang];
    } else {
      _deletionsMarked[lang] = true;
    }
    _renderEditorPanels();
    _updateTabDirtyDots();
  }

  /**
   * Collect all edited values, deletions, and active flags, then persist via API.
   * Handles both save and delete operations in parallel.
   * @returns {Promise<void>}
   */
  async function handleSave() {
    const saveBtn = dialog.querySelector(".lt-btn--save");
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    showDialogError(null);

    // Capture whatever is in the current textarea/toggle before sending
    _persistCurrentEdit();

    const attrData = currentAttrName ? _getAttrInfo(currentSpan, currentAttrName) : null;
    const msgid = attrData ? attrData.m : currentSpan.dataset.ltMsgid;
    const context = attrData ? attrData.c : (currentSpan.dataset.ltContext || "");

    // Separate languages into save vs delete groups
    const translations = {};
    const activeFlags = {};
    const langsToDelete = [];
    for (let i = 0; i < LANGUAGES.length; i++) {
      const lang = LANGUAGES[i];
      if (_deletionsMarked[lang]) {
        langsToDelete.push(lang);
        continue;
      }
      translations[lang] = _editedValues[lang] !== undefined ? _editedValues[lang] : "";
      activeFlags[lang] = _editedActiveFlags[lang] !== undefined ? _editedActiveFlags[lang] : ACTIVE_BY_DEFAULT;
    }

    // Run save and delete sequentially — SQLite cannot handle concurrent
    // write transactions from parallel requests ("database is locked").
    var hasSave = Object.keys(translations).length > 0;
    var hasDelete = langsToDelete.length > 0;

    if (!hasSave && !hasDelete) {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
      closeModal();
      return;
    }

    try {
      var display = null;
      if (hasSave) {
        var saveResult = await api.saveTranslations(msgid, context, translations, activeFlags);
        if (saveResult && saveResult.display) display = saveResult.display;
      }
      if (hasDelete) {
        var deleteResult = await api.deleteTranslation(msgid, context, langsToDelete);
        if (deleteResult && deleteResult.display) display = deleteResult.display;
      }
      if (display) {
        _updateDomInPlace(msgid, context, display.text, display.is_preview_entry);
      }
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
      closeModal();
    } catch (err) {
      showDialogError(err.message, err.details || null);
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
    }
  }

  /**
   * Look up a single attribute descriptor from the element's `data-lt-attrs` JSON array.
   * @param {HTMLElement} element  - Element carrying `data-lt-attrs`.
   * @param {string}      attrName - Attribute name to find (e.g. "title").
   * @returns {AttrInfo|null} The matching descriptor, or null if not found.
   */
  function _getAttrInfo(element, attrName) {
    const attrs = _parseLtAttrs(element);
    for (let i = 0; i < attrs.length; i++) {
      if (attrs[i].a === attrName) return attrs[i];
    }
    return null;
  }

  // ─── History Panel ──────────────────────────────────

  /** @type {HistoryEntry[]} - Cached entries from the last history fetch. */
  let _historyData = [];
  /** @type {string} - Active language filter ("" = show all languages). */
  let _historyLangFilter = "";

  /**
   * Read the msgid and context for the element currently being edited,
   * accounting for both inline text spans and attribute translations.
   * @returns {{msgid: string, context: string}}
   */
  function _getMsgidAndContext() {
    const attrData = currentAttrName ? _getAttrInfo(currentSpan, currentAttrName) : null;
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
    const btn = dialog.querySelector(".lt-btn--history");
    btn.innerHTML = _iconHistory;
    btn.title = "View edit history";

    const tabBar = dialog.querySelector(".lt-editor__tabs");
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
   * @returns {Promise<void>}
   */
  async function _showHistoryView() {
    if (!dialog) return;
    dialog.querySelector(".lt-dialog__title").textContent = "Edit History";
    const btn = dialog.querySelector(".lt-btn--history");
    btn.innerHTML = _iconBack;
    btn.title = "Back to editing";

    // Persist current edits before switching views
    _persistCurrentEdit();

    const tabBar = dialog.querySelector(".lt-editor__tabs");
    if (tabBar) tabBar.style.display = "none";

    dialog.querySelector(".lt-dialog__fields").style.display = "none";
    dialog.querySelector(".lt-dialog__hint").style.display = "none";
    dialog.querySelector(".lt-dialog__actions").style.display = "none";
    dialog.querySelector(".lt-dialog__error").style.display = "none";

    const historyEl = dialog.querySelector(".lt-dialog__history");
    historyEl.style.display = "block";
    historyEl.innerHTML =
      '<div class="lt-history__loading">Loading history\u2026</div>';

    _historyLangFilter = "";
    _historyData = [];

    const info = _getMsgidAndContext();
    try {
      const data = await api.getHistory(info.msgid, info.context);
      _historyData = data.history || [];
      _renderHistoryPanel(historyEl);
    } catch {
      historyEl.innerHTML =
        '<div class="lt-history__empty">Failed to load history.</div>';
    }
  }

  /** @type {Object<string, string>} - Human-readable labels for history action types. */
  const _ACTION_LABELS = {
    create: "Created",
    update: "Updated",
    "delete": "Deleted",
    activate: "Activated",
    deactivate: "Deactivated",
  };

  /** @type {Object<string, string>} - Inline SVG markup for each history action type. */
  const _ACTION_ICONS = {
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
    const langs = [];
    /** @type {Object<string, boolean>} */
    const langSet = {};
    for (let k = 0; k < _historyData.length; k++) {
      const l = _historyData[k].language;
      if (!langSet[l]) {
        langSet[l] = true;
        langs.push(l);
      }
    }
    langs.sort();

    if (langs.length > 1) {
      const filterBar = document.createElement("div");
      filterBar.className = "lt-history__filters";

      const allPill = document.createElement("button");
      allPill.type = "button";
      allPill.className = "lt-history__filter-pill" + (!_historyLangFilter ? " lt-history__filter-pill--active" : "");
      allPill.textContent = "All";
      allPill.addEventListener("click", function () {
        _historyLangFilter = "";
        _renderHistoryPanel(container);
      });
      filterBar.appendChild(allPill);

      for (let p = 0; p < langs.length; p++) {
        (function (code) {
          const meta = LANG_META[code];
          const pill = document.createElement("button");
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
    const filtered = _historyLangFilter
      ? _historyData.filter(function (e) { return e.language === _historyLangFilter; })
      : _historyData;

    if (filtered.length === 0) {
      const emptyMsg = document.createElement("div");
      emptyMsg.className = "lt-history__empty";
      emptyMsg.textContent = "No history for this language.";
      container.appendChild(emptyMsg);
      return;
    }

    // ── Timeline ──
    const timeline = document.createElement("div");
    timeline.className = "lt-history__timeline";

    // Track the newest (current) entry per language to hide its Restore button
    /** @type {Object<string, number>} */
    const newestPerLang = {};
    for (let n = 0; n < filtered.length; n++) {
      if (!newestPerLang[filtered[n].language]) {
        newestPerLang[filtered[n].language] = filtered[n].id;
      }
    }

    for (let i = 0; i < filtered.length; i++) {
      const entry = filtered[i];
      const item = document.createElement("div");
      item.className = "lt-history__entry lt-history__entry--" + entry.action;

      const header = document.createElement("div");
      header.className = "lt-history__entry-header";

      // Action icon (colored container — replaces text label)
      const iconEl = document.createElement("span");
      iconEl.className = "lt-history__icon lt-history__icon--" + entry.action;
      iconEl.innerHTML = _ACTION_ICONS[entry.action] || "";
      iconEl.title = _ACTION_LABELS[entry.action] || entry.action;
      header.appendChild(iconEl);

      // Flag (only when showing all languages)
      let hasFlag = false;
      if (!_historyLangFilter) {
        const langMeta = LANG_META[entry.language];
        if (langMeta) {
          const flag = document.createElement("span");
          flag.className = "lt-history__flag";
          flag.textContent = langMeta.flag;
          header.appendChild(flag);
          hasFlag = true;
        }
      }

      // Separator between flag and time (only when flag is visible)
      if (hasFlag) {
        const sep1 = document.createElement("span");
        sep1.className = "lt-history__sep";
        sep1.textContent = "\u00b7";
        header.appendChild(sep1);
      }

      const time = document.createElement("time");
      time.className = "lt-history__time";
      time.setAttribute("datetime", entry.created_at);
      time.textContent = _formatTime(entry.created_at);
      time.title = new Date(entry.created_at).toLocaleString();
      header.appendChild(time);

      // User
      if (entry.user && entry.user !== "System") {
        const sep2 = document.createElement("span");
        sep2.className = "lt-history__sep";
        sep2.textContent = "\u00b7";
        header.appendChild(sep2);

        const user = document.createElement("span");
        user.className = "lt-history__user";
        user.textContent = entry.user;
        header.appendChild(user);
      }

      item.appendChild(header);

      // ── Content block ──
      const isStateChange = entry.action === "activate" || entry.action === "deactivate";

      if (isStateChange) {
        const statusEl = document.createElement("div");
        statusEl.className = "lt-history__status lt-history__status--" + entry.action;
        const dot = document.createElement("span");
        dot.className = "lt-history__status-dot";
        const statusText = document.createElement("span");
        statusText.textContent = entry.action === "activate"
          ? "Translation enabled"
          : "Translation disabled";
        statusEl.appendChild(dot);
        statusEl.appendChild(statusText);
        item.appendChild(statusEl);
      } else {
        // Build diff view
        let diffView = null;
        if (entry.diff && entry.diff.length > 0) {
          diffView = document.createElement("div");
          diffView.className = "lt-history__diff";
          for (let j = 0; j < entry.diff.length; j++) {
            const seg = entry.diff[j];
            const segSpan = document.createElement("span");
            segSpan.className = "lt-diff lt-diff--" + seg.type;
            segSpan.textContent = seg.text;
            diffView.appendChild(segSpan);
          }
        } else if (entry.action === "create" && entry.new_value) {
          diffView = document.createElement("div");
          diffView.className = "lt-history__diff";
          const cSpan = document.createElement("span");
          cSpan.className = "lt-diff lt-diff--insert";
          cSpan.textContent = entry.new_value;
          diffView.appendChild(cSpan);
        } else if (entry.action === "delete" && entry.old_value) {
          diffView = document.createElement("div");
          diffView.className = "lt-history__diff";
          const dSpan = document.createElement("span");
          dSpan.className = "lt-diff lt-diff--delete";
          dSpan.textContent = entry.old_value;
          diffView.appendChild(dSpan);
        }

        if (diffView) {
          const hasValues = entry.old_value || entry.new_value;
          if (hasValues) {
            // Toggle tabs: Diff / Value
            const tabs = document.createElement("div");
            tabs.className = "lt-history__content-tabs";

            const tDiff = document.createElement("button");
            tDiff.type = "button";
            tDiff.className = "lt-history__content-tab lt-history__content-tab--active";
            tDiff.textContent = "Diff";
            tabs.appendChild(tDiff);

            const tVal = document.createElement("button");
            tVal.type = "button";
            tVal.className = "lt-history__content-tab";
            tVal.textContent = "Value";
            tabs.appendChild(tVal);

            item.appendChild(tabs);
            item.appendChild(diffView);

            // Value view (hidden by default)
            const valView = document.createElement("div");
            valView.className = "lt-history__values";
            valView.style.display = "none";
            _buildValueSections(valView, entry);
            item.appendChild(valView);

            // Toggle handlers (IIFE for closure)
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
      const isCurrent = newestPerLang[entry.language] === entry.id;
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
    const restoreValue = entry.action === "delete" ? entry.old_value : entry.new_value;

    // Restore button sits in the header row, right-aligned (like Revert in edit view).
    // When no lang tag precedes it, it needs margin-left:auto to push right.
    const restoreBtn = document.createElement("button");
    restoreBtn.type = "button";
    restoreBtn.className = "lt-history__restore-btn";
    restoreBtn.style.marginLeft = "auto";
    restoreBtn.textContent = "Restore";
    header.appendChild(restoreBtn);

    // Confirmation panel (hidden initially, appended to the item below header)
    const confirm = document.createElement("div");
    confirm.className = "lt-history__restore-confirm";
    confirm.style.display = "none";

    const confirmActions = document.createElement("div");
    confirmActions.className = "lt-history__restore-actions";

    const activateBtn = document.createElement("button");
    activateBtn.type = "button";
    activateBtn.className = "lt-history__restore-activate";
    activateBtn.textContent = "Restore & activate";

    const inactiveBtn = document.createElement("button");
    inactiveBtn.type = "button";
    inactiveBtn.className = "lt-history__restore-inactive";
    inactiveBtn.textContent = "Restore as inactive";

    const cancelBtn = document.createElement("button");
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
   * @returns {Promise<void>}
   */
  async function _executeRestore(language, value, activate, confirmEl) {
    // Disable buttons during request
    const buttons = confirmEl.querySelectorAll("button");
    for (let b = 0; b < buttons.length; b++) buttons[b].disabled = true;

    const info = _getMsgidAndContext();
    const translations = {};
    translations[language] = value;
    const activeFlags = {};
    activeFlags[language] = activate;

    try {
      const data = await api.saveTranslations(info.msgid, info.context, translations, activeFlags);
      if (data && data.display) {
        _updateDomInPlace(info.msgid, info.context, data.display.text, data.display.is_preview_entry);
      }
      closeModal();
    } catch (err) {
      for (let b = 0; b < buttons.length; b++) buttons[b].disabled = false;
      showToast("Restore failed: " + err.message, "error");
    }
  }

  /**
   * Render "Before" / "After" value sections for the history Value tab.
   * @param {HTMLElement}  container - Parent element to append sections into.
   * @param {HistoryEntry} entry     - The history entry with `old_value` and/or `new_value`.
   * @returns {void}
   */
  function _buildValueSections(container, entry) {
    /**
     * @param {string} label - Section heading ("Before" / "After").
     * @param {string} text  - Value to display.
     */
    function addSection(label, text) {
      const sec = document.createElement("div");
      sec.className = "lt-history__value-section";
      const lbl = document.createElement("div");
      lbl.className = "lt-history__value-label";
      lbl.textContent = label;
      const txt = document.createElement("div");
      txt.className = "lt-history__value-text";
      txt.textContent = text;
      sec.appendChild(lbl);
      sec.appendChild(txt);
      container.appendChild(sec);
    }
    if (entry.old_value) addSection("Before", entry.old_value);
    if (entry.new_value) addSection("After", entry.new_value);
  }

  /**
   * Format an ISO 8601 timestamp as a human-friendly relative time string
   * (e.g. "just now", "5m ago", "3d ago") or a locale date for older entries.
   * @param {string} isoString - ISO 8601 date string from the API.
   * @returns {string}
   */
  function _formatTime(isoString) {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

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
      const delBtn = dialog.querySelector(".lt-btn--delete-override");
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
  let selectedElements = [];
  /** @type {HTMLElement|null} */
  let actionBar = null;
  /** @type {boolean} */
  let actionBarConfirming = false;

  /**
   * Toggle an element's selection state for bulk activation.
   * @param {HTMLElement} el - The element to toggle.
   * @returns {void}
   */
  function _toggleSelected(el) {
    const idx = selectedElements.indexOf(el);
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
    for (let i = 0; i < selectedElements.length; i++) {
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
    const count = selectedElements.length;
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
    const count = selectedElements.length;
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
    const count = selectedElements.length;
    const lang = _pageLang() || "unknown";
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
   * @returns {Promise<void>}
   */
  async function _executeBulkActivate() {
    const confirmBtn = actionBar.querySelector(".lt-action-bar__confirm");
    if (confirmBtn) confirmBtn.disabled = true;

    const msgids = [];
    /** @type {Object<string, boolean>} */
    const seen = {};

    for (let i = 0; i < selectedElements.length; i++) {
      const el = selectedElements[i];

      if (el.dataset.ltMsgid) {
        // Inline text span
        const msgid = el.dataset.ltMsgid;
        const context = el.dataset.ltContext || "";
        const key = _entryKey(msgid, context);
        if (!seen[key]) {
          seen[key] = true;
          msgids.push({ msgid: msgid, context: context });
        }
      } else if (el.dataset.ltAttrs) {
        // Attribute element — collect all preview entries
        const attrs = _parseLtAttrs(el);
        for (let j = 0; j < attrs.length; j++) {
          const aKey = _entryKey(attrs[j].m, attrs[j].c);
          if (!seen[aKey]) {
            seen[aKey] = true;
            msgids.push({ msgid: attrs[j].m, context: attrs[j].c || "" });
          }
        }
      }
    }

    if (msgids.length === 0) {
      showToast("No translations to activate", "error");
      _renderActionBarDefault();
      return;
    }

    const lang = _pageLang();

    try {
      const data = await api.bulkActivate(msgids, lang);
      showToast(data.activated + " translation(s) activated", "success");
      // Delay reload so the user (and tests) can see the success toast.
      setTimeout(_reloadPage, 1500);
    } catch (err) {
      showToast("Bulk activate failed: " + err.message, "error");
      if (confirmBtn) confirmBtn.disabled = false;
    }
  }

  /**
   * Initialize preview mode: mark elements with inactive overrides and create the action bar.
   * Called once on DOMContentLoaded when PREVIEW is true.
   * @returns {void}
   */
  function _initPreviewMode() {
    // Build lookup from config
    /** @type {Object<string, boolean>} */
    const lookup = {};
    for (let i = 0; i < PREVIEW_ENTRIES.length; i++) {
      const pe = PREVIEW_ENTRIES[i];
      lookup[_entryKey(pe.m, pe.c)] = true;
    }

    // Mark inline text elements (lt-t elements created by resolveMarkers)
    const spans = document.querySelectorAll("lt-t");
    for (let s = 0; s < spans.length; s++) {
      const sp = spans[s];
      const spKey = _entryKey(sp.dataset.ltMsgid || "", sp.dataset.ltContext || "");
      if (lookup[spKey]) {
        sp.classList.add("lt-preview");
      }
    }

    // Mark attribute-translatable elements
    const attrEls = document.querySelectorAll("[data-lt-attrs]");
    for (let a = 0; a < attrEls.length; a++) {
      const attrs = _parseLtAttrs(/** @type {HTMLElement} */ (attrEls[a]));
      for (let j = 0; j < attrs.length; j++) {
        const aKey = _entryKey(attrs[j].m || "", attrs[j].c || "");
        if (lookup[aKey]) {
          attrEls[a].classList.add("lt-preview");
          break;
        }
      }
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
    const tag = document.activeElement ? document.activeElement.tagName : "";
    const inInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

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

      // Check for inline text element first
      const span = e.target.closest("lt-t");
      if (span) {
        e.preventDefault();
        e.stopPropagation();

        // Shift+click in preview mode: if the lt-t lives inside an
        // attribute-translatable element that has a preview marker, select
        // the *parent* attribute element (not the inner text span).
        if (e.shiftKey && PREVIEW) {
          var parentAttr = span.closest("[data-lt-attrs]");
          if (parentAttr && parentAttr.classList.contains("lt-preview")) {
            _toggleSelected(parentAttr);
            window.getSelection().removeAllRanges();
            return;
          }
          if (span.classList.contains("lt-preview")) {
            _toggleSelected(span);
            window.getSelection().removeAllRanges();
            return;
          }
        }

        openModal(span);
        return;
      }

      // Check for attribute-translatable element
      const attrEl = e.target.closest("[data-lt-attrs]");
      if (attrEl) {
        e.preventDefault();
        e.stopPropagation();

        // Shift+click on preview elements toggles selection
        if (e.shiftKey && PREVIEW && attrEl.classList.contains("lt-preview")) {
          _toggleSelected(attrEl);
          window.getSelection().removeAllRanges();
          return;
        }

        const attrs = _parseLtAttrs(attrEl);
        if (!attrs.length) return;

        openModal(attrEl, attrs[0]);
      }
    },
    true
  ); // Use capture phase to intercept before other handlers

  // ─── ZWC Marker Resolution + Edit Mode Restore ───────

  document.addEventListener("DOMContentLoaded", function () {
    // Resolve ZWC markers in text nodes and attribute values
    resolveMarkers();

    // Restore edit mode after reload (if persisted in sessionStorage)
    try {
      if (sessionStorage.getItem(_EDIT_MODE_KEY)) {
        sessionStorage.removeItem(_EDIT_MODE_KEY);
        if (state === "inactive") {
          activateEditMode();
        }
      }
    } catch (e) { /* private browsing / quota */ }

    // Preview mode auto-activation
    if (PREVIEW) {
      if (state === "inactive") {
        activateEditMode();
      }
      _initPreviewMode();
    }
  });

  // ─── Shortcut Hint (sticky bar) ──────────────────────

  /** @type {string} */
  const _HINT_POS_KEY = "lt_hint_pos";
  /** @type {HTMLElement|null} */
  let _hintBar = null;
  /** @type {boolean} - True while a drag gesture is in progress (past threshold). */
  let _hintDidDrag = false;

  /**
   * Show a persistent shortcut hint bar at the bottom of the viewport.
   * The entire bar is draggable. Edit/Preview are clickable toggle buttons.
   * Position is remembered in localStorage.
   * @returns {void}
   */
  function _showShortcutHint() {
    const bar = document.createElement("div");
    bar.className = "lt-hint";

    // Brand label
    const brand = document.createElement("span");
    brand.className = "lt-hint__brand";
    brand.textContent = "Live Translations";
    bar.appendChild(brand);

    // Separator after brand
    const sep0 = document.createElement("span");
    sep0.className = "lt-hint__sep";
    bar.appendChild(sep0);

    // Edit mode button
    const editBtn = document.createElement("button");
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
    const previewBtn = document.createElement("button");
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
    const tip = document.createElement("span");
    tip.className = "lt-hint__tip";
    tip.title = "Hold Shift and click translated text to select multiple entries";
    tip.innerHTML = '<kbd class="lt-hint__kbd">Shift</kbd><span class="lt-hint__label">click to select</span>';
    bar.appendChild(tip);

    document.body.appendChild(bar);
    _hintBar = bar;

    // Restore saved position or use default centered bottom
    /** @type {HintPosition|null} */
    let savedPos = null;
    try {
      const raw = localStorage.getItem(_HINT_POS_KEY);
      if (raw) savedPos = JSON.parse(raw);
    } catch (e) { /* ignore */ }

    if (savedPos && typeof savedPos.x === "number" && typeof savedPos.y === "number") {
      const x = Math.max(0, Math.min(window.innerWidth - bar.offsetWidth, savedPos.x));
      const y = Math.max(0, Math.min(window.innerHeight - bar.offsetHeight, savedPos.y));
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
  const _DRAG_THRESHOLD = 3;

  /**
   * Make the entire hint bar draggable.
   * Uses a movement threshold to distinguish clicks from drags — button
   * click handlers check `_hintDidDrag` and bail if a drag just occurred.
   * @param {HTMLElement} bar - The hint bar element.
   * @returns {void}
   */
  function _initHintDrag(bar) {
    /** @type {DragState|null} */
    let dragState = null;

    bar.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return;
      // Don't prevent default — let clicks reach buttons if no drag happens

      const rect = bar.getBoundingClientRect();
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

      const dx = e.clientX - dragState.mouseX;
      const dy = e.clientY - dragState.mouseY;

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

      const newX = dragState.barX + dx;
      const newY = dragState.barY + dy;
      const maxX = window.innerWidth - bar.offsetWidth;
      const maxY = window.innerHeight - bar.offsetHeight;
      bar.style.left = Math.max(0, Math.min(maxX, newX)) + "px";
      bar.style.top = Math.max(0, Math.min(maxY, newY)) + "px";
    });

    document.addEventListener("mouseup", function () {
      if (!dragState) return;
      const wasDrag = dragState.moved;
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
    const editEl = _hintBar.querySelector('[data-mode="edit"]');
    const previewEl = _hintBar.querySelector('[data-mode="preview"]');
    const tipEl = _hintBar.querySelector(".lt-hint__tip");
    if (editEl) editEl.classList.toggle("lt-hint__action--active", state === "active" || state === "editing");
    if (previewEl) previewEl.classList.toggle("lt-hint__action--active", PREVIEW);
    if (tipEl) tipEl.classList.toggle("lt-hint__tip--visible", PREVIEW);
  }

  _showShortcutHint();
})();
