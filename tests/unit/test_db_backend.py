"""Comprehensive tests for the database backend (live_translations.backends.db)."""

import pathlib
import typing as t
import unittest.mock

import django.core.cache
import django.core.checks
import django.db.utils
import django.utils.translation
import django.utils.translation.trans_real
import pytest

from live_translations import models
from live_translations.backends import base, db
from live_translations.types import MsgKey

if t.TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------


class TestCheck:
    def test_missing_cache_alias_returns_w002(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {}
        backend = make_db_backend()
        errors = backend.check()

        assert len(errors) == 1
        assert errors[0].id == "live_translations.W002"
        assert isinstance(errors[0], django.core.checks.Warning)
        assert "not defined in CACHES" in errors[0].msg

    def test_dummy_cache_returns_w003(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
        backend = make_db_backend()
        errors = backend.check()

        assert len(errors) == 1
        assert errors[0].id == "live_translations.W003"
        assert isinstance(errors[0], django.core.checks.Warning)
        assert "DummyCache" in errors[0].msg

    def test_valid_cache_returns_no_errors(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        backend = make_db_backend()
        errors = backend.check()

        assert errors == []

    def test_custom_cache_alias_missing(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        backend = db.DatabaseBackend(locale_dir=tmp_path, domain="django", cache_alias="translations")
        errors = backend.check()

        assert len(errors) == 1
        assert errors[0].id == "live_translations.W002"
        assert "'translations'" in errors[0].msg

    def test_custom_cache_alias_with_dummy(self, tmp_path: pathlib.Path, settings: "SettingsWrapper") -> None:
        settings.CACHES = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "translations": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
        }
        backend = db.DatabaseBackend(locale_dir=tmp_path, domain="django", cache_alias="translations")
        errors = backend.check()

        assert len(errors) == 1
        assert errors[0].id == "live_translations.W003"


# ---------------------------------------------------------------------------
# ensure_current()
# ---------------------------------------------------------------------------


class TestEnsureCurrent:
    @pytest.fixture(autouse=True)
    def _setup(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        self.backend: db.DatabaseBackend = make_db_backend()

    def test_noop_when_version_matches(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.set(db.CATALOG_VERSION_KEY, "v1")
        self.backend._local_version = "v1"

        with unittest.mock.patch.object(self.backend, "inject_overrides") as mock_inject:
            self.backend.ensure_current()

        mock_inject.assert_not_called()

    def test_reloads_when_version_differs(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.set(db.CATALOG_VERSION_KEY, "v2")
        self.backend._local_version = "v1"

        with (
            unittest.mock.patch("django.utils.translation.reloader.translation_file_changed") as mock_file_changed,
            unittest.mock.patch.object(self.backend, "inject_overrides") as mock_inject,
            unittest.mock.patch("django.utils.translation.get_language", return_value="en"),
            unittest.mock.patch("django.utils.translation.activate") as mock_activate,
        ):
            self.backend.ensure_current()

        mock_file_changed.assert_called_once()
        mock_inject.assert_called_once()
        mock_activate.assert_called_once_with("en")
        assert self.backend._local_version == "v2"

    def test_skips_activate_when_no_current_lang(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.set(db.CATALOG_VERSION_KEY, "v3")
        self.backend._local_version = "v1"

        with (
            unittest.mock.patch("django.utils.translation.reloader.translation_file_changed"),
            unittest.mock.patch.object(self.backend, "inject_overrides"),
            unittest.mock.patch("django.utils.translation.get_language", return_value=None),
            unittest.mock.patch("django.utils.translation.activate") as mock_activate,
        ):
            self.backend.ensure_current()

        mock_activate.assert_not_called()
        assert self.backend._local_version == "v3"

    def test_initial_unset_version_always_triggers_reload(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.set(db.CATALOG_VERSION_KEY, "first")

        with (
            unittest.mock.patch("django.utils.translation.reloader.translation_file_changed"),
            unittest.mock.patch.object(self.backend, "inject_overrides") as mock_inject,
            unittest.mock.patch("django.utils.translation.get_language", return_value=None),
        ):
            self.backend.ensure_current()

        mock_inject.assert_called_once()
        assert self.backend._local_version == "first"

    def test_remote_none_triggers_reload_from_unset(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.delete(db.CATALOG_VERSION_KEY)

        with (
            unittest.mock.patch("django.utils.translation.reloader.translation_file_changed"),
            unittest.mock.patch.object(self.backend, "inject_overrides") as mock_inject,
            unittest.mock.patch("django.utils.translation.get_language", return_value=None),
        ):
            self.backend.ensure_current()

        # _UNSET != None, so it should trigger reload
        mock_inject.assert_called_once()
        assert self.backend._local_version is None

    def test_noop_after_syncing_with_none(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.delete(db.CATALOG_VERSION_KEY)
        self.backend._local_version = None

        with unittest.mock.patch.object(self.backend, "inject_overrides") as mock_inject:
            self.backend.ensure_current()

        mock_inject.assert_not_called()


# ---------------------------------------------------------------------------
# bulk_activate()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkActivate:
    @pytest.fixture(autouse=True)
    def _setup(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        self.backend: db.DatabaseBackend = make_db_backend()

    def test_activates_inactive_entries(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=False
        )
        models.TranslationEntry.objects.create(
            language="en", msgid="world", context="", msgstr_forms={"0": "World"}, is_active=False
        )

        keys = [MsgKey("hello", ""), MsgKey("world", "")]
        activated = self.backend.bulk_activate("en", keys)

        assert len(activated) == 2
        assert MsgKey("hello", "") in activated
        assert MsgKey("world", "") in activated

        for entry in models.TranslationEntry.objects.all():
            assert entry.is_active is True

    def test_returns_empty_when_nothing_to_activate(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        activated = self.backend.bulk_activate("en", [MsgKey("hello", "")])

        assert activated == []

    def test_only_activates_matching_language(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=False
        )
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", context="", msgstr_forms={"0": "Ahoj"}, is_active=False
        )

        activated = self.backend.bulk_activate("en", [MsgKey("hello", "")])

        assert len(activated) == 1
        assert activated[0] == MsgKey("hello", "")

        cs_entry = models.TranslationEntry.objects.get(language="cs")
        assert cs_entry.is_active is False

    def test_bumps_catalog_version_when_activated(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=False
        )
        cache = django.core.cache.caches["default"]
        cache.delete(db.CATALOG_VERSION_KEY)

        self.backend.bulk_activate("en", [MsgKey("hello", "")])

        assert cache.get(db.CATALOG_VERSION_KEY) is not None

    def test_does_not_bump_version_when_nothing_activated(self) -> None:
        cache = django.core.cache.caches["default"]
        cache.delete(db.CATALOG_VERSION_KEY)

        self.backend.bulk_activate("en", [MsgKey("nonexistent", "")])

        assert cache.get(db.CATALOG_VERSION_KEY) is None

    def test_activates_entry_with_context(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="open", context="verb", msgstr_forms={"0": "Open"}, is_active=False
        )

        activated = self.backend.bulk_activate("en", [MsgKey("open", "verb")])

        assert len(activated) == 1
        assert activated[0] == MsgKey("open", "verb")

    def test_activates_entry_with_plural(self) -> None:
        models.TranslationEntry.objects.create(
            language="en",
            msgid="item",
            context="",
            msgid_plural="items",
            msgstr_forms={"0": "item", "1": "items"},
            is_active=False,
        )

        activated = self.backend.bulk_activate("en", [MsgKey("item", "", "items")])

        assert len(activated) == 1
        assert activated[0] == MsgKey("item", "", "items")


# ---------------------------------------------------------------------------
# get_inactive_overrides()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetInactiveOverrides:
    @pytest.fixture(autouse=True)
    def _setup(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        self.backend: db.DatabaseBackend = make_db_backend()

    def test_returns_inactive_entries_with_translations(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=False
        )

        overrides = self.backend.get_inactive_overrides("en")

        assert MsgKey("hello", "") in overrides
        assert overrides[MsgKey("hello", "")] == {0: "Hi"}

    def test_excludes_active_entries(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        overrides = self.backend.get_inactive_overrides("en")

        assert overrides == {}

    def test_excludes_entries_with_all_empty_values(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": ""}, is_active=False
        )

        overrides = self.backend.get_inactive_overrides("en")

        assert overrides == {}

    def test_returns_empty_dict_when_no_inactive_entries(self) -> None:
        overrides = self.backend.get_inactive_overrides("en")

        assert overrides == {}

    def test_filters_by_language(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=False
        )
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", context="", msgstr_forms={"0": "Ahoj"}, is_active=False
        )

        overrides = self.backend.get_inactive_overrides("en")

        assert len(overrides) == 1
        assert MsgKey("hello", "") in overrides

    def test_handles_empty_msgstr_forms(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={}, is_active=False
        )

        overrides = self.backend.get_inactive_overrides("en")

        # Empty dict -> forms becomes {0: ""}, all values empty -> excluded
        assert overrides == {}

    def test_handles_db_error_gracefully(self, make_db_backend) -> None:
        backend = make_db_backend()

        with unittest.mock.patch.object(
            models.TranslationEntry.objects,
            "get_queryset",
            side_effect=django.db.utils.OperationalError("table not found"),
        ):
            overrides = backend.get_inactive_overrides("en")

        assert overrides == {}


# ---------------------------------------------------------------------------
# inject_overrides()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInjectOverrides:
    @pytest.fixture(autouse=True)
    def _setup(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        self.make_backend = make_db_backend

    def test_injects_singular_entry_into_catalog(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi there"}, is_active=True
        )

        catalog: dict[str, str] = {}
        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = catalog

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()

        assert catalog["hello"] == "Hi there"

    def test_injects_entry_with_context(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="open", context="verb", msgstr_forms={"0": "Open"}, is_active=True
        )

        catalog: dict[str, str] = {}
        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = catalog

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()

        assert catalog["verb\x04open"] == "Open"

    def test_injects_plural_entries_with_tuple_keys(self) -> None:
        models.TranslationEntry.objects.create(
            language="en",
            msgid="item",
            context="",
            msgid_plural="items",
            msgstr_forms={"0": "1 item", "1": "%d items"},
            is_active=True,
        )

        catalog: dict[t.Any, str] = {}
        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = catalog

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()

        assert catalog[("item", 0)] == "1 item"
        assert catalog[("item", 1)] == "%d items"

    def test_injects_plural_with_context(self) -> None:
        models.TranslationEntry.objects.create(
            language="en",
            msgid="item",
            context="shop",
            msgid_plural="items",
            msgstr_forms={"0": "1 item", "1": "%d items"},
            is_active=True,
        )

        catalog: dict[t.Any, str] = {}
        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = catalog

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()

        assert catalog[("shop\x04item", 0)] == "1 item"
        assert catalog[("shop\x04item", 1)] == "%d items"

    def test_handles_operational_error_on_query(self) -> None:
        backend = self.make_backend()

        with unittest.mock.patch.object(
            models.TranslationEntry.objects,
            "get_queryset",
            side_effect=django.db.utils.OperationalError("no such table"),
        ):
            backend.inject_overrides()  # should not raise

    def test_handles_programming_error_on_query(self) -> None:
        backend = self.make_backend()

        with unittest.mock.patch.object(
            models.TranslationEntry.objects,
            "get_queryset",
            side_effect=django.db.utils.ProgrammingError("relation does not exist"),
        ):
            backend.inject_overrides()  # should not raise

    def test_skips_language_when_translation_raises(self) -> None:
        models.TranslationEntry.objects.create(
            language="xx", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        backend = self.make_backend()
        with unittest.mock.patch(
            "django.utils.translation.trans_real.translation",
            side_effect=Exception("no such language"),
        ):
            backend.inject_overrides()  # should not raise

    def test_warns_and_returns_when_no_catalog_attribute(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        mock_trans = unittest.mock.MagicMock(spec=[])  # no _catalog attribute

        backend = self.make_backend()
        with (
            unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans),
            unittest.mock.patch("live_translations.backends.db.logger") as mock_logger,
        ):
            backend.inject_overrides()

        mock_logger.warning.assert_called_once()
        assert "_catalog" in mock_logger.warning.call_args[0][0]

    def test_skips_language_when_catalog_is_none(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = None

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()  # should not raise, just skip

    def test_injects_multiple_languages(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", context="", msgstr_forms={"0": "Ahoj"}, is_active=True
        )

        catalogs: dict[str, dict[str, str]] = {"en": {}, "cs": {}}

        def fake_translation(lang: str) -> unittest.mock.MagicMock:
            mock = unittest.mock.MagicMock()
            mock._catalog = catalogs[lang]
            return mock

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", side_effect=fake_translation):
            backend.inject_overrides()

        assert catalogs["en"]["hello"] == "Hi"
        assert catalogs["cs"]["hello"] == "Ahoj"

    def test_only_injects_active_entries(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="active", context="", msgstr_forms={"0": "Active"}, is_active=True
        )
        models.TranslationEntry.objects.create(
            language="en", msgid="inactive", context="", msgstr_forms={"0": "Inactive"}, is_active=False
        )

        catalog: dict[str, str] = {}
        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = catalog

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()

        assert catalog.get("active") == "Active"
        assert "inactive" not in catalog

    def test_handles_empty_msgstr_forms(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={}, is_active=True
        )

        catalog: dict[str, str] = {}
        mock_trans = unittest.mock.MagicMock()
        mock_trans._catalog = catalog

        backend = self.make_backend()
        with unittest.mock.patch("django.utils.translation.trans_real.translation", return_value=mock_trans):
            backend.inject_overrides()

        assert catalog["hello"] == ""


# ---------------------------------------------------------------------------
# get_translations()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetTranslations:
    @pytest.fixture(autouse=True)
    def _setup(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        self.make_backend = make_db_backend

    def test_returns_po_default_when_no_db_override(self) -> None:
        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].msgstr_forms == {0: "Hello"}
        assert result["en"].has_override is False
        assert result["en"].is_active is True

    def test_returns_db_override_when_exists(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].msgstr_forms == {0: "Hi"}
        assert result["en"].has_override is True
        assert result["en"].is_active is True

    def test_inactive_db_override_returns_correct_flags(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=False
        )

        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].msgstr_forms == {0: "Hi"}
        assert result["en"].has_override is True
        assert result["en"].is_active is False
        assert result["en"].fuzzy is False

    def test_fuzzy_from_po_preserved_without_override(self) -> None:
        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})

        # Patch the PO backend to return a fuzzy entry
        po_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr_forms={0: "Hello"}, context="", fuzzy=True
        )
        with unittest.mock.patch.object(backend._get_po_backend(), "get_translations", return_value={"en": po_entry}):
            result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].fuzzy is True
        assert result["en"].has_override is False

    def test_fuzzy_cleared_when_db_override_exists(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})

        po_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr_forms={0: "Hello"}, context="", fuzzy=True
        )
        with unittest.mock.patch.object(backend._get_po_backend(), "get_translations", return_value={"en": po_entry}):
            result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].fuzzy is False
        assert result["en"].has_override is True

    def test_multiple_languages(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", context="", msgstr_forms={"0": "Hi"}, is_active=True
        )

        backend = self.make_backend(defaults={"en": {"hello": "Hello"}, "cs": {"hello": "Ahoj"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en", "cs"])

        assert result["en"].has_override is True
        assert result["en"].msgstr_forms == {0: "Hi"}
        assert result["cs"].has_override is False
        assert result["cs"].msgstr_forms == {0: "Ahoj"}

    def test_language_with_no_po_and_no_db(self) -> None:
        backend = self.make_backend()
        result = backend.get_translations(MsgKey("hello", ""), ["de"])

        assert result["de"].msgstr_forms == {0: ""}
        assert result["de"].has_override is False
        assert result["de"].fuzzy is False

    def test_handles_db_error_gracefully(self) -> None:
        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})

        with unittest.mock.patch.object(
            models.TranslationEntry.objects,
            "get_queryset",
            side_effect=django.db.utils.OperationalError("connection lost"),
        ):
            result = backend.get_translations(MsgKey("hello", ""), ["en"])

        # Falls back to PO defaults
        assert result["en"].msgstr_forms == {0: "Hello"}
        assert result["en"].has_override is False

    def test_handles_programming_error_gracefully(self) -> None:
        backend = self.make_backend(defaults={"en": {"hello": "Hello"}})

        with unittest.mock.patch.object(
            models.TranslationEntry.objects,
            "get_queryset",
            side_effect=django.db.utils.ProgrammingError("relation does not exist"),
        ):
            result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].msgstr_forms == {0: "Hello"}
        assert result["en"].has_override is False

    def test_with_context(self) -> None:
        models.TranslationEntry.objects.create(
            language="en", msgid="open", context="verb", msgstr_forms={"0": "Open it"}, is_active=True
        )

        backend = self.make_backend(defaults={"en": {"open": "Open"}})
        result = backend.get_translations(MsgKey("open", "verb"), ["en"])

        assert result["en"].msgstr_forms == {0: "Open it"}
        assert result["en"].has_override is True
        assert result["en"].context == "verb"


# ---------------------------------------------------------------------------
# bump_catalog_version()
# ---------------------------------------------------------------------------


class TestBumpCatalogVersion:
    def test_sets_new_version_in_cache(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        backend = make_db_backend()
        cache = django.core.cache.caches["default"]

        backend.bump_catalog_version()

        version = cache.get(db.CATALOG_VERSION_KEY)
        assert version is not None
        assert isinstance(version, str)
        assert len(version) == 32  # uuid4 hex

    def test_each_bump_produces_unique_version(self, make_db_backend, settings: "SettingsWrapper") -> None:
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
        backend = make_db_backend()
        cache = django.core.cache.caches["default"]

        backend.bump_catalog_version()
        v1 = cache.get(db.CATALOG_VERSION_KEY)

        backend.bump_catalog_version()
        v2 = cache.get(db.CATALOG_VERSION_KEY)

        assert v1 != v2


# ---------------------------------------------------------------------------
# _get_po_backend()
# ---------------------------------------------------------------------------


class TestGetPoBackend:
    def test_returns_po_backend(self, make_db_backend) -> None:
        backend = make_db_backend()
        po_backend = backend._get_po_backend()

        from live_translations.backends.po import POFileBackend

        assert isinstance(po_backend, POFileBackend)
        assert po_backend.locale_dir == backend.locale_dir
        assert po_backend.domain == backend.domain

    def test_caches_po_backend(self, make_db_backend) -> None:
        backend = make_db_backend()
        first = backend._get_po_backend()
        second = backend._get_po_backend()

        assert first is second


# ---------------------------------------------------------------------------
# get_defaults()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetDefaults:
    def test_returns_po_file_values(self, make_db_backend) -> None:
        backend = make_db_backend(defaults={"en": {"hello": "Hello"}, "cs": {"hello": "Ahoj"}})
        defaults = backend.get_defaults(MsgKey("hello", ""), ["en", "cs"])

        assert defaults["en"] == {0: "Hello"}
        assert defaults["cs"] == {0: "Ahoj"}

    def test_returns_empty_forms_for_missing_language(self, make_db_backend) -> None:
        backend = make_db_backend(defaults={"en": {"hello": "Hello"}})
        defaults = backend.get_defaults(MsgKey("hello", ""), ["en", "de"])

        assert defaults["en"] == {0: "Hello"}
        assert defaults["de"] == {0: ""}
