"""Benchmark suite configuration — Django settings, fixtures, and helpers."""

import contextlib
import pathlib
import sys
import typing as t

import django
import django.conf
import django.http
import django.test
import polib
import pytest

from live_translations.types import LanguageCode

if t.TYPE_CHECKING:
    from live_translations.backends.db import DatabaseBackend

# ---------------------------------------------------------------------------
# Django configuration
# ---------------------------------------------------------------------------


def pytest_configure() -> None:
    # Ensure ``tests`` package is importable for dotted-path settings
    # (e.g. ``tests.backends.TestBackend``, ``tests.permissions.allow_all``).
    repo_root = str(pathlib.Path(__file__).resolve().parent.parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    django.conf.settings.configure(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "django.contrib.sessions",
            "django.contrib.staticfiles",
            "live_translations",
        ],
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "live_translations.middleware.LiveTranslationsMiddleware",
        ],
        TEMPLATES=[
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "DIRS": [],
                "OPTIONS": {
                    "context_processors": [],
                    "loaders": [
                        ("django.template.loaders.locmem.Loader", {}),
                    ],
                },
            },
        ],
        STATIC_URL="/static/",
        USE_TZ=True,
        LANGUAGES=[("en", "English"), ("cs", "Czech")],
        LANGUAGE_CODE="en",
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        },
    )
    django.setup()


# ---------------------------------------------------------------------------
# Imports that require django.setup() to have completed
# ---------------------------------------------------------------------------

from live_translations import conf, strings  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCALES: t.Final[list[int]] = [100, 500]
LANGUAGES: t.Final[list[LanguageCode]] = ["en", "cs"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def generate_msgid(index: int) -> str:
    return f"bench.msg_{index:04d}"


def generate_msgstr(index: int, language: LanguageCode = "en") -> str:
    return f"[{language}] Translated message number {index} with some realistic length"


def _split_n(n: int) -> tuple[int, int, int, int, int]:
    """Split n translations into (trans, blocktrans, gettext, gettext_lazy, pgettext) counts.

    Mix: 35% {% trans %}, 15% {% blocktrans %}, 20% gettext(), 20% gettext_lazy(), 10% pgettext().
    """
    n_trans = int(n * 0.35)
    n_blocktrans = int(n * 0.15)
    n_gettext = int(n * 0.20)
    n_lazy = int(n * 0.20)
    n_pgettext = n - n_trans - n_blocktrans - n_gettext - n_lazy
    return n_trans, n_blocktrans, n_gettext, n_lazy, n_pgettext


def generate_template_string(n: int) -> str:
    """Generate a Django template with N translation calls (mixed types).

    Mix: 35% {% trans %}, 15% {% blocktrans %}, 20% gettext(), 20% gettext_lazy(), 10% pgettext().
    Context variables (gettext/lazy/pgettext) are rendered as {{ var_N }}.
    """
    n_trans, n_blocktrans, n_gettext, n_lazy, n_pgettext = _split_n(n)

    lines: list[str] = [
        "{% load i18n %}",
        "<!DOCTYPE html>",
        "<html><head><title>Benchmark</title></head>",
        "<body>",
    ]

    idx = 0
    for _ in range(n_trans):
        msgid = generate_msgid(idx)
        lines.append(f'<div class="item"><p>{{% trans "{msgid}" %}}</p></div>')
        idx += 1

    for _ in range(n_blocktrans):
        msgid = generate_msgid(idx)
        lines.append(f"<section><h3>{{% blocktrans %}}{msgid}{{% endblocktrans %}}</h3></section>")
        idx += 1

    # gettext, gettext_lazy, and pgettext all render via {{ var_N }}
    n_context_var = n_gettext + n_lazy + n_pgettext
    for i in range(n_context_var):
        lines.append(f'<span class="translated">{{{{ var_{idx} }}}}</span>')
        idx += 1

    lines.extend(["</body>", "</html>"])
    return "\n".join(lines)


def generate_template_context(n: int, gettext_fn: t.Callable[[str], str]) -> dict[str, str | object]:
    """Generate template context with a mix of gettext(), gettext_lazy(), and pgettext() values.

    gettext_lazy values are lazy proxy objects that resolve at template render time,
    exercising the patched gettext path during rendering (not during context creation).
    """
    from django.utils.translation import gettext_lazy, pgettext

    n_trans, n_blocktrans, n_gettext, n_lazy, n_pgettext = _split_n(n)
    start_idx = n_trans + n_blocktrans

    context: dict[str, str | object] = {}
    idx = start_idx

    # Eager gettext() — resolved immediately
    for _ in range(n_gettext):
        context[f"var_{idx}"] = gettext_fn(generate_msgid(idx))
        idx += 1

    # Lazy gettext_lazy() — resolved at render time when template calls str()
    for _ in range(n_lazy):
        context[f"var_{idx}"] = gettext_lazy(generate_msgid(idx))
        idx += 1

    # pgettext() — with context string
    for _ in range(n_pgettext):
        context[f"var_{idx}"] = pgettext("bench_ctx", generate_msgid(idx))
        idx += 1

    return context


def generate_po_file(n: int, locale_dir: pathlib.Path, language: LanguageCode) -> pathlib.Path:
    """Generate a .po file with N entries and compile to .mo."""
    po_dir = locale_dir / language / "LC_MESSAGES"
    po_dir.mkdir(parents=True, exist_ok=True)
    po_path = po_dir / "django.po"

    po = polib.POFile()
    po.metadata = {"Content-Type": "text/plain; charset=UTF-8", "Language": language}

    for i in range(n):
        entry = polib.POEntry(msgid=generate_msgid(i), msgstr=generate_msgstr(i, language))
        po.append(entry)

    po.save(str(po_path))
    po.save_as_mofile(str(po_dir / "django.mo"))
    return po_path


def populate_db_overrides(n: int, languages: list[LanguageCode]) -> None:
    """Bulk-create TranslationEntry rows: 80% active, 20% inactive."""
    from live_translations.models import TranslationEntry

    n_active = int(n * 0.8)
    entries: list[TranslationEntry] = []
    for lang in languages:
        for i in range(n):
            entries.append(
                TranslationEntry(
                    language=lang,
                    msgid=generate_msgid(i),
                    context="",
                    msgstr=generate_msgstr(i, lang),
                    is_active=i < n_active,
                )
            )
    TranslationEntry.objects.bulk_create(entries)


# ---------------------------------------------------------------------------
# Fixtures — autouse
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_conf_caches():
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()
    yield
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()


@pytest.fixture(autouse=True)
def _reset_string_registry():
    strings.reset_string_registry()
    yield
    strings.reset_string_registry()


# ---------------------------------------------------------------------------
# Fixtures — gettext helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def original_gettext() -> t.Callable[[str], str]:
    """Return the unpatched gettext from trans_real (not affected by monkey-patch)."""
    import django.utils.translation.trans_real

    return django.utils.translation.trans_real.gettext


@pytest.fixture
def restore_original_gettext(
    original_gettext: t.Callable[[str], str],
) -> t.Callable[[], contextlib.AbstractContextManager[None]]:
    """Context manager that temporarily swaps _trans.gettext back to the original."""

    @contextlib.contextmanager
    def _ctx() -> t.Iterator[None]:
        _trans = django.utils.translation._trans  # type: ignore[attr-defined]
        patched = _trans.gettext
        _trans.gettext = original_gettext
        try:
            yield
        finally:
            _trans.gettext = patched

    return _ctx


# ---------------------------------------------------------------------------
# Fixtures — request factory
# ---------------------------------------------------------------------------


RequestFactory = t.Callable[..., django.http.HttpRequest]


@pytest.fixture
def make_bench_request() -> RequestFactory:
    """Create a Django HttpRequest with configurable user permissions."""
    from django.contrib.auth.models import AnonymousUser, User

    def _make(
        *,
        path: str = "/bench/",
        is_superuser: bool = False,
    ) -> django.http.HttpRequest:
        factory = django.test.RequestFactory()
        request = factory.get(path)
        if is_superuser:
            request.user = User(username="bench", is_superuser=True, is_active=True)  # type: ignore[assignment]
        else:
            request.user = AnonymousUser()  # type: ignore[assignment]
        return request

    return _make


# ---------------------------------------------------------------------------
# Fixtures — DB backend
# ---------------------------------------------------------------------------


@pytest.fixture
def db_backend_with_overrides(
    request: pytest.FixtureRequest, tmp_path: pathlib.Path, transactional_db: None
) -> "tuple[int, DatabaseBackend]":
    """Populate DB with N overrides per language and return a DatabaseBackend.

    Usage: @pytest.mark.parametrize("db_backend_with_overrides", SCALES, indirect=True)

    Depends on transactional_db so pytest-django creates the tables and allows DB access.
    """
    import django.core.cache

    from live_translations.backends.db import CATALOG_VERSION_KEY
    from live_translations.backends.db import DatabaseBackend as _DatabaseBackend
    from live_translations.models import TranslationEntry

    n: int = request.param

    # Clean slate
    TranslationEntry.objects.all().delete()

    # Populate with n entries per language (80% active / 20% inactive)
    populate_db_overrides(n, LANGUAGES)

    # Create real PO files so the PO sub-backend has something to read
    locale_dir = tmp_path / "locale"
    for lang in LANGUAGES:
        generate_po_file(n, locale_dir, lang)

    # Create backend with real PO files
    backend = _DatabaseBackend(locale_dir=locale_dir, domain="django")

    # Prime the cache so ensure_current() can detect hit/miss
    cache = django.core.cache.caches["default"]
    version = "bench-v1"
    cache.set(CATALOG_VERSION_KEY, version)
    backend._local_version = version  # cache hit by default

    return n, backend
