"""Full request-response cycle benchmarks.

End-to-end: RequestFactory -> middleware -> view -> template render -> response.
Three scenarios (baseline / normal-user / translator) x two scales (100 / 500)
for both PO and DB backends.

DB backend additionally tests the cache-miss path where ensure_current() must
reload all active overrides from the database.

All configuration is injected via Django settings and ``conf.cache_clear()``
— no mocks are used.
"""

import contextlib
import pathlib
import typing as t

import django.conf
import django.http
import django.template
import django.utils.translation
import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from live_translations import conf, strings
from live_translations.middleware import LiveTranslationsMiddleware

from .conftest import (
    LANGUAGES,
    SCALES,
    RequestFactory,
    generate_po_file,
    generate_template_context,
    generate_template_string,
)

if t.TYPE_CHECKING:
    from live_translations.backends.db import DatabaseBackend

# ---------------------------------------------------------------------------
# Shared view callable
# ---------------------------------------------------------------------------


def _bench_view(
    request: django.http.HttpRequest,
    *,
    template: t.Any,
    context: dict[str, str | object],
) -> django.http.HttpResponse:
    html: str = template.render(context, request)
    return django.http.HttpResponse(html, content_type="text/html")


# ---------------------------------------------------------------------------
# Settings-based configuration helpers (no mocks)
# ---------------------------------------------------------------------------


def _configure_settings(
    settings: django.conf.LazySettings,
    *,
    backend: str,
    permission: str,
    locale_dir: str | pathlib.Path = "/tmp",
) -> None:
    """Configure LIVE_TRANSLATIONS via Django settings and clear conf caches."""
    settings.LIVE_TRANSLATIONS = {  # type: ignore[attr-defined]
        "BACKEND": backend,
        "LANGUAGES": LANGUAGES,
        "LOCALE_DIR": str(locale_dir),
        "PERMISSION_CHECK": permission,
    }
    conf.get_settings.cache_clear()
    conf.get_backend_instance.cache_clear()
    conf.get_permission_checker.cache_clear()


# ---------------------------------------------------------------------------
# PO backend
# ---------------------------------------------------------------------------


class TestFullRequestPo:
    """Full request cycle with InMemoryBackend (lightweight, no PO/cache deps)."""

    @pytest.fixture(autouse=True)
    def _setup_locale(self, tmp_path: pathlib.Path, settings: django.conf.LazySettings) -> t.Iterator[None]:
        locale_dir = tmp_path / "locale"
        for n in SCALES:
            for lang in LANGUAGES:
                generate_po_file(n, locale_dir, lang)

        settings.LOCALE_PATHS = [str(locale_dir)]  # type: ignore[misc]
        from django.utils.translation import trans_real

        trans_real._translations = {}  # type: ignore[attr-defined]
        yield
        trans_real._translations = {}  # type: ignore[attr-defined]

    @pytest.mark.parametrize("n", SCALES, ids=[f"n={n}" for n in SCALES])
    def test_baseline(
        self,
        benchmark: BenchmarkFixture,
        n: int,
        original_gettext: t.Callable[[str], str],
        restore_original_gettext: t.Callable[[], contextlib.AbstractContextManager[None]],
        make_bench_request: RequestFactory,
    ) -> None:
        """View only, original gettext, no middleware — pure Django baseline."""
        benchmark.group = f"po-n{n}"
        benchmark.name = "baseline"

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)

        with restore_original_gettext():
            request = make_bench_request(is_superuser=False)

            def run() -> None:
                ctx = generate_template_context(n, original_gettext)
                _bench_view(request, template=template, context=ctx)

            benchmark(run)

    @pytest.mark.parametrize("n", SCALES, ids=[f"n={n}" for n in SCALES])
    def test_normal_user(
        self,
        benchmark: BenchmarkFixture,
        n: int,
        make_bench_request: RequestFactory,
        settings: django.conf.LazySettings,
    ) -> None:
        """Full middleware, permission denied — near-zero overhead expected."""
        benchmark.group = f"po-n{n}"
        benchmark.name = "normal-user"

        _configure_settings(
            settings,
            backend="tests.backends.InMemoryBackend",
            permission="tests.permissions.deny_all",
        )

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=False)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        benchmark(mw, request)

    @pytest.mark.parametrize("n", SCALES, ids=[f"n={n}" for n in SCALES])
    def test_translator(
        self,
        benchmark: BenchmarkFixture,
        n: int,
        make_bench_request: RequestFactory,
        settings: django.conf.LazySettings,
    ) -> None:
        """Full middleware, permission granted — marker encoding + asset injection."""
        benchmark.group = f"po-n{n}"
        benchmark.name = "translator"

        _configure_settings(
            settings,
            backend="tests.backends.InMemoryBackend",
            permission="tests.permissions.allow_all",
        )

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=True)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        def run() -> None:
            strings.reset_string_registry()
            mw(request)

        benchmark(run)


# ---------------------------------------------------------------------------
# DB backend (real TranslationEntry rows, 80% active / 20% inactive)
# ---------------------------------------------------------------------------


class TestFullRequestDb:
    """Full request cycle with DatabaseBackend and real DB entries."""

    @pytest.fixture(autouse=True)
    def _setup_locale(self, tmp_path: pathlib.Path, settings: django.conf.LazySettings) -> t.Iterator[None]:
        locale_dir = tmp_path / "locale"
        for n in SCALES:
            for lang in LANGUAGES:
                generate_po_file(n, locale_dir, lang)

        settings.LOCALE_PATHS = [str(locale_dir)]  # type: ignore[misc]
        from django.utils.translation import trans_real

        trans_real._translations = {}  # type: ignore[attr-defined]
        yield
        trans_real._translations = {}  # type: ignore[attr-defined]

    def _setup_db_conf(
        self,
        settings: django.conf.LazySettings,
        *,
        permission: str,
        locale_dir: pathlib.Path,
    ) -> None:
        """Configure settings to use DatabaseBackend with given permission."""
        _configure_settings(
            settings,
            backend="live_translations.backends.db.DatabaseBackend",
            permission=permission,
            locale_dir=locale_dir,
        )

    @pytest.mark.parametrize("db_backend_with_overrides", SCALES, indirect=True)
    def test_normal_user(
        self,
        benchmark: BenchmarkFixture,
        db_backend_with_overrides: "tuple[int, DatabaseBackend]",
        make_bench_request: RequestFactory,
        settings: django.conf.LazySettings,
    ) -> None:
        """DB backend, permission denied, cache hit — ensure_current() is a no-op."""
        n, backend = db_backend_with_overrides
        benchmark.group = f"db-n{n}"
        benchmark.name = "normal-user"

        self._setup_db_conf(settings, permission="tests.permissions.deny_all", locale_dir=backend.locale_dir)
        # Prime the conf-cached instance with our pre-populated backend
        instance = t.cast("DatabaseBackend", conf.get_backend_instance())
        instance._local_version = backend._local_version

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=False)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        benchmark(mw, request)

    @pytest.mark.parametrize("db_backend_with_overrides", SCALES, indirect=True)
    def test_translator_cache_hit(
        self,
        benchmark: BenchmarkFixture,
        db_backend_with_overrides: "tuple[int, DatabaseBackend]",
        make_bench_request: RequestFactory,
        settings: django.conf.LazySettings,
    ) -> None:
        """DB backend, permission granted, cache hit — steady-state translator request."""
        n, backend = db_backend_with_overrides
        benchmark.group = f"db-n{n}"
        benchmark.name = "translator-cache-hit"

        self._setup_db_conf(settings, permission="tests.permissions.allow_all", locale_dir=backend.locale_dir)
        instance = t.cast("DatabaseBackend", conf.get_backend_instance())
        instance._local_version = backend._local_version

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=True)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        def run() -> None:
            strings.reset_string_registry()
            mw(request)

        benchmark(run)

    @pytest.mark.parametrize("db_backend_with_overrides", SCALES, indirect=True)
    def test_translator_cache_miss(
        self,
        benchmark: BenchmarkFixture,
        db_backend_with_overrides: "tuple[int, DatabaseBackend]",
        make_bench_request: RequestFactory,
        settings: django.conf.LazySettings,
    ) -> None:
        """DB backend, permission granted, cache miss — ensure_current() reloads all active overrides."""
        n, backend = db_backend_with_overrides
        benchmark.group = f"db-n{n}"
        benchmark.name = "translator-cache-miss"

        self._setup_db_conf(settings, permission="tests.permissions.allow_all", locale_dir=backend.locale_dir)
        instance = t.cast("DatabaseBackend", conf.get_backend_instance())

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=True)

        django.utils.translation.activate("en")

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        def run() -> None:
            strings.reset_string_registry()
            instance._local_version = "stale"  # force cache miss each iteration
            mw(request)

        benchmark(run)
