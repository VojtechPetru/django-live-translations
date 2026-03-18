import json
import pathlib
import typing as t
import unittest.mock

import django
import django.conf
import django.test
import pytest

if t.TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

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
def make_db_backend():
    """Factory that creates a DatabaseBackend with a mocked PO backend (no .po files needed)."""
    from live_translations.backends import db

    def _factory() -> db.DatabaseBackend:
        backend = db.DatabaseBackend(locale_dir=pathlib.Path("/tmp"), domain="django")
        mock_po = unittest.mock.MagicMock()
        mock_po.get_translations.return_value = {}
        mock_po.get_hint.return_value = ""
        backend._po_backend = mock_po
        return backend

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
            request.user = unittest.mock.MagicMock(is_authenticated=has_permission, is_superuser=has_permission)
        return request

    return _make
