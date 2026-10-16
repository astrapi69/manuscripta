import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_md_bullet_points.py
import locale
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path

import manuscripta.markdown.bullet_points as bp
from manuscripta.markdown.bullet_points import (
    convert_bullets_in_text,
    main,
    process_file,
    process_path,
)

PROG = "replace-md-bullet-points"


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


def seed(root: Path, files: dict[str, str]) -> None:
    """Write the files (path below root -> text), creating their directories."""
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def files_of(root: Path) -> dict[str, str]:
    """Every file below root (path below root -> text)."""
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file()
    }


# Each row: text and the text with its bullets converted
BULLET_CASES = [
    pytest.param(
        "- First item\n* Second item\nNormal line\n",
        "• First item  \n• Second item  \nNormal line\n",
        id="simple-dash-and-star-bullets",
    ),
    pytest.param(
        "- First item with continuation line\n"
        "  second line of the item\n"
        "Next normal line\n",
        "• First item with continuation line  \n"
        "  second line of the item  \n"
        "Next normal line\n",
        id="multiline-bullet-item",
    ),
    pytest.param(
        "- Point one\nNormal line\n  Not a follow-item, just indented\n",
        "• Point one  \nNormal line\n  Not a follow-item, just indented\n",
        id="list-state-resets-for-non-indented-line",
    ),
    pytest.param(
        "```python\n- this is not a bullet, but code\n```\n- actual bullet\n",
        "```python\n- this is not a bullet, but code\n```\n• actual bullet  \n",
        id="code-block-is-ignored",
    ),
    pytest.param(
        "Normal line\n"
        "  indented line without a list\n"
        "- List item\n"
        "  continuation line\n",
        "Normal line\n"
        "  indented line without a list\n"
        "• List item  \n"
        "  continuation line  \n",
        id="indented-follow-line-without-list-start-not-treated-as-bullet",
    ),
    pytest.param(
        "- outer\n  - inner\n",
        "• outer  \n  • inner  \n",
        id="nested-bullets-keep-their-indent",
    ),
    pytest.param(
        "- a\n\n  not a continuation\n",
        "• a  \n\n  not a continuation\n",
        id="blank-line-ends-the-list",
    ),
    pytest.param(
        "* * *\n- a\n",
        "* * *\n• a  \n",
        id="spaced-star-thematic-break-is-left-alone",
    ),
    pytest.param(
        "- a\n- - -\n- b\n",
        "• a  \n- - -\n• b  \n",
        id="spaced-dash-thematic-break-ends-the-list",
    ),
    pytest.param(
        "***\n---\n___\n_ _ _ _\n",
        "***\n---\n___\n_ _ _ _\n",
        id="bare-thematic-breaks-are-left-alone",
    ),
    pytest.param(
        "- a\n  * * *\n",
        "• a  \n  * * *\n",
        id="indented-thematic-break-gets-no-hard-break",
    ),
    pytest.param(
        "* * item\n- - x -\n",
        "• * item  \n• - x -  \n",
        id="markers-followed-by-text-are-bullets",
    ),
    pytest.param(
        "  indented first line\n- a\n",
        "  indented first line\n• a  \n",
        id="an-indented-first-line-is-no-continuation",
    ),
    pytest.param(
        "- a\n***\n  plain\n",
        "• a  \n***\n  plain\n",
        id="a-thematic-break-ends-the-list-for-the-indented-line-after-it",
    ),
    pytest.param(
        "- a\n   \nplain\n",
        "• a  \n   \nplain\n",
        id="a-whitespace-only-line-is-blank-and-ends-the-list",
    ),
]


@pytest.mark.parametrize("text, expected", BULLET_CASES)
def test_convert_bullets_in_text(text, expected):
    assert convert_bullets_in_text(text) == expected


# Each row: text and the text with its bullets converted without hard breaks
NO_HARD_BREAK_CASES = [
    pytest.param("- a\n* b\n", "• a\n• b\n", id="bullets-get-no-trailing-spaces"),
    pytest.param(
        "- a\n  more\nplain\n",
        "• a\n  more\nplain\n",
        id="continuation-lines-get-no-trailing-spaces",
    ),
]


@pytest.mark.parametrize("text, expected", NO_HARD_BREAK_CASES)
def test_convert_bullets_in_text_without_hard_breaks(text, expected):
    assert convert_bullets_in_text(text, add_hard_break=False) == expected


# ---------------------------------------------------------------------------
# process_file / process_path
# ---------------------------------------------------------------------------
# Each row: the files seeded below tmp_path (path -> text), the target below
# tmp_path, hard breaks?, whether the target was found, the files afterwards
# (path -> text), the lines printed to stdout (TMP stands for tmp_path), the
# lines printed to stderr
PROCESS_PATHS = [
    pytest.param(
        {"a.md": "- x\n"},
        "a.md",
        True,
        True,
        {"a.md": "• x  \n"},
        ["[OK] TMP/a.md"],
        [],
        id="file-target",
    ),
    pytest.param(
        {"a.md": "- x\n  more\n"},
        "a.md",
        False,
        True,
        {"a.md": "• x\n  more\n"},
        ["[OK] TMP/a.md"],
        [],
        id="file-target-without-hard-breaks",
    ),
    pytest.param(
        {"a.md": "- x\n", "sub/b.md": "* y\n", "sub/c.txt": "- z\n"},
        ".",
        True,
        True,
        {"a.md": "• x  \n", "sub/b.md": "• y  \n", "sub/c.txt": "- z\n"},
        ["[OK] TMP/a.md", "[OK] TMP/sub/b.md"],
        [],
        id="directory-target-recurses-over-md-files-only",
    ),
    pytest.param(
        {"a.md": "- x\n"},
        "missing.md",
        True,
        False,
        {"a.md": "- x\n"},
        [],
        ["[ERROR] Path not found: TMP/missing.md"],
        id="missing-target-is-reported-on-stderr",
    ),
    pytest.param(
        {"a.md": "- x\n", "sub/b.md": "- y\n  more\n"},
        ".",
        False,
        True,
        {"a.md": "• x\n", "sub/b.md": "• y\n  more\n"},
        ["[OK] TMP/a.md", "[OK] TMP/sub/b.md"],
        [],
        id="directory-target-without-hard-breaks",
    ),
]


@pytest.mark.parametrize(
    "files, target, hard_break, found, files_after, out_lines, err_lines",
    PROCESS_PATHS,
)
def test_process_path(
    files,
    target,
    hard_break,
    found,
    files_after,
    out_lines,
    err_lines,
    tmp_path,
    capsys,
):
    seed(tmp_path, files)
    assert process_path(tmp_path / target, add_hard_break=hard_break) is found
    out, err = capsys.readouterr()
    assert files_of(tmp_path) == files_after
    assert sorted(out.splitlines()) == [
        line.replace("TMP", str(tmp_path)) for line in out_lines
    ]
    assert err.splitlines() == [
        line.replace("TMP", str(tmp_path)) for line in err_lines
    ]


def test_process_file_writes_the_conversion_back_and_reports(tmp_path, capsys):
    path = tmp_path / "a.md"
    path.write_text("- x\n", encoding="utf-8")
    process_file(path)
    assert path.read_text(encoding="utf-8") == "• x  \n"
    assert capsys.readouterr().out == f"[OK] {path}\n"


def test_process_file_reads_and_writes_utf8_under_c_locale(tmp_path, monkeypatch):
    """The file is read and written as UTF-8 whatever the locale: under
    LC_ALL=C the locale codec is ASCII and can carry neither the umlaut nor
    the bullet."""
    path = tmp_path / "a.md"
    path.write_bytes("- Grüße\n".encode("utf-8"))
    with c_locale(monkeypatch):
        process_file(path)
    assert path.read_bytes().decode("utf-8") == "• Grüße  \n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def run_main(monkeypatch, *argv: str) -> int:
    """main() driven through sys.argv; its exit status (0 when it returns)."""
    monkeypatch.setattr(sys, "argv", [PROG, *argv])
    try:
        main()
    except SystemExit as exc:
        return exc.code
    return 0


# Each row: the arguments (FILE stands for a.md holding "- x", MISSING for a
# path to no file), the exit status, the text of a.md afterwards, the lines
# printed to stdout, the lines printed to stderr
MAIN_RUNS = [
    pytest.param(
        [],
        1,
        "- x\n",
        ["Usage: replace_md_bullet_points.py <file-or-dir>"],
        [],
        id="no-argument-prints-the-usage-and-exits-1",
    ),
    pytest.param(
        ["FILE"], 0, "• x  \n", ["[OK] FILE"], [], id="converts-with-hard-breaks"
    ),
    pytest.param(
        ["FILE", "ignored"],
        0,
        "• x  \n",
        ["[OK] FILE"],
        [],
        id="only-the-first-argument-counts",
    ),
    pytest.param(
        ["MISSING"],
        1,
        "- x\n",
        [],
        ["[ERROR] Path not found: MISSING"],
        id="missing-path-is-reported-and-exits-1",
    ),
]


@pytest.mark.parametrize("argv, code, text_after, out_lines, err_lines", MAIN_RUNS)
def test_main(
    argv, code, text_after, out_lines, err_lines, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "a.md"
    path.write_text("- x\n", encoding="utf-8")
    names = {"FILE": str(path), "MISSING": str(tmp_path / "missing.md")}

    def fill(text: str) -> str:
        for token, value in names.items():
            text = text.replace(token, value)
        return text

    assert run_main(monkeypatch, *[fill(arg) for arg in argv]) == code
    assert path.read_text(encoding="utf-8") == text_after
    out, err = capsys.readouterr()
    assert out == "".join(fill(line) + "\n" for line in out_lines)
    assert err == "".join(fill(line) + "\n" for line in err_lines)


def test_script_run_as_main(tmp_path, monkeypatch, capsys):
    path = tmp_path / "a.md"
    path.write_text("- x\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [PROG, str(path)])
    runpy.run_path(bp.__file__, run_name="__main__")
    assert path.read_text(encoding="utf-8") == "• x  \n"
    assert capsys.readouterr().out == f"[OK] {path}\n"
