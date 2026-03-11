"""TranslatableString and gettext monkey-patching for live translation editing.

TranslatableString is a str subclass that carries the original msgid.
When rendered in Django templates via {{ variable }}, the autoescape system
calls __html__() which produces a text-safe marker. The middleware later
resolves markers into <span> wrappers (text content) or plain text with
data-lt-attrs metadata (HTML attributes).

In non-HTML contexts (JSON, emails, DB), it behaves as a normal str.
"""

import base64
import contextvars
import logging
import re
import typing as t

import django.utils.html
import django.utils.safestring

logger = logging.getLogger("live_translations")

# -- Marker format --
# Text-safe markers use ASCII control characters as delimiters.
# They contain no HTML special chars (<, >, ", ', &) so they're
# valid in both text content and HTML attribute values.
#
# Format: \x02 base64(msgid) \x01 base64(ctx) \x01 base64(content) \x01 flag \x03
#   flag: "r" = raw content (needs HTML escaping)
#          "e" = already escaped by Django's template engine

MARKER_START = "\x02"
MARKER_SEP = "\x01"
MARKER_END = "\x03"

MARKER_RE = re.compile(
    MARKER_START
    + r"([A-Za-z0-9+/=]*)"  # group 1: base64 msgid
    + MARKER_SEP
    + r"([A-Za-z0-9+/=]*)"  # group 2: base64 context
    + MARKER_SEP
    + r"([A-Za-z0-9+/=]*)"  # group 3: base64 content
    + MARKER_SEP
    + r"([re])"  # group 4: flag
    + MARKER_END
)


def _b64e(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _b64d(s: str) -> str:
    return base64.b64decode(s).decode()


def make_marker(
    content: str,
    msgid: str,
    context: str = "",
    *,
    escaped: bool = False,
) -> str:
    """Build a text-safe marker containing translation metadata.

    Args:
        content: The translated text.
        msgid: The gettext message ID.
        context: The gettext message context (pgettext).
        escaped: True if content is already HTML-escaped (from template tags).
    """
    flag = "e" if escaped else "r"
    return django.utils.safestring.mark_safe(  # type: ignore[return-value]
        MARKER_START
        + _b64e(msgid)
        + MARKER_SEP
        + _b64e(context)
        + MARKER_SEP
        + _b64e(content)
        + MARKER_SEP
        + flag
        + MARKER_END
    )


# Per-request flag controlling whether TranslatableString produces wrapping spans.
# Set by LiveTranslationsMiddleware, reset in its finally block.
lt_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "lt_active", default=False
)


class TranslatableString(str):
    """A str subclass that remembers its gettext msgid for live translation.

    Behaves identically to str in all contexts except Django template
    autoescaping, where __html__() produces a <span> wrapper when
    the lt_active contextvar is True.
    """

    _lt_msgid: str
    _lt_context: str

    def __new__(
        cls,
        value: str,
        msgid: str,
        context: str = "",
    ) -> t.Self:
        instance = super().__new__(cls, value)
        instance._lt_msgid = msgid
        instance._lt_context = context
        return instance

    def __html__(self) -> str:
        """Called by Django's conditional_escape during template autoescaping.

        When lt_active is True, produces a text-safe marker instead of HTML.
        The middleware resolves markers into <span> wrappers (text content)
        or plain text with data-lt-attrs metadata (HTML attributes).
        """
        if not lt_active.get(False):
            return django.utils.html.escape(str.__str__(self))

        return make_marker(
            str.__str__(self), self._lt_msgid, self._lt_context, escaped=False
        )

    def __mod__(
        self,
        args: t.Any,
    ) -> str:  # type: ignore[override]
        """Support %-formatting (used by gettext for %(var)s placeholders).

        Returns a plain str since the formatted result may not match the msgid.
        """
        return str.__str__(self) % args

    def format(
        self,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> str:  # type: ignore[override]
        """Support .format() — returns plain str."""
        return str.__str__(self).format(*args, **kwargs)


def install_gettext_patch() -> None:
    """Monkey-patch Django's translation system to return TranslatableString.

    Called once from AppConfig.ready(). Patches:
    - _trans.gettext / _trans.pgettext -- for direct calls and {{ var }} rendering
    - translation.gettext_lazy / pgettext_lazy -- so lazy proxies expose __html__

    Wraps result in TranslatableString when lt_active is True (superuser edit mode).
    For regular users, the patched functions are a near-zero-cost pass-through.
    All TranslatableString wrapping is guarded by try/except so failures never
    affect regular users and degrade gracefully for translators.
    """
    import django.utils.functional
    import django.utils.translation

    _trans = django.utils.translation._trans  # type: ignore[attr-defined]

    # Force lazy resolution of _trans attributes by accessing them once.
    # After this, _trans.gettext is a regular attribute (not lazy-loaded).
    try:
        _orig_gettext = _trans.gettext  # type: ignore[union-attr]
    except AttributeError:
        logger.warning(
            "Could not access _trans.gettext -- live translation patching skipped"
        )
        return

    try:
        _orig_pgettext = _trans.pgettext  # type: ignore[union-attr]
    except AttributeError:
        _orig_pgettext = None

    def _patched_gettext(message: str) -> str:
        result = _orig_gettext(message)
        if not lt_active.get(False):
            return result  # type: ignore[no-any-return]
        try:
            return TranslatableString(result, msgid=str(message))
        except Exception:
            logger.exception("Failed to wrap gettext result in TranslatableString")
            return result  # type: ignore[no-any-return]

    def _patched_pgettext(
        context: str,
        message: str,
    ) -> str:
        result = (
            _orig_pgettext(context, message)
            if _orig_pgettext is not None
            else _orig_gettext(message)
        )
        if not lt_active.get(False):
            return result  # type: ignore[no-any-return]
        try:
            return TranslatableString(result, msgid=str(message), context=str(context))
        except Exception:
            logger.exception("Failed to wrap pgettext result in TranslatableString")
            return result  # type: ignore[no-any-return]

    _trans.gettext = _patched_gettext  # type: ignore[union-attr]
    if _orig_pgettext is not None:
        _trans.pgettext = _patched_pgettext  # type: ignore[union-attr]

    # -- Lazy variants --
    # Django's gettext_lazy = lazy(gettext, str). The proxy only has str
    # methods, so __html__ is missing and templates can't produce spans.
    # We replace it with lazy(func, TranslatableString) so the proxy
    # class includes __html__. The wrapped function must ALWAYS return
    # TranslatableString (not just when lt_active is True) because the
    # proxy dispatches methods to the result type — __html__ checks
    # lt_active itself and returns plain escaped text for normal users.

    def _gettext_translatable(message: str) -> TranslatableString:
        result = _orig_gettext(message)
        try:
            return TranslatableString(result, msgid=str(message))
        except Exception:
            logger.exception("Failed to create TranslatableString for lazy gettext")
            return result  # type: ignore[return-value]

    def _pgettext_translatable(
        context: str,
        message: str,
    ) -> TranslatableString:
        result = (
            _orig_pgettext(context, message)
            if _orig_pgettext is not None
            else _orig_gettext(message)
        )
        try:
            return TranslatableString(result, msgid=str(message), context=str(context))
        except Exception:
            logger.exception("Failed to create TranslatableString for lazy pgettext")
            return result  # type: ignore[return-value]

    django.utils.translation.gettext_lazy = django.utils.functional.lazy(  # type: ignore[assignment]
        _gettext_translatable, TranslatableString
    )
    if _orig_pgettext is not None:
        django.utils.translation.pgettext_lazy = django.utils.functional.lazy(  # type: ignore[assignment]
            _pgettext_translatable, TranslatableString
        )

    # -- Template rendering patch --
    # Django's render_value_in_context() calls str() on non-str values
    # (including lazy proxies) before passing to conditional_escape().
    # str() downcasts TranslatableString to plain str, losing __html__.
    # Similarly, conditional_escape() calls str() on Promise objects.
    # We add an early __html__ check so objects that support it (our lazy
    # proxy, TranslatableString, SafeString) short-circuit correctly.
    import django.template.base as _tpl

    _orig_render_value = _tpl.render_value_in_context

    def _patched_render_value_in_context(
        value: t.Any,
        context: t.Any,
    ) -> str:
        import django.utils.formats

        value = _tpl.template_localtime(value, use_tz=context.use_tz)
        value = django.utils.formats.localize(value, use_l10n=context.use_l10n)
        if context.autoescape:
            if hasattr(value, "__html__"):
                try:
                    return value.__html__()  # type: ignore[no-any-return]
                except Exception:
                    logger.exception("Failed to call __html__() on value")
                    return _orig_render_value(value, context)  # type: ignore[no-any-return]
            if not issubclass(type(value), str):
                value = str(value)
            return django.utils.html.conditional_escape(value)  # type: ignore[no-any-return]
        return str(value)

    _tpl.render_value_in_context = _patched_render_value_in_context
