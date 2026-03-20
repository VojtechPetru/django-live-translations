"""Permission check callables for use in test settings via DI."""

import django.http

from live_translations.types import PermissionResult

__all__ = ["allow_all", "allow_en_cs", "allow_es_only", "deny_all"]


def allow_all(request: django.http.HttpRequest) -> bool:
    return True


def deny_all(request: django.http.HttpRequest) -> bool:
    return False


def allow_es_only(request: django.http.HttpRequest) -> PermissionResult:
    return {"es"}


def allow_en_cs(request: django.http.HttpRequest) -> PermissionResult:
    return {"en", "cs"}
