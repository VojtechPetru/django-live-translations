"""Zero-width character markers and gettext monkey-patching for live translation editing.

Patched gettext/pgettext functions append an invisible 18-character ZWC marker
(encoding a per-request string-table ID) to each translated string.  The marker
survives Django's autoescaping because ZWC characters are not HTML-special.

The middleware injects the string table as ``window.__LT_STRINGS__`` and the
client-side JS strips the markers, builds an internal registry, and wraps text
nodes in temporary ``<span>`` elements only while edit mode is active.
"""

import contextvars
import logging
import typing as t

import django.utils.translation

if t.TYPE_CHECKING:
    import types

from live_translations.types import MsgKey, OverrideMap, StringId

__all__ = [
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
ZWC_BOUNDARY: t.Final[str] = "\ufeff"  # BOM / ZWNBSP → marker boundary

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

# Preview overrides: maps MsgKey → msgstr for inactive translations shown in preview mode.
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


def register_string(msgid: str, context: str) -> StringId:
    """Register a translatable string and return its ID.  Deduplicates by MsgKey."""
    registry = _lt_string_registry.get()
    id_map = _lt_string_id_map.get()
    if registry is None or id_map is None:
        registry, id_map = [], {}
        _lt_string_registry.set(registry)
        _lt_string_id_map.set(id_map)
    key = MsgKey(msgid, context)
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


def _append_marker(result: str, msgid: str, context: str) -> str:
    """Append a ZWC-encoded string-table ID to a translated string.

    Also applies preview overrides when active.
    """
    preview = lt_preview_overrides.get(None)
    if preview is not None:
        pv = preview.get(MsgKey(msgid, context))
        if pv is not None:
            result = pv
    string_id = register_string(msgid, context)
    return result + encode_zwc(string_id)


# ---------------------------------------------------------------------------
# Gettext monkey-patching
# ---------------------------------------------------------------------------


def install_gettext_patch() -> None:
    """Monkey-patch Django's translation system to append ZWC markers.

    Called once from ``AppConfig.ready()``.  Patches ``_trans.gettext`` and
    ``_trans.pgettext``.  Lazy variants (``gettext_lazy``, ``pgettext_lazy``)
    automatically pick up the patches because their proxies delegate to
    ``_trans.gettext`` / ``_trans.pgettext`` on evaluation.

    For regular users (``lt_active=False``), the patched functions are a
    near-zero-cost pass-through.
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

    def _patched_gettext(message: str) -> str:
        result: str = _orig_gettext(message)
        if not lt_active.get(False):
            return result
        # Django may pass lazy proxy objects; force to str once upfront.
        message = str(message)
        try:
            return _append_marker(result, message, "")
        except Exception:
            logger.exception("Failed to append translation marker")
            return result

    def _patched_pgettext(context: str, message: str) -> str:
        result: str = _orig_pgettext(context, message) if _orig_pgettext is not None else _orig_gettext(message)
        if not lt_active.get(False):
            return result
        # Django may pass lazy proxy objects; force to str once upfront.
        message, context = str(message), str(context)
        try:
            return _append_marker(result, message, context)
        except Exception:
            logger.exception("Failed to append translation marker")
            return result

    _trans.gettext = _patched_gettext  # type: ignore[union-attr]
    if _orig_pgettext is not None:
        _trans.pgettext = _patched_pgettext  # type: ignore[union-attr]
