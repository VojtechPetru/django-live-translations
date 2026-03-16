"""Unit tests for LiveTranslateNode and LiveBlockTranslateNode."""

import unittest.mock

import django.template
import django.template.context

from live_translations import strings
from live_translations.templatetags.live_translations import LiveBlockTranslateNode, LiveTranslateNode


class TestLiveTranslateNodeAsvar:
    """{% trans "..." as X %} must store a TranslatableString in context."""

    def _make_node(self, *, asvar: str | None = None, noop: bool = False, rendered: str = "Hello") -> LiveTranslateNode:
        original = unittest.mock.MagicMock(spec_set=["render", "asvar", "noop", "filter_expression", "message_context"])
        original.asvar = asvar
        original.noop = noop
        original.render.return_value = rendered
        original.message_context = None
        original.filter_expression.var.literal = "test.msgid"
        return LiveTranslateNode(original)

    def test_asvar_returns_empty_string(self) -> None:
        node = self._make_node(asvar="my_var", rendered="")
        ctx = django.template.Context()
        ts = strings.TranslatableString("Hello", msgid="test.msgid")
        token = strings.lt_active.set(True)
        try:
            with unittest.mock.patch("django.utils.translation.gettext", return_value=ts):
                result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert result == ""
        assert strings.MARKER_START not in result

    def test_asvar_stores_translatable_string_when_active(self) -> None:
        node = self._make_node(asvar="my_var", rendered="")
        ctx = django.template.Context()
        ts = strings.TranslatableString("Hello", msgid="test.msgid")
        token = strings.lt_active.set(True)
        try:
            with unittest.mock.patch("django.utils.translation.gettext", return_value=ts):
                node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        stored = ctx["my_var"]
        assert isinstance(stored, strings.TranslatableString)
        assert stored._lt_msgid == "test.msgid"
        assert hasattr(stored, "__html__")

    def test_asvar_uses_pgettext_when_message_context(self) -> None:
        node = self._make_node(asvar="my_var", rendered="")
        # Set up message_context to return a resolved value
        node.original_node.message_context = unittest.mock.MagicMock()
        node.original_node.message_context.resolve.return_value = "menu"
        ts = strings.TranslatableString("File", msgid="test.msgid", context="menu")
        ctx = django.template.Context()
        token = strings.lt_active.set(True)
        try:
            with unittest.mock.patch("django.utils.translation.pgettext", return_value=ts) as mock_pgettext:
                node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        mock_pgettext.assert_called_once_with("menu", "test.msgid")
        stored = ctx["my_var"]
        assert isinstance(stored, strings.TranslatableString)
        assert stored._lt_context == "menu"

    def test_asvar_skips_when_inactive(self) -> None:
        node = self._make_node(asvar="my_var", rendered="")
        ctx = django.template.Context()
        token = strings.lt_active.set(False)
        try:
            result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert result == ""
        # gettext is NOT re-called when inactive, so context is untouched by us
        assert "my_var" not in ctx

    def test_noop_returns_original_when_active(self) -> None:
        node = self._make_node(noop=True, rendered="Hello")
        ctx = django.template.Context()
        token = strings.lt_active.set(True)
        try:
            result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert result == "Hello"
        assert strings.MARKER_START not in result

    def test_normal_produces_marker_when_active(self) -> None:
        node = self._make_node(rendered="Hello")
        ctx = django.template.Context()
        token = strings.lt_active.set(True)
        try:
            result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert strings.MARKER_START in result
        assert strings.MARKER_END in result

    def test_normal_returns_plain_when_inactive(self) -> None:
        node = self._make_node(rendered="Hello")
        ctx = django.template.Context()
        token = strings.lt_active.set(False)
        try:
            result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert result == "Hello"
        assert strings.MARKER_START not in result


class TestLiveBlockTranslateNodeAsvar:
    """{% blocktrans ... as X %} must skip marker wrapping."""

    def _make_node(self, *, asvar: str | None = None, rendered: str = "Hello") -> LiveBlockTranslateNode:
        original = unittest.mock.MagicMock(
            spec_set=["render", "asvar", "singular", "render_token_list", "message_context"]
        )
        original.asvar = asvar
        original.render.return_value = rendered
        original.message_context = None
        original.render_token_list.return_value = ("test.block.msgid", set())
        return LiveBlockTranslateNode(original)

    def test_asvar_returns_original_when_active(self) -> None:
        node = self._make_node(asvar="my_var", rendered="")
        ctx = django.template.Context()
        token = strings.lt_active.set(True)
        try:
            result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert result == ""
        assert strings.MARKER_START not in result

    def test_normal_produces_marker_when_active(self) -> None:
        node = self._make_node(rendered="Hello")
        ctx = django.template.Context()
        token = strings.lt_active.set(True)
        try:
            result = node.render(ctx)
        finally:
            strings.lt_active.reset(token)
        assert strings.MARKER_START in result
        assert strings.MARKER_END in result
