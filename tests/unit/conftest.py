import json
import pathlib
import typing as t

import django
import django.conf
import django.test
import polib
import pytest

if t.TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

    from live_translations.backends import db
    from tests.backends import InMemoryBackend  # type: ignore[import-not-found]

from live_translations import conf


def pytest_configure() -> None:
    django.conf.settings.configure(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "django.contrib.admin",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "live_translations",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "OPTIONS": {
                    "context_processors": [
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            },
        ],
        STATIC_URL="/static/",
        USE_TZ=True,
    )
    django.setup()


@pytest.fixture(autouse=True)
def _clear_conf_caches():
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()
    yield
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()


@pytest.fixture
def make_db_backend(tmp_path: pathlib.Path):
    """Factory that creates a DatabaseBackend with real (optionally populated) .po files."""

    def _factory(
        *,
        defaults: dict[str, dict[str, str]] | None = None,
    ) -> "db.DatabaseBackend":
        locale_dir = tmp_path / "locale"
        # Always ensure at least an empty locale dir structure
        if defaults:
            for lang in defaults:
                lc = locale_dir / lang / "LC_MESSAGES"
                lc.mkdir(parents=True, exist_ok=True)
                po = polib.POFile()
                po.metadata = {"Content-Type": "text/plain; charset=utf-8"}
                for msgid, msgstr in defaults[lang].items():
                    po.append(polib.POEntry(msgid=msgid, msgstr=msgstr))
                po.save(str(lc / "django.po"))
        from live_translations.backends import db as db_mod

        return db_mod.DatabaseBackend(locale_dir=locale_dir, domain="django")

    return _factory


@pytest.fixture
def make_request():
    def _make(
        method: t.Literal["get", "post"],
        path: str,
        *,
        data: dict | None = None,
        raw_body: bytes | None = None,
        has_permission: bool = True,
        anonymous: bool = False,
        user: "AbstractBaseUser | None" = None,
    ):
        factory = django.test.RequestFactory(enforce_csrf_checks=False)
        if method == "get":
            request = factory.get(path, data or {})
        elif raw_body is not None:
            request = factory.post(path, data=raw_body, content_type="application/json")
            request._dont_enforce_csrf_checks = True  # type: ignore[missing-attribute]
        else:
            request = factory.post(path, data=json.dumps(data or {}), content_type="application/json")
            request._dont_enforce_csrf_checks = True  # type: ignore[missing-attribute]

        if anonymous:
            from django.contrib.auth.models import AnonymousUser

            request.user = AnonymousUser()
        elif user is not None:
            request.user = user  # type: ignore[assignment]
        else:
            from django.contrib.auth.models import User

            request.user = User(  # type: ignore[assignment]
                username="testuser",
                is_active=True,
                is_staff=has_permission,
                is_superuser=has_permission,
            )
        return request

    return _make


@pytest.fixture
def in_memory_backend(settings) -> "InMemoryBackend":
    """Configure InMemoryBackend via Django settings and return the instance."""
    settings.LIVE_TRANSLATIONS = {
        "BACKEND": "tests.backends.InMemoryBackend",
        "LANGUAGES": ["en", "cs"],
        "LOCALE_DIR": "/tmp",
        "PERMISSION_CHECK": "tests.permissions.allow_all",
    }
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()
    backend = conf.get_backend_instance()
    assert type(backend).__name__ == "InMemoryBackend"
    return backend  # type: ignore[return-value]
