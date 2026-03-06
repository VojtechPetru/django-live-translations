"""TranslatableString and gettext monkey-patching for live translation editing.

TranslatableString is a str subclass that carries the original msgid.
When rendered in Django templates via {{ variable }}, the autoescape system
calls __html__() which wraps the text in a <span> for superuser editing.

In non-HTML contexts (JSON, emails, DB), it behaves as a normal str.
"""

import contextvars
import logging
import typing as t

from django.utils.html import escape
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

# Per-request flag controlling whether TranslatableString produces wrapping spans.
# Set by LiveTranslationsMiddleware, reset in its finally block.
lt_active: contextvars.ContextVar[bool] = contextvars.ContextVar("lt_active", default=False)


class TranslatableString(str):
    """A str subclass that remembers its gettext msgid for live translation.

    Behaves identically to str in all contexts except Django template
    autoescaping, where __html__() produces a <span> wrapper when
    the lt_active contextvar is True.
    """

    _lt_msgid: str
    _lt_context: str

    def __new__(cls, value: str, msgid: str, context: str = "") -> TranslatableString:
        instance = super().__new__(cls, value)
        instance._lt_msgid = msgid
        instance._lt_context = context
        return instance

    def __html__(self) -> str:
        """Called by Django's conditional_escape during template autoescaping."""
        if not lt_active.get(False):
            return escape(str.__str__(self))

        escaped_content = escape(str.__str__(self))
        escaped_msgid = escape(self._lt_msgid)
        escaped_ctx = escape(self._lt_context)
        return mark_safe(  # type: ignore[return-value]
            f'<span class="lt-translatable" data-lt-msgid="{escaped_msgid}"'
            f' data-lt-context="{escaped_ctx}">{escaped_content}</span>'
        )

    def __mod__(self, args: t.Any) -> str:  # type: ignore[override]
        """Support %-formatting (used by gettext for %(var)s placeholders).

        Returns a plain str since the formatted result may not match the msgid.
        """
        return str.__str__(self) % args

    def format(self, *args: t.Any, **kwargs: t.Any) -> str:  # type: ignore[override]
        """Support .format() — returns plain str."""
        return str.__str__(self).format(*args, **kwargs)


def _get_db_override(msgid: str, context: str = "") -> str | None:
    """Look up a translation override for the current language via the configured backend."""
    from django.utils.translation import get_language

    from .conf import get_backend_instance, get_conf

    backend = get_backend_instance()
    # lookup_override is a no-op (returns None) for backends without DB caching,
    # so the fast path is: get_language() + dict lookup in cached overrides.
    lang = get_language()
    if not lang or lang not in get_conf().languages:
        return None

    return backend.lookup_override(lang, msgid, context)  # type: ignore[no-any-return]


def install_gettext_patch() -> None:
    """Monkey-patch Django's translation system to return TranslatableString.

    Called once from AppConfig.ready(). Patches _trans.gettext and _trans.pgettext
    so that both direct calls and lazy evaluations flow through our wrapper.

    Two responsibilities:
    1. Overlay DB translation overrides on top of .po gettext (for ALL users).
    2. Wrap result in TranslatableString when lt_active is True (superuser edit mode).
    """
    from django.utils.translation import _trans  # type: ignore[attr-defined]

    # Force lazy resolution of _trans attributes by accessing them once.
    # After this, _trans.gettext is a regular attribute (not lazy-loaded).
    try:
        _orig_gettext = _trans.gettext  # type: ignore[union-attr]
    except AttributeError:
        logger.warning("Could not access _trans.gettext — live translation patching skipped")
        return

    try:
        _orig_pgettext = _trans.pgettext  # type: ignore[union-attr]
    except AttributeError:
        _orig_pgettext = None

    def _patched_gettext(message: str) -> str:
        result = _orig_gettext(message)
        # Apply DB override (for all users)
        override = _get_db_override(str(message))
        if override is not None:
            result = override
        if lt_active.get(False):
            return TranslatableString(result, msgid=str(message))
        return result  # type: ignore[no-any-return]

    def _patched_pgettext(context: str, message: str) -> str:
        result = _orig_pgettext(context, message) if _orig_pgettext is not None else _orig_gettext(message)
        # Apply DB override (for all users)
        override = _get_db_override(str(message), str(context))
        if override is not None:
            result = override
        if lt_active.get(False):
            return TranslatableString(result, msgid=str(message), context=str(context))
        return result  # type: ignore[no-any-return]

    _trans.gettext = _patched_gettext  # type: ignore[union-attr]
    if _orig_pgettext is not None:
        _trans.pgettext = _patched_pgettext  # type: ignore[union-attr]
