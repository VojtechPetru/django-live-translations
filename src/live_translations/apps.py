import typing as t

from django.apps import AppConfig
from django.core.checks import Error, register


class LiveTranslationsConfig(AppConfig):
    name: str = "live_translations"
    verbose_name: str = "Live Translations"
    default_auto_field: str = "django.db.models.BigAutoField"

    @t.override
    def ready(self) -> None:
        _register_checks()
        _patch_gettext()


def _register_checks() -> None:
    @register("live_translations")
    def check_settings(app_configs: t.Any, **kwargs: t.Any) -> list[Error]:
        from .conf import get_conf

        errors: list[Error] = []
        conf = get_conf()

        if not conf.languages:
            errors.append(
                Error(
                    "LIVE_TRANSLATIONS['LANGUAGES'] is empty and settings.LANGUAGES is not set.",
                    hint="Set LIVE_TRANSLATIONS['LANGUAGES'] to a list of language codes.",
                    id="live_translations.E001",
                )
            )

        return errors


def _patch_gettext() -> None:
    from .strings import install_gettext_patch

    install_gettext_patch()
