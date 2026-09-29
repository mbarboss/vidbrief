# Recipes normally require literal tabs, which are often lost when copying from a
# browser; a visible prefix prevents the resulting "missing separator" errors.
.RECIPEPREFIX := >
.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test audit check

help: ## List available targets
> @grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install dependencies and git hooks
> uv sync
> uv run pre-commit install

lint: ## Lint and verify formatting
> uv run ruff check .
> uv run ruff format --check .

format: ## Auto-format and apply safe lint fixes
> uv run ruff format .
> uv run ruff check --fix .

typecheck: ## Static type checking (strict)
> uv run mypy src tests

test: ## Run unit tests with coverage
> uv run pytest

audit: ## Scan dependencies for known vulnerabilities
> uv export --format requirements-txt --no-emit-project --quiet -o .audit-requirements.txt
> uvx pip-audit --disable-pip -r .audit-requirements.txt; status=$$?; rm -f .audit-requirements.txt; exit $$status

check: lint typecheck test audit ## Run every quality gate
