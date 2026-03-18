"""Full request-response cycle benchmarks.

End-to-end: RequestFactory -> middleware -> view -> template render -> response.
Three scenarios (baseline / normal-user / translator) x two scales (100 / 500)
for both PO and DB backends.

DB backend additionally tests the cache-miss path where ensure_current() must
reload all active overrides from the database.
"""

import contextlib
import pathlib
import typing as t
import unittest.mock

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
# Shared mock helpers
# ---------------------------------------------------------------------------

_STATIC_PATCH = unittest.mock.patch(
    "live_translations.middleware.django.templatetags.static.static",
    side_effect=lambda p: f"/static/{p}",
)
_CSRF_PATCH = unittest.mock.patch(
    "live_translations.middleware.django.middleware.csrf.get_token",
    return_value="bench-csrf-token",
)


def _conf_patches(
    *, backend: "unittest.mock.MagicMock | DatabaseBackend", permission: bool
) -> contextlib.AbstractContextManager[dict[str, unittest.mock.MagicMock]]:
    settings = conf.LiveTranslationsConf(languages=LANGUAGES)
    return unittest.mock.patch.multiple(
        "live_translations.middleware.conf",
        get_backend_instance=unittest.mock.MagicMock(return_value=backend),
        get_permission_checker=unittest.mock.MagicMock(return_value=lambda _: permission),
        is_preview_request=unittest.mock.MagicMock(return_value=False),
        get_settings=unittest.mock.MagicMock(return_value=settings),
    )


def _noop_backend() -> unittest.mock.MagicMock:
    backend = unittest.mock.MagicMock()
    backend.ensure_current.return_value = None
    return backend


# ---------------------------------------------------------------------------
# PO backend
# ---------------------------------------------------------------------------


class TestFullRequestPo:
    """Full request cycle with PO backend (mocked ensure_current)."""

    @pytest.fixture(autouse=True)
    def _setup_locale(self, tmp_path: pathlib.Path) -> t.Iterator[None]:
        locale_dir = tmp_path / "locale"
        for n in SCALES:
            for lang in LANGUAGES:
                generate_po_file(n, locale_dir, lang)

        with unittest.mock.patch.object(django.conf.settings, "LOCALE_PATHS", [str(locale_dir)]):
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
    ) -> None:
        """Full middleware, permission denied — near-zero overhead expected."""
        benchmark.group = f"po-n{n}"
        benchmark.name = "normal-user"

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=False)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with _conf_patches(backend=_noop_backend(), permission=False):
            benchmark(mw, request)

    @pytest.mark.parametrize("n", SCALES, ids=[f"n={n}" for n in SCALES])
    def test_translator(
        self,
        benchmark: BenchmarkFixture,
        n: int,
        make_bench_request: RequestFactory,
    ) -> None:
        """Full middleware, permission granted — marker encoding + asset injection."""
        benchmark.group = f"po-n{n}"
        benchmark.name = "translator"

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=True)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with _conf_patches(backend=_noop_backend(), permission=True), _CSRF_PATCH, _STATIC_PATCH:

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
    def _setup_locale(self, tmp_path: pathlib.Path) -> t.Iterator[None]:
        locale_dir = tmp_path / "locale"
        for n in SCALES:
            for lang in LANGUAGES:
                generate_po_file(n, locale_dir, lang)

        with unittest.mock.patch.object(django.conf.settings, "LOCALE_PATHS", [str(locale_dir)]):
            from django.utils.translation import trans_real

            trans_real._translations = {}  # type: ignore[attr-defined]
            yield
            trans_real._translations = {}  # type: ignore[attr-defined]

    @pytest.mark.parametrize("db_backend_with_overrides", SCALES, indirect=True)
    def test_normal_user(
        self,
        benchmark: BenchmarkFixture,
        db_backend_with_overrides: "tuple[int, DatabaseBackend]",
        make_bench_request: RequestFactory,
    ) -> None:
        """DB backend, permission denied, cache hit — ensure_current() is a no-op."""
        n, backend = db_backend_with_overrides
        benchmark.group = f"db-n{n}"
        benchmark.name = "normal-user"

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=False)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with _conf_patches(backend=backend, permission=False):
            benchmark(mw, request)

    @pytest.mark.parametrize("db_backend_with_overrides", SCALES, indirect=True)
    def test_translator_cache_hit(
        self,
        benchmark: BenchmarkFixture,
        db_backend_with_overrides: "tuple[int, DatabaseBackend]",
        make_bench_request: RequestFactory,
    ) -> None:
        """DB backend, permission granted, cache hit — steady-state translator request."""
        n, backend = db_backend_with_overrides
        benchmark.group = f"db-n{n}"
        benchmark.name = "translator-cache-hit"

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=True)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with _conf_patches(backend=backend, permission=True), _CSRF_PATCH, _STATIC_PATCH:

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
    ) -> None:
        """DB backend, permission granted, cache miss — ensure_current() reloads all active overrides."""
        n, backend = db_backend_with_overrides
        benchmark.group = f"db-n{n}"
        benchmark.name = "translator-cache-miss"

        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        request = make_bench_request(is_superuser=True)

        django.utils.translation.activate("en")

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with _conf_patches(backend=backend, permission=True), _CSRF_PATCH, _STATIC_PATCH:

            def run() -> None:
                strings.reset_string_registry()
                backend._local_version = "stale"  # force cache miss each iteration
                mw(request)

            benchmark(run)
