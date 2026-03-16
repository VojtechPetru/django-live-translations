"""Drop-in replacement for {% load i18n %}.

Re-exports all standard i18n tags and filters, but overrides
trans/translate and blocktrans/blocktranslate to produce text-safe
markers when live translations are active. The middleware resolves
these markers into <span> wrappers or attribute metadata.
"""

import typing as t

import django.template
import django.template.base
import django.template.context
import django.templatetags.i18n
import django.utils.translation

from live_translations import strings

__all__ = [
    "LiveBlockTranslateNode",
    "LiveTranslateNode",
    "do_live_block_translate",
    "do_live_translate",
    "register",
]

register = django.template.Library()

# -- Re-export all tags and filters from Django's i18n library --
_i18n_lib: django.template.Library = django.templatetags.i18n.register
register.filters.update(_i18n_lib.filters)
register.tags.update(_i18n_lib.tags)


# -- Helpers --


def _resolve_message_context(
    node: django.templatetags.i18n.TranslateNode | django.templatetags.i18n.BlockTranslateNode,
    context: django.template.context.Context,
) -> str:
    """Extract the gettext context string from a node, or '' if none."""
    msg_ctx = node.message_context
    if msg_ctx is None:
        return ""
    resolved = msg_ctx.resolve(context)
    return str(resolved) if resolved is not None else ""


def _extract_trans_msgid(node: django.templatetags.i18n.TranslateNode) -> str:
    """Extract the literal msgid from a TranslateNode."""
    var = node.filter_expression.var
    if hasattr(var, "literal") and var.literal is not None:
        return str(var.literal)
    return str(var)


def _wrap_marker(
    content: str,
    msgid: str,
    context: str,
) -> str:
    """Produce a text-safe marker for live-translation.

    Content from template tags is already HTML-escaped by Django,
    so we pass escaped=True to avoid double-escaping.
    """
    return strings.make_marker(content, msgid, context, escaped=True)


# -- Wrapper nodes --


class LiveTranslateNode(django.template.Node):
    """Wraps a standard TranslateNode, producing markers for superusers."""

    child_nodelists: t.ClassVar[list[str]] = []  # type: ignore[bad-override]

    def __init__(
        self,
        original_node: django.templatetags.i18n.TranslateNode,
    ) -> None:
        self.original_node = original_node

    @t.override
    def render(self, context: django.template.context.Context) -> str:
        rendered: str = self.original_node.render(context)

        if (not strings.lt_active.get(False)) or self.original_node.noop:
            return rendered

        if self.original_node.asvar:
            # Django's TranslateNode stored the translated text in
            # context[asvar] after passing it through the *original*
            # render_value_in_context (imported via `from ... import`
            # before our patch), which downcasts TranslatableString to
            # plain str — losing __html__().  Re-store as
            # TranslatableString so {{ var }} produces markers.
            asvar_name = self.original_node.asvar
            msgid = _extract_trans_msgid(self.original_node)
            msg_ctx = _resolve_message_context(self.original_node, context)
            if msg_ctx:
                context[asvar_name] = django.utils.translation.pgettext(msg_ctx, msgid)
            else:
                context[asvar_name] = django.utils.translation.gettext(msgid)
            return rendered  # always ""

        msgid = _extract_trans_msgid(self.original_node)
        msg_context = _resolve_message_context(self.original_node, context)

        # The original TranslateNode.render() may already produce a marker
        # if the resolved lazy proxy has __html__ (e.g. via the retroactive
        # proxy patch). Avoid double-wrapping.
        if strings.MARKER_START in rendered:
            return rendered

        return _wrap_marker(rendered, msgid, msg_context)


class LiveBlockTranslateNode(django.template.Node):
    """Wraps a standard BlockTranslateNode, producing markers for superusers."""

    child_nodelists: t.ClassVar[list[str]] = []  # type: ignore[bad-override]

    def __init__(
        self,
        original_node: django.templatetags.i18n.BlockTranslateNode,
    ) -> None:
        self.original_node = original_node

    def _extract_msgid(self) -> str:
        """Extract the source msgid from the block's singular nodelist.

        BlockTranslateNode.render_token_list() returns (msg, sentinel_set).
        The msg is the gettext-ready msgid with %(var)s placeholders.
        """
        msg, _sentinels = self.original_node.render_token_list(self.original_node.singular)
        return msg

    @t.override
    def render(self, context: django.template.context.Context) -> str:
        rendered: str = self.original_node.render(context)

        if (not strings.lt_active.get(False)) or self.original_node.asvar:
            return rendered

        msgid = self._extract_msgid()
        msg_context = _resolve_message_context(self.original_node, context)

        # Same guard as LiveTranslateNode: avoid double-wrapping if
        # the inner render already produced a marker.
        if strings.MARKER_START in rendered:
            return rendered

        return _wrap_marker(rendered, msgid, msg_context)


# -- Tag registration (overrides the re-exported i18n tags) --


@register.tag("trans")
@register.tag("translate")
def do_live_translate(
    parser: django.template.base.Parser,
    token: django.template.base.Token,
) -> LiveTranslateNode:
    """Parse with Django's do_translate, then wrap in LiveTranslateNode."""
    original_node: django.templatetags.i18n.TranslateNode = django.templatetags.i18n.do_translate(parser, token)
    return LiveTranslateNode(original_node)


@register.tag("blocktrans")
@register.tag("blocktranslate")
def do_live_block_translate(
    parser: django.template.base.Parser,
    token: django.template.base.Token,
) -> LiveBlockTranslateNode:
    """Parse with Django's do_block_translate, then wrap in LiveBlockTranslateNode."""
    original_node: django.templatetags.i18n.BlockTranslateNode = django.templatetags.i18n.do_block_translate(
        parser, token
    )
    return LiveBlockTranslateNode(original_node)
