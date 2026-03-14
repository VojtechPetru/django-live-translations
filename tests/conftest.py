import json
import typing as t
import unittest.mock

import django
import django.conf
import django.test
import pytest

from live_translations import conf


def pytest_configure() -> None:
    django.conf.settings.configure(
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "live_translations",
        ],
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


@pytest.fixture()
def make_request():
    def _make(method: t.Literal["get", "post"], path: str, *, data: dict | None = None, has_permission: bool = True):
        factory = django.test.RequestFactory(enforce_csrf_checks=False)
        if method == "get":
            request = factory.get(path, data or {})
        else:
            request = factory.post(path, data=json.dumps(data or {}), content_type="application/json")
            request._dont_enforce_csrf_checks = True
        request.user = unittest.mock.MagicMock(is_authenticated=has_permission, is_superuser=has_permission)
        return request

    return _make
