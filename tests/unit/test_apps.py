"""Tests for system checks registered by LiveTranslationsConfig (live_translations.apps)."""

import unittest.mock

import django.core.checks


def _run_checks() -> list[django.core.checks.CheckMessage]:
    return django.core.checks.run_checks(tags=["live_translations"])


def _ids(messages: list[django.core.checks.CheckMessage]) -> list[str | None]:
    return [m.id for m in messages]


# ---------------------------------------------------------------------------
# check_settings
# ---------------------------------------------------------------------------


class TestCheckSettings:
    def test_unknown_keys_warning_w004(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"], "BOGUS_KEY": True}
        messages = _run_checks()
        assert "live_translations.W004" in _ids(messages)
        w004 = next(m for m in messages if m.id == "live_translations.W004")
        assert "BOGUS_KEY" in w004.msg

    def test_empty_languages_error_e001(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": []}
        settings.LANGUAGES = []
        settings.LANGUAGE_CODE = ""
        messages = _run_checks()
        assert "live_translations.E001" in _ids(messages)

    def test_missing_staticfiles_w001(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}
        settings.INSTALLED_APPS = [app for app in settings.INSTALLED_APPS if app != "django.contrib.staticfiles"]
        messages = _run_checks()
        assert "live_translations.W001" in _ids(messages)

    def test_backend_check_errors_included(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}
        backend_warning = django.core.checks.Warning("backend issue", id="live_translations.W999")
        mock_backend = unittest.mock.MagicMock()
        mock_backend.check.return_value = [backend_warning]
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            messages = _run_checks()
        assert "live_translations.W999" in _ids(messages)

    def test_backend_check_exception_swallowed(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en"]}
        mock_backend = unittest.mock.MagicMock()
        mock_backend.check.side_effect = RuntimeError("backend exploded")
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            messages = _run_checks()
        # No crash; the RuntimeError is suppressed. Only check no unexpected errors leaked.
        ids = _ids(messages)
        assert "live_translations.E001" not in ids  # languages are set

    def test_valid_config_no_errors(self, settings):
        settings.LIVE_TRANSLATIONS = {"LANGUAGES": ["en", "cs"]}
        mock_backend = unittest.mock.MagicMock()
        mock_backend.check.return_value = []
        with unittest.mock.patch("live_translations.conf.get_backend_instance", return_value=mock_backend):
            messages = _run_checks()
        assert messages == []
