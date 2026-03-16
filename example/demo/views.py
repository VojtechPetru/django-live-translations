import django.contrib.auth
import django.contrib.auth.models
import django.http
import django.shortcuts
import django.utils.translation
import django.views.decorators.http

from demo.forms import FeedbackForm

# Module-level lazy string — evaluated at render time, not import time.
PAGE_DESCRIPTION = django.utils.translation.gettext_lazy("demo.description")

DEMO_SUPERUSER_USERNAME = "admin"
DEMO_SUPERUSER_PASSWORD = "admin"


def home(request: django.http.HttpRequest) -> django.http.HttpResponse:
    context = {
        "welcome_message": django.utils.translation.gettext("demo.welcome"),
        "page_description": PAGE_DESCRIPTION,
        "tooltip_text": django.utils.translation.gettext("attrs.tooltip_gettext"),
        "current_language": request.LANGUAGE_CODE,
        "form": FeedbackForm(),
    }
    return django.shortcuts.render(request, "demo/home.html", context)


@django.views.decorators.http.require_POST
def quick_login(request: django.http.HttpRequest) -> django.http.HttpResponse:
    user, _ = django.contrib.auth.models.User.objects.get_or_create(
        username=DEMO_SUPERUSER_USERNAME,
        defaults={"is_superuser": True, "is_staff": True},
    )
    user.set_password(DEMO_SUPERUSER_PASSWORD)
    user.is_superuser = True
    user.is_staff = True
    user.save()
    django.contrib.auth.login(request, user)
    return django.shortcuts.redirect(request.POST.get("next", "/"))


@django.views.decorators.http.require_POST
def quick_logout(request: django.http.HttpRequest) -> django.http.HttpResponse:
    django.contrib.auth.logout(request)
    return django.shortcuts.redirect(request.POST.get("next", "/"))
