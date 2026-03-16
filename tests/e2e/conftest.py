"""E2E test fixtures — server management, page helpers, backend parameterization."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE_DIR = PROJECT_ROOT / "example"
MANAGE_PY = EXAMPLE_DIR / "manage.py"
SOURCE_LOCALE_DIR = EXAMPLE_DIR / "locale"

# ---------------------------------------------------------------------------
# Backend parameterization
# ---------------------------------------------------------------------------

PO_SETTINGS = "config.settings_e2e_po"
DB_SETTINGS = "config.settings_e2e_db"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--backend",
        action="store",
        default="po",
        choices=["po", "db", "both"],
        help="Which backend(s) to test: po, db, or both (default: po)",
    )


@pytest.fixture(params=["po", "db"], scope="session")
def backend_id(request: pytest.FixtureRequest) -> str:
    chosen = request.config.getoption("--backend")
    if chosen != "both" and request.param != chosen:
        pytest.skip(f"Skipping {request.param} backend (--backend={chosen})")
    return request.param


# ---------------------------------------------------------------------------
# Temp locale dir (per-session copy so PO writes don't mutate source)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def session_tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("e2e")


@pytest.fixture(scope="session")
def locale_dir(session_tmp_path: Path) -> Path:
    dest = session_tmp_path / "locale"
    shutil.copytree(SOURCE_LOCALE_DIR, dest)
    return dest


# ---------------------------------------------------------------------------
# Fresh locale dir (per-test copy for tests that modify PO files)
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_locale(tmp_path: Path) -> Path:
    dest = tmp_path / "locale"
    shutil.copytree(SOURCE_LOCALE_DIR, dest)
    return dest


# ---------------------------------------------------------------------------
# Django live server (per-session)
# ---------------------------------------------------------------------------


def _wait_for_server(port: int, timeout: float = 15.0) -> None:
    """Poll until the server responds on the given port."""
    import socket

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"Server did not start on port {port} within {timeout}s")


@pytest.fixture(scope="session")
def _po_server(locale_dir: Path, session_tmp_path: Path) -> str:
    """Start a Django dev server with PO backend. Returns base URL."""
    port = 8111
    db_path = session_tmp_path / "po_test.sqlite3"
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": PO_SETTINGS,
        "LT_E2E_LOCALE_DIR": str(locale_dir),
        "LT_E2E_DB_PATH": str(db_path),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    # Run migrate + createsuperuser
    subprocess.run(
        [sys.executable, str(MANAGE_PY), "migrate", "--run-syncdb", "--verbosity=0"],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(MANAGE_PY),
            "shell",
            "-c",
            (
                "from django.contrib.auth.models import User;"
                "User.objects.create_superuser('admin', 'admin@test.com', 'admin123')"
            ),
        ],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    # Also create a regular staff user
    subprocess.run(
        [
            sys.executable,
            str(MANAGE_PY),
            "shell",
            "-c",
            (
                "from django.contrib.auth.models import User;"
                "u = User.objects.create_user('staff', 'staff@test.com', 'staff123');"
                "u.is_staff = True; u.save()"
            ),
        ],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    proc = subprocess.Popen(
        [sys.executable, str(MANAGE_PY), "runserver", str(port), "--noreload"],
        cwd=str(EXAMPLE_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_server(port)
    yield f"http://127.0.0.1:{port}"
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def _db_server(session_tmp_path: Path) -> str:
    """Start a Django dev server with Database backend. Returns base URL."""
    port = 8112
    db_path = session_tmp_path / "db_test.sqlite3"
    locale_dest = session_tmp_path / "locale_db"
    shutil.copytree(SOURCE_LOCALE_DIR, locale_dest)
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": DB_SETTINGS,
        "LT_E2E_LOCALE_DIR": str(locale_dest),
        "LT_E2E_DB_PATH": str(db_path),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    subprocess.run(
        [sys.executable, str(MANAGE_PY), "migrate", "--run-syncdb", "--verbosity=0"],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(MANAGE_PY),
            "shell",
            "-c",
            (
                "from django.contrib.auth.models import User;"
                "User.objects.create_superuser('admin', 'admin@test.com', 'admin123')"
            ),
        ],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(MANAGE_PY),
            "shell",
            "-c",
            (
                "from django.contrib.auth.models import User;"
                "u = User.objects.create_user('staff', 'staff@test.com', 'staff123');"
                "u.is_staff = True; u.save()"
            ),
        ],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    proc = subprocess.Popen(
        [sys.executable, str(MANAGE_PY), "runserver", str(port), "--noreload"],
        cwd=str(EXAMPLE_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_server(port)
    yield f"http://127.0.0.1:{port}"
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def po_base_url(_po_server: str) -> str:
    return _po_server


@pytest.fixture(scope="session")
def db_base_url(_db_server: str) -> str:
    return _db_server


@pytest.fixture(scope="session")
def base_url(_po_server: str) -> str:
    """Default base URL — PO backend. Overrides pytest-base-url fixture."""
    return _po_server


@pytest.fixture
def base_url_for_backend(backend_id: str, _po_server: str, _db_server: str) -> str:
    """Returns the correct base URL for the current backend parameterization."""
    return _po_server if backend_id == "po" else _db_server


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------

SUPERUSER = ("admin", "admin123")
STAFF_USER = ("staff", "staff123")


def _login(page: Page, base_url: str, username: str, password: str) -> None:
    """Log in via the Django admin login page."""
    page.goto(f"{base_url}/en/admin/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", password)
    page.click('input[type="submit"]')
    page.wait_for_url("**/admin/**")


# ---------------------------------------------------------------------------
# Page fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def page_as_superuser(page: Page, base_url: str) -> Page:
    """Logged-in superuser on the home page."""
    _login(page, base_url, *SUPERUSER)
    page.goto(f"{base_url}/en/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def page_as_superuser_for_backend(page: Page, base_url_for_backend: str) -> Page:
    """Logged-in superuser for parameterized backend tests."""
    _login(page, base_url_for_backend, *SUPERUSER)
    page.goto(f"{base_url_for_backend}/en/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def page_as_regular_user(page: Page, base_url: str) -> Page:
    """Logged-in staff (non-superuser) on the home page."""
    _login(page, base_url, *STAFF_USER)
    page.goto(f"{base_url}/en/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def page_anonymous(page: Page, base_url: str) -> Page:
    """Unauthenticated page on the home page."""
    page.goto(f"{base_url}/en/")
    page.wait_for_load_state("networkidle")
    return page


# ---------------------------------------------------------------------------
# Interaction helpers
# ---------------------------------------------------------------------------

API_PREFIX = "/__live-translations__"


def activate_edit_mode(page: Page) -> None:
    """Toggle edit mode on via keyboard shortcut."""
    page.keyboard.press("Control+Shift+KeyE")
    expect(page.locator("body")).to_have_class(re.compile(r"lt-edit-mode"), timeout=3000)


def deactivate_edit_mode(page: Page) -> None:
    """Toggle edit mode off via keyboard shortcut."""
    page.keyboard.press("Control+Shift+KeyE")
    expect(page.locator("body")).not_to_have_class(re.compile(r"lt-edit-mode"), timeout=3000)


def open_modal(page: Page, msgid: str, *, attr: bool = False) -> None:
    """Activate edit mode and click a translatable element to open the modal."""
    if not page.locator("body").get_attribute("class", timeout=500) or "lt-edit-mode" not in (
        page.locator("body").get_attribute("class") or ""
    ):
        activate_edit_mode(page)
    if attr:
        # Dispatch click directly on the [data-lt-attrs] element via JS
        # to avoid the click being captured by child .lt-translatable spans
        page.evaluate(
            """(msgid) => {
                const el = document.querySelector('[data-lt-attrs*="' + msgid + '"]');
                if (el) el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
            }""",
            msgid,
        )
    else:
        page.locator(f'.lt-translatable[data-lt-msgid="{msgid}"]').first.click()
    expect(page.locator("dialog.lt-dialog[open]")).to_be_visible(timeout=3000)


def wait_for_fields_loaded(page: Page) -> None:
    """Wait for the modal fields to finish loading."""
    expect(page.locator(".lt-dialog__loading")).to_be_hidden(timeout=5000)
    expect(page.locator(".lt-dialog__fields")).to_be_visible(timeout=5000)


def close_modal(page: Page) -> None:
    """Close the modal via the close button."""
    page.locator(".lt-dialog__close").click()
    expect(page.locator("dialog.lt-dialog[open]")).to_be_hidden(timeout=3000)


def check_active_toggle(page: Page, lang: str = "en") -> None:
    """Check the active toggle for a language. Uses JS because the checkbox is CSS-hidden."""
    page.evaluate(
        """(lang) => {
            const cb = document.getElementById('lt-active-' + lang);
            if (cb && !cb.checked) { cb.click(); }
        }""",
        lang,
    )


def uncheck_active_toggle(page: Page, lang: str = "en") -> None:
    """Uncheck the active toggle for a language. Uses JS because the checkbox is CSS-hidden."""
    page.evaluate(
        """(lang) => {
            const cb = document.getElementById('lt-active-' + lang);
            if (cb && cb.checked) { cb.click(); }
        }""",
        lang,
    )


def api_save(
    page: Page,
    base_url: str,
    msgid: str,
    translations: dict[str, str],
    active_flags: dict[str, bool] | None = None,
    *,
    context: str = "",
    page_language: str = "en",
) -> dict:
    """Save a translation via the API directly (for test setup)."""
    csrf = page.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
    body: dict = {
        "msgid": msgid,
        "context": context,
        "translations": translations,
        "active_flags": active_flags or {lang: True for lang in translations},
        "page_language": page_language,
    }
    response = page.request.post(
        f"{base_url}{API_PREFIX}/translations/save/",
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
        },
    )
    return response.json()


def api_delete(
    page: Page,
    base_url: str,
    msgid: str,
    languages: list[str] | None = None,
    *,
    context: str = "",
    page_language: str = "en",
) -> dict:
    """Delete a translation override via the API directly (for test setup)."""
    csrf = page.evaluate("() => window.__LT_CONFIG__?.csrfToken || ''")
    body: dict = {
        "msgid": msgid,
        "context": context,
        "page_language": page_language,
    }
    if languages:
        body["languages"] = languages
    response = page.request.post(
        f"{base_url}{API_PREFIX}/translations/delete/",
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "X-CSRFToken": csrf,
        },
    )
    return response.json()


# Known PO defaults for cleanup — saving original value back restores PO state
PO_DEFAULTS = {
    ("demo.title", "en"): "Live Translations Demo",
    ("demo.title", "cs"): "Demo živých překladů",
    ("demo.welcome", "en"): "Welcome to the demo application!",
    ("demo.welcome", "cs"): "Vítejte v demo aplikaci!",
    ("demo.description", "en"): "A minimal example app for testing django-live-translations.",
    ("demo.description", "cs"): "Minimální příklad pro testování django-live-translations.",
    ("about.heading", "en"): "About this page",
    ("about.heading", "cs"): "O této stránce",
    ("attrs.tooltip_trans", "en"): "This tooltip was translated with the trans tag",
    ("attrs.tooltip_trans", "cs"): "Tento tooltip byl přeložen pomocí tagu trans",
    ("attrs.tooltip_gettext", "en"): "This tooltip was translated with gettext()",
    ("attrs.tooltip_gettext", "cs"): "Tento tooltip byl přeložen pomocí gettext()",
}


def api_restore_po_default(
    page: Page,
    base_url: str,
    msgid: str,
    languages: list[str] | None = None,
    *,
    context: str = "",
) -> None:
    """Restore PO defaults for a msgid. For PO backend cleanup — saves original values back."""
    langs = languages or ["en", "cs"]
    translations = {}
    active_flags = {}
    for lang in langs:
        default = PO_DEFAULTS.get((msgid, lang))
        if default is not None:
            translations[lang] = default
            active_flags[lang] = True
    if translations:
        api_save(page, base_url, msgid, translations, active_flags, context=context)
