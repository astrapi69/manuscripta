.DEFAULT_GOAL := help
SHELL := /bin/bash

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

.PHONY: lock-install install install-dev update update-deps hooks

lock-install: ## Lock and install project dependencies
	poetry lock
	poetry install

install: ## Install project with all dependencies
	poetry install

install-dev: ## Install with dev dependencies
	poetry install --with dev

update: ## Update dependencies
	poetry update

update-deps: ## Update dependencies, verify build, and run tests
	poetry update
	poetry build
	poetry run pytest -q --maxfail=1 --disable-warnings --no-cov

hooks: ## Install pre-commit hooks
	poetry run pre-commit install

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

.PHONY: lint lint-fix format format-check fix typecheck codespell codespell-fix precommit

lint: ## Run ruff linter
	poetry run ruff check src/ tests/

lint-fix: ## Run ruff linter with auto-fix
	poetry run ruff check src/ tests/ --fix --unsafe-fixes

format: ## Format code with black
	poetry run black src/ tests/

format-check: ## Check formatting without changes
	poetry run black --check src/ tests/

fix: ## Run all auto-fixes (ruff + black)
	poetry run ruff check src/ tests/ --fix --unsafe-fixes
	poetry run black src/ tests/

typecheck: ## Run MyPy type checks
	poetry run mypy src/

codespell: ## Run codespell
	poetry run codespell src/ tests/

codespell-fix: ## Run codespell with auto-fix
	poetry run codespell src/ tests/ --write-changes

precommit: ## Run all pre-commit hooks
	poetry run pre-commit run -a

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

.PHONY: test test-v test-fast test-cov test-xml

test: ## Run all tests
	poetry run pytest

test-v: ## Run all tests (verbose)
	poetry run pytest -v

test-fast: ## Run tests without coverage (faster)
	poetry run pytest -q --maxfail=1 --disable-warnings --no-cov

test-cov: ## Run tests with coverage report
	poetry run pytest --cov=manuscripta --cov-report=term-missing

test-xml: ## Run tests with XML coverage (for CI)
	poetry run pytest -q --maxfail=1 --disable-warnings --cov=manuscripta --cov-report=xml

# ---------------------------------------------------------------------------
# Mutation testing (Phase 4b)
# ---------------------------------------------------------------------------
# Runs nightly in CI, not per-PR (~10+ min). Not a merge gate; a quality
# signal. Scope and thresholds live in pyproject.toml; policy in
# docs/decisions/0002-mutation-testing.md; response workflow in TESTING.md §14.

.PHONY: mutation mutation-check mutation-report mutation-fast

mutation: ## Run mutation tests on the configured scope (no threshold enforcement)
	poetry run --with mutation mutmut run

mutation-check: mutation ## Run mutation tests + enforce per-module thresholds (CI gate)
	poetry run python scripts/check_mutation_thresholds.py

mutation-report: ## Print a human-readable report of surviving mutants
	poetry run --with mutation mutmut results

mutation-fast: ## Dev loop — mutate only modules changed since main
	@CHANGED=$$(git diff --name-only origin/main...HEAD -- 'src/manuscripta/**/*.py' | tr '\n' ' '); \
	if [ -z "$$CHANGED" ]; then \
		echo "No Python sources changed vs origin/main; nothing to mutate."; \
		exit 0; \
	fi; \
	echo "Mutating only: $$CHANGED"; \
	poetry run --with mutation mutmut run $$CHANGED

# ---------------------------------------------------------------------------
# CI
# ---------------------------------------------------------------------------

.PHONY: ci

ci: lint format-check test ## Full CI pipeline (lint + format-check + test)

# ---------------------------------------------------------------------------
# Version Management
# ---------------------------------------------------------------------------

.PHONY: bump-patch bump-minor bump-major tag-message

bump-patch: ## Bump patch version (0.1.0 -> 0.1.1)
	poetry version patch

bump-minor: ## Bump minor version (0.1.0 -> 0.2.0)
	poetry version minor

bump-major: ## Bump major version (0.1.0 -> 1.0.0)
	poetry version major

tag-message: ## Interactive: generate tag message and (optionally) create tag
	poetry run make-tag-message

# ---------------------------------------------------------------------------
# Build & Publish
# ---------------------------------------------------------------------------

.PHONY: build publish publish-test

build: ## Build distribution package
	poetry build

publish: ci build ## Run CI, build and publish to PyPI
	poetry publish

publish-test: ci build ## Run CI, build and publish to TestPyPI
	poetry publish -r testpypi

# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

.PHONY: git-setup

git-setup: ## Configure git hooks and commit template
	git config core.hooksPath .githooks
	git config commit.template .gitmessage
	chmod +x .githooks/*
	@echo "Git hooks and commit template activated."

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

.PHONY: clean clean-venv

clean: ## Remove build artifacts and caches
	rm -rf dist/ build/ .pytest_cache/ .ruff_cache/ .mypy_cache/ .coverage coverage.xml
	find src/ tests/ -type d -name __pycache__ -exec rm -rf {} +
	find . -name '*.pyc' -delete

clean-venv: ## Remove Poetry virtualenv
	poetry env remove --all || true

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
