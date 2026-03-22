"""Tests for the is_active field on TranslationEntry."""

import json
import pathlib
import typing as t

import django.utils.translation
import django.utils.translation.trans_real
import polib
import pytest

from live_translations import conf, models
from live_translations.backends import base, db
from live_translations.types import MsgKey

if t.TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

    from tests.backends import TestBackend  # type: ignore[import-not-found]


@pytest.mark.django_db
class TestTranslationEntryModel:
    def test_is_active_field_exists(self):
        entry = models.TranslationEntry(language="en", msgid="hello", msgstr_forms={"0": "Hello"}, context="")
        assert hasattr(entry, "is_active")

    def test_is_active_defaults_to_false(self):
        entry = models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hello"}, context=""
        )
        entry.refresh_from_db()
        assert entry.is_active is False

    def test_active_queryset_filter(self):
        models.TranslationEntry.objects.create(
            language="en", msgid="active_msg", msgstr_forms={"0": "Active"}, is_active=True
        )
        models.TranslationEntry.objects.create(
            language="en", msgid="inactive_msg", msgstr_forms={"0": "Inactive"}, is_active=False
        )
        active_qs = models.TranslationEntry.objects.qs.active()
        assert active_qs.count() == 1
        entry = active_qs.first()
        assert entry is not None
        assert entry.msgid == "active_msg"

    def test_active_manager_method(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True)
        models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr_forms={"0": "M2"}, is_active=False)
        assert models.TranslationEntry.objects.qs.active().count() == 1


class TestBaseDataclass:
    def test_is_active_defaults_to_true(self):
        entry = base.TranslationEntry(language="en", msgid="hello", msgstr_forms={0: "Hello"}, context="")
        assert entry.is_active is True

    def test_is_active_can_be_set_false(self):
        entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr_forms={0: "Hello"}, context="", is_active=False
        )
        assert entry.is_active is False


@pytest.mark.django_db
class TestInjectOverrides:
    def test_only_active_overrides_injected(self, tmp_path: pathlib.Path, settings: "SettingsWrapper"):
        models.TranslationEntry.objects.create(
            language="en", msgid="active_key", msgstr_forms={"0": "Active Value"}, is_active=True
        )
        models.TranslationEntry.objects.create(
            language="en",
            msgid="inactive_key",
            msgstr_forms={"0": "Inactive Value"},
            is_active=False,
        )

        # Create real .po/.mo files so Django can load a catalog for "en"
        locale_dir = tmp_path / "locale"
        lc = locale_dir / "en" / "LC_MESSAGES"
        lc.mkdir(parents=True)
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8", "Language": "en"}
        po.append(polib.POEntry(msgid="active_key", msgstr="Original Active"))
        po.append(polib.POEntry(msgid="inactive_key", msgstr="Original Inactive"))
        po.save(str(lc / "django.po"))
        po.save_as_mofile(str(lc / "django.mo"))

        settings.LOCALE_PATHS = [str(locale_dir)]

        # Clear Django's translation cache so it picks up our new locale path
        if hasattr(django.utils.translation.trans_real, "_translations"):
            django.utils.translation.trans_real._translations = {}  # type: ignore[missing-attribute]

        django.utils.translation.activate("en")

        backend = db.DatabaseBackend(locale_dir=locale_dir, domain="django")
        backend.inject_overrides()

        trans_obj = django.utils.translation.trans_real.translation("en")
        catalog = trans_obj._catalog  # type: ignore[missing-attribute]

        assert catalog.get("active_key") == "Active Value"
        assert catalog.get("inactive_key") != "Inactive Value"

    def test_survives_missing_catalog_attribute(self, tmp_path: pathlib.Path, settings: "SettingsWrapper"):
        """inject_overrides must not crash if the translation object has no entries to inject."""
        models.TranslationEntry.objects.create(
            language="xx_missing", msgid="hello", msgstr_forms={"0": "Hi"}, is_active=True
        )

        locale_dir = tmp_path / "locale"
        locale_dir.mkdir(parents=True)

        backend = db.DatabaseBackend(locale_dir=locale_dir, domain="django")
        # inject_overrides for language "xx_missing" will fail to get a translation
        # object (since no .mo file exists) and should silently skip -- no crash.
        backend.inject_overrides()  # should not raise


@pytest.mark.django_db
class TestGetTranslations:
    def test_returns_is_active_for_db_override(self, make_db_backend):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="", is_active=False
        )

        backend = make_db_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].is_active is False
        assert result["en"].msgstr_forms == {0: "Hi"}

    def test_po_only_entry_has_is_active_true(self, make_db_backend):
        backend = make_db_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])

        assert result["en"].is_active is True
        assert result["en"].msgstr_forms == {0: "Hello"}


@pytest.mark.django_db
class TestSaveTranslations:
    @pytest.fixture(autouse=True)
    def _backend(self, make_db_backend, settings: "SettingsWrapper"):
        self._make_backend = make_db_backend
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

    @pytest.mark.parametrize("active_default", [True, False])
    def test_new_entry_without_flags_uses_setting(self, active_default, settings: "SettingsWrapper"):
        """When no active_flags provided, new entries use TRANSLATION_ACTIVE_BY_DEFAULT."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": active_default}
        conf.get_settings.cache_clear()

        backend = self._make_backend()
        backend.save_translations(MsgKey("hello", ""), {"en": {0: "Hi"}})

        entry = models.TranslationEntry.objects.qs.get(language="en", msgid="hello")
        assert entry.is_active is active_default

    def test_explicit_active_flag_overrides_setting(self, settings: "SettingsWrapper"):
        """When active_flags is provided, it takes priority over the setting."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": False}
        conf.get_settings.cache_clear()

        backend = self._make_backend()
        backend.save_translations(MsgKey("hello", ""), {"en": {0: "Hi"}}, active_flags={"en": True})

        entry = models.TranslationEntry.objects.qs.get(language="en", msgid="hello")
        assert entry.is_active is True

    def test_explicit_active_flag_updates_existing(self, settings: "SettingsWrapper"):
        """When active_flags is provided on update, it overwrites the existing is_active."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": True}
        conf.get_settings.cache_clear()

        # Pre-create an active entry
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Old"}, context="", is_active=True
        )

        backend = self._make_backend()
        backend.save_translations(MsgKey("hello", ""), {"en": {0: "New"}}, active_flags={"en": False})

        entry = models.TranslationEntry.objects.qs.get(language="en", msgid="hello")
        assert entry.msgstr_forms == {"0": "New"}
        assert entry.is_active is False

    def test_no_flags_uses_fallback_on_update(self, settings: "SettingsWrapper"):
        """Without active_flags, updating uses the setting fallback."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": False}
        conf.get_settings.cache_clear()

        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Old"}, context="", is_active=True
        )

        backend = self._make_backend()
        backend.save_translations(MsgKey("hello", ""), {"en": {0: "New"}})

        entry = models.TranslationEntry.objects.qs.get(language="en", msgid="hello")
        assert entry.msgstr_forms == {"0": "New"}
        # Without explicit flags, the setting fallback (False) is used in defaults
        assert entry.is_active is False


@pytest.mark.django_db
class TestSaveTranslationsView:
    def test_requires_permission(self, settings: "SettingsWrapper", make_request) -> None:
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "live_translations.backends.db.DatabaseBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": "/tmp",
        }
        conf.get_settings.cache_clear()

        request = make_request(
            "post",
            "/__live-translations__/translations/save/",
            data={"msgid": "hello", "context": "", "translations": {"en": {"0": "Hi"}}},
            has_permission=False,
        )

        from live_translations import views

        response = views.save_translations(request)
        assert response.status_code == 403


@pytest.mark.django_db
class TestSettingDefault:
    def test_default_is_false(self):
        settings = conf.get_settings()
        assert settings.translation_active_by_default is False

    def test_setting_can_be_overridden(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": True}
        conf.get_settings.cache_clear()
        resolved = conf.get_settings()
        assert resolved.translation_active_by_default is True


@pytest.mark.django_db
class TestAdminActions:
    """Test the activate/deactivate logic at the queryset level.

    We can't import TranslationEntryAdmin directly because the test conftest
    doesn't include django.contrib.admin in INSTALLED_APPS. Instead, we test
    the underlying bulk update + version bump logic that the admin actions use.
    """

    def test_bulk_activate(self):
        e1 = models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=False
        )
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr_forms={"0": "M2"}, is_active=False
        )

        qs = models.TranslationEntry.objects.qs.all()
        updated = qs.filter(is_active=False).update(is_active=True)

        assert updated == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is True
        assert e2.is_active is True

    def test_bulk_deactivate(self):
        e1 = models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True
        )
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr_forms={"0": "M2"}, is_active=True
        )

        qs = models.TranslationEntry.objects.qs.all()
        updated = qs.filter(is_active=True).update(is_active=False)

        assert updated == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is False
        assert e2.is_active is False

    def test_activate_noop_returns_zero(self):
        """If all selected translations are already active, update returns 0."""
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True)

        qs = models.TranslationEntry.objects.qs.all()
        updated = qs.filter(is_active=False).update(is_active=True)
        assert updated == 0


@pytest.mark.django_db
class TestGetTranslationsView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper", tmp_path: pathlib.Path):
        locale_dir = tmp_path / "locale"
        lc = locale_dir / "en" / "LC_MESSAGES"
        lc.mkdir(parents=True)
        po = polib.POFile()
        po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
        po.append(polib.POEntry(msgid="hello", msgstr="Hello"))
        po.save(str(lc / "django.po"))

        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "live_translations.backends.db.DatabaseBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": str(locale_dir),
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_response_includes_is_active(self, make_request):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="", is_active=False
        )

        request = make_request(
            "get",
            "/__live-translations__/translations/",
            data={"msgid": "hello", "context": ""},
        )

        from live_translations import views

        response = views.get_translations(request)
        data = json.loads(response.content)

        assert data["translations"]["en"]["is_active"] is False
        assert data["translations"]["en"]["has_override"] is True

    def test_requires_permission(self, make_request) -> None:
        request = make_request(
            "get",
            "/__live-translations__/translations/",
            data={"msgid": "hello", "context": ""},
            has_permission=False,
        )

        from live_translations import views

        response = views.get_translations(request)
        assert response.status_code == 403


@pytest.mark.django_db
class TestHasOverride:
    def test_db_entry_has_override_true(self, make_db_backend):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hello"}, context="", is_active=True
        )
        backend = make_db_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].has_override is True

    def test_po_only_has_override_false(self, make_db_backend):
        backend = make_db_backend(defaults={"en": {"hello": "Hello"}})
        result = backend.get_translations(MsgKey("hello", ""), ["en"])
        assert result["en"].has_override is False


@pytest.mark.django_db
class TestDeleteTranslationView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "tests.backends.TestBackend",
            "LANGUAGES": ["en", "cs", "de"],
            "LOCALE_DIR": "/tmp",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def _get_backend(self) -> "TestBackend":
        backend = conf.get_backend_instance()
        assert type(backend).__name__ == "TestBackend"
        return backend  # type: ignore[return-value]

    _URL = "/__live-translations__/translations/delete/"

    def test_deletes_all_languages(self, make_request):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="")

        from live_translations import views

        backend = self._get_backend()
        version_before = backend._version
        response = views.delete_translation(make_request("post", self._URL, data={"msgid": "hello", "context": ""}))

        data = json.loads(response.content)
        assert data["ok"] is True
        assert data["deleted"] == 2
        assert models.TranslationEntry.objects.qs.count() == 0
        assert backend._version > version_before

    def test_records_history(self, make_request):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")

        from live_translations import views

        views.delete_translation(make_request("post", self._URL, data={"msgid": "hello", "context": ""}))

        h = models.TranslationHistory.objects.get()
        assert h.action == "delete"
        assert h.old_value == "Hi"
        assert h.new_value == ""

    def test_deletes_single_language(self, make_request):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="")

        from live_translations import views

        response = views.delete_translation(
            make_request(
                "post",
                self._URL,
                data={"msgid": "hello", "context": "", "language": "cs"},
            )
        )

        data = json.loads(response.content)
        assert data["ok"] is True
        assert data["deleted"] == 1
        # English override still exists
        assert models.TranslationEntry.objects.qs.count() == 1
        assert models.TranslationEntry.objects.qs.get().language == "en"

    def test_deletes_multiple_languages(self, make_request):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="")
        models.TranslationEntry.objects.create(
            language="de",
            msgid="hello",
            msgstr_forms={"0": "Hallo"},
            context="",
        )

        from live_translations import views

        response = views.delete_translation(
            make_request(
                "post",
                self._URL,
                data={"msgid": "hello", "context": "", "languages": ["cs", "de"]},
            )
        )

        data = json.loads(response.content)
        assert data["ok"] is True
        assert data["deleted"] == 2
        assert models.TranslationEntry.objects.qs.count() == 1
        assert models.TranslationEntry.objects.qs.get().language == "en"

    def test_missing_msgid_returns_400(self, make_request):
        from live_translations import views

        response = views.delete_translation(make_request("post", self._URL, data={"context": ""}))
        assert response.status_code == 400

    def test_requires_permission(self, make_request) -> None:
        from live_translations import views

        request = make_request(
            "post",
            self._URL,
            data={"msgid": "hello", "context": ""},
            has_permission=False,
        )
        response = views.delete_translation(request)
        assert response.status_code == 403


@pytest.mark.django_db
class TestBulkActivateView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings: "SettingsWrapper"):
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "tests.backends.TestBackend",
            "LANGUAGES": ["en", "cs"],
            "LOCALE_DIR": "/tmp",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    _URL = "/__live-translations__/translations/bulk-activate/"

    def test_activates_only_given_language(self, make_request):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hello"}, context="", is_active=False
        )
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="", is_active=False
        )

        from live_translations import views

        response = views.bulk_activate(
            make_request(
                "post",
                self._URL,
                data={"language": "en", "msgids": [{"msgid": "hello", "context": ""}]},
            )
        )
        data = json.loads(response.content)

        assert response.status_code == 200
        assert data["ok"] is True
        assert data["activated"] == 1

        en_entry = models.TranslationEntry.objects.qs.get(language="en", msgid="hello")
        cs_entry = models.TranslationEntry.objects.qs.get(language="cs", msgid="hello")
        assert en_entry.is_active is True
        assert cs_entry.is_active is False

    def test_missing_language_returns_400(self, make_request):
        from live_translations import views

        response = views.bulk_activate(
            make_request("post", self._URL, data={"msgids": [{"msgid": "hello", "context": ""}]})
        )
        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["error"] == "language is required"

    def test_empty_language_returns_400(self, make_request):
        from live_translations import views

        response = views.bulk_activate(
            make_request(
                "post",
                self._URL,
                data={"language": "", "msgids": [{"msgid": "hello", "context": ""}]},
            )
        )
        assert response.status_code == 400

    def test_requires_permission(self, make_request) -> None:
        from live_translations import views

        request = make_request(
            "post",
            self._URL,
            data={"language": "en", "msgids": [{"msgid": "hello", "context": ""}]},
            has_permission=False,
        )
        response = views.bulk_activate(request)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# No phantom entries -- save_translations must not create DB rows for
# languages whose value matches the .po default when no override exists yet.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSaveNoPhantomEntries:
    """DatabaseBackend.save_translations should skip creating entries for
    languages that match the .po default and have no existing DB override."""

    @pytest.fixture(autouse=True)
    def _backend(self, make_db_backend, settings: "SettingsWrapper"):
        self._make_backend = make_db_backend
        settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

    def test_unchanged_language_not_saved(self, settings: "SettingsWrapper"):
        """Sending en+cs where only en differs from PO default: only en gets a row.

        The active flag for cs matches TRANSLATION_ACTIVE_BY_DEFAULT (False),
        so no override is needed.
        """
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"], "TRANSLATION_ACTIVE_BY_DEFAULT": False}
        conf.get_settings.cache_clear()

        backend = self._make_backend(defaults={"en": {"hello": "Hello"}, "cs": {"hello": "Ahoj"}})
        backend.save_translations(
            MsgKey("hello", ""),
            {"en": {0: "Hi there"}, "cs": {0: "Ahoj"}},  # cs unchanged
            active_flags={"en": True, "cs": False},  # cs flag matches default
        )

        assert models.TranslationEntry.objects.qs.count() == 1
        entry = models.TranslationEntry.objects.qs.get()
        assert entry.language == "en"
        assert entry.msgstr_forms == {"0": "Hi there"}

    def test_all_unchanged_creates_no_entries(self, settings: "SettingsWrapper"):
        """If every language matches its PO default and active flags match the setting, no rows are created."""
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"], "TRANSLATION_ACTIVE_BY_DEFAULT": True}
        conf.get_settings.cache_clear()

        backend = self._make_backend(defaults={"en": {"hello": "Hello"}, "cs": {"hello": "Ahoj"}})
        backend.save_translations(
            MsgKey("hello", ""),
            {"en": {0: "Hello"}, "cs": {0: "Ahoj"}},
            active_flags={"en": True, "cs": True},
        )

        assert models.TranslationEntry.objects.qs.count() == 0

    def test_existing_entry_still_updated_even_if_matches_default(self, settings: "SettingsWrapper"):
        """An existing DB row is always updated, even when the new value matches the PO default."""
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}
        conf.get_settings.cache_clear()

        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Old override"}, context=""
        )

        backend = self._make_backend(defaults={"en": {"hello": "Hello"}})
        backend.save_translations(MsgKey("hello", ""), {"en": {0: "Hello"}}, active_flags={"en": True})

        entry = models.TranslationEntry.objects.qs.get()
        assert entry.msgstr_forms == {"0": "Hello"}
        assert entry.is_active is True

    def test_non_default_active_flag_creates_entry(self, settings: "SettingsWrapper"):
        """If value matches PO default but active flag differs from the setting, an entry is created."""
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "TRANSLATION_ACTIVE_BY_DEFAULT": False}
        conf.get_settings.cache_clear()

        backend = self._make_backend(defaults={"en": {"hello": "Hello"}})
        # Value matches PO default, but active flag (True) differs from setting (False)
        backend.save_translations(MsgKey("hello", ""), {"en": {0: "Hello"}}, active_flags={"en": True})

        assert models.TranslationEntry.objects.qs.count() == 1
        entry = models.TranslationEntry.objects.qs.get()
        assert entry.is_active is True

    def test_missing_po_default_treated_as_empty(self, settings: "SettingsWrapper"):
        """A language with no PO default is treated as empty string for comparison."""
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "de"]}
        conf.get_settings.cache_clear()

        # Only en has a PO default; de has no entry
        backend = self._make_backend(defaults={"en": {"hello": "Hello"}})
        backend.save_translations(
            MsgKey("hello", ""),
            {"en": {0: "Hello"}, "de": {0: ""}},  # both match their defaults (en="Hello", de="")
        )

        assert models.TranslationEntry.objects.qs.count() == 0
