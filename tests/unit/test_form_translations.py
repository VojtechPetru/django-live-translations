"""Tests for TranslatableString surviving string operations (capfirst etc.)
and for the original gettext_lazy proxy class gaining __html__ retroactively.

These cover the two fixes needed so that model-level verbose_name / help_text
render as translatable markers in Django forms:

1. TranslatableString must preserve type through __getitem__, upper(), __add__,
   __radd__ — because Django's capfirst() does ``x[0].upper() + x[1:]``.

2. The *original* gettext_lazy proxy class (created before AppConfig.ready()
   patches it) must gain __html__ so that model-level lazy strings produce
   markers when rendered in templates.
"""

import django.utils.html
import django.utils.text

from live_translations.strings import TranslatableString, lt_active

# ---------------------------------------------------------------------------
# 1. TranslatableString string-operation preservation
# ---------------------------------------------------------------------------


class TestTranslatableStringGetitem:
    def test_single_index_returns_translatable_string(self) -> None:
        ts = TranslatableString("hello", msgid="test.msg")
        result = ts[0]
        assert isinstance(result, TranslatableString)
        assert result == "h"

    def test_single_index_preserves_msgid(self) -> None:
        ts = TranslatableString("hello", msgid="test.msg", context="ctx")
        result = ts[0]
        assert result._lt_msgid == "test.msg"
        assert result._lt_context == "ctx"

    def test_slice_returns_translatable_string(self) -> None:
        ts = TranslatableString("hello", msgid="test.msg")
        result = ts[1:]
        assert isinstance(result, TranslatableString)
        assert result == "ello"
        assert result._lt_msgid == "test.msg"


class TestTranslatableStringUpper:
    def test_upper_returns_translatable_string(self) -> None:
        ts = TranslatableString("hello", msgid="test.msg")
        result = ts.upper()
        assert isinstance(result, TranslatableString)
        assert result == "HELLO"

    def test_upper_preserves_msgid(self) -> None:
        ts = TranslatableString("hello", msgid="test.msg", context="ctx")
        result = ts.upper()
        assert result._lt_msgid == "test.msg"
        assert result._lt_context == "ctx"


class TestTranslatableStringAdd:
    def test_add_returns_translatable_string(self) -> None:
        ts = TranslatableString("hel", msgid="test.msg")
        result = ts + "lo"
        assert isinstance(result, TranslatableString)
        assert result == "hello"

    def test_add_preserves_msgid(self) -> None:
        ts = TranslatableString("hel", msgid="test.msg", context="ctx")
        result = ts + "lo"
        assert result._lt_msgid == "test.msg"
        assert result._lt_context == "ctx"

    def test_add_with_translatable_string_rhs(self) -> None:
        ts1 = TranslatableString("hel", msgid="left.msg")
        ts2 = TranslatableString("lo", msgid="right.msg")
        result = ts1 + ts2
        assert isinstance(result, TranslatableString)
        assert result == "hello"
        # Left operand's msgid wins
        assert result._lt_msgid == "left.msg"


class TestTranslatableStringRadd:
    def test_radd_returns_translatable_string(self) -> None:
        ts = TranslatableString("lo", msgid="test.msg")
        result = "hel" + ts
        assert isinstance(result, TranslatableString)
        assert result == "hello"

    def test_radd_preserves_msgid(self) -> None:
        ts = TranslatableString("lo", msgid="test.msg", context="ctx")
        result = "hel" + ts
        assert result._lt_msgid == "test.msg"
        assert result._lt_context == "ctx"


# ---------------------------------------------------------------------------
# 2. capfirst preserves TranslatableString
# ---------------------------------------------------------------------------


class TestCapfirstPreservesTranslatableString:
    """Django's capfirst does ``x[0].upper() + x[1:]``.

    With __getitem__, upper(), and __add__ preserving TranslatableString,
    capfirst should return a TranslatableString with the original msgid.
    """

    def test_capfirst_returns_translatable_string(self) -> None:
        ts = TranslatableString("full name", msgid="form.name.label")
        result = django.utils.text.capfirst(ts)
        assert isinstance(result, TranslatableString)
        assert result == "Full name"

    def test_capfirst_preserves_msgid(self) -> None:
        ts = TranslatableString("full name", msgid="form.name.label", context="ctx")
        result = django.utils.text.capfirst(ts)
        assert result._lt_msgid == "form.name.label"
        assert result._lt_context == "ctx"

    def test_capfirst_result_has_working_html(self) -> None:
        ts = TranslatableString("full name", msgid="form.name.label")
        result = django.utils.text.capfirst(ts)
        token = lt_active.set(True)
        try:
            html = result.__html__()
        finally:
            lt_active.reset(token)
        assert "form.name.label" in html  # msgid is encoded in the marker
