"""Drop-in replacement for {% load i18n %}.

Re-exports all standard i18n tags and filters, but overrides
trans/translate and blocktrans/blocktranslate to wrap output
in <span> elements when live translations are active.
"""

import typing as t

from django import template
from django.template import Node
from django.template.base import Parser, Token  # noqa: TC002
from django.template.context import Context  # noqa: TC002
from django.templatetags import i18n
from django.templatetags.i18n import BlockTranslateNode, TranslateNode  # noqa: TC002
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# ── Re-export all tags and filters from Django's i18n library ──
_i18n_lib: template.Library = i18n.register
register.filters.update(_i18n_lib.filters)
register.tags.update(_i18n_lib.tags)


# ── Helpers ────────────────────────────────────────────────────


def _resolve_message_context(node: TranslateNode | BlockTranslateNode, context: Context) -> str:
    """Extract the gettext context string from a node, or '' if none."""
    msg_ctx = node.message_context
    if msg_ctx is None:
        return ""
    resolved = msg_ctx.resolve(context)
    return str(resolved) if resolved is not None else ""


def _extract_trans_msgid(node: TranslateNode) -> str:
    """Extract the literal msgid from a TranslateNode."""
    var = node.filter_expression.var
    if hasattr(var, "literal") and var.literal is not None:
        return str(var.literal)
    return str(var)


def _wrap_span(content: str, msgid: str, context: str) -> str:
    """Wrap translated content in a live-translation span."""
    escaped_msgid = escape(msgid)
    escaped_context = escape(context)
    return mark_safe(  # type: ignore[return-value]
        f'<span class="lt-translatable" data-lt-msgid="{escaped_msgid}"'
        f' data-lt-context="{escaped_context}">{content}</span>'
    )


# ── Wrapper nodes ──────────────────────────────────────────────


class LiveTranslateNode(Node):
    """Wraps a standard TranslateNode, adding <span> for superusers."""

    child_nodelists: t.ClassVar[list[str]] = []

    def __init__(self, original_node: TranslateNode) -> None:
        self.original_node = original_node

    @t.override
    def render(self, context: Context) -> str:
        rendered: str = self.original_node.render(context)

        # Never wrap asvar or noop — they don't produce direct output
        if self.original_node.asvar or self.original_node.noop:
            return rendered

        # Check the flag set by context processor
        if not context.get("_live_translations_active", False):
            return rendered

        msgid = _extract_trans_msgid(self.original_node)
        msg_context = _resolve_message_context(self.original_node, context)

        return _wrap_span(rendered, msgid, msg_context)


class LiveBlockTranslateNode(Node):
    """Wraps a standard BlockTranslateNode, adding <span> for superusers."""

    child_nodelists: t.ClassVar[list[str]] = []

    def __init__(self, original_node: BlockTranslateNode) -> None:
        self.original_node = original_node

    def _extract_msgid(self) -> str:
        """Extract the source msgid from the block's singular nodelist.

        BlockTranslateNode.render_token_list() returns (msg, sentinel_set).
        The msg is the gettext-ready msgid with %(var)s placeholders.
        """
        msg, _sentinels = self.original_node.render_token_list(self.original_node.singular)
        return msg

    @t.override
    def render(self, context: Context) -> str:
        rendered: str = self.original_node.render(context)

        if self.original_node.asvar:
            return rendered

        if not context.get("_live_translations_active", False):
            return rendered

        msgid = self._extract_msgid()
        msg_context = _resolve_message_context(self.original_node, context)

        return _wrap_span(rendered, msgid, msg_context)


# ── Tag registration (overrides the re-exported i18n tags) ─────


@register.tag("trans")
@register.tag("translate")
def do_live_translate(parser: Parser, token: Token) -> LiveTranslateNode:
    """Parse with Django's do_translate, then wrap in LiveTranslateNode."""
    original_node: TranslateNode = i18n.do_translate(parser, token)
    return LiveTranslateNode(original_node)


@register.tag("blocktrans")
@register.tag("blocktranslate")
def do_live_block_translate(parser: Parser, token: Token) -> LiveBlockTranslateNode:
    """Parse with Django's do_block_translate, then wrap in LiveBlockTranslateNode."""
    original_node: BlockTranslateNode = i18n.do_block_translate(parser, token)
    return LiveBlockTranslateNode(original_node)
