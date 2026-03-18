"""Minimal URL configuration for unit tests that need URL resolution (e.g. admin path detection)."""

import django.contrib.admin
import django.urls

urlpatterns = [
    django.urls.path("admin/", django.contrib.admin.site.urls),
]
