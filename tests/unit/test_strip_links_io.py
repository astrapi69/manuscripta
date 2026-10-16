import pytest

pytestmark = pytest.mark.unit

# tests/test_strip_links_io.py
from pathlib import Path
from manuscripta.markdown.strip_links import process_file

# Each row: the text of t.md, overwrite?, the links counted, the file written
# (None: none), the files of the directory afterwards with their text
PROCESS_FILE_CASES = [
    pytest.param("A [b](c) D", True, 1, "t.md", {"t.md": "A b D"}, id="overwrite"),
    pytest.param(
        "no links here",
        False,
        0,
        None,
        {"t.md": "no links here"},
        id="copy-only-when-changed",
    ),
    pytest.param(
        "A [b](c)",
        False,
        1,
        "t-nolinks.md",
        {"t.md": "A [b](c)", "t-nolinks.md": "A b"},
        id="copy-when-changed",
    ),
    pytest.param(
        "no links here",
        True,
        0,
        None,
        {"t.md": "no links here"},
        id="overwrite-only-when-changed",
    ),
]


@pytest.mark.parametrize(
    "text, overwrite, count, written, files_after", PROCESS_FILE_CASES
)
def test_process_file(text, overwrite, count, written, files_after, tmp_path: Path):
    f = tmp_path / "t.md"
    f.write_text(text, encoding="utf-8")
    src, n, dest = process_file(f, overwrite=overwrite, suffix="-nolinks.md")
    assert src == f
    assert n == count
    assert dest == (None if written is None else tmp_path / written)
    assert {
        p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()
    } == files_after
