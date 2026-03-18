# AGENTS.md

Django app providing live, in-browser translation editing with pluggable backends (PO files, database).
Package source lives in `src/live_translations/`, tests in `tests/`, demo app in `example/`.

## Commands

```bash
# Dependencies (uses uv)
uv sync --all-extras

# Unit tests
just unit                          # or: uv run pytest tests/unit
uv run pytest tests/unit -k "test_name"                        # single test by name
uv run pytest tests/unit/test_services.py                      # single file
uv run pytest tests/unit/test_services.py::TestClass            # single class
uv run pytest tests/unit/test_services.py::TestClass::test_foo  # single method

# E2E tests (Playwright)
just e2e                           # both backends
just e2e-po                        # PO backend only
just e2e-db                        # DB backend only

# Benchmarks
just bench                         # pytest-benchmark suite
just bench-ci                      # CI overhead ratio checks

# Lint & format
uv run ruff check src tests        # lint
uv run ruff check --fix src tests  # lint + autofix
uv run ruff format src tests       # format

# Type check (pyrefly, NOT mypy/pyright)
uv run pyrefly check

# Coverage (must be >= 90%)
uv run pytest tests/unit --cov --cov-report=term-missing
```

## Quality Gates

Before submitting work, verify:
1. `uv run ruff check src tests` -- no lint errors
2. `uv run ruff format --check src tests` -- formatting OK
3. `uv run pyrefly check` -- no type errors
4. `uv run pytest tests/unit --cov` -- tests pass, coverage >= 90%

## Project Layout

```
src/live_translations/       # Main Django app
  apps.py                    # AppConfig, system checks, gettext monkey-patch
  models.py                  # TranslationEntry, TranslationHistory
  services.py                # All business logic (views/admin are thin adapters)
  views.py                   # Function-based JSON API views
  middleware.py              # API dispatch, asset injection, contextvar mgmt
  conf.py                    # Settings resolution from LIVE_TRANSLATIONS dict
  strings.py                 # Gettext monkey-patching with ZWC markers
  history.py                 # Audit history recording
  types.py                   # TypedDicts, NamedTuples, type aliases
  admin.py                   # ModelAdmin for TranslationEntry/TranslationHistory
  backends/                  # Pluggable: base ABC, po.py, db.py
  migrations/
  static/live_translations/  # JS/CSS widget assets
tests/
  unit/                      # Pure unit tests (mocked backends, in-memory SQLite)
  e2e/                       # Playwright browser tests against live Django server
  benchmarks/                # Performance overhead tests
example/                     # Demo Django project for development/testing
```

## Code Style

### Imports

Three groups separated by blank lines: stdlib, third-party, first-party.

Third-party imports use **fully-qualified module imports** -- never `from django.http import X`:
```python
import django.http
import django.views.decorators.csrf

# Then use as:
def my_view(request: django.http.HttpRequest) -> django.http.JsonResponse: ...
```

First-party imports use `from`:
```python
from live_translations import conf, services
from live_translations.types import MsgKey, LanguageCode
```

### Type Hints

- **Always** on function signatures (params + return types)
- `import typing as t` -- use the `t.` prefix consistently
- Union syntax: `T | None` (never `Optional[T]`)
- No `from __future__ import annotations`
- Use `t.TYPE_CHECKING` blocks for import-only types
- Modern Python: `type` keyword for aliases, generic `[T]` syntax on functions
- Type checker is **pyrefly** (not mypy/pyright)

### General

- Every module defines `__all__` explicitly
- Minimal docstrings -- only when intent is non-obvious from the name
- Line length: **120 characters**

### Error Handling

- `ValueError` for validation errors
- `FileNotFoundError` for missing PO files
- Custom `PlaceholderValidationError(Exception)` with structured details
- Views map exceptions to HTTP status: `ValueError -> 400`, `Exception -> 500`
- Use `logger.exception()` for unexpected errors
- `contextlib.suppress(Exception)` for non-critical paths
- `# noqa: BLE001` on intentional broad `except Exception`

### Architecture

- **Views are thin** -- parse HTTP input, call `services.*`, map exceptions to responses
- **Services hold all logic** -- `services.py` is the core module
- **No CBVs** -- function-based views with decorators (`@require_GET`, `@csrf_protect`)
- **No urls.py** -- middleware dispatches API routes via path matching
- **Backend pattern** -- abstract `TranslationBackend` base, implementations in `backends/`
- **Django settings** -- single `LIVE_TRANSLATIONS` dict, resolved in `conf.py` with `@functools.cache`

## Test Conventions

- **pytest** with `pytest-django`
- **Class-based** test organization: `class TestSaveTranslations:`
- Plain `assert` statements (not `self.assertEqual`)
- `@pytest.mark.django_db` for database tests
- Fixtures in `conftest.py`: `make_request`, `make_db_backend`, autouse `_clear_conf_caches`
- Unit tests mock backends and external deps with `unittest.mock.patch`
- E2E tests use Playwright with session-scoped live servers (ports 8111/8112)

