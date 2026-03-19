# How It Works

This page documents the technical internals of django-live-translations. We believe in being transparent about what the package does to your Django process, especially the parts that rely on monkey-patching and private APIs.

## Gettext monkey-patching

The core mechanism is a monkey-patch applied to Django's translation system. On `AppConfig.ready()`, the package replaces `_trans.gettext` and `_trans.pgettext` on Django's internal `django.utils.translation._trans` module.

The patched functions wrap the originals:

- When `lt_active` is `False` (regular users), they call the original function and return immediately. The overhead is a single contextvar lookup - no markers are appended, no string registry is built, no assets are injected, and no response content is modified.
- When `lt_active` is `True` (authorized users), they append an invisible marker to the translated string before returning it.

The middleware sets `lt_active` to `True` only when the request passes the configured permission check. For regular users, the gettext path is a near-zero-cost pass-through and the response is not modified - no markers, no JavaScript, no DOM changes. The only work that runs unconditionally is `ensure_current()` for the database backend (a single cache read per request).

Lazy variants (`gettext_lazy`, `pgettext_lazy`) are automatically covered because their proxies delegate to `_trans.gettext` / `_trans.pgettext` on evaluation.

!!! warning "Private API dependency"
    We patch `django.utils.translation._trans`, which is not a public Django API. This has been stable across Django 4.2 through 5.x, but could break in a future Django release. We test against all supported Django and Python versions in CI.

## Zero-width character markers

To track which string on the rendered page corresponds to which `msgid`, the patched gettext appends an invisible 18-character marker to each translated string.

The marker format is:

```
FEFF + 16 × (200B | 200C) + FEFF
```

- `U+FEFF` (byte order mark) serves as a boundary delimiter
- `U+200B` (zero-width space) represents bit `0`
- `U+200C` (zero-width non-joiner) represents bit `1`
- The 16 bits encode a string-table ID (0--65535), which is a per-request index into the string registry

These characters are invisible in rendered HTML and survive Django's autoescaping, `capfirst`, `html.escape`, and string formatting operations.

### Where markers can leak

The middleware strips markers from non-HTML responses (JSON, plain text, etc.) using a regex. However, markers could theoretically appear in:

- Cached template fragments that were rendered for an authorized user
- Signals or side effects triggered during response rendering
- Third-party middleware that captures response content before our middleware runs

If you encounter ZWC characters in unexpected places, ensure `LiveTranslationsMiddleware` is positioned after any middleware that might cache rendered content.

## Middleware response processing

The middleware (`LiveTranslationsMiddleware`) has three jobs:

1. **API dispatch** - requests to `/__live-translations__/*` are routed directly to view functions, bypassing Django's URL resolver. No `urls.py` configuration is needed.
2. **Asset injection** - for HTML responses from authorized users, the middleware injects three elements before `</body>`:
    - A `<link>` tag loading the widget's CSS (edit mode outlines, modal styles, hint bar)
    - An inline `<script>` containing `window.__LT_CONFIG__` (API base URL, CSRF token, configured languages, keyboard shortcuts) and `window.__LT_STRINGS__` (the per-request string registry mapping ZWC marker IDs to their `msgid` and context - this is how the client-side widget knows what each marker represents)
    - A `<script>` tag loading the widget JavaScript
3. **Marker stripping** - for non-HTML responses (JSON APIs, file downloads), ZWC markers are stripped via regex to prevent them from leaking into API consumers.

The middleware skips Django admin URLs (`/admin/`) entirely to avoid interfering with the admin interface.

``` mermaid
graph TD
    A[Request arrives] --> B{API or admin path?}
    B -->|Yes| C[Return early<br>API dispatch or pass through]
    B -->|No| D{User is translator?}
    D -->|No| E[Return response unmodified]

    D -->|Yes| F["Gettext monkey-patch appends<br>ZWC marker to each translation"]
    F --> G[Django renders response]
    G --> H{HTML response?}
    H -->|No| I[Strip ZWC markers<br>return clean response]
    H -->|Yes| J[Middleware injects<br>string table + widget assets]
    J --> K[Browser renders page]
    K --> L["Widget decodes ZWC markers,<br>resolves msgids from string table"]
    L --> M{Text node or attribute?}
    M -->|Text node| N["Wrap in &lt;lt-t&gt; element"]
    M -->|Attribute| O["Store msgid in data-lt-attrs"]
    N --> P[Widget ready for editing]
    O --> P
```

## Catalog injection (database backend)

The database backend needs to make DB-stored overrides visible to Django's `gettext()` without modifying `.po` files. It does this by writing directly into Django's internal translation catalog objects.

Specifically, it accesses `DjangoTranslation._catalog` (a dict-like object that maps msgid strings to translations) and inserts overrides:

```python
# Simplified version of what happens
catalog[msgid] = override_msgstr
# For context-based translations:
catalog[f"{context}\x04{msgid}"] = override_msgstr
```

!!! warning "Private API dependency"
    `DjangoTranslation._catalog` is an internal implementation detail of `django.utils.translation.trans_real`. The `\x04` separator for context-based lookups is also an internal convention inherited from GNU gettext. Both have been stable for many Django versions, but are not guaranteed.

### Cross-process synchronization

When running multiple processes (e.g. gunicorn workers), each process has its own copy of the translation catalogs. The database backend uses Django's cache framework to keep them in sync:

1. When a translation is saved, a new UUID version is written to the cache
2. On each request, the middleware calls `ensure_current()`, which compares the local version against the cache
3. If stale, the process clears its translation catalogs (via Django's `translation_file_changed` signal) and re-injects all DB overrides

This means there's a brief window after a save where other processes may serve stale translations - typically just the duration of one request cycle.

## PO file pending translations

The PO backend needs to support inactive translations (when `TRANSLATION_ACTIVE_BY_DEFAULT` is `False`) while keeping the `.po` file format valid. It does this by encoding the pending translation as base64 in the entry's translator comment:

```
# ltpending:SGVsbG8gV29ybGQ=
msgid "Hello"
msgstr "original translation"
```

The `ltpending:` prefix (deliberately without a hyphen - polib's textwrap breaks at hyphens) marks the comment as a pending override. The base64 encoding avoids issues with special characters in the comment field.

When the translation is activated, the pending value replaces `msgstr` and the comment is removed.

!!! note
    These comments are visible if you inspect `.po` files directly. They are stripped from the translator hint displayed in the editing widget.

## Frontend widget injection

The widget is a single JavaScript file (~2500 lines, vanilla JS, zero dependencies) bundled as a Django static file. It is injected as a `<script>` tag only for authorized users.

The widget:

1. Walks the DOM looking for ZWC boundary characters (`U+FEFF`)
2. Decodes the 16-bit ID from the ZWC sequence
3. Looks up the `msgid` and context in `window.__LT_STRINGS__`
4. Strips the markers and wraps the text node in an `<lt-t>` custom element (an inert inline element with no shadow DOM)
5. Attaches click handlers for edit mode

The `<lt-t>` element was chosen because it's an unknown HTML element that browsers treat as an inline `<span>`-like element, with no default styling or semantic meaning. All widget styles are prefixed with `.lt-` to avoid conflicts with the host page.

## Test suite

The package is tested at multiple levels to catch regressions across the full stack:

- **470+ unit tests** covering all core modules, backends, views, admin, and error handling
- **290+ end-to-end tests** using Playwright against a real Django dev server
- E2E tests run against **both backends** (PO and database), each with their own Django server instance
- CI matrix tests across **Python 3.12--3.14** and **Django 4.2--6.0**
- CI enforces **90%+ unit test coverage**; e2e coverage is tracked separately
- **Type checking** with pyrefly and **linting** with ruff run on every push and PR
- **Benchmarks** verify runtime overhead stays within bounds: < 10% for normal users, < 100% for translators. Normal users (not authorized for live translation) only pay for a single contextvar lookup per `gettext()` call: no markers, no injection, no response modification. In practice the overhead is ~1-2% in a pure translation-rendering scenario (no DB hits, network I/O, etc.), so in real applications the relative cost is even lower. Run with `pytest tests/benchmarks/`.

## Performance characteristics

| Scenario | Overhead |
|----------|----------|
| Regular user (not authorized) | One contextvar lookup per `gettext()` call. No markers, no injection, no response modification. DB backend adds one cache read per request (`ensure_current()`). |
| Authorized user, edit mode off | ZWC encoding + string registry per `gettext()` call, asset injection on response |
| Authorized user, edit mode on | Same as above, plus client-side DOM walking |
| Database backend, per request | One cache read (`ensure_current()`), occasional full catalog re-injection |
