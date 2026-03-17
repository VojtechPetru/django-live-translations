"""Tests for the services module (live_translations.services)."""

import unittest.mock

import django.contrib.auth.models
import pytest

from live_translations import models, services
from live_translations.backends import base
from live_translations.types import MsgKey

# ---------------------------------------------------------------------------
# extract_placeholders
# ---------------------------------------------------------------------------


class TestExtractPlaceholders:
    def test_empty_string(self):
        assert services.extract_placeholders("") == set()

    def test_no_placeholders(self):
        assert services.extract_placeholders("Hello world") == set()

    def test_printf_s(self):
        assert services.extract_placeholders("Hello %s") == {"%s"}

    def test_printf_d(self):
        assert services.extract_placeholders("Count: %d items") == {"%d"}

    def test_printf_f(self):
        assert services.extract_placeholders("Price: %f") == {"%f"}

    def test_printf_named(self):
        assert services.extract_placeholders("Hello %(name)s") == {"%(name)s"}

    def test_printf_named_d(self):
        assert services.extract_placeholders("%(count)d items") == {"%(count)d"}

    def test_brace_placeholder(self):
        assert services.extract_placeholders("Hello {name}") == {"{name}"}

    def test_multiple_brace_placeholders(self):
        result = services.extract_placeholders("{first} and {second}")
        assert result == {"{first}", "{second}"}

    def test_mixed_printf_and_brace(self):
        result = services.extract_placeholders("%(name)s has {count}")
        assert result == {"%(name)s", "{count}"}

    def test_multiple_printf_types(self):
        result = services.extract_placeholders("%s has %d items at %f each")
        assert result == {"%s", "%d", "%f"}

    def test_printf_percent_literal(self):
        # %% is a literal percent sign, captured by the regex
        result = services.extract_placeholders("100%% done")
        assert "%%" in result

    def test_printf_various_format_specifiers(self):
        for spec in "diouxXeEfFgGcrsab":
            result = services.extract_placeholders(f"%{spec}")
            assert f"%{spec}" in result, f"Failed for %{spec}"

    def test_named_with_underscores(self):
        result = services.extract_placeholders("%(my_var)s and {another_var}")
        assert result == {"%(my_var)s", "{another_var}"}

    def test_named_with_digits(self):
        result = services.extract_placeholders("%(var1)s {item2}")
        assert result == {"%(var1)s", "{item2}"}

    def test_duplicate_placeholder_returns_single(self):
        result = services.extract_placeholders("%s and %s")
        assert result == {"%s"}


# ---------------------------------------------------------------------------
# validate_placeholders
# ---------------------------------------------------------------------------


class TestValidatePlaceholders:
    def test_no_placeholders_returns_none(self):
        result = services.validate_placeholders("Hello", {"en": "Hi", "cs": "Ahoj"})
        assert result is None

    def test_matching_placeholders_returns_none(self):
        result = services.validate_placeholders("Hello %s", {"en": "Hi %s", "cs": "Ahoj %s"})
        assert result is None

    def test_missing_placeholder(self):
        result = services.validate_placeholders("Hello %s", {"en": "Hi"})
        assert result is not None
        assert "en" in result
        assert any("missing" in part for part in result["en"])
        assert any("%s" in part for part in result["en"])

    def test_extra_placeholder(self):
        result = services.validate_placeholders("Hello", {"en": "Hi %s"})
        # No placeholders in msgid => returns None (early return)
        assert result is None

    def test_extra_placeholder_when_expected_exist(self):
        result = services.validate_placeholders("Hello %s", {"en": "Hi %s %d"})
        assert result is not None
        assert "en" in result
        assert any("unexpected" in part for part in result["en"])

    def test_missing_and_extra(self):
        result = services.validate_placeholders("Hello %(name)s", {"en": "Hi {user}"})
        assert result is not None
        assert "en" in result
        parts = result["en"]
        assert any("missing" in p for p in parts)
        assert any("unexpected" in p for p in parts)

    def test_empty_translation_skipped(self):
        result = services.validate_placeholders("Hello %s", {"en": ""})
        assert result is None

    def test_none_msgstr_skipped(self):
        # Empty string is falsy, should be skipped
        result = services.validate_placeholders("Hello %s", {"en": "", "cs": "Ahoj %s"})
        assert result is None

    def test_multiple_languages_errors(self):
        result = services.validate_placeholders("Hello %s", {"en": "Hi", "cs": "Ahoj"})
        assert result is not None
        assert "en" in result
        assert "cs" in result

    def test_only_bad_languages_reported(self):
        result = services.validate_placeholders("Hello %s", {"en": "Hi %s", "cs": "Ahoj"})
        assert result is not None
        assert "en" not in result
        assert "cs" in result

    def test_brace_placeholders_validated(self):
        result = services.validate_placeholders("Hello {name}", {"en": "Hi {name}"})
        assert result is None

    def test_brace_placeholder_missing(self):
        result = services.validate_placeholders("Hello {name}", {"en": "Hi"})
        assert result is not None
        assert "en" in result


# ---------------------------------------------------------------------------
# PlaceholderValidationError
# ---------------------------------------------------------------------------


class TestPlaceholderValidationError:
    def test_stores_details(self):
        details = {"en": ["missing %s"]}
        err = services.PlaceholderValidationError(details)
        assert err.details == details

    def test_is_exception(self):
        err = services.PlaceholderValidationError({})
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# format_user
# ---------------------------------------------------------------------------


class TestFormatUser:
    def test_none_returns_system(self):
        assert services.format_user(None) == "System"

    def test_full_name(self):
        user = unittest.mock.MagicMock()
        user.get_full_name.return_value = "Jane Doe"
        assert services.format_user(user) == "Jane Doe"

    def test_empty_full_name_falls_back_to_username(self):
        user = unittest.mock.MagicMock()
        user.get_full_name.return_value = ""
        user.USERNAME_FIELD = "username"
        user.username = "jdoe"
        assert services.format_user(user) == "jdoe"

    def test_no_get_full_name_uses_username(self):
        user = unittest.mock.MagicMock(spec=[])
        user.USERNAME_FIELD = "email"
        user.email = "jane@example.com"
        assert services.format_user(user) == "jane@example.com"

    def test_no_username_field_returns_unknown(self):
        user = unittest.mock.MagicMock(spec=[])
        # No get_full_name, no USERNAME_FIELD
        assert services.format_user(user) == "Unknown"

    def test_username_field_is_empty_string_returns_unknown(self):
        user = unittest.mock.MagicMock()
        user.get_full_name.return_value = ""
        user.USERNAME_FIELD = ""
        assert services.format_user(user) == "Unknown"

    @pytest.mark.django_db
    def test_real_django_user_with_full_name(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="jdoe", password="test", first_name="Jane", last_name="Doe"
        )
        assert services.format_user(user) == "Jane Doe"

    @pytest.mark.django_db
    def test_real_django_user_without_full_name(self):
        user = django.contrib.auth.models.User.objects.create_user(username="jdoe", password="test")
        assert services.format_user(user) == "jdoe"


# ---------------------------------------------------------------------------
# get_translations
# ---------------------------------------------------------------------------


class TestGetTranslations:
    def test_empty_msgid_raises(self):
        with pytest.raises(ValueError, match="msgid is required"):
            services.get_translations(key=MsgKey("", ""))

    def test_returns_translations_dict(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}

        mock_entry = base.TranslationEntry(
            language="en", msgid="hello", msgstr="Hello", context="", is_active=True, has_override=False
        )
        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {"en": mock_entry}
        mock_backend.get_defaults.return_value = {"en": "Hello", "cs": ""}
        mock_backend.get_hint.return_value = "A greeting"

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.get_translations(key=MsgKey("hello", ""))

        assert result["msgid"] == "hello"
        assert result["context"] == ""
        assert result["hint"] == "A greeting"
        assert "en" in result["translations"]
        assert result["translations"]["en"]["msgstr"] == "Hello"
        assert result["translations"]["en"]["is_active"] is True
        assert result["defaults"] == {"en": "Hello", "cs": ""}

    def test_passes_all_languages_to_backend(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs", "de"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}
        mock_backend.get_hint.return_value = ""

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.get_translations(key=MsgKey("hello", ""))

        mock_backend.get_translations.assert_called_once_with(MsgKey("hello", ""), ["en", "cs", "de"])


# ---------------------------------------------------------------------------
# save_translations
# ---------------------------------------------------------------------------


class TestSaveTranslations:
    def test_empty_msgid_raises(self):
        with pytest.raises(ValueError, match="msgid is required"):
            services.save_translations(key=MsgKey("", ""), translations={"en": "Hi"})

    def test_empty_translations_raises(self):
        with pytest.raises(ValueError, match="translations dict is required"):
            services.save_translations(key=MsgKey("hello", ""), translations={})

    def test_invalid_language_raises(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        with pytest.raises(ValueError, match="Invalid language codes: xx"):
            services.save_translations(key=MsgKey("hello", ""), translations={"xx": "Nope"})

    def test_multiple_invalid_languages(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        with pytest.raises(ValueError, match="Invalid language codes:"):
            services.save_translations(key=MsgKey("hello", ""), translations={"xx": "A", "yy": "B"})

    def test_placeholder_mismatch_raises(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        with pytest.raises(services.PlaceholderValidationError) as exc_info:
            services.save_translations(key=MsgKey("Hello %s", ""), translations={"en": "Hi"})

        assert "en" in exc_info.value.details

    @pytest.mark.django_db
    def test_successful_save(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.save_translations(key=MsgKey("hello", ""), translations={"en": "Hi"})

        assert result["ok"] is True
        assert "display" in result
        mock_backend.save_translations.assert_called_once()

    @pytest.mark.django_db
    def test_passes_active_flags(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.save_translations(
                key=MsgKey("hello", ""),
                translations={"en": "Hi"},
                active_flags={"en": True},
            )

        call_kwargs = mock_backend.save_translations.call_args
        assert call_kwargs[1]["active_flags"] == {"en": True}

    @pytest.mark.django_db
    def test_none_active_flags_passes_empty_dict(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.save_translations(key=MsgKey("hello", ""), translations={"en": "Hi"})

        call_kwargs = mock_backend.save_translations.call_args
        assert call_kwargs[1]["active_flags"] == {}


# ---------------------------------------------------------------------------
# delete_translations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteTranslations:
    def test_deletes_all_languages(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}

        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="")

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.delete_translations(key=MsgKey("hello", ""))

        assert result["ok"] is True
        assert result["deleted"] == 2
        assert models.TranslationEntry.objects.count() == 0

    def test_deletes_specific_languages(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}

        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="")

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.delete_translations(key=MsgKey("hello", ""), languages=["cs"])

        assert result["deleted"] == 1
        assert models.TranslationEntry.objects.count() == 1
        remaining = models.TranslationEntry.objects.first()
        assert remaining is not None
        assert remaining.language == "en"

    def test_records_history(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.delete_translations(key=MsgKey("hello", ""))

        h = models.TranslationHistory.objects.get()
        assert h.action == "delete"
        assert h.old_value == "Hi"
        assert h.new_value == ""

    def test_bumps_catalog_version(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.delete_translations(key=MsgKey("hello", ""))

        mock_backend.bump_catalog_version.assert_called_once()

    def test_no_entries_no_history_no_bump(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.delete_translations(key=MsgKey("hello", ""))

        assert result["deleted"] == 0
        assert models.TranslationHistory.objects.count() == 0
        mock_backend.bump_catalog_version.assert_not_called()

    def test_returns_display(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {"en": "Default"}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.delete_translations(key=MsgKey("hello", ""), page_language="en")

        assert "display" in result
        assert result["display"]["text"] == "Default"


# ---------------------------------------------------------------------------
# delete_entries (batch admin delete)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteEntries:
    def test_deletes_entries(self):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="")

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.delete_entries(queryset=qs)

        assert count == 2
        assert models.TranslationEntry.objects.count() == 0

    def test_records_history_per_entry(self):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="world", msgstr="Svet", context="ctx")

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.delete_entries(queryset=qs)

        assert models.TranslationHistory.objects.count() == 2
        actions = set(models.TranslationHistory.objects.values_list("action", flat=True))
        assert actions == {"delete"}

    def test_history_includes_old_value(self):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.delete_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.old_value == "Hi"
        assert h.new_value == ""
        assert h.msgid == "hello"

    def test_bumps_catalog_version(self):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.delete_entries(queryset=qs)

        mock_backend.bump_catalog_version.assert_called_once()

    def test_empty_queryset_returns_zero(self):
        qs = models.TranslationEntry.objects.none()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.delete_entries(queryset=qs)

        assert count == 0
        assert models.TranslationHistory.objects.count() == 0
        mock_backend.bump_catalog_version.assert_not_called()

    def test_preserves_context_in_history(self):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="greeting")

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.delete_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.context == "greeting"


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetHistory:
    def test_empty_history(self):
        result = services.get_history(key=MsgKey("hello", ""))
        assert result["history"] == []

    def test_returns_entries(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="create", old_value="", new_value="Hello"
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert len(result["history"]) == 1
        assert result["history"][0]["action"] == "create"
        assert result["history"][0]["new_value"] == "Hello"

    def test_respects_limit(self):
        for i in range(10):
            models.TranslationHistory.objects.create(
                language="en", msgid="hello", context="", action="update", old_value=f"v{i}", new_value=f"v{i + 1}"
            )
        result = services.get_history(key=MsgKey("hello", ""), limit=3)
        assert len(result["history"]) == 3

    def test_filters_by_key(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="create", new_value="Hello"
        )
        models.TranslationHistory.objects.create(
            language="en", msgid="other", context="", action="create", new_value="Other"
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert len(result["history"]) == 1

    def test_filters_by_context(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="ctx1", action="create", new_value="A"
        )
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="ctx2", action="create", new_value="B"
        )
        result = services.get_history(key=MsgKey("hello", "ctx1"))
        assert len(result["history"]) == 1

    def test_includes_diff_for_update(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="update", old_value="Hi", new_value="Hello"
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert "diff" in result["history"][0]

    def test_no_diff_for_activate(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="activate", old_value="inactive", new_value="active"
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert "diff" not in result["history"][0]

    def test_no_diff_for_deactivate(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="deactivate", old_value="active", new_value="inactive"
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert "diff" not in result["history"][0]

    def test_user_formatted(self):
        user = django.contrib.auth.models.User.objects.create_user(
            username="jdoe", password="test", first_name="Jane", last_name="Doe"
        )
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="create", new_value="Hello", user=user
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert result["history"][0]["user"] == "Jane Doe"

    def test_null_user_shows_system(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="create", new_value="Hello", user=None
        )
        result = services.get_history(key=MsgKey("hello", ""))
        assert result["history"][0]["user"] == "System"

    def test_created_at_is_isoformat(self):
        models.TranslationHistory.objects.create(
            language="en", msgid="hello", context="", action="create", new_value="Hello"
        )
        result = services.get_history(key=MsgKey("hello", ""))
        created_at = result["history"][0]["created_at"]
        assert isinstance(created_at, str)
        assert "T" in created_at  # ISO format contains T separator


# ---------------------------------------------------------------------------
# bulk_activate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkActivate:
    def test_delegates_to_backend(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        keys = [MsgKey("hello", ""), MsgKey("world", "")]
        mock_backend = unittest.mock.MagicMock()
        mock_backend.bulk_activate.return_value = keys

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.bulk_activate(language="en", keys=keys)

        assert result["ok"] is True
        assert result["activated"] == 2
        mock_backend.bulk_activate.assert_called_once_with("en", keys)

    def test_records_history_when_activated(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        activated = [MsgKey("hello", "")]
        mock_backend = unittest.mock.MagicMock()
        mock_backend.bulk_activate.return_value = activated

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.bulk_activate(language="en", keys=activated)

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"
        assert h.language == "en"
        assert h.msgid == "hello"

    def test_no_history_when_nothing_activated(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.bulk_activate.return_value = []

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.bulk_activate(language="en", keys=[MsgKey("hello", "")])

        assert result["activated"] == 0
        assert models.TranslationHistory.objects.count() == 0


# ---------------------------------------------------------------------------
# activate_entries / deactivate_entries
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestActivateEntries:
    def test_activates_inactive_entries(self):
        e1 = models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)
        e2 = models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr="M2", is_active=False)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.activate_entries(queryset=qs)

        assert count == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is True
        assert e2.is_active is True

    def test_skips_already_active(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.activate_entries(queryset=qs)

        assert count == 0

    def test_records_history(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", context="", is_active=False)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.activate_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"

    def test_bumps_catalog_version(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.activate_entries(queryset=qs)

        mock_backend.bump_catalog_version.assert_called_once()

    def test_no_bump_when_nothing_updated(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.activate_entries(queryset=qs)

        mock_backend.bump_catalog_version.assert_not_called()

    def test_mixed_active_inactive(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)
        e2 = models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr="M2", is_active=False)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.activate_entries(queryset=qs)

        assert count == 1
        e2.refresh_from_db()
        assert e2.is_active is True


@pytest.mark.django_db
class TestDeactivateEntries:
    def test_deactivates_active_entries(self):
        e1 = models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)
        e2 = models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr="M2", is_active=True)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.deactivate_entries(queryset=qs)

        assert count == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is False
        assert e2.is_active is False

    def test_skips_already_inactive(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            count = services.deactivate_entries(queryset=qs)

        assert count == 0

    def test_records_history(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", context="", is_active=True)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.deactivate_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.action == "deactivate"
        assert h.old_value == "active"
        assert h.new_value == "inactive"

    def test_bumps_catalog_version(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.deactivate_entries(queryset=qs)

        mock_backend.bump_catalog_version.assert_called_once()

    def test_no_bump_when_nothing_updated(self):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)

        qs = models.TranslationEntry.objects.all()

        mock_backend = unittest.mock.MagicMock()
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            services.deactivate_entries(queryset=qs)

        mock_backend.bump_catalog_version.assert_not_called()


# ---------------------------------------------------------------------------
# compute_display
# ---------------------------------------------------------------------------


class TestComputeDisplay:
    def test_active_entry_returns_msgstr(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        entry = base.TranslationEntry(language="en", msgid="hello", msgstr="Hi", context="", is_active=True)
        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {"en": entry}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Hi"
        assert result["is_preview_entry"] is False

    def test_inactive_entry_returns_default(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        entry = base.TranslationEntry(language="en", msgid="hello", msgstr="Hi", context="", is_active=False)
        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {"en": entry}
        mock_backend.get_defaults.return_value = {"en": "Default Hello"}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Default Hello"
        assert result["is_preview_entry"] is False

    def test_preview_shows_inactive_entry(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        entry = base.TranslationEntry(language="en", msgid="hello", msgstr="Preview Text", context="", is_active=False)
        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {"en": entry}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["text"] == "Preview Text"
        assert result["is_preview_entry"] is True

    def test_preview_active_entry_not_marked_as_preview(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        entry = base.TranslationEntry(language="en", msgid="hello", msgstr="Active Text", context="", is_active=True)
        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {"en": entry}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["text"] == "Active Text"
        assert result["is_preview_entry"] is False

    def test_no_entry_returns_default(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {"en": "Default Text"}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Default Text"
        assert result["is_preview_entry"] is False

    def test_no_entry_no_default_returns_empty(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == ""

    def test_uses_page_language(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}

        entry = base.TranslationEntry(language="cs", msgid="hello", msgstr="Ahoj", context="", is_active=True)
        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {"cs": entry}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="cs")

        assert result["text"] == "Ahoj"
        mock_backend.get_translations.assert_called_once_with(MsgKey("hello", ""), ["cs"])

    def test_falls_back_to_django_language(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with (
            unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend),
            unittest.mock.patch("django.utils.translation.get_language", return_value="cs"),
        ):
            services.compute_display(key=MsgKey("hello", ""), page_language="")

        mock_backend.get_translations.assert_called_once_with(MsgKey("hello", ""), ["cs"])

    def test_falls_back_to_first_configured_language(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["de", "en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {}

        with (
            unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend),
            unittest.mock.patch("django.utils.translation.get_language", return_value=None),
        ):
            services.compute_display(key=MsgKey("hello", ""), page_language="")

        mock_backend.get_translations.assert_called_once_with(MsgKey("hello", ""), ["de"])

    def test_preview_with_no_entry_not_marked(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_translations.return_value = {}
        mock_backend.get_defaults.return_value = {"en": "Default"}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["is_preview_entry"] is False


# ---------------------------------------------------------------------------
# get_default
# ---------------------------------------------------------------------------


class TestGetDefault:
    def test_delegates_to_backend(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_defaults.return_value = {"en": "Default Hello"}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.get_default(key=MsgKey("hello", ""), language="en")

        assert result == "Default Hello"
        mock_backend.get_defaults.assert_called_once_with(MsgKey("hello", ""), ["en"])

    def test_returns_empty_when_no_default(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        mock_backend = unittest.mock.MagicMock()
        mock_backend.get_defaults.return_value = {}

        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            result = services.get_default(key=MsgKey("hello", ""), language="en")

        assert result == ""
