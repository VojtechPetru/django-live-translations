from django.urls import path

from . import views

app_name = "live_translations"

urlpatterns = [
    path("translations/", views.get_translations, name="get_translations"),
    path("translations/save/", views.save_translations, name="save_translations"),
]
