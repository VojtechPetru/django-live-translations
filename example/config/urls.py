import django.conf.urls.i18n
import django.contrib.admin
import django.urls
from demo import views
from django.conf.urls.i18n import i18n_patterns

urlpatterns = [
    django.urls.path("i18n/", django.urls.include(django.conf.urls.i18n)),
]

urlpatterns += i18n_patterns(
    django.urls.path("admin/", django.contrib.admin.site.urls),
    django.urls.path("", views.home, name="home"),
)
