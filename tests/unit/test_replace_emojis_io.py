import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_emojis_io.py
import locale
from contextlib import contextmanager
from pathlib import Path

from manuscripta.markdown.emojis import process_file


@contextmanager
def c_locale(monkeypatch):
    """LC_ALL=C for the block: the locale codec is ASCII and can carry no
    non-ASCII text, so a read or write that relies on it fails."""
    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_ALL, saved)


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


# Each row: overwrite?, the files of the directory afterwards (name -> text)
# for a.md holding "Grüße 🔥" and the mapping 🔥 -> +++
C_LOCALE_MODES = [
    pytest.param(True, {"a.md": "Grüße +++"}, id="overwrite"),
    pytest.param(False, {"a.md": "Grüße 🔥", "a-final.md": "Grüße +++"}, id="copy"),
]


@pytest.mark.parametrize("overwrite, files_after", C_LOCALE_MODES)
def test_process_file_reads_and_writes_the_given_encoding_under_c_locale(
    overwrite, files_after, tmp_path, monkeypatch
):
    """The source is read and the result written in the encoding given,
    whatever the locale: under LC_ALL=C the locale codec is ASCII and can
    carry neither the umlauts nor the emoji."""
    src = tmp_path / "a.md"
    src.write_bytes("Grüße 🔥".encode("utf-8"))
    with c_locale(monkeypatch):
        process_file(
            src,
            overwrite=overwrite,
            suffix="-final.md",
            mapping={"🔥": "+++"},
            encoding="utf-8",
        )
    assert {
        p.name: p.read_bytes().decode("utf-8") for p in tmp_path.iterdir()
    } == files_after
