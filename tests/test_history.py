"""Tests for translation edit history."""

import json
import unittest.mock

import django.contrib.auth.models
import django.test
import pytest

from live_translations import conf, history, models, strings
from live_translations.backends import db


@pytest.mark.django_db
class TestTranslationHistoryModel:
    def test_create_entry(self):
        entry = models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            context="",
            action=models.TranslationHistory.Action.CREATE,
            old_value="",
            new_value="Hello",
        )
        assert entry.pk is not None
        assert entry.action == "create"
        assert entry.new_value == "Hello"

    def test_str_representation(self):
        entry = models.TranslationHistory(
            language="en",
            msgid="hello",
            context="",
            action="update",
        )
        assert str(entry) == "update en: hello"

    def test_str_with_context(self):
        entry = models.TranslationHistory(
            language="en",
            msgid="hello",
            context="greeting",
            action="create",
        )
        assert str(entry) == "create en: hello [greeting]"

    def test_ordering_is_newest_first(self):
        models.TranslationHistory.objects.create(
            language="en",
            msgid="a",
            action="create",
            new_value="First",
        )
        models.TranslationHistory.objects.create(
            language="en",
            msgid="b",
            action="create",
            new_value="Second",
        )
        entries = list(models.TranslationHistory.objects.all())
        assert entries[0].msgid == "b"
        assert entries[1].msgid == "a"

    def test_user_can_be_null(self):
        entry = models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            action="create",
            new_value="Hi",
            user=None,
        )
        entry.refresh_from_db()
        assert entry.user is None

    def test_user_fk(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="translator",
            password="test",
        )
        entry = models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            action="update",
            old_value="Hi",
            new_value="Hello",
            user=user,
        )
        entry.refresh_from_db()
        assert entry.user == user

    def test_user_set_null_on_delete(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="temp",
            password="test",
        )
        entry = models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            action="create",
            user=user,
        )
        user.delete()
        entry.refresh_from_db()
        assert entry.user is None


@pytest.mark.django_db
class TestRecordChange:
    def test_creates_entry(self):
        entry = history.record_change(
            language="en",
            msgid="hello",
            context="",
            action=models.TranslationHistory.Action.UPDATE,
            old_value="Hi",
            new_value="Hello",
        )
        assert entry.pk is not None
        assert entry.action == "update"

    def test_reads_user_from_contextvar(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="admin",
            password="test",
        )
        token = strings.lt_current_user.set(user)
        try:
            entry = history.record_change(
                language="en",
                msgid="hello",
                context="",
                action=models.TranslationHistory.Action.CREATE,
                new_value="Hello",
            )
        finally:
            strings.lt_current_user.reset(token)

        assert entry.user == user

    def test_null_user_when_contextvar_unset(self):
        entry = history.record_change(
            language="en",
            msgid="hello",
            context="",
            action=models.TranslationHistory.Action.CREATE,
            new_value="Hello",
        )
        assert entry.user is None

    def test_anonymous_user_stored_as_null(self):
        anon = unittest.mock.MagicMock(is_authenticated=False)
        token = strings.lt_current_user.set(anon)
        try:
            entry = history.record_change(
                language="en",
                msgid="hello",
                context="",
                action=models.TranslationHistory.Action.CREATE,
                new_value="Hello",
            )
        finally:
            strings.lt_current_user.reset(token)

        assert entry.user is None


@pytest.mark.django_db
class TestRecordBulkAction:
    def test_bulk_creates_entries(self):
        entries = [("en", "hello", ""), ("cs", "hello", "")]
        history.record_bulk_action(
            entries=entries,
            action=models.TranslationHistory.Action.ACTIVATE,
            old_value="inactive",
            new_value="active",
        )
        assert models.TranslationHistory.objects.count() == 2
        for h in models.TranslationHistory.objects.all():
            assert h.action == "activate"
            assert h.old_value == "inactive"
            assert h.new_value == "active"

    def test_empty_entries_noop(self):
        history.record_bulk_action(
            entries=[],
            action=models.TranslationHistory.Action.ACTIVATE,
            old_value="inactive",
            new_value="active",
        )
        assert models.TranslationHistory.objects.count() == 0


class TestComputeDiff:
    def test_empty_strings(self):
        assert history.compute_diff("", "") == []

    def test_insert_only(self):
        result = history.compute_diff("", "Hello")
        assert result == [{"type": "insert", "text": "Hello"}]

    def test_delete_only(self):
        result = history.compute_diff("Hello", "")
        assert result == [{"type": "delete", "text": "Hello"}]

    def test_equal_strings(self):
        result = history.compute_diff("Hello world", "Hello world")
        assert len(result) == 1
        assert result[0]["type"] == "equal"
        assert result[0]["text"] == "Hello world"

    def test_word_replacement(self):
        result = history.compute_diff("Hello world", "Hello everyone")
        types = [s["type"] for s in result]
        assert "equal" in types
        assert "delete" in types
        assert "insert" in types
        # "Hello " should be equal
        equal_segments = [s for s in result if s["type"] == "equal"]
        assert any("Hello" in s["text"] for s in equal_segments)

    def test_mixed_operations(self):
        result = history.compute_diff(
            "Welcome to our website",
            "Welcome to the platform",
        )
        assert len(result) > 1
        # Should have at least one equal, one delete, one insert
        types = {s["type"] for s in result}
        assert "equal" in types

    def test_preserves_whitespace(self):
        result = history.compute_diff("a  b", "a  b")
        assert len(result) == 1
        assert result[0]["text"] == "a  b"


@pytest.mark.django_db
class TestHistoryIntegrationWidget:
    """Test history recording through DatabaseBackend.save_translations()."""

    def _make_backend(self):
        backend = db.DatabaseBackend(locale_dir="/tmp", domain="django")
        mock_po = unittest.mock.MagicMock()
        mock_po.get_translations.return_value = {}
        mock_po.get_hint.return_value = ""
        backend._po_backend = mock_po
        return backend

    def test_create_records_history(self):
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations("hello", {"en": "Hi"}, context="")

        h = models.TranslationHistory.objects.get()
        assert h.action == "create"
        assert h.language == "en"
        assert h.new_value == "Hi"
        assert h.old_value == ""

    def test_create_records_po_default_as_old_value(self):
        backend = self._make_backend()
        with unittest.mock.patch.object(
            backend, "get_defaults", return_value={"en": "Default hello"}
        ):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations("hello", {"en": "Override"}, context="")

        h = models.TranslationHistory.objects.get()
        assert h.action == "create"
        assert h.old_value == "Default hello"
        assert h.new_value == "Override"

    def test_update_records_history(self):
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations("hello", {"en": "Hello"}, context="")

        h = models.TranslationHistory.objects.get()
        assert h.action == "update"
        assert h.old_value == "Hi"
        assert h.new_value == "Hello"

    def test_save_matching_po_default_keeps_override(self):
        """Saving text that matches .po default no longer auto-deletes the
        DB entry -- explicit delete action is required instead."""
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
            is_active=True,
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(
            backend, "get_defaults", return_value={"en": "Default"}
        ):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Default"}, context="", active_flags={"en": True}
                )

        entry = models.TranslationEntry.objects.get(language="en", msgid="hello")
        assert entry.msgstr == "Default"
        assert entry.is_active is True
        # History records the text change, not a delete
        h = models.TranslationHistory.objects.get()
        assert h.action == "update"
        assert h.old_value == "Hi"
        assert h.new_value == "Default"

    def test_save_matching_po_default_inactive(self):
        """Saving text that matches .po default as inactive preserves the
        entry so the user can preview the revert before activating."""
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
            is_active=False,
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(
            backend, "get_defaults", return_value={"en": "Default"}
        ):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Default"}, context="", active_flags={"en": False}
                )

        entry = models.TranslationEntry.objects.get(language="en", msgid="hello")
        assert entry.msgstr == "Default"
        assert entry.is_active is False

    def test_no_change_no_history(self):
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations("hello", {"en": "Hi"}, context="")

        assert models.TranslationHistory.objects.count() == 0

    def test_activate_via_widget_records_history(self):
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
            is_active=False,
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Hi"}, context="", active_flags={"en": True}
                )

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"

    def test_deactivate_via_widget_records_history(self):
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
            is_active=True,
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Hi"}, context="", active_flags={"en": False}
                )

        h = models.TranslationHistory.objects.get()
        assert h.action == "deactivate"
        assert h.old_value == "active"
        assert h.new_value == "inactive"

    def test_text_change_and_activate_records_both(self):
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
            is_active=False,
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Hello"}, context="", active_flags={"en": True}
                )

        entries = list(models.TranslationHistory.objects.order_by("created_at"))
        assert len(entries) == 2
        actions = {e.action for e in entries}
        assert actions == {"update", "activate"}

    def test_no_state_change_no_activate_history(self):
        """Active flag unchanged should produce no activate/deactivate entry."""
        models.TranslationEntry.objects.create(
            language="en",
            msgid="hello",
            msgstr="Hi",
            context="",
            is_active=True,
        )
        backend = self._make_backend()
        with unittest.mock.patch.object(backend, "get_defaults", return_value={}):
            with unittest.mock.patch.object(backend, "bump_catalog_version"):
                backend.save_translations(
                    "hello", {"en": "Hello"}, context="", active_flags={"en": True}
                )

        # Only text change, no state change
        assert models.TranslationHistory.objects.count() == 1
        assert models.TranslationHistory.objects.get().action == "update"


@pytest.mark.django_db
class TestHistoryView:
    @pytest.fixture(autouse=True)
    def _setup(self, settings):
        settings.LIVE_TRANSLATIONS = {
            "BACKEND": "live_translations.backends.db.DatabaseBackend",
            "LANGUAGES": ["en"],
            "LOCALE_DIR": "/tmp",
        }
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()
        yield
        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()
        conf.get_permission_checker.cache_clear()

    def _make_request(self, params: dict[str, str]):
        factory = django.test.RequestFactory()
        request = factory.get(
            "/__live-translations__/translations/history/",
            params,
        )
        request.user = unittest.mock.MagicMock(
            is_authenticated=True,
            is_superuser=True,
        )
        return request

    def test_returns_history_entries(self):
        models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            context="",
            action="update",
            old_value="Hi",
            new_value="Hello",
        )
        from live_translations import views

        response = views.get_history(self._make_request({"msgid": "hello"}))
        data = json.loads(response.content)
        assert len(data["history"]) == 1
        entry = data["history"][0]
        assert entry["action"] == "update"
        assert entry["old_value"] == "Hi"
        assert entry["new_value"] == "Hello"
        assert "diff" in entry

    def test_requires_msgid(self):
        from live_translations import views

        response = views.get_history(self._make_request({}))
        assert response.status_code == 400

    def test_requires_permission(self):
        from live_translations import views

        factory = django.test.RequestFactory()
        request = factory.get(
            "/__live-translations__/translations/history/",
            {"msgid": "hello"},
        )
        request.user = unittest.mock.MagicMock(
            is_authenticated=False,
            is_superuser=False,
        )
        response = views.get_history(request)
        assert response.status_code == 403

    def test_empty_history(self):
        from live_translations import views

        response = views.get_history(self._make_request({"msgid": "hello"}))
        data = json.loads(response.content)
        assert data["history"] == []

    def test_limit_parameter(self):
        for i in range(10):
            models.TranslationHistory.objects.create(
                language="en",
                msgid="hello",
                context="",
                action="update",
                old_value=f"v{i}",
                new_value=f"v{i + 1}",
            )
        from live_translations import views

        response = views.get_history(
            self._make_request({"msgid": "hello", "limit": "3"})
        )
        data = json.loads(response.content)
        assert len(data["history"]) == 3

    def test_diff_segments_included(self):
        models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            context="",
            action="update",
            old_value="Hello world",
            new_value="Hello everyone",
        )
        from live_translations import views

        response = views.get_history(self._make_request({"msgid": "hello"}))
        data = json.loads(response.content)
        diff = data["history"][0]["diff"]
        assert isinstance(diff, list)
        assert len(diff) > 0
        types = {s["type"] for s in diff}
        assert "equal" in types

    def test_activate_action_has_no_diff(self):
        models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            context="",
            action="activate",
            old_value="inactive",
            new_value="active",
        )
        from live_translations import views

        response = views.get_history(self._make_request({"msgid": "hello"}))
        data = json.loads(response.content)
        assert "diff" not in data["history"][0]

    def test_user_formatted(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="translator",
            password="test",
            first_name="Jane",
            last_name="Doe",
        )
        models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            action="create",
            new_value="Hello",
            user=user,
        )
        from live_translations import views

        response = views.get_history(self._make_request({"msgid": "hello"}))
        data = json.loads(response.content)
        assert data["history"][0]["user"] == "Jane Doe"

    def test_null_user_shows_system(self):
        models.TranslationHistory.objects.create(
            language="en",
            msgid="hello",
            action="create",
            new_value="Hello",
            user=None,
        )
        from live_translations import views

        response = views.get_history(self._make_request({"msgid": "hello"}))
        data = json.loads(response.content)
        assert data["history"][0]["user"] == "System"


@pytest.mark.django_db
class TestMiddlewareContextvar:
    def test_sets_user_for_authenticated_request(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="admin",
            password="test",
        )

        captured_user = None

        def capturing_view(request):
            nonlocal captured_user
            captured_user = strings.lt_current_user.get(None)
            return django.http.HttpResponse("ok")

        from live_translations.middleware import LiveTranslationsMiddleware

        mw = LiveTranslationsMiddleware(capturing_view)
        factory = django.test.RequestFactory()
        request = factory.get("/some-page/")
        request.user = user

        with unittest.mock.patch("live_translations.conf.get_backend_instance"):
            with unittest.mock.patch(
                "live_translations.conf.get_permission_checker",
                return_value=lambda r: False,
            ):
                mw(request)

        assert captured_user == user

    def test_sets_none_for_anonymous(self):
        captured_user = "sentinel"

        def capturing_view(request):
            nonlocal captured_user
            captured_user = strings.lt_current_user.get(None)
            return django.http.HttpResponse("ok")

        from live_translations.middleware import LiveTranslationsMiddleware

        mw = LiveTranslationsMiddleware(capturing_view)
        factory = django.test.RequestFactory()
        request = factory.get("/some-page/")
        request.user = unittest.mock.MagicMock(is_authenticated=False)

        with unittest.mock.patch("live_translations.conf.get_backend_instance"):
            with unittest.mock.patch(
                "live_translations.conf.get_permission_checker",
                return_value=lambda r: False,
            ):
                mw(request)

        assert captured_user is None

    def test_resets_after_request(self):
        def noop_view(request):
            return django.http.HttpResponse("ok")

        from live_translations.middleware import LiveTranslationsMiddleware

        mw = LiveTranslationsMiddleware(noop_view)
        factory = django.test.RequestFactory()
        request = factory.get("/some-page/")
        request.user = unittest.mock.MagicMock(is_authenticated=True)

        with unittest.mock.patch("live_translations.conf.get_backend_instance"):
            with unittest.mock.patch(
                "live_translations.conf.get_permission_checker",
                return_value=lambda r: False,
            ):
                mw(request)

        assert strings.lt_current_user.get(None) is None
