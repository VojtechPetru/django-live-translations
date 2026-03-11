import django.http
import django.shortcuts
import django.utils.translation

# Module-level lazy string — evaluated at render time, not import time.
PAGE_DESCRIPTION = django.utils.translation.gettext_lazy(
    "A minimal example app for testing django-live-translations."
)


def home(request: django.http.HttpRequest) -> django.http.HttpResponse:
    context = {
        "welcome_message": django.utils.translation.gettext(
            "Welcome to the demo application!"
        ),
        "page_description": PAGE_DESCRIPTION,
        "tooltip_text": django.utils.translation.gettext(
            "This tooltip was translated with gettext()"
        ),
        "current_language": request.LANGUAGE_CODE,
    }
    return django.shortcuts.render(request, "demo/home.html", context)
