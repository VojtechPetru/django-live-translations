"""E2E test fixtures — server management, page helpers, backend parameterization."""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

# Make helpers.py importable without global pythonpath config
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from helpers import STAFF_USER, SUPERUSER, login
from playwright.sync_api import Page

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


def _setup_db(env: dict[str, str]) -> None:
    """Run migrate and create test users for a Django server."""
    subprocess.run(
        [sys.executable, str(MANAGE_PY), "migrate", "--run-syncdb", "--verbosity=0"],
        cwd=str(EXAMPLE_DIR),
        env=env,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(MANAGE_PY), "createsuperuser", "--noinput"],
        cwd=str(EXAMPLE_DIR),
        env={
            **env,
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_EMAIL": "admin@test.com",
            "DJANGO_SUPERUSER_PASSWORD": "admin123",
        },
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


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port (best-effort)."""
    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-t"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for pid_str in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid_str), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        if result.stdout.strip():
            time.sleep(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def _start_server(env: dict[str, str], port: int, tmp_dir: Path) -> subprocess.Popen:
    """Start a Django dev server and wait for it to be ready."""
    _kill_port(port)
    stderr_log = tmp_dir / f"server_{port}_stderr.log"
    stderr_fh = stderr_log.open("w")
    proc = subprocess.Popen(
        [sys.executable, str(MANAGE_PY), "runserver", str(port), "--noreload"],
        cwd=str(EXAMPLE_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr_fh,
    )
    _wait_for_server(port)
    if proc.poll() is not None:
        stderr_fh.close()
        stderr_output = stderr_log.read_text()
        raise RuntimeError(
            f"Django server exited immediately on port {port} (port likely in use by a stale process). "
            f"Kill the process manually: lsof -i :{port} -t | xargs kill\n"
            f"Server stderr: {stderr_output}"
        )
    return proc


@pytest.fixture(scope="session")
def _po_server(locale_dir: Path, session_tmp_path: Path) -> str:
    """Start a Django dev server with PO backend. Returns base URL."""
    port = 8111
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": PO_SETTINGS,
        "LT_E2E_LOCALE_DIR": str(locale_dir),
        "LT_E2E_DB_PATH": str(session_tmp_path / "po_test.sqlite3"),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    _setup_db(env)
    proc = _start_server(env, port, session_tmp_path)
    yield f"http://127.0.0.1:{port}"
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


@pytest.fixture(scope="session")
def _db_server(session_tmp_path: Path) -> str:
    """Start a Django dev server with Database backend. Returns base URL."""
    port = 8112
    locale_dest = session_tmp_path / "locale_db"
    shutil.copytree(SOURCE_LOCALE_DIR, locale_dest)
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": DB_SETTINGS,
        "LT_E2E_LOCALE_DIR": str(locale_dest),
        "LT_E2E_DB_PATH": str(session_tmp_path / "db_test.sqlite3"),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
    }
    _setup_db(env)
    proc = _start_server(env, port, session_tmp_path)
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
# Page fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def page_as_superuser(page: Page, base_url: str) -> Page:
    """Logged-in superuser on the home page."""
    login(page, base_url, *SUPERUSER)
    page.goto(f"{base_url}/en/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def page_as_superuser_for_backend(page: Page, base_url_for_backend: str) -> Page:
    """Logged-in superuser for parameterized backend tests."""
    login(page, base_url_for_backend, *SUPERUSER)
    page.goto(f"{base_url_for_backend}/en/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def page_as_regular_user(page: Page, base_url: str) -> Page:
    """Logged-in staff (non-superuser) on the home page."""
    login(page, base_url, *STAFF_USER)
    page.goto(f"{base_url}/en/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def page_anonymous(page: Page, base_url: str) -> Page:
    """Unauthenticated page on the home page."""
    page.goto(f"{base_url}/en/")
    page.wait_for_load_state("networkidle")
    return page
