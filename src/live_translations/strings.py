"""Zero-width character markers and gettext monkey-patching for live translation editing.

Patched gettext/pgettext/ngettext/npgettext functions insert an invisible ZWC start
flag and append an 18-character ZWC end marker (encoding a per-request string-table ID)
to each translated string.  Both markers survive Django's autoescaping because ZWC
characters are not HTML-special.

Two distinct start-flag characters are used: ``\\u2060`` (WORD JOINER) at
**position 1** for normal text (safe from ``capfirst``), and ``\\uFEFF`` at
**position 0** when the translation starts with an HTML tag (to avoid breaking
the tag name).  The distinct characters let the JS apply the correct wrapping
strategy for multi-node inline-HTML translations.

The middleware injects the string table as ``window.__LT_STRINGS__`` and the
client-side JS uses the start flag to locate the beginning of a translation span
(which may contain multiple DOM nodes when HTML tags are present), strips the
markers, builds an internal registry, and wraps text nodes in ``<lt-t>`` elements.
"""

import contextvars
import logging
import typing as t

import django.utils.safestring
import django.utils.translation

if t.TYPE_CHECKING:
    import types

from live_translations.types import MsgKey, OverrideMap, PluralForms, StringId

__all__ = [
    "WJ",
    "ZWC_BOUNDARY",
    "encode_zwc",
    "get_string_registry",
    "install_gettext_patch",
    "lt_active",
    "lt_current_user",
    "lt_preview_overrides",
    "register_string",
    "reset_string_registry",
]

logger = logging.getLogger("live_translations")

# ---------------------------------------------------------------------------
# Zero-width character encoding
# ---------------------------------------------------------------------------
# Format: FEFF + 16 x (200B | 200C) + FEFF = 18 invisible chars
# Supports IDs 0-65535 (one per unique MsgKey per request).

ZWC_0: t.Final[str] = "\u200b"  # ZERO WIDTH SPACE  → bit 0
ZWC_1: t.Final[str] = "\u200c"  # ZERO WIDTH NON-JOINER → bit 1
ZWC_BOUNDARY: t.Final[str] = "\ufeff"  # BOM / ZWNBSP → marker boundary + position-0 start flag
WJ: t.Final[str] = "\u2060"  # WORD JOINER → position-1 start flag

_ZWC_BITS: t.Final[int] = 16
_ZWC_MAX_ID: t.Final[int] = (1 << _ZWC_BITS) - 1


def encode_zwc(n: StringId) -> str:
    """Encode a string-table ID as 18 zero-width characters."""
    if n < 0 or n > _ZWC_MAX_ID:
        raise ValueError(f"StringId out of range: {n}")
    bits = format(n, f"0{_ZWC_BITS}b")
    return ZWC_BOUNDARY + "".join(ZWC_1 if b == "1" else ZWC_0 for b in bits) + ZWC_BOUNDARY


# ---------------------------------------------------------------------------
# Per-request contextvars
# ---------------------------------------------------------------------------

# Whether the current request should produce translation markers.
lt_active: contextvars.ContextVar[bool] = contextvars.ContextVar("lt_active", default=False)

if t.TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

# Current user reference for history tracking.
lt_current_user: "contextvars.ContextVar[AbstractBaseUser | None]" = contextvars.ContextVar(
    "lt_current_user", default=None
)

# Preview overrides: maps MsgKey → PluralForms for inactive translations shown in preview mode.
lt_preview_overrides: contextvars.ContextVar[OverrideMap | None] = contextvars.ContextVar(
    "lt_preview_overrides", default=None
)

# ---------------------------------------------------------------------------
# Per-request string registry
# ---------------------------------------------------------------------------

_lt_string_registry: contextvars.ContextVar[list[MsgKey] | None] = contextvars.ContextVar(
    "lt_string_registry", default=None
)
_lt_string_id_map: contextvars.ContextVar[dict[MsgKey, StringId] | None] = contextvars.ContextVar(
    "lt_string_id_map", default=None
)


def register_string(key: MsgKey) -> StringId:
    """Register a translatable string and return its ID.  Deduplicates by MsgKey."""
    registry = _lt_string_registry.get()
    id_map = _lt_string_id_map.get()
    if registry is None or id_map is None:
        registry, id_map = [], {}
        _lt_string_registry.set(registry)
        _lt_string_id_map.set(id_map)
    existing = id_map.get(key)
    if existing is not None:
        return existing
    string_id: StringId = len(registry)
    registry.append(key)
    id_map[key] = string_id
    return string_id


def get_string_registry() -> list[MsgKey]:
    """Return the current request's string registry for middleware serialization."""
    return _lt_string_registry.get() or []


def reset_string_registry() -> None:
    """Reset the per-request string registry.  Called in middleware ``finally`` block."""
    _lt_string_registry.set(None)
    _lt_string_id_map.set(None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

type _GettextFn = t.Callable[[str], str]
type _PgettextFn = t.Callable[[str, str], str]
type _NgettextFn = t.Callable[[str, str, int], str]
type _NpgettextFn = t.Callable[[str, str, str, int], str]


def _insert_markers(result: str, key: MsgKey) -> str:
    """Insert a ZWC start flag and append a ZWC end marker to a translated string.

    This function is pure marker insertion -- no preview override logic.
    Preview resolution is handled by each patched function individually
    (ngettext needs the ``number`` arg to resolve the correct plural form).

    Two distinct start-flag characters are used so the client-side JS can apply
    the correct wrapping strategy for inline-HTML translations:

    * **Position-0 flag** (``\\uFEFF``): used when the translation starts with
      an HTML tag (``result[0] == '<'``).  The flag goes before the ``<`` to
      avoid breaking tag names.

    * **Position-1 flag** (``\\u2060`` WORD JOINER): used for normal text.  The
      flag is placed at position 1 (after the first visible character) so that
      ``capfirst`` (``x[0].upper() + x[1:]``) still operates on the first
      visible character.

    **SafeString preservation**: Django's ``{% trans %}`` passes template
    literals as ``SafeString`` through ``gettext``.  We must re-wrap the output
    with ``mark_safe`` when the input was ``SafeData``, otherwise Django's
    ``conditional_escape`` will HTML-escape the result.
    """
    was_safe = isinstance(result, django.utils.safestring.SafeData)

    string_id = register_string(key)
    end_marker = encode_zwc(string_id)

    if len(result) == 0:
        output = end_marker
    elif result[0] == "<":
        # HTML at position 0: FEFF flag before the tag to avoid breaking tag names.
        output = ZWC_BOUNDARY + result + end_marker
    elif result[0] == "%":
        # Format specifier at start: FEFF flag before to avoid breaking %(name)s patterns.
        # blocktranslate does `result % vars` after ngettext returns; a WJ between % and (
        # would break the format specifier.
        output = ZWC_BOUNDARY + result + end_marker
    else:
        # Normal case: WJ flag at position 1 (after first char, safe from capfirst).
        output = result[0] + WJ + result[1:] + end_marker

    return django.utils.safestring.mark_safe(output) if was_safe else output  # noqa: S308


def _resolve_singular_preview(key: MsgKey) -> str | None:
    """Resolve a singular preview override (form 0). Returns None if no override."""
    preview = lt_preview_overrides.get(None)
    if preview is None:
        return None
    pv = preview.get(key)
    if pv is None:
        return None
    return pv.get(0, "")


def _resolve_plural_preview(key: MsgKey, number: int) -> str | None:
    """Resolve a plural preview override for the given number. Returns None if no override."""
    preview = lt_preview_overrides.get(None)
    if preview is None:
        return None
    pv: PluralForms | None = preview.get(key)
    if pv is None:
        return None
    form_idx = _get_plural_index(number)
    return pv.get(form_idx, pv.get(0, ""))


def _get_plural_index(number: int) -> int:
    """Get the plural form index for the current language and given number."""
    from django.utils.translation import trans_real

    lang = trans_real.get_language() or "en"
    try:
        trans = trans_real.translation(lang)
        return trans.plural(number)  # type: ignore[attr-defined, no-any-return]
    except Exception:  # noqa: BLE001
        # Fallback: 0 for 1, 1 otherwise (English-style)
        return 0 if number == 1 else 1


# ---------------------------------------------------------------------------
# Gettext monkey-patching
# ---------------------------------------------------------------------------


def install_gettext_patch() -> None:
    """Monkey-patch Django's translation system to append ZWC markers.

    Called once from ``AppConfig.ready()``.  Patches ``_trans.gettext``,
    ``_trans.pgettext``, ``_trans.ngettext``, and ``_trans.npgettext``.
    Lazy variants automatically pick up the patches because their proxies
    delegate to the ``_trans`` functions on evaluation.

    For regular users (``lt_active=False``), the patched functions are a
    near-zero-cost pass-through: one extra function call + one ContextVar.get().
    """
    _trans: types.ModuleType = django.utils.translation._trans  # type: ignore[attr-defined]

    # Force lazy resolution of _trans attributes by accessing them once.
    try:
        _orig_gettext: _GettextFn = _trans.gettext  # type: ignore[union-attr]
    except AttributeError:
        logger.warning("Could not access _trans.gettext -- live translation patching skipped")
        return

    _orig_pgettext: _PgettextFn | None
    try:
        _orig_pgettext = _trans.pgettext  # type: ignore[union-attr]
    except AttributeError:
        _orig_pgettext = None

    _orig_ngettext: _NgettextFn | None
    try:
        _orig_ngettext = _trans.ngettext  # type: ignore[union-attr]
    except AttributeError:
        _orig_ngettext = None

    _orig_npgettext: _NpgettextFn | None
    try:
        _orig_npgettext = _trans.npgettext  # type: ignore[union-attr]
    except AttributeError:
        _orig_npgettext = None

    def _patched_gettext(message: str) -> str:
        result: str = _orig_gettext(message)
        if not lt_active.get(False):
            return result
        message = str(message)
        key = MsgKey(message, "")
        try:
            pv = _resolve_singular_preview(key)
            if pv is not None:
                result = pv
            return _insert_markers(result, key)
        except Exception:
            logger.exception("Failed to append translation marker")
            return result

    def _patched_pgettext(context: str, message: str) -> str:
        result: str = _orig_pgettext(context, message) if _orig_pgettext is not None else _orig_gettext(message)
        if not lt_active.get(False):
            return result
        message, context = str(message), str(context)
        key = MsgKey(message, context)
        try:
            pv = _resolve_singular_preview(key)
            if pv is not None:
                result = pv
            return _insert_markers(result, key)
        except Exception:
            logger.exception("Failed to append translation marker")
            return result

    def _patched_ngettext(singular: str, plural: str, number: int) -> str:
        if _orig_ngettext is None:
            return _orig_gettext(singular if number == 1 else plural)
        result: str = _orig_ngettext(singular, plural, number)
        if not lt_active.get(False):
            return result
        singular, plural = str(singular), str(plural)
        key = MsgKey(singular, "", plural)
        try:
            pv = _resolve_plural_preview(key, number)
            if pv is not None:
                result = pv
            return _insert_markers(result, key)
        except Exception:
            logger.exception("Failed to append translation marker")
            return result

    def _patched_npgettext(context: str, singular: str, plural: str, number: int) -> str:
        if _orig_npgettext is None:
            return _patched_ngettext(singular, plural, number)
        result: str = _orig_npgettext(context, singular, plural, number)
        if not lt_active.get(False):
            return result
        singular, plural, context = str(singular), str(plural), str(context)
        key = MsgKey(singular, context, plural)
        try:
            pv = _resolve_plural_preview(key, number)
            if pv is not None:
                result = pv
            return _insert_markers(result, key)
        except Exception:
            logger.exception("Failed to append translation marker")
            return result

    _trans.gettext = _patched_gettext  # type: ignore[union-attr]
    if _orig_pgettext is not None:
        _trans.pgettext = _patched_pgettext  # type: ignore[union-attr]
    if _orig_ngettext is not None:
        _trans.ngettext = _patched_ngettext  # type: ignore[union-attr]
    if _orig_npgettext is not None:
        _trans.npgettext = _patched_npgettext  # type: ignore[union-attr]
