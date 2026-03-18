"""Tests for live_translations.conf — draft language detection."""

import pytest

from live_translations import conf


class TestDraftLanguages:
    """Draft languages: in LIVE_TRANSLATIONS['LANGUAGES'] but not in Django LANGUAGES."""

    def test_draft_detected_from_settings_diff(self, settings):
        settings.LANGUAGES = [("en", "English"), ("cs", "Czech")]
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs", "ja"]}

        result = conf.get_settings()
        assert result.draft_languages == ["ja"]

    def test_no_draft_when_all_published(self, settings):
        settings.LANGUAGES = [("en", "English"), ("cs", "Czech")]
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}

        result = conf.get_settings()
        assert result.draft_languages == []

    def test_no_draft_when_languages_not_set(self, settings):
        """When LT LANGUAGES falls back to Django LANGUAGES, there are no drafts."""
        settings.LANGUAGES = [("en", "English"), ("cs", "Czech")]
        settings.LIVE_TRANSLATIONS = {}

        result = conf.get_settings()
        assert result.languages == ["en", "cs"]
        assert result.draft_languages == []

    def test_all_draft_when_django_languages_empty(self, settings):
        settings.LANGUAGES = []
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["ja", "ko"]}

        result = conf.get_settings()
        assert result.draft_languages == ["ja", "ko"]

    def test_multiple_drafts_preserve_order(self, settings):
        settings.LANGUAGES = [("en", "English")]
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "de", "ja", "ko"]}

        result = conf.get_settings()
        assert result.draft_languages == ["de", "ja", "ko"]

    def test_draft_languages_empty_by_default(self):
        """LiveTranslationsConf default has empty draft_languages."""
        default = conf.LiveTranslationsConf()
        assert default.draft_languages == []


class TestIsDraftLanguage:
    """Helper function is_draft_language()."""

    def test_true_for_draft(self, settings):
        settings.LANGUAGES = [("en", "English")]
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "ja"]}

        assert conf.is_draft_language("ja") is True

    def test_false_for_published(self, settings):
        settings.LANGUAGES = [("en", "English")]
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "ja"]}

        assert conf.is_draft_language("en") is False

    def test_false_for_unknown_code(self, settings):
        settings.LANGUAGES = [("en", "English")]
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}

        assert conf.is_draft_language("xx") is False


class TestDraftLanguagesFallbackToLanguageCode:
    """Edge case: LANGUAGES not set and settings.LANGUAGES empty, fallback to LANGUAGE_CODE."""

    @pytest.fixture(autouse=True)
    def _setup_settings(self, settings):
        settings.LANGUAGES = []
        settings.LANGUAGE_CODE = "en"
        settings.LIVE_TRANSLATIONS = {}

    def test_single_language_from_language_code_is_draft(self):
        """When falling back to LANGUAGE_CODE and LANGUAGES is empty, the single code is draft."""
        result = conf.get_settings()
        assert result.languages == ["en"]
        # "en" is not in settings.LANGUAGES (which is []), so it's technically draft
        assert result.draft_languages == ["en"]
