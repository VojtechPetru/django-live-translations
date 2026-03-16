# Run all tests (unit + e2e with both backends)
test: unit e2e

# Run unit tests
unit *args:
    pytest tests/unit {{ args }}

# Run e2e tests against both backends
e2e *args:
    pytest tests/e2e --backend=both {{ args }}

# Run e2e tests against po backend only
e2e-po *args:
    pytest tests/e2e --backend=po {{ args }}

# Run e2e tests against database backend only
e2e-db *args:
    pytest tests/e2e --backend=db {{ args }}

# Revert .po files to their git-committed state
revert-po:
    git checkout HEAD -- example/locale/
