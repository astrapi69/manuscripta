"""Lint test: the manuscripta library must never call os.chdir().

The v0.8.0 contract is that the library does not mutate process working
directory; callers own cwd, and the library anchors every path on an
explicit ``source_dir``. This test greps the shipped package for forbidden
patterns so the constraint survives future refactors.
"""

from __future__ import annotations
import pytest

pytestmark = pytest.mark.unit


import re
from pathlib import Path

import manuscripta

PACKAGE_ROOT = Path(manuscripta.__file__).resolve().parent

# Allow ``os.chdir`` mentions inside comments/docstrings (they document the
# contract), but forbid actual calls.
_FORBIDDEN = re.compile(r"^[^#\n]*\bos\.chdir\s*\(", re.MULTILINE)


def test_no_chdir_calls_in_library_sources():
    offenders: list[str] = []
    for py in PACKAGE_ROOT.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        # Strip triple-quoted docstrings to avoid false positives.
        text_no_docstrings = re.sub(
            r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'', "", text
        )
        for match in _FORBIDDEN.finditer(text_no_docstrings):
            line_no = text_no_docstrings[: match.start()].count("\n") + 1
            offenders.append(f"{py.relative_to(PACKAGE_ROOT)}:{line_no}")
    assert not offenders, (
        "manuscripta library must never call os.chdir(); offenders:\n  "
        + "\n  ".join(offenders)
    )
