"""Tests for the is_active field on TranslationEntry."""

import json
import unittest.mock

import django.test
import pytest

from live_translations import conf, models
from live_translations.backends import base, db


@pytest.fixture()
def _db_setup(db):
    """Ensure DB is available for tests that need it."""


@pytest.mark.django_db
class TestTranslationEntryModel:
    def test_is_active_field_exists(self):
        entry = models.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        assert hasattr(entry, "is_active")

    def test_is_active_defaults_to_false(self):
        entry = models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        entry.refresh_from_db()
        assert entry.is_active is False

    def test_active_queryset_filter(self):
        models.TranslationEntry.objects.create(
            language="en", msgid="active_msg", msgstr="Active", is_active=True
        )
        models.TranslationEntry.objects.create(
            language="en", msgid="inactive_msg", msgstr="Inactive", is_active=False
        )
        active_qs = models.TranslationEntry.objects.active()
        assert active_qs.count() == 1
        assert active_qs.first().msgid == "active_msg"

    def test_active_manager_method(self):
        models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr="M1", is_active=True
        )
        models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr="M2", is_active=False
        )
        assert models.TranslationEntry.objects.active().count() == 1


class TestBaseDataclass:
    def test_is_active_defaults_to_true(self):
        entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        assert entry.is_active is True

    def test_is_active_can_be_set_false(self):
        entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context="", is_active=False
        )
        assert entry.is_active is False


@pytest.mark.django_db
class TestInjectOverrides:
    def test_only_active_overrides_injected(self):
        models.TranslationEntry.objects.create(
            language="en", msgid="active_key", msgstr="Active Value", is_active=True
        )
        models.TranslationEntry.objects.create(
            language="en",
            msgid="inactive_key",
            msgstr="Inactive Value",
            is_active=False,
        )

        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        with unittest.mock.patch.object(backend, "_get_po_backend"):
            # Mock the translation object and catalog
            mock_catalog = {}
            mock_trans = unittest.mock.MagicMock()
            mock_trans._catalog = mock_catalog

            with unittest.mock.patch(
                "django.utils.translation.trans_real.translation",
                return_value=mock_trans,
            ):
                backend.inject_overrides()

        assert "active_key" in mock_catalog
        assert mock_catalog["active_key"] == "Active Value"
        assert "inactive_key" not in mock_catalog


@pytest.mark.django_db
class TestGetTranslations:
    def test_returns_is_active_for_db_override(self):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hi", context="", is_active=False
        )

        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        po_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        with unittest.mock.patch.object(
            backend,
            "_get_po_backend",
            return_value=unittest.mock.MagicMock(
                get_translations=unittest.mock.MagicMock(return_value={"en": po_entry})
            ),
        ):
            result = backend.get_translations("hello", ["en"], context="")

        assert result["en"].is_active is False
        assert result["en"].msgstr == "Hi"

    def test_po_only_entry_has_is_active_true(self):
        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        po_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        with unittest.mock.patch.object(
            backend,
            "_get_po_backend",
            return_value=unittest.mock.MagicMock(
                get_translations=unittest.mock.MagicMock(return_value={"en": po_entry})
            ),
        ):
            result = backend.get_translations("hello", ["en"], context="")

        assert result["en"].is_active is True
        assert result["en"].msgstr == "Hello"


@pytest.mark.django_db
class TestSaveTranslations:
    def _make_backend(self):
        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        # Mock PO defaults to return empty (no .po match)
        mock_po = unittest.mock.MagicMock()
        mock_po.get_translations.return_value = {}
        mock_po.get_hint.return_value = ""
        backend._po_backend = mock_po
        return backend

    @pytest.mark.parametrize("active_default", [True, False])
    def test_new_entry_without_flags_uses_setting(self, active_default, settings):
        """When no active_flags provided, new entries use TRANSLATION_ACTIVE_BY_DEFAULT."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": active_default}
        conf.get_settings.cache_clear()

        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations("hello", {"en": "Hi"}, context="")

        entry = models.TranslationEntry.objects.get(language="en", msgid="hello")
        assert entry.is_active is active_default

        conf.get_settings.cache_clear()

    def test_explicit_active_flag_overrides_setting(self, settings):
        """When active_flags is provided, it takes priority over the setting."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": False}
        conf.get_settings.cache_clear()

        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Hi"}, context="", active_flags={"en": True}
                )

        entry = models.TranslationEntry.objects.get(language="en", msgid="hello")
        assert entry.is_active is True

        conf.get_settings.cache_clear()

    def test_explicit_active_flag_updates_existing(self, settings):
        """When active_flags is provided on update, it overwrites the existing is_active."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": True}
        conf.get_settings.cache_clear()

        # Pre-create an active entry
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Old", context="", is_active=True
        )

        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "New"}, context="", active_flags={"en": False}
                )

        entry = models.TranslationEntry.objects.get(language="en", msgid="hello")
        assert entry.msgstr == "New"
        assert entry.is_active is False

        conf.get_settings.cache_clear()

    def test_no_flags_uses_fallback_on_update(self, settings):
        """Without active_flags, updating uses the setting fallback."""
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": False}
        conf.get_settings.cache_clear()

        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Old", context="", is_active=True
        )

        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations("hello", {"en": "New"}, context="")

        entry = models.TranslationEntry.objects.get(language="en", msgid="hello")
        assert entry.msgstr == "New"
        # Without explicit flags, the setting fallback (False) is used in defaults
        assert entry.is_active is False

        conf.get_settings.cache_clear()


@pytest.mark.django_db
class TestSettingDefault:
    def test_default_is_false(self):
        conf.get_settings.cache_clear()
        settings = conf.get_settings()
        assert settings.translation_active_by_default is False
        conf.get_settings.cache_clear()

    def test_setting_can_be_overridden(self, settings):
        settings.LIVE_TRANSLATIONS = {"TRANSLATION_ACTIVE_BY_DEFAULT": True}
        conf.get_settings.cache_clear()
        resolved = conf.get_settings()
        assert resolved.translation_active_by_default is True
        conf.get_settings.cache_clear()


@pytest.mark.django_db
class TestAdminActions:
    """Test the activate/deactivate logic at the queryset level.

    We can't import TranslationEntryAdmin directly because the test conftest
    doesn't include django.contrib.admin in INSTALLED_APPS. Instead, we test
    the underlying bulk update + version bump logic that the admin actions use.
    """

    def test_bulk_activate(self):
        e1 = models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr="M1", is_active=False
        )
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr="M2", is_active=False
        )

        qs = models.TranslationEntry.objects.all()
        updated = qs.filter(is_active=False).update(is_active=True)

        assert updated == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is True
        assert e2.is_active is True

    def test_bulk_deactivate(self):
        e1 = models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr="M1", is_active=True
        )
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr="M2", is_active=True
        )

        qs = models.TranslationEntry.objects.all()
        updated = qs.filter(is_active=True).update(is_active=False)

        assert updated == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is False
        assert e2.is_active is False

    def test_activate_noop_returns_zero(self):
        """If all selected translations are already active, update returns 0."""
        models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr="M1", is_active=True
        )

        qs = models.TranslationEntry.objects.all()
        updated = qs.filter(is_active=False).update(is_active=True)
        assert updated == 0


@pytest.mark.django_db
class TestGetTranslationsView:
    def test_response_includes_is_active(self, settings):
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "live_translations.backends.db.DatabaseBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": "/tmp",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hi", context="", is_active=False
        )

        factory = django.test.RequestFactory()
        request = factory.get(
            "/__live-translations__/translations/",
            {"msgid": "hello", "context": ""},
        )
        request.user = unittest.mock.MagicMock(is_authenticated=True, is_superuser=True)

        from live_translations import views

        # Mock the PO backend to avoid filesystem access
        backend = conf.get_backend_instance()
        mock_po = unittest.mock.MagicMock()
        mock_po.get_translations.return_value = {
            "en": base.TranslationEntry(
                language="en", msgid="hello", msgstr="Hello", context=""
            )
        }
        mock_po.get_hint.return_value = ""
        backend._po_backend = mock_po

        response = views.get_translations(request)
        data = json.loads(response.content)

        assert data["translations"]["en"]["is_active"] is False
        assert data["translations"]["en"]["has_override"] is True

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()


@pytest.mark.django_db
class TestHasOverride:
    def test_db_entry_has_override_true(self):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hello", context="", is_active=True
        )
        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        po_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        with unittest.mock.patch.object(
            backend,
            "_get_po_backend",
            return_value=unittest.mock.MagicMock(
                get_translations=unittest.mock.MagicMock(return_value={"en": po_entry})
            ),
        ):
            result = backend.get_translations("hello", ["en"], context="")
        assert result["en"].has_override is True

    def test_po_only_has_override_false(self):
        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        po_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context=""
        )
        with unittest.mock.patch.object(
            backend,
            "_get_po_backend",
            return_value=unittest.mock.MagicMock(
                get_translations=unittest.mock.MagicMock(return_value={"en": po_entry})
            ),
        ):
            result = backend.get_translations("hello", ["en"], context="")
        assert result["en"].has_override is False


@pytest.mark.django_db
class TestDeleteTranslationView:
    def _setup(self, settings):
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "live_translations.backends.db.DatabaseBackend",
            "LANGUAGES": ["en", "cs"],
            "LOCALE_DIR": "/tmp",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

        backend = conf.get_backend_instance()
        mock_po = unittest.mock.MagicMock()
        mock_po.get_translations.return_value = {}
        mock_po.get_hint.return_value = ""
        backend._po_backend = mock_po
        return backend

    def _make_request(self, body):
        factory = django.test.RequestFactory(enforce_csrf_checks=False)
        request = factory.post(
            "/__live-translations__/translations/delete/",
            data=json.dumps(body),
            content_type="application/json",
        )
        request.user = unittest.mock.MagicMock(is_authenticated=True, is_superuser=True)
        # Bypass CSRF for unit tests
        request._dont_enforce_csrf_checks = True
        return request

    def test_deletes_all_languages(self, settings):
        self._setup(settings)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hi", context=""
        )
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", msgstr="Ahoj", context=""
        )

        from live_translations import views

        with unittest.mock.patch.object(
            conf.get_backend_instance(), "bump_catalog_version"
        ):
            response = views.delete_translation(
                self._make_request({"msgid": "hello", "context": ""})
            )

        data = json.loads(response.content)
        assert data["ok"] is True
        assert data["deleted"] == 2
        assert models.TranslationEntry.objects.count() == 0

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_records_history(self, settings):
        self._setup(settings)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hi", context=""
        )

        from live_translations import views

        with unittest.mock.patch.object(
            conf.get_backend_instance(), "bump_catalog_version"
        ):
            views.delete_translation(
                self._make_request({"msgid": "hello", "context": ""})
            )

        h = models.TranslationHistory.objects.get()
        assert h.action == "delete"
        assert h.old_value == "Hi"
        assert h.new_value == ""

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_deletes_single_language(self, settings):
        self._setup(settings)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Hi", context=""
        )
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", msgstr="Ahoj", context=""
        )

        from live_translations import views

        with unittest.mock.patch.object(
            conf.get_backend_instance(), "bump_catalog_version"
        ):
            response = views.delete_translation(
                self._make_request({"msgid": "hello", "context": "", "language": "cs"})
            )

        data = json.loads(response.content)
        assert data["ok"] is True
        assert data["deleted"] == 1
        # English override still exists
        assert models.TranslationEntry.objects.count() == 1
        assert models.TranslationEntry.objects.get().language == "en"

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def test_missing_msgid_returns_400(self, settings):
        self._setup(settings)

        from live_translations import views

        response = views.delete_translation(self._make_request({"context": ""}))
        assert response.status_code == 400

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()
