"""Comprehensive tests for the PO file backend (live_translations.backends.po)."""

import base64
import pathlib

import polib
import pytest

from live_translations import conf
from live_translations.backends.po import (
    LT_PENDING_PREFIX,
    POFileBackend,
    _clean_comment,
    _clear_pending,
    _get_pending,
    _set_pending,
)
from live_translations.types import LanguageCode, MsgKey

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_translations():
    """Restore Django's translation cache after each test.

    ``translation_file_changed`` (called by save/activate) clears
    ``trans_real._translations``.  We snapshot and restore the dict so
    tests don't leak cache state to one another.
    """
    from django.utils.translation import trans_real

    saved = getattr(trans_real, "_translations", {}).copy()
    yield
    trans_real._translations = saved  # type: ignore[missing-attribute]


@pytest.fixture
def po_backend(tmp_path: pathlib.Path, settings) -> POFileBackend:
    """Create a POFileBackend with a temp locale dir and one .po file for 'en'."""
    locale_dir = tmp_path / "locale"
    en_dir = locale_dir / "en" / "LC_MESSAGES"
    en_dir.mkdir(parents=True)

    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
    po.append(polib.POEntry(msgid="hello", msgstr="Hello"))
    po.append(polib.POEntry(msgid="world", msgstr="World"))
    po.save(str(en_dir / "django.po"))

    settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()

    return POFileBackend(locale_dir=locale_dir, domain="django")


@pytest.fixture
def locale_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a bare locale directory (no .po files yet)."""
    d = tmp_path / "locale"
    d.mkdir()
    return d


def _make_po_file(
    locale_dir: pathlib.Path,
    language: LanguageCode,
    entries: list[polib.POEntry],
    domain: str = "django",
) -> pathlib.Path:
    """Helper: write a .po file and return its path."""
    lc = locale_dir / language / "LC_MESSAGES"
    lc.mkdir(parents=True, exist_ok=True)
    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
    for e in entries:
        po.append(e)
    path = lc / f"{domain}.po"
    po.save(str(path))
    return path


def _make_entry(
    msgid: str = "hello",
    msgstr: str = "Hello",
    comment: str = "",
    msgctxt: str | None = None,
    flags: list[str] | None = None,
) -> polib.POEntry:
    entry = polib.POEntry(msgid=msgid, msgstr=msgstr, msgctxt=msgctxt)
    entry.comment = comment
    if flags:
        entry.flags = flags
    return entry


# ===========================================================================
# Module-level helpers
# ===========================================================================


class TestGetPending:
    def test_returns_none_when_no_comment(self):
        entry = _make_entry(comment="")
        assert _get_pending(entry) is None

    def test_returns_none_when_comment_has_no_prefix(self):
        entry = _make_entry(comment="translator note")
        assert _get_pending(entry) is None

    def test_extracts_base64_pending_value(self):
        value = "Pending translation"
        encoded = base64.b64encode(value.encode()).decode()
        entry = _make_entry(comment=f"{LT_PENDING_PREFIX}{encoded}")
        assert _get_pending(entry) == value

    def test_extracts_pending_after_existing_comment(self):
        value = "New value"
        encoded = base64.b64encode(value.encode()).decode()
        entry = _make_entry(comment=f"translator note\n{LT_PENDING_PREFIX}{encoded}")
        assert _get_pending(entry) == value

    def test_handles_continuation_lines(self):
        # Simulate polib wrapping a long base64 string across lines
        value = "A" * 200  # long enough to produce long base64
        encoded = base64.b64encode(value.encode()).decode()
        # Split the encoded string into prefix line + continuation
        split_at = 40
        first = encoded[:split_at]
        rest = encoded[split_at:]
        entry = _make_entry(comment=f"{LT_PENDING_PREFIX}{first}\n{rest}")
        assert _get_pending(entry) == value

    def test_returns_raw_on_invalid_base64(self):
        entry = _make_entry(comment=f"{LT_PENDING_PREFIX}!!!not-valid-base64!!!")
        result = _get_pending(entry)
        assert result == "!!!not-valid-base64!!!"

    def test_returns_raw_on_unicode_decode_error(self):
        # Create invalid UTF-8 bytes encoded as base64
        bad_bytes = b"\xff\xfe"
        encoded = base64.b64encode(bad_bytes).decode()
        entry = _make_entry(comment=f"{LT_PENDING_PREFIX}{encoded}")
        # b64decode succeeds but .decode() fails -> returns raw
        result = _get_pending(entry)
        assert result == encoded

    def test_returns_none_for_empty_string_comment(self):
        entry = _make_entry()
        entry.comment = ""
        assert _get_pending(entry) is None

    def test_unicode_pending_value(self):
        value = "Ahoj svetě! 🌍"
        encoded = base64.b64encode(value.encode()).decode()
        entry = _make_entry(comment=f"{LT_PENDING_PREFIX}{encoded}")
        assert _get_pending(entry) == value


class TestSetPending:
    def test_sets_pending_on_empty_comment(self):
        entry = _make_entry(comment="")
        _set_pending(entry, "New value")
        encoded = base64.b64encode(b"New value").decode()
        assert entry.comment == f"{LT_PENDING_PREFIX}{encoded}"

    def test_appends_pending_to_existing_comment(self):
        entry = _make_entry(comment="translator note")
        _set_pending(entry, "New value")
        encoded = base64.b64encode(b"New value").decode()
        assert entry.comment == f"translator note\n{LT_PENDING_PREFIX}{encoded}"

    def test_replaces_existing_pending(self):
        old_encoded = base64.b64encode(b"Old").decode()
        entry = _make_entry(comment=f"note\n{LT_PENDING_PREFIX}{old_encoded}")
        _set_pending(entry, "New")
        new_encoded = base64.b64encode(b"New").decode()
        assert entry.comment == f"note\n{LT_PENDING_PREFIX}{new_encoded}"
        # Only one pending line should exist
        assert entry.comment.count(LT_PENDING_PREFIX) == 1

    def test_roundtrip_with_get_pending(self):
        entry = _make_entry(comment="some note")
        _set_pending(entry, "Round trip value")
        assert _get_pending(entry) == "Round trip value"

    def test_unicode_value(self):
        entry = _make_entry(comment="")
        _set_pending(entry, "Přeložený text")
        assert _get_pending(entry) == "Přeložený text"


class TestClearPending:
    def test_noop_on_empty_comment(self):
        entry = _make_entry(comment="")
        _clear_pending(entry)
        assert entry.comment == ""

    def test_noop_when_no_pending(self):
        entry = _make_entry(comment="translator note")
        _clear_pending(entry)
        assert entry.comment == "translator note"

    def test_removes_pending_line(self):
        encoded = base64.b64encode(b"value").decode()
        entry = _make_entry(comment=f"{LT_PENDING_PREFIX}{encoded}")
        _clear_pending(entry)
        assert entry.comment == ""

    def test_removes_pending_preserves_preceding_comment(self):
        encoded = base64.b64encode(b"value").decode()
        entry = _make_entry(comment=f"translator note\n{LT_PENDING_PREFIX}{encoded}")
        _clear_pending(entry)
        assert entry.comment == "translator note"

    def test_removes_pending_and_continuation_lines(self):
        encoded = base64.b64encode(b"value").decode()
        entry = _make_entry(comment=f"note\n{LT_PENDING_PREFIX}{encoded}\ncontinuation")
        _clear_pending(entry)
        assert entry.comment == "note"

    def test_strips_trailing_whitespace(self):
        encoded = base64.b64encode(b"val").decode()
        entry = _make_entry(comment=f"note \n{LT_PENDING_PREFIX}{encoded}")
        _clear_pending(entry)
        assert entry.comment == "note"


class TestCleanComment:
    def test_strips_whitespace(self):
        assert _clean_comment("  hello  ") == "hello"

    def test_removes_pending_data(self):
        encoded = base64.b64encode(b"val").decode()
        assert _clean_comment(f"note\n{LT_PENDING_PREFIX}{encoded}") == "note"

    def test_returns_full_comment_when_no_pending(self):
        assert _clean_comment("translator note\nsecond line") == "translator note\nsecond line"

    def test_empty_string(self):
        assert _clean_comment("") == ""

    def test_only_pending_returns_empty(self):
        encoded = base64.b64encode(b"val").decode()
        assert _clean_comment(f"{LT_PENDING_PREFIX}{encoded}") == ""

    def test_multiline_before_pending(self):
        encoded = base64.b64encode(b"val").decode()
        result = _clean_comment(f"line one\nline two\n{LT_PENDING_PREFIX}{encoded}")
        assert result == "line one\nline two"


# ===========================================================================
# POFileBackend — internal helpers
# ===========================================================================


class TestPoPath:
    def test_po_path(self, locale_dir: pathlib.Path):
        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        assert backend._po_path("en") == locale_dir / "en" / "LC_MESSAGES" / "django.po"

    def test_mo_path(self, locale_dir: pathlib.Path):
        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        assert backend._mo_path("cs") == locale_dir / "cs" / "LC_MESSAGES" / "django.mo"

    def test_custom_domain(self, locale_dir: pathlib.Path):
        backend = POFileBackend(locale_dir=locale_dir, domain="djangojs")
        assert backend._po_path("en") == locale_dir / "en" / "LC_MESSAGES" / "djangojs.po"
        assert backend._mo_path("en") == locale_dir / "en" / "LC_MESSAGES" / "djangojs.mo"


class TestLoadPo:
    def test_loads_existing_po_file(self, po_backend: POFileBackend):
        po = po_backend._load_po("en")
        assert len(po) == 2
        assert po.find("hello") is not None

    def test_raises_file_not_found_for_missing_language(self, po_backend: POFileBackend):
        with pytest.raises(FileNotFoundError, match="PO file not found"):
            po_backend._load_po("fr")

    def test_caches_by_mtime(self, po_backend: POFileBackend):
        po1 = po_backend._load_po("en")
        po2 = po_backend._load_po("en")
        assert po1 is po2

    def test_invalidates_cache_on_mtime_change(self, po_backend: POFileBackend, tmp_path: pathlib.Path):
        po1 = po_backend._load_po("en")
        # Modify the file to change mtime
        path = po_backend._po_path("en")
        po_file = polib.pofile(str(path))
        po_file.append(polib.POEntry(msgid="new_entry", msgstr="New"))
        po_file.save()
        po2 = po_backend._load_po("en")
        assert po2 is not po1
        assert po2.find("new_entry") is not None


class TestFindEntry:
    def test_finds_by_msgid(self, po_backend: POFileBackend):
        po = po_backend._load_po("en")
        entry = po_backend._find_entry(po, MsgKey("hello", ""))
        assert entry is not None
        assert entry.msgstr == "Hello"

    def test_returns_none_for_missing_msgid(self, po_backend: POFileBackend):
        po = po_backend._load_po("en")
        entry = po_backend._find_entry(po, MsgKey("nonexistent", ""))
        assert entry is None

    def test_finds_by_context(self, locale_dir: pathlib.Path, settings):
        entries = [
            polib.POEntry(msgid="hello", msgstr="Hello generic"),
            polib.POEntry(msgid="hello", msgstr="Hello greeting", msgctxt="greeting"),
        ]
        _make_po_file(locale_dir, "en", entries)
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        po = backend._load_po("en")

        no_ctx = backend._find_entry(po, MsgKey("hello", ""))
        assert no_ctx is not None
        assert no_ctx.msgstr == "Hello generic"

        with_ctx = backend._find_entry(po, MsgKey("hello", "greeting"))
        assert with_ctx is not None
        assert with_ctx.msgstr == "Hello greeting"


# ===========================================================================
# POFileBackend — get_translations
# ===========================================================================


class TestGetTranslations:
    def test_returns_existing_entry(self, po_backend: POFileBackend):
        result = po_backend.get_translations(MsgKey("hello", ""), ["en"])
        assert "en" in result
        assert result["en"].msgstr == "Hello"
        assert result["en"].is_active is True
        assert result["en"].fuzzy is False
        assert result["en"].language == "en"
        assert result["en"].msgid == "hello"
        assert result["en"].context == ""

    def test_returns_empty_msgstr_for_missing_entry(self, po_backend: POFileBackend):
        result = po_backend.get_translations(MsgKey("nonexistent", ""), ["en"])
        assert result["en"].msgstr == ""
        assert result["en"].is_active is True

    def test_returns_empty_msgstr_for_missing_language(self, po_backend: POFileBackend):
        result = po_backend.get_translations(MsgKey("hello", ""), ["fr"])
        assert result["fr"].msgstr == ""

    def test_returns_pending_value_when_present(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Active Value")
        _set_pending(entry, "Pending Value")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].msgstr == "Pending Value"
        assert result["en"].is_active is False

    def test_fuzzy_flag_detected(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Hello")
        entry.flags = ["fuzzy"]
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].fuzzy is True

    def test_multiple_languages(self, locale_dir: pathlib.Path, settings):
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hello")])
        _make_po_file(locale_dir, "cs", [polib.POEntry(msgid="hello", msgstr="Ahoj")])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_translations(MsgKey("hello", ""), ["en", "cs"])
        assert result["en"].msgstr == "Hello"
        assert result["cs"].msgstr == "Ahoj"

    def test_mixed_existing_and_missing_languages(self, po_backend: POFileBackend):
        result = po_backend.get_translations(MsgKey("hello", ""), ["en", "fr"])
        assert result["en"].msgstr == "Hello"
        assert result["fr"].msgstr == ""

    def test_context_preserved_in_result(self, locale_dir: pathlib.Path, settings):
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hello", msgctxt="greeting")])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_translations(MsgKey("hello", "greeting"), ["en"])
        assert result["en"].context == "greeting"
        assert result["en"].msgstr == "Hello"


# ===========================================================================
# POFileBackend — get_inactive_overrides
# ===========================================================================


class TestGetInactiveOverrides:
    def test_returns_empty_when_no_pending(self, po_backend: POFileBackend):
        result = po_backend.get_inactive_overrides("en")
        assert result == {}

    def test_returns_pending_entries(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Active")
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_inactive_overrides("en")
        assert MsgKey("hello", "") in result
        assert result[MsgKey("hello", "")] == "Pending"

    def test_returns_empty_for_missing_language(self, po_backend: POFileBackend):
        result = po_backend.get_inactive_overrides("fr")
        assert result == {}

    def test_skips_entries_without_pending(self, locale_dir: pathlib.Path, settings):
        entries = [
            polib.POEntry(msgid="active_one", msgstr="Active"),
            polib.POEntry(msgid="pending_one", msgstr="Old"),
        ]
        _set_pending(entries[1], "New Pending")
        _make_po_file(locale_dir, "en", entries)
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_inactive_overrides("en")
        assert len(result) == 1
        assert MsgKey("active_one", "") not in result
        assert MsgKey("pending_one", "") in result

    def test_preserves_msgctxt_in_key(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Active", msgctxt="ctx")
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_inactive_overrides("en")
        assert MsgKey("hello", "ctx") in result


# ===========================================================================
# POFileBackend — save_translations
# ===========================================================================


@pytest.mark.django_db
class TestSaveTranslations:
    def test_save_new_entry_active(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(MsgKey("new_key", ""), {"en": "New Value"})

        # Verify the entry was written to disk
        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("new_key")
        assert entry is not None
        assert entry.msgstr == "New Value"
        assert _get_pending(entry) is None

    def test_save_new_entry_inactive(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": False,
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(MsgKey("new_key", ""), {"en": "New Value"})

        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("new_key")
        assert entry is not None
        # msgstr should be empty for inactive new entries
        assert entry.msgstr == ""
        assert _get_pending(entry) == "New Value"

    def test_save_updates_existing_entry_active(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(MsgKey("hello", ""), {"en": "Updated Hello"})

        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Updated Hello"
        assert _get_pending(entry) is None

    def test_save_inactive_sets_pending(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(
            MsgKey("hello", ""),
            {"en": "Pending Hello"},
            active_flags={"en": False},
        )

        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        # Original msgstr preserved
        assert entry.msgstr == "Hello"
        assert _get_pending(entry) == "Pending Hello"

    def test_save_inactive_matching_msgstr_clears_pending(self, po_backend: POFileBackend, settings):
        """When saving inactive with value matching current msgstr, pending is cleared."""
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(
            MsgKey("hello", ""),
            {"en": "Hello"},  # Same as existing msgstr
            active_flags={"en": False},
        )

        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Hello"
        assert _get_pending(entry) is None

    def test_save_active_clears_fuzzy(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Hello")
        entry.flags = ["fuzzy"]
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(MsgKey("hello", ""), {"en": "Updated"})

        po = polib.pofile(str(backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert "fuzzy" not in entry.flags

    def test_save_inactive_clears_fuzzy(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Hello")
        entry.flags = ["fuzzy"]
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(MsgKey("hello", ""), {"en": "Pending"}, active_flags={"en": False})

        po = polib.pofile(str(backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert "fuzzy" not in entry.flags

    def test_save_creates_mo_file(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(MsgKey("hello", ""), {"en": "Updated"})

        mo_path = po_backend._mo_path("en")
        assert mo_path.exists()

    def test_save_notifies_reloader(self, po_backend: POFileBackend, settings):
        """Saving an active translation triggers the translation reloader (clears trans cache)."""
        from django.utils.translation import trans_real

        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        # Seed the translations cache so we can detect it being cleared
        trans_real._translations["_sentinel"] = object()  # type: ignore[assignment]

        po_backend.save_translations(MsgKey("hello", ""), {"en": "Updated"})

        # translation_file_changed clears _translations
        assert "_sentinel" not in trans_real._translations  # type: ignore[missing-attribute]

    def test_save_invalidates_po_cache(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        # Pre-populate cache
        po_backend._load_po("en")
        assert po_backend._po_path("en") in po_backend._po_cache

        po_backend.save_translations(MsgKey("hello", ""), {"en": "Updated"})

        assert po_backend._po_path("en") not in po_backend._po_cache

    def test_save_with_explicit_active_flags(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": False,
        }
        conf.get_settings.cache_clear()

        # active_flags override the fallback
        po_backend.save_translations(MsgKey("hello", ""), {"en": "Active!"}, active_flags={"en": True})

        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Active!"
        assert _get_pending(entry) is None

    def test_save_active_clears_existing_pending(self, locale_dir: pathlib.Path, settings):
        """Saving as active should clear any existing pending value."""
        entry = polib.POEntry(msgid="hello", msgstr="Original")
        _set_pending(entry, "Was Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(MsgKey("hello", ""), {"en": "Now Active"}, active_flags={"en": True})

        po = polib.pofile(str(backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Now Active"
        assert _get_pending(entry) is None

    def test_save_multiple_languages(self, locale_dir: pathlib.Path, settings):
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hello")])
        _make_po_file(locale_dir, "cs", [polib.POEntry(msgid="hello", msgstr="Ahoj")])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en", "cs"],
            "LOCALE_DIR": str(locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(MsgKey("hello", ""), {"en": "Hi", "cs": "Cau"})

        po_en = polib.pofile(str(backend._po_path("en")))
        po_cs = polib.pofile(str(backend._po_path("cs")))
        en_entry = po_en.find("hello")
        cs_entry = po_cs.find("hello")
        assert en_entry is not None
        assert cs_entry is not None
        assert en_entry.msgstr == "Hi"
        assert cs_entry.msgstr == "Cau"

    def test_save_new_entry_with_context(self, po_backend: POFileBackend, settings):
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(MsgKey("hello", "greeting"), {"en": "Hi there"})

        po = polib.pofile(str(po_backend._po_path("en")))
        entry = po.find("hello", msgctxt="greeting")
        assert entry is not None
        assert entry.msgstr == "Hi there"
        assert entry.msgctxt == "greeting"

    def test_save_records_history(self, po_backend: POFileBackend, settings):
        from live_translations import models

        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(po_backend.locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        po_backend.save_translations(MsgKey("hello", ""), {"en": "Updated"})

        history_entries = models.TranslationHistory.objects.all()
        assert history_entries.count() >= 1

    def test_save_existing_with_pending_records_old_as_pending(self, locale_dir: pathlib.Path, settings):
        """When an entry has a pending value, old_entries should capture the pending value."""
        from live_translations import models

        entry = polib.POEntry(msgid="hello", msgstr="Original")
        _set_pending(entry, "Pending Old")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(MsgKey("hello", ""), {"en": "Brand New"})

        h = models.TranslationHistory.objects.filter(action="update").first()
        assert h is not None
        assert h.old_value == "Pending Old"
        assert h.new_value == "Brand New"


# ===========================================================================
# POFileBackend — bulk_activate
# ===========================================================================


class TestBulkActivate:
    def test_activates_pending_entries(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Original")
        _set_pending(entry, "Pending Value")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        activated = backend.bulk_activate("en", [MsgKey("hello", "")])

        assert activated == [MsgKey("hello", "")]
        # Verify the file was updated
        po = polib.pofile(str(backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert entry.msgstr == "Pending Value"
        assert _get_pending(entry) is None

    def test_skips_entries_without_pending(self, po_backend: POFileBackend):
        activated = po_backend.bulk_activate("en", [MsgKey("hello", "")])
        assert activated == []
        # No .mo file should be created when nothing was activated
        assert not po_backend._mo_path("en").exists()

    def test_skips_missing_entries(self, po_backend: POFileBackend):
        activated = po_backend.bulk_activate("en", [MsgKey("nonexistent", "")])
        assert activated == []
        assert not po_backend._mo_path("en").exists()

    def test_returns_empty_for_missing_language(self, po_backend: POFileBackend):
        activated = po_backend.bulk_activate("fr", [MsgKey("hello", "")])
        assert activated == []

    def test_clears_fuzzy_on_activate(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Original")
        entry.flags = ["fuzzy"]
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.bulk_activate("en", [MsgKey("hello", "")])

        po = polib.pofile(str(backend._po_path("en")))
        entry = po.find("hello")
        assert entry is not None
        assert "fuzzy" not in entry.flags

    def test_creates_mo_file(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Original")
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.bulk_activate("en", [MsgKey("hello", "")])

        assert backend._mo_path("en").exists()

    def test_notifies_reloader(self, locale_dir: pathlib.Path, settings):
        """Activating pending translations triggers the translation reloader."""
        from django.utils.translation import trans_real

        entry = polib.POEntry(msgid="hello", msgstr="Original")
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        # Seed the translations cache so we can detect it being cleared
        trans_real._translations["_sentinel"] = object()  # type: ignore[assignment]

        backend.bulk_activate("en", [MsgKey("hello", "")])

        assert "_sentinel" not in trans_real._translations  # type: ignore[missing-attribute]

    def test_invalidates_cache(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Original")
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        # Pre-populate cache
        backend._load_po("en")
        assert backend._po_path("en") in backend._po_cache

        backend.bulk_activate("en", [MsgKey("hello", "")])
        assert backend._po_path("en") not in backend._po_cache

    def test_activates_multiple_entries(self, locale_dir: pathlib.Path, settings):
        entries = [
            polib.POEntry(msgid="hello", msgstr="Hello"),
            polib.POEntry(msgid="world", msgstr="World"),
            polib.POEntry(msgid="no_pending", msgstr="Unchanged"),
        ]
        _set_pending(entries[0], "Pending Hello")
        _set_pending(entries[1], "Pending World")
        _make_po_file(locale_dir, "en", entries)
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        activated = backend.bulk_activate(
            "en",
            [MsgKey("hello", ""), MsgKey("world", ""), MsgKey("no_pending", "")],
        )

        assert len(activated) == 2
        assert MsgKey("hello", "") in activated
        assert MsgKey("world", "") in activated

        po = polib.pofile(str(backend._po_path("en")))
        hello = po.find("hello")
        world = po.find("world")
        no_pending = po.find("no_pending")
        assert hello is not None
        assert world is not None
        assert no_pending is not None
        assert hello.msgstr == "Pending Hello"
        assert world.msgstr == "Pending World"
        assert no_pending.msgstr == "Unchanged"

    def test_no_save_when_nothing_activated(self, po_backend: POFileBackend):
        """When no entries are actually activated, files shouldn't be saved."""
        po_backend.bulk_activate("en", [MsgKey("hello", "")])
        assert not po_backend._mo_path("en").exists()


# ===========================================================================
# POFileBackend — get_defaults
# ===========================================================================


class TestGetDefaults:
    def test_returns_existing_msgstr(self, po_backend: POFileBackend):
        result = po_backend.get_defaults(MsgKey("hello", ""), ["en"])
        assert result == {"en": "Hello"}

    def test_skips_missing_entry(self, po_backend: POFileBackend):
        result = po_backend.get_defaults(MsgKey("nonexistent", ""), ["en"])
        assert result == {}

    def test_skips_missing_language(self, po_backend: POFileBackend):
        result = po_backend.get_defaults(MsgKey("hello", ""), ["fr"])
        assert result == {}

    def test_multiple_languages(self, locale_dir: pathlib.Path, settings):
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hello")])
        _make_po_file(locale_dir, "cs", [polib.POEntry(msgid="hello", msgstr="Ahoj")])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_defaults(MsgKey("hello", ""), ["en", "cs"])
        assert result == {"en": "Hello", "cs": "Ahoj"}

    def test_with_context(self, locale_dir: pathlib.Path, settings):
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hi", msgctxt="ctx")])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_defaults(MsgKey("hello", "ctx"), ["en"])
        assert result == {"en": "Hi"}

    def test_empty_msgstr_included(self, locale_dir: pathlib.Path, settings):
        """An entry with empty msgstr still has the entry; empty strings are falsy but entry exists."""
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="")])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        result = backend.get_defaults(MsgKey("hello", ""), ["en"])
        # Entry exists but msgstr is falsy — the code checks `if entry:` which is truthy for POEntry
        # even with empty msgstr. But polib.POEntry with empty msgstr is still truthy.
        assert result == {"en": ""}


# ===========================================================================
# POFileBackend — get_hint
# ===========================================================================


class TestGetHint:
    def test_returns_comment(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Hello")
        entry.comment = "This is a greeting"
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        assert backend.get_hint(MsgKey("hello", "")) == "This is a greeting"

    def test_returns_empty_for_no_comment(self, po_backend: POFileBackend):
        assert po_backend.get_hint(MsgKey("hello", "")) == ""

    def test_strips_pending_from_hint(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Hello")
        entry.comment = "Translator note"
        _set_pending(entry, "Pending value")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        hint = backend.get_hint(MsgKey("hello", ""))
        assert hint == "Translator note"
        assert LT_PENDING_PREFIX not in hint

    def test_returns_empty_for_missing_msgid(self, po_backend: POFileBackend):
        assert po_backend.get_hint(MsgKey("nonexistent", "")) == ""

    def test_returns_empty_when_only_pending_in_comment(self, locale_dir: pathlib.Path, settings):
        entry = polib.POEntry(msgid="hello", msgstr="Hello")
        _set_pending(entry, "Pending")
        _make_po_file(locale_dir, "en", [entry])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        assert backend.get_hint(MsgKey("hello", "")) == ""

    def test_searches_across_languages(self, locale_dir: pathlib.Path, settings):
        """get_hint iterates languages; should find comment in 2nd language if 1st has no comment."""
        entry_en = polib.POEntry(msgid="hello", msgstr="Hello")
        entry_cs = polib.POEntry(msgid="hello", msgstr="Ahoj")
        entry_cs.comment = "Czech comment"
        _make_po_file(locale_dir, "en", [entry_en])
        _make_po_file(locale_dir, "cs", [entry_cs])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        assert backend.get_hint(MsgKey("hello", "")) == "Czech comment"


# ===========================================================================
# POFileBackend — edge cases & integration
# ===========================================================================


class TestEdgeCases:
    def test_empty_context_treated_as_no_context(self, po_backend: POFileBackend):
        """MsgKey with empty string context should match entries without msgctxt."""
        result = po_backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].msgstr == "Hello"

    def test_po_cache_dict_type(self, po_backend: POFileBackend):
        assert isinstance(po_backend._po_cache, dict)

    @pytest.mark.django_db
    def test_save_and_get_roundtrip(self, locale_dir: pathlib.Path, settings):
        """Full roundtrip: save active, then get, verify consistency."""
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hello")])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
            "TRANSLATION_ACTIVE_BY_DEFAULT": True,
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(MsgKey("hello", ""), {"en": "Updated Hello"})

        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].msgstr == "Updated Hello"
        assert result["en"].is_active is True

    @pytest.mark.django_db
    def test_save_inactive_then_activate_roundtrip(self, locale_dir: pathlib.Path, settings):
        """Save as inactive, verify pending, then activate, verify active."""
        _make_po_file(locale_dir, "en", [polib.POEntry(msgid="hello", msgstr="Hello")])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        # Save as inactive
        backend.save_translations(
            MsgKey("hello", ""),
            {"en": "Pending Hello"},
            active_flags={"en": False},
        )

        # Verify pending
        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].msgstr == "Pending Hello"
        assert result["en"].is_active is False

        # Activate
        activated = backend.bulk_activate("en", [MsgKey("hello", "")])
        assert activated == [MsgKey("hello", "")]

        # Verify active
        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].msgstr == "Pending Hello"
        assert result["en"].is_active is True

    @pytest.mark.django_db
    def test_save_new_entry_inactive_with_context(self, locale_dir: pathlib.Path, settings):
        """New entry with context saved as inactive."""
        _make_po_file(locale_dir, "en", [])
        settings.LIVE_TRANSLATIONS = {
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
        }
        conf.get_settings.cache_clear()

        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        backend.save_translations(
            MsgKey("hello", "greeting"),
            {"en": "Hi greeting"},
            active_flags={"en": False},
        )

        po = polib.pofile(str(backend._po_path("en")))
        entry = po.find("hello", msgctxt="greeting")
        assert entry is not None
        assert entry.msgctxt == "greeting"
        assert entry.msgstr == ""
        assert _get_pending(entry) == "Hi greeting"


class TestEnsurePo:
    """_ensure_po auto-creates .po files for missing languages (e.g. drafts)."""

    def test_creates_po_file_when_missing(self, locale_dir: pathlib.Path, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["de"]}
        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        po = backend._ensure_po("de")

        assert po is not None
        po_path = locale_dir / "de" / "LC_MESSAGES" / "django.po"
        assert po_path.exists()

    def test_creates_parent_directories(self, tmp_path: pathlib.Path, settings):
        locale_dir = tmp_path / "locale"
        # Don't create it -- _ensure_po should handle it
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["ja"]}
        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        po = backend._ensure_po("ja")

        assert po is not None
        assert (locale_dir / "ja" / "LC_MESSAGES" / "django.po").exists()

    def test_created_file_has_metadata(self, locale_dir: pathlib.Path, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["ko"]}
        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        po = backend._ensure_po("ko")

        assert po.metadata.get("Language") == "ko"
        assert "charset=UTF-8" in po.metadata.get("Content-Type", "")

    def test_returns_existing_file(self, locale_dir: pathlib.Path, settings):
        _make_po_file(locale_dir, "en", [_make_entry(msgid="hi", msgstr="Hi")])
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}
        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        po = backend._ensure_po("en")

        assert po.find("hi") is not None

    @pytest.mark.django_db
    def test_save_works_after_auto_create(self, locale_dir: pathlib.Path, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["fr"], "LOCALE_DIR": str(locale_dir)}
        conf.get_settings.cache_clear()
        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        key = MsgKey(msgid="greeting", context="")

        backend.save_translations(key, {"fr": "Bonjour"}, {"fr": True})

        po = backend._load_po("fr")
        entry = po.find("greeting")
        assert entry is not None
        assert entry.msgstr == "Bonjour"

    def test_cache_invalidated_after_create(self, locale_dir: pathlib.Path, settings):
        """Auto-created file is correctly loaded into cache (no stale entry)."""
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["pt"]}
        backend = POFileBackend(locale_dir=locale_dir, domain="django")

        # Pre-populate cache with a fake stale entry
        po_path = locale_dir / "pt" / "LC_MESSAGES" / "django.po"
        backend._po_cache[po_path] = (0.0, polib.POFile())

        po = backend._ensure_po("pt")

        # Stale entry should be gone, fresh file loaded
        assert po_path in backend._po_cache
        assert backend._po_cache[po_path][0] > 0.0  # Real mtime, not our fake 0.0
        assert po.metadata.get("Language") == "pt"


class TestConstructor:
    def test_accepts_cache_alias(self, locale_dir: pathlib.Path):
        backend = POFileBackend(locale_dir=locale_dir, domain="django", cache_alias="translations")
        assert backend.cache_alias == "translations"

    def test_default_cache_alias(self, locale_dir: pathlib.Path):
        backend = POFileBackend(locale_dir=locale_dir, domain="django")
        assert backend.cache_alias == "default"

    def test_stores_locale_dir_and_domain(self, locale_dir: pathlib.Path):
        backend = POFileBackend(locale_dir=locale_dir, domain="djangojs")
        assert backend.locale_dir == locale_dir
        assert backend.domain == "djangojs"
