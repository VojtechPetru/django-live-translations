"""Permission check callables for use in test settings via DI."""

import django.http

__all__ = ["allow_all", "deny_all"]


def allow_all(request: django.http.HttpRequest) -> bool:
    return True


def deny_all(request: django.http.HttpRequest) -> bool:
    return False
