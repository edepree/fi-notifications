# list available recipes
help:
    @just --list

# install dependencies, including the dev group
sync:
    uv sync

# run the test suite, passing any extra args to pytest
test *args:
    uv run pytest {{args}}

# lint with ruff
lint:
    uv run ruff check

# format and auto-fix lint issues with ruff
fmt:
    uv run ruff format
    uv run ruff check --fix

# type check with ty
typecheck:
    uv run ty check

# test, lint, format check, types
check: test lint typecheck
    uv run ruff format --check

# Build the Docker image locally
docker-build:
    docker build -t fi-notifications .
