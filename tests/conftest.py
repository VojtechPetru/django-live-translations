import django
import django.conf


def pytest_configure() -> None:
    django.conf.settings.configure(
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "live_translations",
        ],
        USE_TZ=True,
    )
    django.setup()
