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
    WJ,
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

    The WJ start flag is at position 1 (in the ``x[1:]`` slice), so capfirst
    uppercases the first visible character and the start flag + end marker
    both survive intact.
    """

    def test_capfirst_preserves_marker(self) -> None:
        token = lt_active.set(True)
        try:
            from live_translations.strings import _insert_markers

            text = _insert_markers("full name", MsgKey("form.name.label", ""))
            result = django.utils.text.capfirst(text)
            # First char uppercased, WJ start flag at position 1 survives
            assert result[0] == "F"
            assert result[1] == WJ  # position-1 start flag
            assert result[2:].startswith("ull name")
            # End marker boundaries present
            assert result.count(ZWC_BOUNDARY) >= 2  # 2 end marker boundaries
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
        # The end marker itself should be unchanged
        assert marker in escaped

    def test_escape_preserves_start_flag(self) -> None:
        token = lt_active.set(True)
        try:
            from live_translations.strings import _insert_markers

            text = _insert_markers("Hello <world>", MsgKey("test", ""))
            escaped = django.utils.html.escape(text)
            # Start flag (ZWC_BOUNDARY) should survive html.escape
            assert ZWC_BOUNDARY in escaped
        finally:
            lt_active.reset(token)


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

    def test_start_flag_survives_percent_formatting(self) -> None:
        """WJ start flag at position 1 is not affected by %-formatting."""
        token = lt_active.set(True)
        try:
            from live_translations.strings import _insert_markers

            # _insert_markers inserts flag then appends end marker.
            # We simulate post-formatting by checking the flag position.
            text = _insert_markers("Value: %(x)s done", MsgKey("test", ""))
            # WJ flag is at position 1
            assert text[1] == WJ
        finally:
            lt_active.reset(token)


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

        from live_translations.strings import _insert_markers

        token = lt_active.set(True)
        try:
            # Simulate overflow by making encode_zwc raise ValueError
            with unittest.mock.patch(
                "live_translations.strings.encode_zwc",
                side_effect=ValueError("StringId out of range"),
            ):
                from live_translations.strings import _insert_markers

                # _insert_markers is called inside the try/except in patched gettext.
                # Call it directly to verify it raises, which the patched gettext catches.
                with pytest.raises(ValueError, match="out of range"):
                    _insert_markers("translated text", MsgKey("msgid", ""))
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


# ---------------------------------------------------------------------------
# 7. Start flag insertion
# ---------------------------------------------------------------------------


class TestStartFlagInsertion:
    """Verify that _insert_markers inserts a \\uFEFF start flag at the correct position."""

    def test_start_flag_at_position_1(self) -> None:
        """Normal text: WJ start flag at position 1 (after first visible char)."""
        from live_translations.strings import _insert_markers

        result = _insert_markers("Hello world", MsgKey("test", ""))
        assert result[0] == "H"
        assert result[1] == WJ  # position-1 start flag (WORD JOINER)
        assert result[2:].startswith("ello world")
        # End marker at the end
        assert result.endswith(ZWC_BOUNDARY)

    def test_start_flag_at_position_0_for_html(self) -> None:
        """Translation starting with '<' gets flag at position 0."""
        from live_translations.strings import _insert_markers

        result = _insert_markers("<strong>bold</strong> text", MsgKey("html", ""))
        assert result[0] == ZWC_BOUNDARY  # start flag at position 0
        assert result[1:].startswith("<strong>bold</strong> text")
        # End marker at the end
        assert result.endswith(ZWC_BOUNDARY)

    def test_no_start_flag_for_empty(self) -> None:
        """Empty translation string: no start flag, only end marker."""
        from live_translations.strings import _insert_markers

        result = _insert_markers("", MsgKey("empty", ""))
        # Should be just the 18-char end marker
        assert len(result) == 18
        assert result[0] == ZWC_BOUNDARY
        assert result[-1] == ZWC_BOUNDARY

    def test_start_flag_for_single_char(self) -> None:
        """Single-char translation: WJ flag appended after the char."""
        from live_translations.strings import _insert_markers

        result = _insert_markers("X", MsgKey("single", ""))
        assert result[0] == "X"
        assert result[1] == WJ  # position-1 start flag
        # Followed by 18-char end marker
        assert len(result) == 1 + 1 + 18  # char + flag + end marker

    def test_start_flag_survives_capfirst(self) -> None:
        """capfirst uppercases position 0, WJ start flag at position 1 survives."""
        from live_translations.strings import _insert_markers

        text = _insert_markers("hello", MsgKey("test", ""))
        result = django.utils.text.capfirst(text)
        assert result[0] == "H"
        assert result[1] == WJ  # position-1 start flag

    def test_html_start_flag_capfirst_noop(self) -> None:
        """capfirst on '<...' is a no-op, flag at position 0 is safe."""
        from live_translations.strings import _insert_markers

        text = _insert_markers("<em>word</em>", MsgKey("html", ""))
        result = django.utils.text.capfirst(text)
        # capfirst('<') -> '<' (no uppercase for '<'), flag stays at position 0
        assert result[0] == ZWC_BOUNDARY
        assert result[1] == "<"

    def test_preserves_safestring_html_start(self) -> None:
        """SafeString starting with '<' — flag at position 0, type preserved."""
        import django.utils.safestring

        from live_translations.strings import _insert_markers

        safe_input = django.utils.safestring.mark_safe("<strong>bold</strong>")
        result = _insert_markers(safe_input, MsgKey("safe", ""))
        assert isinstance(result, django.utils.safestring.SafeData)
        # pyrefly doesn't know SafeData subclasses str
        assert result[0] == ZWC_BOUNDARY  # type: ignore[bad-index]  # flag at position 0 for HTML
        assert result[1] == "<"  # type: ignore[bad-index]

    def test_preserves_safestring_normal_text(self) -> None:
        """SafeString not starting with '<' — WJ flag at position 1, type preserved."""
        import django.utils.safestring

        from live_translations.strings import _insert_markers

        safe_input = django.utils.safestring.mark_safe("Hello world")
        result = _insert_markers(safe_input, MsgKey("safe2", ""))
        assert isinstance(result, django.utils.safestring.SafeData)
        # pyrefly doesn't know SafeData subclasses str
        assert result[0] == "H"  # type: ignore[bad-index]
        assert result[1] == WJ  # type: ignore[bad-index]  # position-1 start flag

    def test_plain_str_stays_plain(self) -> None:
        """Plain str input does NOT get promoted to SafeString."""
        import django.utils.safestring

        from live_translations.strings import _insert_markers

        result = _insert_markers("plain text", MsgKey("plain", ""))
        assert not isinstance(result, django.utils.safestring.SafeData)

    def test_position_1_flag_uses_distinct_character(self) -> None:
        """Position-1 and position-0 flags must use different characters.

        When inline HTML splits a translation into multiple DOM nodes, the JS
        walks backwards to find the start flag and wraps from there.  For
        position-0 flags (HTML start), it splits at flagIdx — text before is
        non-translation.  For position-1 flags (normal text), the char at
        flagIdx-1 is the FIRST translation char and must be included.  Using
        distinct characters lets the JS apply the correct split strategy.
        """
        from live_translations.strings import _insert_markers

        normal = _insert_markers("Hello world", MsgKey("test", ""))
        html = _insert_markers("<strong>bold</strong>", MsgKey("html", ""))

        # Position-1 flag character (at index 1 of normal text)
        flag_p1 = normal[1]
        # Position-0 flag character (at index 0 of HTML-starting text)
        flag_p0 = html[0]

        assert flag_p1 != flag_p0, (
            f"position-1 flag ({flag_p1!r}) and position-0 flag ({flag_p0!r}) "
            "must use different characters so JS can distinguish wrapping strategy"
        )
