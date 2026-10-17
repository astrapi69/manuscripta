import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_links_to_plain_text.py
import locale
from contextlib import contextmanager
from pathlib import Path
from manuscripta.markdown.links_to_plain import (
    convert_links_in_text,
    convert_file,
    convert_many,
)


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@contextmanager
def c_locale(monkeypatch):
    """The C locale for the block: its codec is ASCII, so a file read or
    written with the locale default instead of UTF-8 cannot carry an
    umlaut."""
    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        yield
    finally:
        locale.setlocale(locale.LC_ALL, saved)


# Each row: text, the text with its links converted, the links counted
CONVERT_TEXT_CASES = [
    pytest.param(
        "Visit [Example](https://example.com) now.",
        "Visit Example: https://example.com now.",
        1,
        id="basic-link-conversion",
    ),
    pytest.param(
        "![Img](pic.png) and [anchor](#section)",
        "![Img](pic.png) and [anchor](#section)",
        0,
        id="skip-images-and-anchor-links",
    ),
    pytest.param(
        "```\n[Link](https://secret.com)\n``` and `[Another](https://skip.com)`",
        "```\n[Link](https://secret.com)\n``` and `[Another](https://skip.com)`",
        0,
        id="skip-links-in-code",
    ),
]


@pytest.mark.parametrize("text, expected, count", CONVERT_TEXT_CASES)
def test_convert_links_in_text(text, expected, count):
    assert convert_links_in_text(text) == (expected, count)


# Each row: the text of doc.md, (changed, links converted) returned, the text
# of doc.md afterwards
CONVERT_FILE_CASES = [
    pytest.param(
        "Go [Home](https://home.test) now.",
        (True, 1),
        "Go Home: https://home.test now.",
        id="converts-and-writes-back",
    ),
    # An unchanged file converted no link: the count is 0, not an arbitrary
    # number next to changed=False.
    pytest.param(
        "No links here",
        (False, 0),
        "No links here",
        id="unchanged-file-counts-no-link",
    ),
    pytest.param(
        "Jump to [Top](#top).",
        (False, 0),
        "Jump to [Top](#top).",
        id="anchor-only-file-is-unchanged",
    ),
]


@pytest.mark.parametrize("text, result, after", CONVERT_FILE_CASES)
def test_convert_file(text, result, after, tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text(text, encoding="utf-8")
    assert convert_file(f) == result
    assert f.read_text(encoding="utf-8") == after


def test_convert_file_reads_and_writes_utf8_under_c_locale(tmp_path, monkeypatch):
    """The file is read and written as UTF-8 whatever the locale: under
    LC_ALL=C the locale codec is ASCII and cannot carry the umlauts."""
    doc = tmp_path / "umlaut.md"
    doc.write_bytes("Über [Ärger](https://a.test) grün.".encode("utf-8"))
    with c_locale(monkeypatch):
        assert convert_file(doc) == (True, 1)
    assert doc.read_bytes() == "Über Ärger: https://a.test grün.".encode("utf-8")


# Each row: the files written (name -> text), the names passed, (files changed,
# links converted) returned, texts the output must carry, the files afterwards
# with their text
CONVERT_MANY_CASES = [
    pytest.param(
        {"file1.md": "Check [A](https://a.com)", "file2.md": "No links here"},
        ["file1.md", "file2.md"],
        (1, 1),
        ["file1.md"],
        {"file1.md": "Check A: https://a.com", "file2.md": "No links here"},
        id="counts-only-changed-files",
    ),
    # The counts add up across files: two changed files, three links.
    pytest.param(
        {
            "file1.md": "Check [A](https://a.com)",
            "file2.md": "[B](https://b.com) and [C](https://c.com)",
        },
        ["file1.md", "file2.md"],
        (2, 3),
        ["file1.md", "file2.md"],
        {
            "file1.md": "Check A: https://a.com",
            "file2.md": "B: https://b.com and C: https://c.com",
        },
        id="counts-add-up-across-changed-files",
    ),
    pytest.param(
        {"file1.md": "Check A: https://a.com", "file2.md": "No links here"},
        ["file1.md", "file2.md"],
        (0, 0),
        [],
        {"file1.md": "Check A: https://a.com", "file2.md": "No links here"},
        id="nothing-to-convert-counts-zero",
    ),
    pytest.param(
        {"file1.md": "Check [A](https://a.com)"},
        ["missing.md", "file1.md"],
        (1, 1),
        ["File not found", "missing.md"],
        {"file1.md": "Check A: https://a.com"},
        id="missing-file-is-reported-and-the-rest-converted",
    ),
]


@pytest.mark.parametrize(
    "files, names, result, reported, files_after", CONVERT_MANY_CASES
)
def test_convert_many(files, names, result, reported, files_after, tmp_path, capsys):
    for name, text in files.items():
        write(tmp_path / name, text)
    assert convert_many([tmp_path / name for name in names]) == result
    out, _ = capsys.readouterr()
    for line in reported:
        assert line in out
    assert {
        p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()
    } == files_after
