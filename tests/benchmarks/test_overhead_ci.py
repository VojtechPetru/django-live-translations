"""CI-safe overhead ratio tests.

Measures the ratio of normal-user / baseline request time and asserts it stays
below a threshold.  Uses timeit with enough iterations to get a stable median.

These tests do NOT use pytest-benchmark — they run as plain pytest tests so they
can fail CI without any special flags.

Thresholds:
  - Normal user overhead: < 10% vs baseline  (should be ~1-5% in practice)
  - Translator overhead:  < 100% vs baseline (should be ~35% in practice)
"""

import contextlib
import pathlib
import statistics
import timeit
import typing as t
import unittest.mock

import django.conf
import django.http
import django.template
import django.test
import django.utils.translation
import pytest

from live_translations import conf, strings
from live_translations.middleware import LiveTranslationsMiddleware

from .conftest import (
    LANGUAGES,
    SCALES,
    generate_po_file,
    generate_template_context,
    generate_template_string,
)

# ---------------------------------------------------------------------------
# Thresholds (ratio = scenario_time / baseline_time)
# ---------------------------------------------------------------------------

MAX_NORMAL_USER_RATIO = 1.10  # 10% overhead max
MAX_TRANSLATOR_RATIO = 2.00  # 100% overhead max

# ---------------------------------------------------------------------------
# Measurement config
# ---------------------------------------------------------------------------

WARMUP_RUNS = 10
TIMED_RUNS = 80


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _measure(fn: t.Callable[[], object], *, warmup: int = WARMUP_RUNS, runs: int = TIMED_RUNS) -> float:
    """Run fn `warmup` times, then `runs` times, return the median duration in seconds."""
    for _ in range(warmup):
        fn()
    times = timeit.repeat(fn, number=1, repeat=runs)
    return statistics.median(times)


def _bench_view(
    request: django.http.HttpRequest,
    *,
    template: t.Any,
    context: dict[str, str | object],
) -> django.http.HttpResponse:
    html: str = template.render(context, request)
    return django.http.HttpResponse(html, content_type="text/html")


def _noop_backend() -> unittest.mock.MagicMock:
    backend = unittest.mock.MagicMock()
    backend.ensure_current.return_value = None
    return backend


def _conf_patches(
    *, backend: unittest.mock.MagicMock, permission: bool
) -> contextlib.AbstractContextManager[dict[str, unittest.mock.MagicMock]]:
    settings = conf.LiveTranslationsConf(languages=LANGUAGES)
    return unittest.mock.patch.multiple(
        "live_translations.middleware.conf",
        get_backend_instance=unittest.mock.MagicMock(return_value=backend),
        get_permission_checker=unittest.mock.MagicMock(return_value=lambda _: permission),
        is_preview_request=unittest.mock.MagicMock(return_value=False),
        get_settings=unittest.mock.MagicMock(return_value=settings),
    )


@contextlib.contextmanager
def _restore_original_gettext() -> t.Iterator[None]:
    """Temporarily swap _trans.gettext back to the unpatched original."""
    import django.utils.translation.trans_real

    _trans = django.utils.translation._trans  # type: ignore[attr-defined]
    patched = _trans.gettext
    _trans.gettext = django.utils.translation.trans_real.gettext
    try:
        yield
    finally:
        _trans.gettext = patched


def _make_request(*, is_superuser: bool = False) -> django.http.HttpRequest:
    factory = django.test.RequestFactory()
    request = factory.get("/bench/")
    request.user = unittest.mock.MagicMock(  # type: ignore[assignment]
        is_authenticated=is_superuser,
        is_superuser=is_superuser,
    )
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNormalUserOverhead:
    """Assert that normal users experience < 20% overhead vs no-package baseline."""

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
    def test_normal_user_overhead(self, n: int) -> None:
        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        original_gettext = django.utils.translation.trans_real.gettext  # type: ignore[attr-defined]

        # --- baseline: no middleware, unpatched gettext ---
        with _restore_original_gettext():
            baseline_req = _make_request(is_superuser=False)

            def baseline_fn() -> None:
                ctx = generate_template_context(n, original_gettext)
                _bench_view(baseline_req, template=template, context=ctx)

            t_baseline = _measure(baseline_fn)

        # --- normal user: middleware + patched gettext, permission denied ---
        normal_req = _make_request(is_superuser=False)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with _conf_patches(backend=_noop_backend(), permission=False):

            def normal_fn() -> None:
                mw(normal_req)

            t_normal = _measure(normal_fn)

        ratio = t_normal / t_baseline
        overhead_pct = (ratio - 1) * 100
        max_pct = (MAX_NORMAL_USER_RATIO - 1) * 100

        print(
            f"\n  n={n}: baseline={t_baseline * 1000:.2f}ms, "
            f"normal={t_normal * 1000:.2f}ms, "
            f"overhead={overhead_pct:+.1f}% (max {max_pct:.0f}%)"
        )

        assert ratio < MAX_NORMAL_USER_RATIO, (
            f"Normal user overhead too high: {ratio:.2f}x baseline (threshold: {MAX_NORMAL_USER_RATIO:.2f}x) at n={n}"
        )


class TestTranslatorOverhead:
    """Assert that translators experience < 100% overhead vs no-package baseline."""

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
    def test_translator_overhead(self, n: int) -> None:
        tpl_source = generate_template_string(n)
        template = django.template.engines["django"].from_string(tpl_source)
        original_gettext = django.utils.translation.trans_real.gettext  # type: ignore[attr-defined]

        # --- baseline ---
        with _restore_original_gettext():
            baseline_req = _make_request(is_superuser=False)

            def baseline_fn() -> None:
                ctx = generate_template_context(n, original_gettext)
                _bench_view(baseline_req, template=template, context=ctx)

            t_baseline = _measure(baseline_fn)

        # --- translator: middleware + patched gettext, permission granted ---
        translator_req = _make_request(is_superuser=True)

        def inner(req: django.http.HttpRequest) -> django.http.HttpResponse:
            ctx = generate_template_context(n, django.utils.translation.gettext)
            return _bench_view(req, template=template, context=ctx)

        mw = LiveTranslationsMiddleware(inner)

        with (
            _conf_patches(backend=_noop_backend(), permission=True),
            unittest.mock.patch(
                "live_translations.middleware.django.middleware.csrf.get_token",
                return_value="bench-csrf-token",
            ),
            unittest.mock.patch(
                "live_translations.middleware.django.templatetags.static.static",
                side_effect=lambda p: f"/static/{p}",
            ),
        ):

            def translator_fn() -> None:
                strings.reset_string_registry()
                mw(translator_req)

            t_translator = _measure(translator_fn)

        ratio = t_translator / t_baseline
        overhead_pct = (ratio - 1) * 100
        max_pct = (MAX_TRANSLATOR_RATIO - 1) * 100

        print(
            f"\n  n={n}: baseline={t_baseline * 1000:.2f}ms, "
            f"translator={t_translator * 1000:.2f}ms, "
            f"overhead={overhead_pct:+.1f}% (max {max_pct:.0f}%)"
        )

        assert ratio < MAX_TRANSLATOR_RATIO, (
            f"Translator overhead too high: {ratio:.2f}x baseline (threshold: {MAX_TRANSLATOR_RATIO:.2f}x) at n={n}"
        )
