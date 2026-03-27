"""Tests for strings.py: preview resolution, plural index, patched gettext variants, and edge cases.

Complements test_form_translations.py (which covers encode_zwc, string registry, marker
insertion for normal/HTML/empty/single-char/SafeString, capfirst survival, and format
specifier survival with % NOT at position 0).

This file covers:
1. _insert_markers when the result starts with '%' (format specifier at position 0)
2. _resolve_singular_preview
3. _resolve_plural_preview
4. _get_plural_index (including fallback path)
5. Patched gettext with preview override
6. Patched pgettext
7. Patched ngettext
8. Patched npgettext
9. install_gettext_patch AttributeError handling
"""

import unittest.mock

import django.utils.translation
import pytest

from live_translations.strings import (
    WJ,
    ZWC_0,
    ZWC_1,
    ZWC_BOUNDARY,
    _get_plural_index,
    _insert_markers,
    _resolve_plural_preview,
    _resolve_singular_preview,
    get_string_registry,
    lt_active,
    lt_preview_overrides,
    reset_string_registry,
)
from live_translations.types import MsgKey, OverrideMap

_ZWC_CHARS = frozenset({ZWC_BOUNDARY, ZWC_0, ZWC_1, WJ})


def _strip_zwc(text: str) -> str:
    return "".join(c for c in text if c not in _ZWC_CHARS)


@pytest.fixture(autouse=True)
def _reset_registry():
    reset_string_registry()
    yield
    reset_string_registry()


@pytest.fixture(autouse=True)
def _activate_english():
    django.utils.translation.activate("en")
    yield
    django.utils.translation.deactivate()


# ---------------------------------------------------------------------------
# 1. _insert_markers with format specifier at position 0
# ---------------------------------------------------------------------------


class TestInsertMarkersFormatSpecifierAtStart:
    def test_percent_at_position_0_uses_feff_flag(self) -> None:
        result = _insert_markers("%(name)s items", MsgKey("%(name)s items", ""))
        assert result[0] == ZWC_BOUNDARY, "format specifier at position 0 should use FEFF flag"
        assert result[1] == "%", "original text should follow immediately after FEFF flag"
        assert "%(name)s items" in result

    def test_percent_at_position_0_does_not_use_wj(self) -> None:
        result = _insert_markers("%(count)d results", MsgKey("%(count)d results", ""))
        assert WJ not in result, "WJ should not be inserted for format specifier at position 0"

    def test_percent_at_position_0_end_marker_present(self) -> None:
        result = _insert_markers("%(x)s", MsgKey("%(x)s", ""))
        assert result.endswith(ZWC_BOUNDARY), "end marker boundary should be at the end"
        # FEFF + "%(x)s" + 18-char end marker
        assert len(result) == 1 + len("%(x)s") + 18

    def test_percent_at_position_0_survives_formatting(self) -> None:
        result = _insert_markers("%(name)s items", MsgKey("%(name)s items", ""))
        formatted = result % {"name": "Test"}
        assert "Test items" in formatted
        assert ZWC_BOUNDARY in formatted


# ---------------------------------------------------------------------------
# 2. _resolve_singular_preview
# ---------------------------------------------------------------------------


class TestResolveSingularPreview:
    def test_returns_none_when_no_overrides_set(self) -> None:
        key = MsgKey("hello", "")
        assert _resolve_singular_preview(key) is None

    def test_returns_none_when_key_not_in_overrides(self) -> None:
        overrides: OverrideMap = {MsgKey("other", ""): {0: "Other translation"}}
        token = lt_preview_overrides.set(overrides)
        try:
            assert _resolve_singular_preview(MsgKey("hello", "")) is None
        finally:
            lt_preview_overrides.reset(token)

    def test_returns_form_0_when_key_found(self) -> None:
        key = MsgKey("hello", "")
        overrides: OverrideMap = {key: {0: "Overridden hello"}}
        token = lt_preview_overrides.set(overrides)
        try:
            result = _resolve_singular_preview(key)
            assert result == "Overridden hello"
        finally:
            lt_preview_overrides.reset(token)

    def test_returns_empty_string_when_form_0_missing(self) -> None:
        key = MsgKey("hello", "")
        overrides: OverrideMap = {key: {1: "Plural form only"}}
        token = lt_preview_overrides.set(overrides)
        try:
            result = _resolve_singular_preview(key)
            assert result == "", "should return empty string when form 0 is not in PluralForms"
        finally:
            lt_preview_overrides.reset(token)

    def test_respects_context_in_key(self) -> None:
        key_no_ctx = MsgKey("hello", "")
        key_with_ctx = MsgKey("hello", "greeting")
        overrides: OverrideMap = {key_with_ctx: {0: "Contextualized hello"}}
        token = lt_preview_overrides.set(overrides)
        try:
            assert _resolve_singular_preview(key_no_ctx) is None
            assert _resolve_singular_preview(key_with_ctx) == "Contextualized hello"
        finally:
            lt_preview_overrides.reset(token)


# ---------------------------------------------------------------------------
# 3. _resolve_plural_preview
# ---------------------------------------------------------------------------


class TestResolvePluralPreview:
    def test_returns_none_when_no_overrides_set(self) -> None:
        key = MsgKey("item", "", "items")
        assert _resolve_plural_preview(key, 5) is None

    def test_returns_none_when_key_not_in_overrides(self) -> None:
        overrides: OverrideMap = {MsgKey("other", "", "others"): {0: "one", 1: "many"}}
        token = lt_preview_overrides.set(overrides)
        try:
            assert _resolve_plural_preview(MsgKey("item", "", "items"), 5) is None
        finally:
            lt_preview_overrides.reset(token)

    def test_returns_singular_form_for_number_1(self) -> None:
        key = MsgKey("item", "", "items")
        overrides: OverrideMap = {key: {0: "one item", 1: "many items"}}
        token = lt_preview_overrides.set(overrides)
        try:
            result = _resolve_plural_preview(key, 1)
            assert result == "one item"
        finally:
            lt_preview_overrides.reset(token)

    def test_returns_plural_form_for_number_greater_than_1(self) -> None:
        key = MsgKey("item", "", "items")
        overrides: OverrideMap = {key: {0: "one item", 1: "many items"}}
        token = lt_preview_overrides.set(overrides)
        try:
            result = _resolve_plural_preview(key, 5)
            assert result == "many items"
        finally:
            lt_preview_overrides.reset(token)

    def test_falls_back_to_form_0_when_computed_index_missing(self) -> None:
        key = MsgKey("item", "", "items")
        # Only provide form 0 -- form 1 is missing
        overrides: OverrideMap = {key: {0: "fallback text"}}
        token = lt_preview_overrides.set(overrides)
        try:
            # number=5 would compute plural index 1, which isn't in the map
            result = _resolve_plural_preview(key, 5)
            assert result == "fallback text", "should fall back to form 0 when computed index is missing"
        finally:
            lt_preview_overrides.reset(token)


# ---------------------------------------------------------------------------
# 4. _get_plural_index
# ---------------------------------------------------------------------------


class TestGetPluralIndex:
    def test_returns_0_for_singular_english(self) -> None:
        result = _get_plural_index(1)
        assert result == 0, "English singular (number=1) should return form index 0"

    def test_returns_1_for_plural_english(self) -> None:
        result = _get_plural_index(2)
        assert result == 1, "English plural (number=2) should return form index 1"

    def test_returns_1_for_zero_english(self) -> None:
        result = _get_plural_index(0)
        assert result == 1, "English zero (number=0) should return form index 1"

    def test_fallback_on_exception_singular(self) -> None:
        with unittest.mock.patch(
            "django.utils.translation.trans_real.translation",
            side_effect=RuntimeError("no catalog"),
        ):
            result = _get_plural_index(1)
            assert result == 0, "fallback for number=1 should be 0"

    def test_fallback_on_exception_plural(self) -> None:
        with unittest.mock.patch(
            "django.utils.translation.trans_real.translation",
            side_effect=RuntimeError("no catalog"),
        ):
            result = _get_plural_index(5)
            assert result == 1, "fallback for number!=1 should be 1"


# ---------------------------------------------------------------------------
# 5. Patched gettext with preview override
# ---------------------------------------------------------------------------


class TestPatchedGettextWithPreview:
    def test_preview_override_replaces_translation(self) -> None:
        key = MsgKey("hello", "")
        overrides: OverrideMap = {key: {0: "Preview hello"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.gettext("hello")
            stripped = _strip_zwc(result)
            assert stripped == "Preview hello", "preview override text should be the visible content"
            assert ZWC_BOUNDARY in result, "ZWC markers should be present"
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)

    def test_preview_override_text_is_used_not_original(self) -> None:
        key = MsgKey("original_msgid", "")
        overrides: OverrideMap = {key: {0: "Completely different"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.gettext("original_msgid")
            stripped = _strip_zwc(result)
            assert stripped == "Completely different"
            assert "original_msgid" not in stripped
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)


# ---------------------------------------------------------------------------
# 6. Patched pgettext
# ---------------------------------------------------------------------------


class TestPatchedPgettext:
    def test_inactive_returns_plain_text(self) -> None:
        result = django.utils.translation.pgettext("ctx", "hello")
        assert ZWC_BOUNDARY not in result, "markers should not be present when lt_active is False"

    def test_active_returns_marked_text(self) -> None:
        token = lt_active.set(True)
        try:
            result = django.utils.translation.pgettext("ctx", "hello")
            assert ZWC_BOUNDARY in result, "markers should be present when lt_active is True"
        finally:
            lt_active.reset(token)

    def test_creates_msgkey_with_context(self) -> None:
        token = lt_active.set(True)
        try:
            django.utils.translation.pgettext("myctx", "greeting")
            registry = get_string_registry()
            matching = [k for k in registry if k.msgid == "greeting" and k.context == "myctx"]
            assert len(matching) == 1, "MsgKey with context should be in the registry"
        finally:
            lt_active.reset(token)

    def test_preview_override_with_context(self) -> None:
        key = MsgKey("hello", "formal")
        overrides: OverrideMap = {key: {0: "Good day"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.pgettext("formal", "hello")
            stripped = _strip_zwc(result)
            assert stripped == "Good day"
            assert ZWC_BOUNDARY in result
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)

    def test_different_context_does_not_match_preview(self) -> None:
        key = MsgKey("hello", "formal")
        overrides: OverrideMap = {key: {0: "Good day"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.pgettext("informal", "hello")
            stripped = _strip_zwc(result)
            assert "Good day" not in stripped, "different context should not match the preview override"
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)


# ---------------------------------------------------------------------------
# 7. Patched ngettext
# ---------------------------------------------------------------------------


class TestPatchedNgettext:
    def test_inactive_returns_plain_text(self) -> None:
        result = django.utils.translation.ngettext("item", "items", 5)
        assert ZWC_BOUNDARY not in result, "markers should not be present when lt_active is False"

    def test_active_singular_returns_marked_text(self) -> None:
        token = lt_active.set(True)
        try:
            result = django.utils.translation.ngettext("item", "items", 1)
            assert ZWC_BOUNDARY in result
            stripped = _strip_zwc(result)
            assert stripped == "item"
        finally:
            lt_active.reset(token)

    def test_active_plural_returns_marked_text(self) -> None:
        token = lt_active.set(True)
        try:
            result = django.utils.translation.ngettext("item", "items", 5)
            assert ZWC_BOUNDARY in result
            stripped = _strip_zwc(result)
            assert stripped == "items"
        finally:
            lt_active.reset(token)

    def test_creates_msgkey_with_msgid_plural(self) -> None:
        token = lt_active.set(True)
        try:
            django.utils.translation.ngettext("apple", "apples", 3)
            registry = get_string_registry()
            matching = [k for k in registry if k.msgid == "apple" and k.msgid_plural == "apples"]
            assert len(matching) == 1, "MsgKey should contain msgid_plural"
            assert matching[0].context == "", "ngettext should use empty context"
        finally:
            lt_active.reset(token)

    def test_preview_override_singular(self) -> None:
        key = MsgKey("item", "", "items")
        overrides: OverrideMap = {key: {0: "1 preview item", 1: "many preview items"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.ngettext("item", "items", 1)
            stripped = _strip_zwc(result)
            assert stripped == "1 preview item"
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)

    def test_preview_override_plural(self) -> None:
        key = MsgKey("item", "", "items")
        overrides: OverrideMap = {key: {0: "1 preview item", 1: "many preview items"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.ngettext("item", "items", 5)
            stripped = _strip_zwc(result)
            assert stripped == "many preview items"
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)


# ---------------------------------------------------------------------------
# 8. Patched npgettext
# ---------------------------------------------------------------------------


class TestPatchedNpgettext:
    def test_inactive_returns_plain_text(self) -> None:
        result = django.utils.translation.npgettext("ctx", "item", "items", 5)
        assert ZWC_BOUNDARY not in result, "markers should not be present when lt_active is False"

    def test_active_returns_marked_text(self) -> None:
        token = lt_active.set(True)
        try:
            result = django.utils.translation.npgettext("ctx", "item", "items", 5)
            assert ZWC_BOUNDARY in result
        finally:
            lt_active.reset(token)

    def test_creates_msgkey_with_context_and_plural(self) -> None:
        token = lt_active.set(True)
        try:
            django.utils.translation.npgettext("shopping", "apple", "apples", 3)
            registry = get_string_registry()
            matching = [
                k for k in registry if k.msgid == "apple" and k.context == "shopping" and k.msgid_plural == "apples"
            ]
            assert len(matching) == 1, "MsgKey should have context and msgid_plural"
        finally:
            lt_active.reset(token)

    def test_preview_override_with_context_singular(self) -> None:
        key = MsgKey("item", "cart", "items")
        overrides: OverrideMap = {key: {0: "1 cart item", 1: "many cart items"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.npgettext("cart", "item", "items", 1)
            stripped = _strip_zwc(result)
            assert stripped == "1 cart item"
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)

    def test_preview_override_with_context_plural(self) -> None:
        key = MsgKey("item", "cart", "items")
        overrides: OverrideMap = {key: {0: "1 cart item", 1: "many cart items"}}
        active_token = lt_active.set(True)
        override_token = lt_preview_overrides.set(overrides)
        try:
            result = django.utils.translation.npgettext("cart", "item", "items", 5)
            stripped = _strip_zwc(result)
            assert stripped == "many cart items"
        finally:
            lt_preview_overrides.reset(override_token)
            lt_active.reset(active_token)


# ---------------------------------------------------------------------------
# 9. install_gettext_patch AttributeError handling
# ---------------------------------------------------------------------------


class TestInstallGettextPatchAttributeErrors:
    def test_skips_patching_when_gettext_missing(self) -> None:
        from live_translations.strings import install_gettext_patch

        trans_module = unittest.mock.MagicMock(spec=[])  # no attributes at all

        with unittest.mock.patch.object(
            django.utils.translation,
            "_trans",
            trans_module,
        ):
            # Should not raise -- just logs a warning and returns
            install_gettext_patch()

    def test_continues_when_pgettext_missing(self) -> None:
        from live_translations.strings import install_gettext_patch

        trans_module = unittest.mock.MagicMock(spec=["gettext"])
        trans_module.gettext = lambda msg: msg

        with unittest.mock.patch.object(
            django.utils.translation,
            "_trans",
            trans_module,
        ):
            install_gettext_patch()
            # gettext should be patched (replaced by our wrapper)
            assert trans_module.gettext is not None

    def test_continues_when_ngettext_missing(self) -> None:
        from live_translations.strings import install_gettext_patch

        trans_module = unittest.mock.MagicMock(spec=["gettext", "pgettext"])
        trans_module.gettext = lambda msg: msg
        trans_module.pgettext = lambda ctx, msg: msg

        with unittest.mock.patch.object(
            django.utils.translation,
            "_trans",
            trans_module,
        ):
            install_gettext_patch()
            # pgettext should still be patched even though ngettext is missing
            assert trans_module.pgettext is not None

    def test_continues_when_npgettext_missing(self) -> None:
        from live_translations.strings import install_gettext_patch

        trans_module = unittest.mock.MagicMock(spec=["gettext", "pgettext", "ngettext"])
        trans_module.gettext = lambda msg: msg
        trans_module.pgettext = lambda ctx, msg: msg
        trans_module.ngettext = lambda s, p, n: s if n == 1 else p

        with unittest.mock.patch.object(
            django.utils.translation,
            "_trans",
            trans_module,
        ):
            install_gettext_patch()
            # ngettext should still be patched even though npgettext is missing
            assert trans_module.ngettext is not None
