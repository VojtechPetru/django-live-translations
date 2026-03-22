"""Tests for the services module (live_translations.services)."""

import typing as t
import unittest.mock

import django.contrib.auth.models
import django.db
import django.utils.translation
import pytest

from live_translations import models, services
from live_translations.types import MsgKey

if t.TYPE_CHECKING:
    from tests.backends import TestBackend  # type: ignore[import-not-found]

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
        result = services.validate_placeholders(MsgKey("Hello", ""), {"en": {0: "Hi"}, "cs": {0: "Ahoj"}})
        assert result is None

    def test_matching_placeholders_returns_none(self):
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: "Hi %s"}, "cs": {0: "Ahoj %s"}})
        assert result is None

    def test_missing_placeholder(self):
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: "Hi"}})
        assert result is not None
        assert "en" in result
        assert any("missing" in part for part in result["en"])
        assert any("%s" in part for part in result["en"])

    def test_extra_placeholder(self):
        result = services.validate_placeholders(MsgKey("Hello", ""), {"en": {0: "Hi %s"}})
        # No placeholders in msgid => returns None (early return)
        assert result is None

    def test_extra_placeholder_when_expected_exist(self):
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: "Hi %s %d"}})
        assert result is not None
        assert "en" in result
        assert any("unexpected" in part for part in result["en"])

    def test_missing_and_extra(self):
        result = services.validate_placeholders(MsgKey("Hello %(name)s", ""), {"en": {0: "Hi {user}"}})
        assert result is not None
        assert "en" in result
        parts = result["en"]
        assert any("missing" in p for p in parts)
        assert any("unexpected" in p for p in parts)

    def test_empty_translation_skipped(self):
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: ""}})
        assert result is None

    def test_none_msgstr_skipped(self):
        # Empty string is falsy, should be skipped
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: ""}, "cs": {0: "Ahoj %s"}})
        assert result is None

    def test_multiple_languages_errors(self):
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: "Hi"}, "cs": {0: "Ahoj"}})
        assert result is not None
        assert "en" in result
        assert "cs" in result

    def test_only_bad_languages_reported(self):
        result = services.validate_placeholders(MsgKey("Hello %s", ""), {"en": {0: "Hi %s"}, "cs": {0: "Ahoj"}})
        assert result is not None
        assert "en" not in result
        assert "cs" in result

    def test_brace_placeholders_validated(self):
        result = services.validate_placeholders(MsgKey("Hello {name}", ""), {"en": {0: "Hi {name}"}})
        assert result is None

    def test_brace_placeholder_missing(self):
        result = services.validate_placeholders(MsgKey("Hello {name}", ""), {"en": {0: "Hi"}})
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


class _SimpleUser:
    """Minimal user-like object for testing format_user without mocks."""

    USERNAME_FIELD = "username"

    def __init__(
        self,
        *,
        full_name: str = "",
        username: str = "",
        username_field: str = "username",
        has_get_full_name: bool = True,
    ) -> None:
        self._full_name = full_name
        self.USERNAME_FIELD = username_field
        setattr(self, username_field, username)
        self._has_get_full_name = has_get_full_name

    def get_full_name(self) -> str:
        if not self._has_get_full_name:
            raise AttributeError
        return self._full_name


class _BareUser:
    """User object with no get_full_name and no USERNAME_FIELD."""


class _NoFullNameUser:
    """User object without get_full_name but with USERNAME_FIELD."""

    def __init__(self, *, username_field: str, username_value: str) -> None:
        self.USERNAME_FIELD = username_field
        setattr(self, username_field, username_value)


class TestFormatUser:
    def test_none_returns_system(self):
        assert services.format_user(None) == "System"

    def test_full_name(self):
        user = _SimpleUser(full_name="Jane Doe")
        assert services.format_user(user) == "Jane Doe"  # type: ignore[arg-type]

    def test_empty_full_name_falls_back_to_username(self):
        user = _SimpleUser(full_name="", username="jdoe")
        assert services.format_user(user) == "jdoe"  # type: ignore[arg-type]

    def test_no_get_full_name_uses_username(self):
        user = _NoFullNameUser(username_field="email", username_value="jane@example.com")
        assert services.format_user(user) == "jane@example.com"  # type: ignore[arg-type]

    def test_no_username_field_returns_unknown(self):
        user = _BareUser()
        assert services.format_user(user) == "Unknown"  # type: ignore[arg-type]

    def test_username_field_is_empty_string_returns_unknown(self):
        user = _SimpleUser(full_name="", username_field="", username="ignored")
        assert services.format_user(user) == "Unknown"  # type: ignore[arg-type]

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


@pytest.mark.django_db
class TestGetTranslations:
    def test_empty_msgid_raises(self):
        with pytest.raises(ValueError, match="msgid is required"):
            services.get_translations(key=MsgKey("", ""))

    def test_returns_translations_dict(self, test_backend: "TestBackend"):
        test_backend.seed_default("en", "hello", "Hello")
        test_backend.seed_default("cs", "hello", "")
        test_backend.seed_hint("hello", "A greeting")

        # Create a DB override for "en" (explicitly active)
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hello"}, context="", is_active=True
        )

        result = services.get_translations(key=MsgKey("hello", ""))

        assert result["msgid"] == "hello"
        assert result["context"] == ""
        assert result["hint"] == "A greeting"
        assert "en" in result["translations"]
        assert result["translations"]["en"]["msgstr_forms"] == {0: "Hello"}
        assert result["translations"]["en"]["is_active"] is True
        assert result["defaults"] == {"en": {0: "Hello"}, "cs": {0: ""}}

    def test_passes_all_languages_to_backend(self, test_backend: "TestBackend", settings):
        settings.LIVE_TRANSLATIONS["LANGUAGES"] = ["en", "cs", "de"]

        from live_translations import conf

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        # Cache was cleared, so conf creates a new backend instance
        backend: TestBackend = conf.get_backend_instance()  # type: ignore[assignment]
        services.get_translations(key=MsgKey("hello", ""))

        calls = backend.get_calls("get_translations")
        assert len(calls) >= 1
        args, _ = calls[0]
        assert args == (MsgKey("hello", ""), ["en", "cs", "de"])


# ---------------------------------------------------------------------------
# save_translations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSaveTranslations:
    def test_empty_msgid_raises(self):
        with pytest.raises(ValueError, match="msgid is required"):
            services.save_translations(key=MsgKey("", ""), translations={"en": {0: "Hi"}})

    def test_empty_translations_raises(self):
        with pytest.raises(ValueError, match="translations dict is required"):
            services.save_translations(key=MsgKey("hello", ""), translations={})

    def test_invalid_language_raises(self, test_backend: "TestBackend"):
        with pytest.raises(ValueError, match="Invalid language codes: xx"):
            services.save_translations(key=MsgKey("hello", ""), translations={"xx": {0: "Nope"}})

    def test_multiple_invalid_languages(self, test_backend: "TestBackend"):
        with pytest.raises(ValueError, match="Invalid language codes:"):
            services.save_translations(key=MsgKey("hello", ""), translations={"xx": {0: "A"}, "yy": {0: "B"}})

    def test_placeholder_mismatch_raises(self, test_backend: "TestBackend"):
        with pytest.raises(services.PlaceholderValidationError) as exc_info:
            services.save_translations(key=MsgKey("Hello %s", ""), translations={"en": {0: "Hi"}})

        assert "en" in exc_info.value.details

    def test_successful_save(self, test_backend: "TestBackend"):
        result = services.save_translations(key=MsgKey("hello", ""), translations={"en": {0: "Hi"}})

        assert result["ok"] is True
        assert "display" in result

        calls = test_backend.get_calls("save_translations")
        assert len(calls) == 1

    def test_passes_active_flags(self, test_backend: "TestBackend"):
        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"en": {0: "Hi"}},
            active_flags={"en": True},
        )

        calls = test_backend.get_calls("save_translations")
        assert len(calls) == 1
        _, kwargs = calls[0]
        assert kwargs["active_flags"]["en"] is True

    def test_none_active_flags_passes_empty_dict(self, test_backend: "TestBackend"):
        services.save_translations(key=MsgKey("hello", ""), translations={"en": {0: "Hi"}})

        calls = test_backend.get_calls("save_translations")
        assert len(calls) == 1
        _, kwargs = calls[0]
        assert kwargs["active_flags"] == {}

    def test_draft_language_forced_active(self, test_backend: "TestBackend", settings):
        """Draft languages are always saved as active, regardless of the flag sent."""
        settings.LANGUAGES = [("en", "English")]

        from live_translations import conf

        conf.get_settings.cache_clear()

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"cs": {0: "Ahoj"}},
            active_flags={"cs": False},
        )

        calls = test_backend.get_calls("save_translations")
        _, kwargs = calls[0]
        assert kwargs["active_flags"]["cs"] is True

    def test_draft_forced_active_preserves_published_flags(self, test_backend: "TestBackend", settings):
        """Forcing active for draft languages doesn't affect published language flags."""
        settings.LANGUAGES = [("en", "English")]

        from live_translations import conf

        conf.get_settings.cache_clear()

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"en": {0: "Hi"}, "cs": {0: "Ahoj"}},
            active_flags={"en": False, "cs": False},
        )

        calls = test_backend.get_calls("save_translations")
        _, kwargs = calls[0]
        flags = kwargs["active_flags"]
        assert flags["en"] is False  # published: respects the flag
        assert flags["cs"] is True  # draft: forced active

    def test_draft_forced_active_with_none_flags(self, test_backend: "TestBackend", settings):
        """When active_flags is None (default), draft languages still get forced to True."""
        settings.LANGUAGES = [("en", "English")]

        from live_translations import conf

        conf.get_settings.cache_clear()

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"cs": {0: "Ahoj"}},
        )

        calls = test_backend.get_calls("save_translations")
        _, kwargs = calls[0]
        assert kwargs["active_flags"] == {"cs": True}

    def test_multiple_draft_languages_forced_active(self, test_backend: "TestBackend", settings):
        """All draft languages are forced active in a single save call."""
        settings.LANGUAGES = [("en", "English")]
        settings.LIVE_TRANSLATIONS["LANGUAGES"] = ["en", "ja", "ko"]

        from live_translations import conf

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        # Cache was cleared, so conf creates a new backend instance
        backend: TestBackend = conf.get_backend_instance()  # type: ignore[assignment]

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"ja": {0: "Konnichiwa"}, "ko": {0: "Annyeong"}},
            active_flags={"ja": False, "ko": False},
        )

        calls = backend.get_calls("save_translations")
        _, kwargs = calls[0]
        flags = kwargs["active_flags"]
        assert flags["ja"] is True
        assert flags["ko"] is True


# ---------------------------------------------------------------------------
# delete_translations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteTranslations:
    def test_deletes_all_languages(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="")

        result = services.delete_translations(key=MsgKey("hello", ""))

        assert result["ok"] is True
        assert result["deleted"] == 2
        assert models.TranslationEntry.objects.qs.count() == 0

    def test_deletes_specific_languages(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="")

        result = services.delete_translations(key=MsgKey("hello", ""), languages=["cs"])

        assert result["deleted"] == 1
        assert models.TranslationEntry.objects.qs.count() == 1
        remaining = models.TranslationEntry.objects.qs.first()
        assert remaining is not None
        assert remaining.language == "en"

    def test_records_history(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")

        services.delete_translations(key=MsgKey("hello", ""))

        h = models.TranslationHistory.objects.get()
        assert h.action == "delete"
        assert h.old_value == "Hi"
        assert h.new_value == ""

    def test_bumps_catalog_version(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")

        initial_version = test_backend._version
        services.delete_translations(key=MsgKey("hello", ""))

        assert test_backend._version == initial_version + 1

    def test_no_entries_no_history_no_bump(self, test_backend: "TestBackend"):
        initial_version = test_backend._version
        result = services.delete_translations(key=MsgKey("hello", ""))

        assert result["deleted"] == 0
        assert models.TranslationHistory.objects.count() == 0
        assert test_backend._version == initial_version

    def test_returns_display(self, test_backend: "TestBackend"):
        test_backend.seed_default("en", "hello", "Default")

        result = services.delete_translations(key=MsgKey("hello", ""), page_language="en")

        assert "display" in result
        assert result["display"]["text"] == "Default"


# ---------------------------------------------------------------------------
# delete_entries (batch admin delete)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteEntries:
    def test_deletes_entries(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="")

        qs = models.TranslationEntry.objects.qs.all()
        count = services.delete_entries(queryset=qs)

        assert count == 2
        assert models.TranslationEntry.objects.qs.count() == 0

    def test_records_history_per_entry(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")
        models.TranslationEntry.objects.create(language="cs", msgid="world", msgstr_forms={"0": "Svet"}, context="ctx")

        qs = models.TranslationEntry.objects.qs.all()
        services.delete_entries(queryset=qs)

        assert models.TranslationHistory.objects.count() == 2
        actions = set(models.TranslationHistory.objects.values_list("action", flat=True))
        assert actions == {"delete"}

    def test_history_includes_old_value(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")

        qs = models.TranslationEntry.objects.qs.all()
        services.delete_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.old_value == '{"0": "Hi"}'
        assert h.new_value == ""
        assert h.msgid == "hello"

    def test_bumps_catalog_version(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="")

        initial_version = test_backend._version
        qs = models.TranslationEntry.objects.qs.all()
        services.delete_entries(queryset=qs)

        assert test_backend._version == initial_version + 1

    def test_empty_queryset_returns_zero(self, test_backend: "TestBackend"):
        qs = models.TranslationEntry.objects.qs.none()
        initial_version = test_backend._version

        count = services.delete_entries(queryset=qs)

        assert count == 0
        assert models.TranslationHistory.objects.count() == 0
        assert test_backend._version == initial_version

    def test_preserves_context_in_history(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="greeting"
        )

        qs = models.TranslationEntry.objects.qs.all()
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

    def test_returns_empty_when_table_missing(self):
        error = django.db.OperationalError("no such table: live_translations_translationhistory")
        with unittest.mock.patch.object(models.TranslationHistory.objects, "filter", side_effect=error):
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
    def test_delegates_to_backend(self, test_backend: "TestBackend"):
        # Create inactive entries so bulk_activate has something to activate
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="", is_active=False
        )
        models.TranslationEntry.objects.create(
            language="en", msgid="world", msgstr_forms={"0": "World"}, context="", is_active=False
        )

        keys = [MsgKey("hello", ""), MsgKey("world", "")]
        result = services.bulk_activate(language="en", keys=keys)

        assert result["ok"] is True
        assert result["activated"] == 2

        calls = test_backend.get_calls("bulk_activate")
        assert len(calls) == 1
        args, _ = calls[0]
        assert args == ("en", keys)

    def test_records_history_when_activated(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="", is_active=False
        )

        activated = [MsgKey("hello", "")]
        services.bulk_activate(language="en", keys=activated)

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"
        assert h.language == "en"
        assert h.msgid == "hello"

    def test_no_history_when_nothing_activated(self, test_backend: "TestBackend"):
        # No inactive entries exist, so nothing to activate
        result = services.bulk_activate(language="en", keys=[MsgKey("hello", "")])

        assert result["activated"] == 0
        assert models.TranslationHistory.objects.count() == 0


# ---------------------------------------------------------------------------
# activate_entries / deactivate_entries
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestActivateEntries:
    def test_activates_inactive_entries(self, test_backend: "TestBackend"):
        e1 = models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=False
        )
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr_forms={"0": "M2"}, is_active=False
        )

        qs = models.TranslationEntry.objects.qs.all()
        count = services.activate_entries(queryset=qs)

        assert count == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is True
        assert e2.is_active is True

    def test_skips_already_active(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True)

        qs = models.TranslationEntry.objects.qs.all()
        count = services.activate_entries(queryset=qs)

        assert count == 0

    def test_records_history(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr_forms={"0": "M1"}, context="", is_active=False
        )

        qs = models.TranslationEntry.objects.qs.all()
        services.activate_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"

    def test_bumps_catalog_version(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=False)

        initial_version = test_backend._version
        qs = models.TranslationEntry.objects.qs.all()
        services.activate_entries(queryset=qs)

        assert test_backend._version == initial_version + 1

    def test_no_bump_when_nothing_updated(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True)

        initial_version = test_backend._version
        qs = models.TranslationEntry.objects.qs.all()
        services.activate_entries(queryset=qs)

        assert test_backend._version == initial_version

    def test_mixed_active_inactive(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True)
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr_forms={"0": "M2"}, is_active=False
        )

        qs = models.TranslationEntry.objects.qs.all()
        count = services.activate_entries(queryset=qs)

        assert count == 1
        e2.refresh_from_db()
        assert e2.is_active is True


@pytest.mark.django_db
class TestDeactivateEntries:
    def test_deactivates_active_entries(self, test_backend: "TestBackend"):
        e1 = models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True
        )
        e2 = models.TranslationEntry.objects.create(
            language="en", msgid="msg2", msgstr_forms={"0": "M2"}, is_active=True
        )

        qs = models.TranslationEntry.objects.qs.all()
        count = services.deactivate_entries(queryset=qs)

        assert count == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is False
        assert e2.is_active is False

    def test_skips_already_inactive(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=False)

        qs = models.TranslationEntry.objects.qs.all()
        count = services.deactivate_entries(queryset=qs)

        assert count == 0

    def test_records_history(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="msg1", msgstr_forms={"0": "M1"}, context="", is_active=True
        )

        qs = models.TranslationEntry.objects.qs.all()
        services.deactivate_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.action == "deactivate"
        assert h.old_value == "active"
        assert h.new_value == "inactive"

    def test_bumps_catalog_version(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=True)

        initial_version = test_backend._version
        qs = models.TranslationEntry.objects.qs.all()
        services.deactivate_entries(queryset=qs)

        assert test_backend._version == initial_version + 1

    def test_no_bump_when_nothing_updated(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr_forms={"0": "M1"}, is_active=False)

        initial_version = test_backend._version
        qs = models.TranslationEntry.objects.qs.all()
        services.deactivate_entries(queryset=qs)

        assert test_backend._version == initial_version


# ---------------------------------------------------------------------------
# compute_display
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeDisplay:
    def test_active_entry_returns_msgstr(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="", is_active=True
        )

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Hi"
        assert result["is_preview_entry"] is False

    def test_inactive_entry_returns_default(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Hi"}, context="", is_active=False
        )
        test_backend.seed_default("en", "hello", "Default Hello")

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Default Hello"
        assert result["is_preview_entry"] is False

    def test_preview_shows_inactive_entry(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Preview Text"}, context="", is_active=False
        )

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["text"] == "Preview Text"
        assert result["is_preview_entry"] is True

    def test_preview_active_entry_not_marked_as_preview(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr_forms={"0": "Active Text"}, context="", is_active=True
        )

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["text"] == "Active Text"
        assert result["is_preview_entry"] is False

    def test_no_entry_returns_default(self, test_backend: "TestBackend"):
        test_backend.seed_default("en", "hello", "Default Text")

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Default Text"
        assert result["is_preview_entry"] is False

    def test_no_entry_no_default_returns_empty(self, test_backend: "TestBackend"):
        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == ""

    def test_uses_page_language(self, test_backend: "TestBackend"):
        models.TranslationEntry.objects.create(
            language="cs", msgid="hello", msgstr_forms={"0": "Ahoj"}, context="", is_active=True
        )

        result = services.compute_display(key=MsgKey("hello", ""), page_language="cs")

        assert result["text"] == "Ahoj"

        calls = test_backend.get_calls("get_translations")
        # Last call should be with ["cs"]
        last_args, _ = calls[-1]
        assert last_args == (MsgKey("hello", ""), ["cs"])

    def test_falls_back_to_django_language(self, test_backend: "TestBackend"):
        with django.utils.translation.override("cs"):
            services.compute_display(key=MsgKey("hello", ""), page_language="")

        calls = test_backend.get_calls("get_translations")
        last_args, _ = calls[-1]
        assert last_args == (MsgKey("hello", ""), ["cs"])

    def test_falls_back_to_first_configured_language(self, test_backend: "TestBackend", settings):
        settings.LIVE_TRANSLATIONS["LANGUAGES"] = ["de", "en"]

        from live_translations import conf

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        # Cache was cleared, so conf creates a new backend instance
        backend: TestBackend = conf.get_backend_instance()  # type: ignore[assignment]

        django.utils.translation.deactivate_all()
        services.compute_display(key=MsgKey("hello", ""), page_language="")

        calls = backend.get_calls("get_translations")
        last_args, _ = calls[-1]
        assert last_args == (MsgKey("hello", ""), ["de"])

    def test_preview_with_no_entry_not_marked(self, test_backend: "TestBackend"):
        test_backend.seed_default("en", "hello", "Default")

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["is_preview_entry"] is False


# ---------------------------------------------------------------------------
# get_default
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetDefault:
    def test_delegates_to_backend(self, test_backend: "TestBackend"):
        test_backend.seed_default("en", "hello", "Default Hello")

        result = services.get_default(key=MsgKey("hello", ""), language="en")

        assert result == {0: "Default Hello"}

        calls = test_backend.get_calls("get_defaults")
        assert len(calls) >= 1
        args, _ = calls[-1]
        assert args == (MsgKey("hello", ""), ["en"])

    def test_returns_empty_when_no_default(self, test_backend: "TestBackend"):
        result = services.get_default(key=MsgKey("hello", ""), language="en")

        assert result == {0: ""}


# ---------------------------------------------------------------------------
# HTML content preservation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHtmlContentPreservation:
    """Verify that HTML tags in translations survive the save/retrieve round-trip unchanged."""

    HTML_STRINGS = [
        "Click <strong>here</strong> to continue",
        'Visit <a href="https://example.com">our site</a> for details',
        "Use <em>italic</em> and <strong>bold</strong> together",
        "Line one<br>line two<br/>line three",
        '<span class="highlight">Important</span> notice',
        "Nested <strong><em>bold italic</em></strong> text",
        "Special chars &amp; entities &lt;not tags&gt; preserved",
    ]

    @pytest.mark.parametrize("html_value", HTML_STRINGS)
    def test_save_and_retrieve_preserves_html(self, test_backend: "TestBackend", html_value: str):
        key = MsgKey("html.test", "")
        services.save_translations(key=key, translations={"en": {0: html_value}}, active_flags={"en": True})

        result = services.get_translations(key=key)
        assert result["translations"]["en"]["msgstr_forms"] == {0: html_value}

    @pytest.mark.parametrize("html_value", HTML_STRINGS)
    def test_compute_display_preserves_html(self, test_backend: "TestBackend", html_value: str):
        key = MsgKey("html.test", "")
        services.save_translations(key=key, translations={"en": {0: html_value}}, active_flags={"en": True})

        display = services.compute_display(key=key, page_language="en")
        assert display["text"] == html_value

    def test_html_default_preserved_through_get(self, test_backend: "TestBackend"):
        key = MsgKey("html.default", "")
        test_backend.seed_default("en", "html.default", "Default with <strong>bold</strong> text")

        result = services.get_translations(key=key)
        assert result["translations"]["en"]["msgstr_forms"] == {0: "Default with <strong>bold</strong> text"}

    def test_html_override_replaces_html_default(self, test_backend: "TestBackend"):
        key = MsgKey("html.override", "")
        test_backend.seed_default("en", "html.override", "Old <em>emphasis</em>")
        services.save_translations(
            key=key, translations={"en": {0: "New <strong>bold</strong>"}}, active_flags={"en": True}
        )

        display = services.compute_display(key=key, page_language="en")
        assert display["text"] == "New <strong>bold</strong>"
