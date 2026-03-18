"""Tests for ZWC encoding, string registry, and marker survival through string ops.

With the new architecture, patched gettext() returns a plain str with an appended
18-char zero-width character marker.  These tests verify:

1. encode_zwc / decode round-trip correctness.
2. String registry deduplication via MsgKey.
3. The ZWC marker survives Django's capfirst() (which does x[0].upper() + x[1:])
   because the marker is appended, not prepended.
4. The ZWC marker survives Django's html.escape() (ZWC chars are not HTML-special).
5. The ZWC marker survives %-formatting and .format() operations.
"""

import django.utils.html
import django.utils.text
import pytest

from live_translations.strings import (
    _ZWC_BITS,
    ZWC_BOUNDARY,
    encode_zwc,
    lt_active,
    register_string,
    reset_string_registry,
)
from live_translations.types import MsgKey


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_string_registry()
    yield
    reset_string_registry()


# ---------------------------------------------------------------------------
# 1. ZWC encoding
# ---------------------------------------------------------------------------


class TestEncodeZwc:
    def test_zero(self) -> None:
        result = encode_zwc(0)
        assert len(result) == 18
        assert result[0] == ZWC_BOUNDARY
        assert result[-1] == ZWC_BOUNDARY
        # All inner bits should be ZWC_0 (\u200B)
        inner = result[1:-1]
        assert all(c == "\u200b" for c in inner)

    def test_one(self) -> None:
        result = encode_zwc(1)
        assert len(result) == 18
        # Least significant bit should be ZWC_1 (\u200C)
        assert result[-2] == "\u200c"
        # All other inner bits should be ZWC_0
        assert all(c == "\u200b" for c in result[1:-2])

    def test_max_id(self) -> None:
        max_id = (1 << _ZWC_BITS) - 1
        result = encode_zwc(max_id)
        assert len(result) == 18
        # All inner bits should be ZWC_1 (\u200C)
        inner = result[1:-1]
        assert all(c == "\u200c" for c in inner)

    def test_round_trip(self) -> None:
        """Encode then decode (simulating what JS does) for several IDs."""
        for n in [0, 1, 42, 255, 1000, 65535]:
            marker = encode_zwc(n)
            # Decode: same logic as JS decodeZWC
            decoded = 0
            for i in range(1, 17):
                if ord(marker[i]) == 0x200C:
                    decoded |= 1 << (16 - i)
            assert decoded == n, f"Round-trip failed for {n}: got {decoded}"

    def test_out_of_range_negative(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            encode_zwc(-1)

    def test_out_of_range_too_large(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            encode_zwc(65536)


# ---------------------------------------------------------------------------
# 2. String registry
# ---------------------------------------------------------------------------


class TestStringRegistry:
    def test_register_returns_incrementing_ids(self) -> None:
        id0 = register_string(MsgKey("hello", ""))
        id1 = register_string(MsgKey("world", ""))
        assert id0 == 0
        assert id1 == 1

    def test_deduplication_same_key(self) -> None:
        id0 = register_string(MsgKey("hello", "ctx"))
        id1 = register_string(MsgKey("hello", "ctx"))
        assert id0 == id1

    def test_different_context_different_id(self) -> None:
        id0 = register_string(MsgKey("hello", ""))
        id1 = register_string(MsgKey("hello", "ctx"))
        assert id0 != id1

    def test_get_registry(self) -> None:
        from live_translations.strings import get_string_registry

        register_string(MsgKey("a", ""))
        register_string(MsgKey("b", "ctx"))
        registry = get_string_registry()
        assert registry == [MsgKey("a", ""), MsgKey("b", "ctx")]

    def test_reset_clears_registry(self) -> None:
        from live_translations.strings import get_string_registry

        register_string(MsgKey("a", ""))
        reset_string_registry()
        assert get_string_registry() == []
        # IDs restart from 0
        assert register_string(MsgKey("a", "")) == 0


# ---------------------------------------------------------------------------
# 3. ZWC marker survives capfirst
# ---------------------------------------------------------------------------


class TestCapfirstPreservesMarker:
    """Django's capfirst does ``x[0].upper() + x[1:]``.

    Since the ZWC marker is appended (at the end), capfirst operates on the
    first content character and the marker stays intact at the end.
    """

    def test_capfirst_preserves_marker(self) -> None:
        token = lt_active.set(True)
        try:
            from live_translations.strings import _append_marker

            text = _append_marker("full name", MsgKey("form.name.label", ""))
            result = django.utils.text.capfirst(text)
            assert result.startswith("Full name")
            assert ZWC_BOUNDARY in result
        finally:
            lt_active.reset(token)


# ---------------------------------------------------------------------------
# 4. ZWC marker survives html.escape
# ---------------------------------------------------------------------------


class TestHtmlEscapePreservesMarker:
    def test_escape_preserves_zwc(self) -> None:
        marker = encode_zwc(42)
        text = "Hello <world>" + marker
        escaped = django.utils.html.escape(text)
        assert ZWC_BOUNDARY in escaped
        assert "&lt;world&gt;" in escaped
        # The marker itself should be unchanged
        assert marker in escaped


# ---------------------------------------------------------------------------
# 5. ZWC marker survives formatting
# ---------------------------------------------------------------------------


class TestFormattingPreservesMarker:
    def test_percent_formatting(self) -> None:
        marker = encode_zwc(7)
        template = "Hello %(name)s" + marker
        result = template % {"name": "World"}
        assert result == "Hello World" + marker

    def test_str_format(self) -> None:
        marker = encode_zwc(7)
        template = "Hello {name}" + marker
        result = template.format(name="World")
        assert result == "Hello World" + marker


# ---------------------------------------------------------------------------
# 6. encode_zwc overflow does not break the page
# ---------------------------------------------------------------------------


class TestEncodeZwcOverflowIsSafe:
    """When the string registry exceeds 65535 entries, encode_zwc raises ValueError.

    The patched gettext catches this and returns the original translation
    without a marker. The page renders normally -- the string just won't
    be editable via the widget.
    """

    def test_patched_gettext_returns_original_on_overflow(self) -> None:
        import unittest.mock

        from live_translations.strings import _append_marker

        token = lt_active.set(True)
        try:
            # Simulate overflow by making encode_zwc raise ValueError
            with unittest.mock.patch(
                "live_translations.strings.encode_zwc",
                side_effect=ValueError("StringId out of range"),
            ):
                from live_translations.strings import _append_marker

                # _append_marker is called inside the try/except in patched gettext.
                # Call it directly to verify it raises, which the patched gettext catches.
                with pytest.raises(ValueError, match="out of range"):
                    _append_marker("translated text", MsgKey("msgid", ""))
        finally:
            lt_active.reset(token)

    def test_patched_gettext_gracefully_handles_overflow(self) -> None:
        """Full integration: patched gettext returns unmarked string on overflow."""
        import unittest.mock

        import django.utils.translation

        token = lt_active.set(True)
        try:
            with unittest.mock.patch(
                "live_translations.strings.encode_zwc",
                side_effect=ValueError("StringId out of range"),
            ):
                result = django.utils.translation.gettext("hello")
                # Should return a plain string without ZWC markers
                assert ZWC_BOUNDARY not in result
        finally:
            lt_active.reset(token)
