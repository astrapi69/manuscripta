"""Unit-layer conftest.

Default per-test timeout for the unit layer (Phase 4b Pass 2 Commit
10). Mutation testing scores timeouts against the module (ADR-0002
strict reading): an infinite-loop mutant that hangs an *unmarked*
test is recorded as ``timeout``, not ``killed``, because mutmut cuts
the whole pytest process before any assertion fails. A per-test
ceiling turns the hang into an ordinary test failure — a kill —
regardless of which unit test the mutant happens to hang first.

Unit tests are sub-second by contract (TESTING.md §2); 10 s is far
above any legitimate unit-test duration while staying below mutmut's
own process cut. Tests that declare an explicit ``@pytest.mark.
timeout(…)`` keep their own value.

pytest calls this hook with every collected item, not only those under
tests/unit, so the ceiling is applied by layer marker: the integration
and e2e layers build PDFs, wheels and venvs and take their time.
"""

from __future__ import annotations

import pytest

from manuscripta.export import book as _book

# The module-level path globals that manuscripta.export.book._configure_paths
# rewrites. main() and run_export() call it, so a test that drives either
# leaves absolute paths into its own tmp_path behind, and a later test that
# calls compile_book() appends to that LOG_FILE. The leak went unnoticed
# while every pytest session shared one basetemp whose directories outlived
# the session; mutmut's in-process sessions with a per-child basetemp (see
# tests/conftest.py) made it a FileNotFoundError in compile_book.
_BOOK_PATH_GLOBALS = (
    "BOOK_DIR",
    "OUTPUT_DIR",
    "BACKUP_DIR",
    "CONFIG_DIR",
    "METADATA_FILE",
    "EXPORT_SETTINGS_FILE",
    "TOC_FILE",
    "LOG_FILE",
)


@pytest.fixture(autouse=True)
def _restore_book_path_globals(monkeypatch):
    """Put manuscripta.export.book's path globals back after every unit test."""
    for name in _BOOK_PATH_GLOBALS:
        monkeypatch.setattr(_book, name, getattr(_book, name))


def pytest_collection_modifyitems(items):
    for item in items:
        if "unit" not in item.keywords:
            continue
        if item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(10))
