"""Book-project layout builders used by test fixtures."""

from __future__ import annotations

from pathlib import Path


def scaffold(root: Path, *, title: str = "Test Book", lang: str = "en") -> None:
    """Create the minimal manuscripta-shaped directory tree under ``root``.

    Produces ``manuscript/{chapters,front-matter,back-matter}``, ``config/``
    with a ``metadata.yaml``, and an empty ``assets/``. Does not add any
    markdown or images — callers layer those on top.
    """
    (root / "manuscript" / "chapters").mkdir(parents=True, exist_ok=True)
    (root / "manuscript" / "front-matter").mkdir(parents=True, exist_ok=True)
    (root / "manuscript" / "back-matter").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "config" / "metadata.yaml").write_text(
        f'title: "{title}"\nauthor: "Tester"\nlang: "{lang}"\n',
        encoding="utf-8",
    )
