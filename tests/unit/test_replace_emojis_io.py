import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_emojis_io.py
from pathlib import Path
from manuscripta.markdown.emojis import process_file

# Each row: the text of a.md, overwrite?, the replacements counted, the file
# written (None: none), the files of the directory afterwards with their text
PROCESS_FILE_CASES = [
    pytest.param("hi 🔥", True, 1, "a.md", {"a.md": "hi +++"}, id="overwrite"),
    pytest.param(
        "no emojis here",
        False,
        0,
        None,
        {"a.md": "no emojis here"},
        id="copy-only-if-changed",
    ),
    pytest.param(
        "hi 🔥",
        False,
        1,
        "a-final.md",
        {"a.md": "hi 🔥", "a-final.md": "hi +++"},
        id="copy-when-changed",
    ),
    pytest.param(
        "no emojis here",
        True,
        0,
        None,
        {"a.md": "no emojis here"},
        id="overwrite-only-if-changed",
    ),
]


@pytest.mark.parametrize(
    "text, overwrite, count, written, files_after", PROCESS_FILE_CASES
)
def test_process_file(text, overwrite, count, written, files_after, tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text(text, encoding="utf-8")
    s, n, dest = process_file(
        src,
        overwrite=overwrite,
        suffix="-final.md",
        mapping={"🔥": "+++"},
        encoding="utf-8",
    )
    assert s == src
    assert n == count
    assert dest == (None if written is None else tmp_path / written)
    assert {
        p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()
    } == files_after
