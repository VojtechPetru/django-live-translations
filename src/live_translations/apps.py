import typing as t

import django.apps
import django.conf
import django.core.checks

from live_translations import conf, strings

__all__ = ["LiveTranslationsConfig"]


class LiveTranslationsConfig(django.apps.AppConfig):
    name: str = "live_translations"
    verbose_name: str = "Live Translations"
    default_auto_field: str = "django.db.models.BigAutoField"

    @t.override
    def ready(self) -> None:
        _register_checks()
        _patch_gettext()
        _patch_i18n_tags()


def _register_checks() -> None:
    @django.core.checks.register("live_translations")
    def check_settings(
        app_configs: t.Any,
        **kwargs: t.Any,
    ) -> list[django.core.checks.Error | django.core.checks.Warning]:
        errors: list[django.core.checks.Error | django.core.checks.Warning] = []

        raw: dict[str, t.Any] = getattr(django.conf.settings, "LIVE_TRANSLATIONS", {})
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

        try:
            errors.extend(conf.get_backend_instance().check())
        except Exception:
            pass

        return errors


def _patch_gettext() -> None:
    strings.install_gettext_patch()


def _patch_i18n_tags() -> None:
    """Override Django's built-in i18n template tags with live translation versions.

    This patches ``django.templatetags.i18n.register.tags`` so that
    ``{% load i18n %}`` automatically provides marker-wrapping versions
    of ``{% trans %}``, ``{% blocktrans %}``, and their aliases.
    """
    import django.templatetags.i18n

    from live_translations.templatetags import live_translations as lt_tags

    django.templatetags.i18n.register.tags["trans"] = lt_tags.do_live_translate
    django.templatetags.i18n.register.tags["translate"] = lt_tags.do_live_translate
    django.templatetags.i18n.register.tags["blocktrans"] = (
        lt_tags.do_live_block_translate
    )
    django.templatetags.i18n.register.tags["blocktranslate"] = (
        lt_tags.do_live_block_translate
    )
