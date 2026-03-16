import django.http
import django.shortcuts
import django.utils.translation

from demo.forms import FeedbackForm

# Module-level lazy string — evaluated at render time, not import time.
PAGE_DESCRIPTION = django.utils.translation.gettext_lazy("demo.description")


def home(request: django.http.HttpRequest) -> django.http.HttpResponse:
    context = {
        "welcome_message": django.utils.translation.gettext("demo.welcome"),
        "page_description": PAGE_DESCRIPTION,
        "tooltip_text": django.utils.translation.gettext("attrs.tooltip_gettext"),
        "current_language": request.LANGUAGE_CODE,
        "form": FeedbackForm(),
    }
    return django.shortcuts.render(request, "demo/home.html", context)
