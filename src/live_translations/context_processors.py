"""Template context processor for live translations."""

import typing as t

from django.http import HttpRequest  # noqa: TC002


def live_translations(request: HttpRequest) -> dict[str, t.Any]:
    """Add _live_translations_active flag to template context."""
    return {
        "_live_translations_active": getattr(request, "_live_translations_active", False),
    }
