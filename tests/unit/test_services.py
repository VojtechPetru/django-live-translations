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
    from tests.backends import InMemoryBackend  # type: ignore[import-not-found]

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

    def test_returns_translations_dict(self, in_memory_backend: "InMemoryBackend"):
        in_memory_backend.seed_default("en", "hello", "Hello")
        in_memory_backend.seed_default("cs", "hello", "")
        in_memory_backend.seed_hint("hello", "A greeting")

        # Create a DB override for "en" (explicitly active)
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hello", context="", is_active=True)

        result = services.get_translations(key=MsgKey("hello", ""))

        assert result["msgid"] == "hello"
        assert result["context"] == ""
        assert result["hint"] == "A greeting"
        assert "en" in result["translations"]
        assert result["translations"]["en"]["msgstr"] == "Hello"
        assert result["translations"]["en"]["is_active"] is True
        assert result["defaults"] == {"en": "Hello", "cs": ""}

    def test_passes_all_languages_to_backend(self, in_memory_backend: "InMemoryBackend", settings):
        settings.LIVE_TRANSLATIONS["LANGUAGES"] = ["en", "cs", "de"]

        from live_translations import conf

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        # Cache was cleared, so conf creates a new backend instance
        backend: InMemoryBackend = conf.get_backend_instance()  # type: ignore[assignment]
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
            services.save_translations(key=MsgKey("", ""), translations={"en": "Hi"})

    def test_empty_translations_raises(self):
        with pytest.raises(ValueError, match="translations dict is required"):
            services.save_translations(key=MsgKey("hello", ""), translations={})

    def test_invalid_language_raises(self, in_memory_backend: "InMemoryBackend"):
        with pytest.raises(ValueError, match="Invalid language codes: xx"):
            services.save_translations(key=MsgKey("hello", ""), translations={"xx": "Nope"})

    def test_multiple_invalid_languages(self, in_memory_backend: "InMemoryBackend"):
        with pytest.raises(ValueError, match="Invalid language codes:"):
            services.save_translations(key=MsgKey("hello", ""), translations={"xx": "A", "yy": "B"})

    def test_placeholder_mismatch_raises(self, in_memory_backend: "InMemoryBackend"):
        with pytest.raises(services.PlaceholderValidationError) as exc_info:
            services.save_translations(key=MsgKey("Hello %s", ""), translations={"en": "Hi"})

        assert "en" in exc_info.value.details

    def test_successful_save(self, in_memory_backend: "InMemoryBackend"):
        result = services.save_translations(key=MsgKey("hello", ""), translations={"en": "Hi"})

        assert result["ok"] is True
        assert "display" in result

        calls = in_memory_backend.get_calls("save_translations")
        assert len(calls) == 1

    def test_passes_active_flags(self, in_memory_backend: "InMemoryBackend"):
        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"en": "Hi"},
            active_flags={"en": True},
        )

        calls = in_memory_backend.get_calls("save_translations")
        assert len(calls) == 1
        _, kwargs = calls[0]
        assert kwargs["active_flags"]["en"] is True

    def test_none_active_flags_passes_empty_dict(self, in_memory_backend: "InMemoryBackend"):
        services.save_translations(key=MsgKey("hello", ""), translations={"en": "Hi"})

        calls = in_memory_backend.get_calls("save_translations")
        assert len(calls) == 1
        _, kwargs = calls[0]
        assert kwargs["active_flags"] == {}

    def test_draft_language_forced_active(self, in_memory_backend: "InMemoryBackend", settings):
        """Draft languages are always saved as active, regardless of the flag sent."""
        settings.LANGUAGES = [("en", "English")]

        from live_translations import conf

        conf.get_settings.cache_clear()

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"cs": "Ahoj"},
            active_flags={"cs": False},
        )

        calls = in_memory_backend.get_calls("save_translations")
        _, kwargs = calls[0]
        assert kwargs["active_flags"]["cs"] is True

    def test_draft_forced_active_preserves_published_flags(self, in_memory_backend: "InMemoryBackend", settings):
        """Forcing active for draft languages doesn't affect published language flags."""
        settings.LANGUAGES = [("en", "English")]

        from live_translations import conf

        conf.get_settings.cache_clear()

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"en": "Hi", "cs": "Ahoj"},
            active_flags={"en": False, "cs": False},
        )

        calls = in_memory_backend.get_calls("save_translations")
        _, kwargs = calls[0]
        flags = kwargs["active_flags"]
        assert flags["en"] is False  # published: respects the flag
        assert flags["cs"] is True  # draft: forced active

    def test_draft_forced_active_with_none_flags(self, in_memory_backend: "InMemoryBackend", settings):
        """When active_flags is None (default), draft languages still get forced to True."""
        settings.LANGUAGES = [("en", "English")]

        from live_translations import conf

        conf.get_settings.cache_clear()

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"cs": "Ahoj"},
        )

        calls = in_memory_backend.get_calls("save_translations")
        _, kwargs = calls[0]
        assert kwargs["active_flags"] == {"cs": True}

    def test_multiple_draft_languages_forced_active(self, in_memory_backend: "InMemoryBackend", settings):
        """All draft languages are forced active in a single save call."""
        settings.LANGUAGES = [("en", "English")]
        settings.LIVE_TRANSLATIONS["LANGUAGES"] = ["en", "ja", "ko"]

        from live_translations import conf

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        # Cache was cleared, so conf creates a new backend instance
        backend: InMemoryBackend = conf.get_backend_instance()  # type: ignore[assignment]

        services.save_translations(
            key=MsgKey("hello", ""),
            translations={"ja": "Konnichiwa", "ko": "Annyeong"},
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
    def test_deletes_all_languages(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="")

        result = services.delete_translations(key=MsgKey("hello", ""))

        assert result["ok"] is True
        assert result["deleted"] == 2
        assert models.TranslationEntry.objects.count() == 0

    def test_deletes_specific_languages(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="")

        result = services.delete_translations(key=MsgKey("hello", ""), languages=["cs"])

        assert result["deleted"] == 1
        assert models.TranslationEntry.objects.count() == 1
        remaining = models.TranslationEntry.objects.first()
        assert remaining is not None
        assert remaining.language == "en"

    def test_records_history(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        services.delete_translations(key=MsgKey("hello", ""))

        h = models.TranslationHistory.objects.get()
        assert h.action == "delete"
        assert h.old_value == "Hi"
        assert h.new_value == ""

    def test_bumps_catalog_version(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        initial_version = in_memory_backend._version
        services.delete_translations(key=MsgKey("hello", ""))

        assert in_memory_backend._version == initial_version + 1

    def test_no_entries_no_history_no_bump(self, in_memory_backend: "InMemoryBackend"):
        initial_version = in_memory_backend._version
        result = services.delete_translations(key=MsgKey("hello", ""))

        assert result["deleted"] == 0
        assert models.TranslationHistory.objects.count() == 0
        assert in_memory_backend._version == initial_version

    def test_returns_display(self, in_memory_backend: "InMemoryBackend"):
        in_memory_backend.seed_default("en", "hello", "Default")

        result = services.delete_translations(key=MsgKey("hello", ""), page_language="en")

        assert "display" in result
        assert result["display"]["text"] == "Default"


# ---------------------------------------------------------------------------
# delete_entries (batch admin delete)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteEntries:
    def test_deletes_entries(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="")

        qs = models.TranslationEntry.objects.all()
        count = services.delete_entries(queryset=qs)

        assert count == 2
        assert models.TranslationEntry.objects.count() == 0

    def test_records_history_per_entry(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")
        models.TranslationEntry.objects.create(language="cs", msgid="world", msgstr="Svet", context="ctx")

        qs = models.TranslationEntry.objects.all()
        services.delete_entries(queryset=qs)

        assert models.TranslationHistory.objects.count() == 2
        actions = set(models.TranslationHistory.objects.values_list("action", flat=True))
        assert actions == {"delete"}

    def test_history_includes_old_value(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        qs = models.TranslationEntry.objects.all()
        services.delete_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.old_value == "Hi"
        assert h.new_value == ""
        assert h.msgid == "hello"

    def test_bumps_catalog_version(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="")

        initial_version = in_memory_backend._version
        qs = models.TranslationEntry.objects.all()
        services.delete_entries(queryset=qs)

        assert in_memory_backend._version == initial_version + 1

    def test_empty_queryset_returns_zero(self, in_memory_backend: "InMemoryBackend"):
        qs = models.TranslationEntry.objects.none()
        initial_version = in_memory_backend._version

        count = services.delete_entries(queryset=qs)

        assert count == 0
        assert models.TranslationHistory.objects.count() == 0
        assert in_memory_backend._version == initial_version

    def test_preserves_context_in_history(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="greeting")

        qs = models.TranslationEntry.objects.all()
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
    def test_delegates_to_backend(self, in_memory_backend: "InMemoryBackend"):
        # Create inactive entries so bulk_activate has something to activate
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="", is_active=False)
        models.TranslationEntry.objects.create(
            language="en", msgid="world", msgstr="World", context="", is_active=False
        )

        keys = [MsgKey("hello", ""), MsgKey("world", "")]
        result = services.bulk_activate(language="en", keys=keys)

        assert result["ok"] is True
        assert result["activated"] == 2

        calls = in_memory_backend.get_calls("bulk_activate")
        assert len(calls) == 1
        args, _ = calls[0]
        assert args == ("en", keys)

    def test_records_history_when_activated(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="", is_active=False)

        activated = [MsgKey("hello", "")]
        services.bulk_activate(language="en", keys=activated)

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"
        assert h.language == "en"
        assert h.msgid == "hello"

    def test_no_history_when_nothing_activated(self, in_memory_backend: "InMemoryBackend"):
        # No inactive entries exist, so nothing to activate
        result = services.bulk_activate(language="en", keys=[MsgKey("hello", "")])

        assert result["activated"] == 0
        assert models.TranslationHistory.objects.count() == 0


# ---------------------------------------------------------------------------
# activate_entries / deactivate_entries
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestActivateEntries:
    def test_activates_inactive_entries(self, in_memory_backend: "InMemoryBackend"):
        e1 = models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)
        e2 = models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr="M2", is_active=False)

        qs = models.TranslationEntry.objects.all()
        count = services.activate_entries(queryset=qs)

        assert count == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is True
        assert e2.is_active is True

    def test_skips_already_active(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)

        qs = models.TranslationEntry.objects.all()
        count = services.activate_entries(queryset=qs)

        assert count == 0

    def test_records_history(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", context="", is_active=False)

        qs = models.TranslationEntry.objects.all()
        services.activate_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.action == "activate"
        assert h.old_value == "inactive"
        assert h.new_value == "active"

    def test_bumps_catalog_version(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)

        initial_version = in_memory_backend._version
        qs = models.TranslationEntry.objects.all()
        services.activate_entries(queryset=qs)

        assert in_memory_backend._version == initial_version + 1

    def test_no_bump_when_nothing_updated(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)

        initial_version = in_memory_backend._version
        qs = models.TranslationEntry.objects.all()
        services.activate_entries(queryset=qs)

        assert in_memory_backend._version == initial_version

    def test_mixed_active_inactive(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)
        e2 = models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr="M2", is_active=False)

        qs = models.TranslationEntry.objects.all()
        count = services.activate_entries(queryset=qs)

        assert count == 1
        e2.refresh_from_db()
        assert e2.is_active is True


@pytest.mark.django_db
class TestDeactivateEntries:
    def test_deactivates_active_entries(self, in_memory_backend: "InMemoryBackend"):
        e1 = models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)
        e2 = models.TranslationEntry.objects.create(language="en", msgid="msg2", msgstr="M2", is_active=True)

        qs = models.TranslationEntry.objects.all()
        count = services.deactivate_entries(queryset=qs)

        assert count == 2
        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.is_active is False
        assert e2.is_active is False

    def test_skips_already_inactive(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)

        qs = models.TranslationEntry.objects.all()
        count = services.deactivate_entries(queryset=qs)

        assert count == 0

    def test_records_history(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", context="", is_active=True)

        qs = models.TranslationEntry.objects.all()
        services.deactivate_entries(queryset=qs)

        h = models.TranslationHistory.objects.get()
        assert h.action == "deactivate"
        assert h.old_value == "active"
        assert h.new_value == "inactive"

    def test_bumps_catalog_version(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=True)

        initial_version = in_memory_backend._version
        qs = models.TranslationEntry.objects.all()
        services.deactivate_entries(queryset=qs)

        assert in_memory_backend._version == initial_version + 1

    def test_no_bump_when_nothing_updated(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="msg1", msgstr="M1", is_active=False)

        initial_version = in_memory_backend._version
        qs = models.TranslationEntry.objects.all()
        services.deactivate_entries(queryset=qs)

        assert in_memory_backend._version == initial_version


# ---------------------------------------------------------------------------
# compute_display
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestComputeDisplay:
    def test_active_entry_returns_msgstr(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="", is_active=True)

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Hi"
        assert result["is_preview_entry"] is False

    def test_inactive_entry_returns_default(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="en", msgid="hello", msgstr="Hi", context="", is_active=False)
        in_memory_backend.seed_default("en", "hello", "Default Hello")

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Default Hello"
        assert result["is_preview_entry"] is False

    def test_preview_shows_inactive_entry(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Preview Text", context="", is_active=False
        )

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["text"] == "Preview Text"
        assert result["is_preview_entry"] is True

    def test_preview_active_entry_not_marked_as_preview(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(
            language="en", msgid="hello", msgstr="Active Text", context="", is_active=True
        )

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["text"] == "Active Text"
        assert result["is_preview_entry"] is False

    def test_no_entry_returns_default(self, in_memory_backend: "InMemoryBackend"):
        in_memory_backend.seed_default("en", "hello", "Default Text")

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == "Default Text"
        assert result["is_preview_entry"] is False

    def test_no_entry_no_default_returns_empty(self, in_memory_backend: "InMemoryBackend"):
        result = services.compute_display(key=MsgKey("hello", ""), page_language="en")

        assert result["text"] == ""

    def test_uses_page_language(self, in_memory_backend: "InMemoryBackend"):
        models.TranslationEntry.objects.create(language="cs", msgid="hello", msgstr="Ahoj", context="", is_active=True)

        result = services.compute_display(key=MsgKey("hello", ""), page_language="cs")

        assert result["text"] == "Ahoj"

        calls = in_memory_backend.get_calls("get_translations")
        # Last call should be with ["cs"]
        last_args, _ = calls[-1]
        assert last_args == (MsgKey("hello", ""), ["cs"])

    def test_falls_back_to_django_language(self, in_memory_backend: "InMemoryBackend"):
        with django.utils.translation.override("cs"):
            services.compute_display(key=MsgKey("hello", ""), page_language="")

        calls = in_memory_backend.get_calls("get_translations")
        last_args, _ = calls[-1]
        assert last_args == (MsgKey("hello", ""), ["cs"])

    def test_falls_back_to_first_configured_language(self, in_memory_backend: "InMemoryBackend", settings):
        settings.LIVE_TRANSLATIONS["LANGUAGES"] = ["de", "en"]

        from live_translations import conf

        conf.get_settings.cache_clear()
        conf.get_backend_instance.cache_clear()

        # Cache was cleared, so conf creates a new backend instance
        backend: InMemoryBackend = conf.get_backend_instance()  # type: ignore[assignment]

        django.utils.translation.deactivate_all()
        services.compute_display(key=MsgKey("hello", ""), page_language="")

        calls = backend.get_calls("get_translations")
        last_args, _ = calls[-1]
        assert last_args == (MsgKey("hello", ""), ["de"])

    def test_preview_with_no_entry_not_marked(self, in_memory_backend: "InMemoryBackend"):
        in_memory_backend.seed_default("en", "hello", "Default")

        result = services.compute_display(key=MsgKey("hello", ""), page_language="en", is_preview=True)

        assert result["is_preview_entry"] is False


# ---------------------------------------------------------------------------
# get_default
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetDefault:
    def test_delegates_to_backend(self, in_memory_backend: "InMemoryBackend"):
        in_memory_backend.seed_default("en", "hello", "Default Hello")

        result = services.get_default(key=MsgKey("hello", ""), language="en")

        assert result == "Default Hello"

        calls = in_memory_backend.get_calls("get_defaults")
        assert len(calls) >= 1
        args, _ = calls[-1]
        assert args == (MsgKey("hello", ""), ["en"])

    def test_returns_empty_when_no_default(self, in_memory_backend: "InMemoryBackend"):
        result = services.get_default(key=MsgKey("hello", ""), language="en")

        assert result == ""
