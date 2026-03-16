import contextlib
import typing as t

import django.apps
import django.conf
import django.core.checks

from live_translations import conf, strings

__all__ = ["LiveTranslationsConfig"]


class LiveTranslationsConfig(django.apps.AppConfig):
    name: str = "live_translations"
    verbose_name: str = "Live Translations"  # type: ignore[bad-override]
    default_auto_field: str = "django.db.models.BigAutoField"

    @t.override
    def ready(self) -> None:
        _register_checks()
        strings.install_gettext_patch()


def _register_checks() -> None:
    @django.core.checks.register("live_translations")
    def check_settings(
        *,
        app_configs: t.Sequence[django.apps.AppConfig] | None,
        databases: t.Sequence[str] | None = None,
        **kwargs: object,
    ) -> list[django.core.checks.CheckMessage]:
        errors: list[django.core.checks.CheckMessage] = []

        raw: object = getattr(django.conf.settings, "LIVE_TRANSLATIONS", {})
        if isinstance(raw, dict):
            valid_keys = set(conf.LiveTranslationsSettings.__annotations__)
            extra_keys = set(raw) - valid_keys
            if extra_keys:
                errors.append(
                    django.core.checks.Warning(
                        f"Unknown key(s) in LIVE_TRANSLATIONS: {', '.join(sorted(extra_keys))}.",
                        hint=(
                            "Valid keys are: "
                            + ", ".join(sorted(valid_keys))
                            + ". \n          Use the LiveTranslationsSettings TypedDict as a type hint"
                            " for your LIVE_TRANSLATIONS setting to catch invalid keys:\n"
                            '\n          LIVE_TRANSLATIONS: "LiveTranslationsSettings" = {...}'
                        ),
                        id="live_translations.W004",
                    )
                )

        settings = conf.get_settings()

        if not settings.languages:
            errors.append(
                django.core.checks.Error(
                    "LIVE_TRANSLATIONS['LANGUAGES'] is empty and settings.LANGUAGES is not set.",
                    hint="Set LIVE_TRANSLATIONS['LANGUAGES'] to a list of language codes.",
                    id="live_translations.E001",
                )
            )

        if "django.contrib.staticfiles" not in django.conf.settings.INSTALLED_APPS:
            errors.append(
                django.core.checks.Warning(
                    "django.contrib.staticfiles is not in INSTALLED_APPS.",
                    hint="Live translations requires static files to serve the editing widget's JS and CSS.",
                    id="live_translations.W001",
                )
            )

        with contextlib.suppress(Exception):
            errors.extend(conf.get_backend_instance().check())

        return errors
