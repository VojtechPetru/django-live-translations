import django.contrib.auth
import django.contrib.auth.models
import django.http
import django.shortcuts
import django.utils.translation
import django.views.decorators.http

from demo.forms import FeedbackForm

# Module-level lazy string — evaluated at render time, not import time.
PAGE_DESCRIPTION = django.utils.translation.gettext_lazy("demo.description")

# Numbers that exercise interesting plural forms per language.
# English (2 forms): 1=singular, rest=plural
# Czech (4 forms): 1=form 0, 2-4=form 1, 5+=form 3
PLURAL_CHOICES_DEFAULT: list[int] = [0, 1, 2, 5]
PLURAL_CHOICES: dict[str, list[int]] = {
    "en": PLURAL_CHOICES_DEFAULT.copy(),
    "cs": [0, 1, 2, 5],
}


DEMO_SUPERUSER_USERNAME = "admin"
DEMO_SUPERUSER_PASSWORD = "admin"


def home(request: django.http.HttpRequest) -> django.http.HttpResponse:
    context = {
        "welcome_message": django.utils.translation.gettext("demo.welcome"),
        "page_description": PAGE_DESCRIPTION,
        "tooltip_text": django.utils.translation.gettext("attrs.tooltip_gettext"),
        "current_language": request.LANGUAGE_CODE,
        "form": FeedbackForm(),
        **_plural_context(request),
    }
    return django.shortcuts.render(request, "demo/home.html", context)


def _plural_context(request: django.http.HttpRequest) -> dict[str, object]:
    n = int(request.GET.get("n", "5")) if request.GET.get("n", "").isdigit() else 5
    ngettext = django.utils.translation.ngettext
    return {
        "plural_choices": PLURAL_CHOICES.get(request.LANGUAGE_CODE, PLURAL_CHOICES_DEFAULT),
        "plural_count": n,
        "litre_message": ngettext(
            "plurals.litre_one %(count)s",
            "plurals.litre_other %(count)s",
            n,
        )
        % {"count": n},
    }


def plurals_partial(request: django.http.HttpRequest) -> django.http.HttpResponse:
    return django.shortcuts.render(request, "demo/_plurals.html", _plural_context(request))


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
