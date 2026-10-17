import pytest

pytestmark = pytest.mark.unit

# tests/test_strip_links_io.py
import locale
from contextlib import contextmanager
from pathlib import Path
from manuscripta.markdown.strip_links import process_file


@contextmanager
def c_locale(monkeypatch):
    """The C locale for the block: its codec is ASCII, so a file read or
    written with the locale default instead of the encoding given cannot
    carry an umlaut."""
    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_ALL, saved)


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


# Each row: overwrite?, the file the stripped text lands in
UTF8_UNDER_C_LOCALE = [
    pytest.param(True, "t.md", id="overwrite"),
    pytest.param(False, "t-nolinks.md", id="copy"),
]


@pytest.mark.parametrize("overwrite, written", UTF8_UNDER_C_LOCALE)
def test_process_file_reads_and_writes_utf8_under_c_locale(
    overwrite, written, tmp_path, monkeypatch
):
    """Without an encoding argument the file is read and written as UTF-8
    whatever the locale: under LC_ALL=C the locale codec is ASCII and cannot
    carry the umlauts."""
    f = tmp_path / "t.md"
    f.write_bytes("Über [Ärger](x) grün".encode("utf-8"))
    with c_locale(monkeypatch):
        assert process_file(f, overwrite=overwrite, suffix="-nolinks.md") == (
            f,
            1,
            tmp_path / written,
        )
    assert (tmp_path / written).read_bytes() == "Über Ärger grün".encode("utf-8")
