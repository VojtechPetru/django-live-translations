import django.contrib.admin
import django.urls

from demo import views

urlpatterns = [
    django.urls.path("admin/", django.contrib.admin.site.urls),
    django.urls.path("", views.home, name="home"),
]
