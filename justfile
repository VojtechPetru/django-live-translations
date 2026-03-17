# List available commands
help:
    @just --list

# Run all tests (unit + e2e with both backends)
test: unit e2e

# Run unit tests
unit *args:
    uv run pytest tests/unit {{ args }}

# Run e2e tests against both backends
e2e *args:
    uv run pytest tests/e2e --backend=both {{ args }}

# Run e2e tests against po backend only
e2e-po *args:
    uv run pytest tests/e2e --backend=po {{ args }}

# Run e2e tests against database backend only
e2e-db *args:
    uv run pytest tests/e2e --backend=db {{ args }}

# Revert .po files to their git-committed state
revert-po:
    git checkout HEAD -- example/locale/

# Run the demo app dev server
demo *args:
    uv run python example/manage.py runserver {{ args }}

# Serve docs locally
docs-serve:
    uv run zensical serve

# Build docs
docs-build:
    uv run zensical build --clean
