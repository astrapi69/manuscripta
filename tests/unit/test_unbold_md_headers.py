# tests/test_unbold_md_headers.py
import argparse
import locale
import re
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

import manuscripta.markdown.unbold_headers as m


def write(p: Path, text: str, enc: str = "utf-8"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding=enc)
    return p


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


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


MIXED_SRC = """# **Main Title**
Some paragraph with **bold** should stay bold.
### **From Paper to Practice**
End.
"""
MIXED_EXPECTED = """# Main Title
Some paragraph with **bold** should stay bold.
### From Paper to Practice
End.
"""
LEVELS_SRC = """## **Keep Bold** (H2)
### **Change Me** (H3)
#### **Also Change Me** (H4)
"""
LEVELS_EXPECTED = """## **Keep Bold** (H2)
### Change Me (H3)
#### Also Change Me (H4)
"""

# Each row: the text of doc.md, the header levels allowed (None: all), dry run?,
# backup?, the changes counted, written?, the text of doc.md afterwards, whether
# doc.md.bak exists afterwards (holding the original text)
PROCESS_FILE_CASES = [
    pytest.param(
        MIXED_SRC,
        None,
        False,
        True,
        2,
        True,
        MIXED_EXPECTED,
        True,
        id="header-bold-removed-only-in-headers",
    ),
    # Only levels 3 and 4
    pytest.param(
        LEVELS_SRC,
        {3, 4},
        False,
        False,
        2,
        True,
        LEVELS_EXPECTED,
        False,
        id="levels-filter-only-h3-changes",
    ),
    # File unchanged
    pytest.param(
        "### **X**\n",
        None,
        True,
        True,
        1,
        False,
        "### **X**\n",
        False,
        id="dry-run-reports-but-does-not-write",
    ),
    pytest.param(
        "### **Title**\n",
        None,
        False,
        False,
        1,
        True,
        "### Title\n",
        False,
        id="no-backup-when-disabled",
    ),
    pytest.param(
        "### Title\nParagraph **bold** stays.\n",
        None,
        False,
        True,
        0,
        False,
        "### Title\nParagraph **bold** stays.\n",
        False,
        id="no-change-when-no-bold-in-header",
    ),
    pytest.param(
        "### **Title** with suffix\n",
        None,
        False,
        False,
        1,
        True,
        "### Title with suffix\n",
        False,
        id="trailing-text-after-bold-is-preserved",
    ),
    pytest.param(
        "# **A**\n", {1}, False, False, 1, True, "# A\n", False, id="levels-h1"
    ),
    pytest.param(
        "## **A**\n", {2}, False, False, 1, True, "## A\n", False, id="levels-h2"
    ),
    pytest.param(
        "### **A**\n", {3}, False, False, 1, True, "### A\n", False, id="levels-h3"
    ),
    pytest.param(
        "### **A**\n",
        {4},
        False,
        False,
        0,
        False,
        "### **A**\n",
        False,
        id="levels-h4-leaves-h3",
    ),
    pytest.param(
        "###### **A**\n",
        None,
        False,
        False,
        1,
        True,
        "###### A\n",
        False,
        id="levels-none-allows-h6",
    ),
    # An indented header (CommonMark allows up to three spaces) is still a
    # header; the indentation is kept
    pytest.param(
        "  ### **A**\n",
        None,
        False,
        False,
        1,
        True,
        "  ### A\n",
        False,
        id="indented-header-unbolded-indentation-kept",
    ),
]


@pytest.mark.parametrize(
    "src, levels, dry_run, backup, changes, written, text_after, bak_exists",
    PROCESS_FILE_CASES,
)
def test_process_file(
    src, levels, dry_run, backup, changes, written, text_after, bak_exists, tmp_path
):
    f = write(tmp_path / "doc.md", src)
    assert m.process_file(f, allowed_levels=levels, dry_run=dry_run, backup=backup) == (
        changes,
        written,
    )
    assert read(f) == text_after

    bak = f.with_suffix(".md.bak")
    assert bak.exists() is bak_exists
    if bak_exists:
        # Backup created and equals original
        assert read(bak) == src


def test_recursive_and_extensions(tmp_path: Path):
    # Create .mdx in subdir and .md in root
    mdx = write(tmp_path / "a/b/c.mdx", "### **MDX Title**\n")
    md = write(tmp_path / "root.md", "### **MD Title**\n")

    files = list(m.iter_files([tmp_path], recursive=True, ext=(".md", ".mdx")))
    # Both should be found
    assert set(p.suffix for p in files) == {".md", ".mdx"}

    # Process both
    total_changes = 0
    for p in files:
        ch, wrote = m.process_file(p, allowed_levels=None, dry_run=False, backup=False)
        assert wrote is True
        total_changes += ch

    assert total_changes == 2
    assert read(mdx) == "### MDX Title\n"
    assert read(md) == "### MD Title\n"


UMLAUT_SRC = "### **Über**\n"
UMLAUT_EXPECTED = "### Über\n"

# Each row: the encoding given, the bytes of doc.md, the (changes, written)
# returned, the bytes of doc.md afterwards, the bytes of doc.md.bak (None: no
# backup file). The encoding given, not the locale's, decodes the file and
# encodes the backup and the result
PROCESS_FILE_ENCODINGS = [
    pytest.param(
        "utf-8",
        UMLAUT_SRC.encode("utf-8"),
        (1, True),
        UMLAUT_EXPECTED.encode("utf-8"),
        UMLAUT_SRC.encode("utf-8"),
        id="utf-8-read-backup-and-write",
    ),
    pytest.param(
        "latin-1",
        UMLAUT_SRC.encode("latin-1"),
        (1, True),
        UMLAUT_EXPECTED.encode("latin-1"),
        UMLAUT_SRC.encode("latin-1"),
        id="latin-1-read-backup-and-write",
    ),
    pytest.param(
        "utf-8",
        UMLAUT_SRC.encode("latin-1"),
        (0, False),
        UMLAUT_SRC.encode("latin-1"),
        None,
        id="file-not-in-the-given-encoding-is-reported-and-left-alone",
    ),
]


@pytest.mark.parametrize(
    "encoding, src, result, doc_after, bak_after", PROCESS_FILE_ENCODINGS
)
def test_process_file_honours_the_encoding(
    encoding, src, result, doc_after, bak_after, tmp_path
):
    doc = tmp_path / "doc.md"
    doc.write_bytes(src)
    assert (
        m.process_file(doc, allowed_levels=None, backup=True, encoding=encoding)
        == result
    )
    assert doc.read_bytes() == doc_after
    bak = tmp_path / "doc.md.bak"
    assert (bak.read_bytes() if bak.exists() else None) == bak_after


# Each row: a line as read from the file, the levels allowed (None: all),
# whether the line is a header within the allowed levels (the docstring of
# levels_filter)
LEVELS_FILTER_CASES = [
    pytest.param("### A\n", None, True, id="header-any-level"),
    pytest.param("### A\n", {3}, True, id="header-level-allowed"),
    pytest.param("### A\n", {2, 4}, False, id="header-level-not-allowed"),
    pytest.param("Paragraph\n", None, False, id="paragraph-is-no-header"),
    pytest.param("**Bold** text\n", {1}, False, id="bold-paragraph-is-no-header"),
    pytest.param("  ### A\n", None, True, id="indented-header-any-level"),
    pytest.param("  ## A\n", {2}, True, id="indented-header-level-counted"),
]


@pytest.mark.parametrize("line, levels, is_header", LEVELS_FILTER_CASES)
def test_levels_filter(line, levels, is_header):
    assert m.levels_filter(line, levels) is is_header


# Each row: a line as read from the file, the line transformed, changed?
TRANSFORM_LINE_CASES = [
    pytest.param("### **Title**\n", "### Title\n", True, id="lf-kept"),
    pytest.param("### **Title**\r\n", "### Title\r\n", True, id="crlf-kept"),
    pytest.param("### **Title**", "### Title", True, id="no-eol-at-end-of-file"),
    pytest.param("### Title\n", "### Title\n", False, id="plain-header-untouched"),
    pytest.param(
        "**Bold** paragraph\n", "**Bold** paragraph\n", False, id="paragraph-untouched"
    ),
]


@pytest.mark.parametrize("line, expected, changed", TRANSFORM_LINE_CASES)
def test_transform_line(line, expected, changed):
    assert m.transform_line(line) == (expected, changed)


TREE = {
    "root.md": "",
    "ROOT2.MD": "",
    "notes.txt": "",
    "sub/inner.md": "",
    "sub/deep/leaf.markdown": "",
}

# Each row: the paths given, relative to the tree root ([]: the current
# directory), recursive?, the extensions, the files found (relative to the root)
ITER_FILES_CASES = [
    pytest.param(
        [], False, (".md",), {"root.md", "ROOT2.MD"}, id="default-is-cwd-top-level"
    ),
    pytest.param(
        ["."],
        True,
        (".md", ".markdown"),
        {"root.md", "ROOT2.MD", "sub/inner.md", "sub/deep/leaf.markdown"},
        id="recursive-all-extensions",
    ),
    pytest.param(["sub"], False, (".md",), {"sub/inner.md"}, id="subdir-top-level"),
    pytest.param(
        ["root.md", "notes.txt"],
        False,
        (".md",),
        {"root.md"},
        id="explicit-files-filtered-by-extension",
    ),
    pytest.param(["missing"], True, (".md",), set(), id="missing-path-yields-nothing"),
]


@pytest.mark.parametrize("paths, recursive, ext, found", ITER_FILES_CASES)
def test_iter_files(paths, recursive, ext, found, tmp_path, monkeypatch):
    for name, text in TREE.items():
        write(tmp_path / name, text)
    monkeypatch.chdir(tmp_path)
    files = m.iter_files([Path(p) for p in paths], recursive, ext)
    assert {f.resolve().relative_to(tmp_path).as_posix() for f in files} == found


def unreadable(doc: Path, monkeypatch):
    """doc.md is a directory: reading it fails."""
    doc.mkdir()


def backup_blocked(doc: Path, monkeypatch):
    """doc.md.bak is a directory: the backup cannot be written."""
    write(doc, "### **A**\n")
    doc.with_suffix(".md.bak").mkdir()


def write_blocked(doc: Path, monkeypatch):
    """Writing doc.md itself fails; the backup goes through."""
    write(doc, "### **A**\n")
    real_write_text = Path.write_text

    def write_text(self, *args, **kwargs):
        if self == doc:
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)


# Each row: the builder breaking the file system, the start of the "[ERROR]"
# line printed to stderr ({doc}: doc.md, {bak}: doc.md.bak), the text of doc.md
# afterwards (None: not a readable file), the text of doc.md.bak (None: no
# backup file)
PROCESS_FILE_ERRORS = [
    pytest.param(
        unreadable, "[ERROR] Failed to read {doc}: ", None, None, id="unreadable-file"
    ),
    pytest.param(
        backup_blocked,
        "[ERROR] Backup failed {bak}: ",
        "### **A**\n",
        None,
        id="backup-fails-before-writing",
    ),
    pytest.param(
        write_blocked,
        "[ERROR] Write failed {doc}: ",
        "### **A**\n",
        "### **A**\n",
        id="write-fails-after-backup",
    ),
]


@pytest.mark.parametrize("sabotage, error, doc_text, bak_text", PROCESS_FILE_ERRORS)
def test_process_file_reports_errors(
    sabotage, error, doc_text, bak_text, tmp_path, monkeypatch, capsys
):
    doc = tmp_path / "doc.md"
    bak = tmp_path / "doc.md.bak"
    sabotage(doc, monkeypatch)
    assert m.process_file(doc, allowed_levels=None, backup=True) == (0, False)
    assert capsys.readouterr().err.startswith(error.format(doc=doc, bak=bak))
    assert (read(doc) if doc.is_file() else None) == doc_text
    assert (read(bak) if bak.is_file() else None) == bak_text


# Each row: the --levels value and the set it parses to (None: all levels)
PARSE_LEVELS_CASES = [
    pytest.param(None, None, id="none"),
    pytest.param("", None, id="empty"),
    pytest.param("3", {3}, id="single"),
    pytest.param("2,3,4", {2, 3, 4}, id="list"),
    pytest.param(" 2 , 3 ", {2, 3}, id="whitespace-stripped"),
    pytest.param("2,,3,", {2, 3}, id="empty-parts-skipped"),
    pytest.param("1,9", {1}, id="out-of-range-dropped"),
    pytest.param("0,7", None, id="only-out-of-range-means-all"),
    # Markdown has six levels; both ends of 1-6 are allowed
    pytest.param("1,6", {1, 6}, id="bounds-one-and-six-kept"),
]


@pytest.mark.parametrize("value, levels", PARSE_LEVELS_CASES)
def test_parse_levels(value, levels):
    assert m.parse_levels(value) == levels


def test_parse_levels_rejects_non_numbers():
    with pytest.raises(argparse.ArgumentTypeError, match="Invalid level: x"):
        m.parse_levels("2,x")


BOOK = {
    "intro.md": "# **Intro**\n",
    "notes.markdown": "## **Notes**\n",
    "sub/deep.md": "### **Deep**\n",
    "readme.txt": "# **Text**\n",
}


def snapshot(root: Path) -> dict[str, str]:
    """Every file under ``root`` with its text, keyed by its relative path."""
    return {
        p.relative_to(root).as_posix(): read(p) for p in root.rglob("*") if p.is_file()
    }


# Each row: how the arguments reach main ("sys.argv": set as the process
# arguments, "argv": passed to main directly), the arguments after the program
# name (run inside the tree root), the files changed (name -> text afterwards;
# the others keep their text), the backups written (name -> text), the "[OK]"
# lines printed, the summary line, the stderr
MAIN_RUNS = [
    pytest.param(
        "sys.argv",
        [],
        {"intro.md": "# Intro\n", "notes.markdown": "## Notes\n"},
        {"intro.md.bak": "# **Intro**\n", "notes.markdown.bak": "## **Notes**\n"},
        {"[OK] intro.md: 1 change(s)", "[OK] notes.markdown: 1 change(s)"},
        "Summary: scanned=2, changes=2, written=2",
        "",
        id="defaults-top-level-with-backups",
    ),
    pytest.param(
        "sys.argv",
        ["-r", "--no-backup", "."],
        {
            "intro.md": "# Intro\n",
            "notes.markdown": "## Notes\n",
            "sub/deep.md": "### Deep\n",
        },
        {},
        {
            "[OK] intro.md: 1 change(s)",
            "[OK] notes.markdown: 1 change(s)",
            "[OK] sub/deep.md: 1 change(s)",
        },
        "Summary: scanned=3, changes=3, written=3",
        "",
        id="recursive-without-backups",
    ),
    pytest.param(
        "sys.argv",
        ["--dry-run", "-r", "."],
        {},
        {},
        {
            "[OK] intro.md: 1 change(s) (dry-run)",
            "[OK] notes.markdown: 1 change(s) (dry-run)",
            "[OK] sub/deep.md: 1 change(s) (dry-run)",
        },
        "Summary: scanned=3, changes=3, written=0",
        "",
        id="dry-run-counts-but-writes-nothing",
    ),
    pytest.param(
        "sys.argv",
        ["-L", "1", "-r", "--no-backup", "."],
        {"intro.md": "# Intro\n"},
        {},
        {"[OK] intro.md: 1 change(s)"},
        "Summary: scanned=3, changes=1, written=1",
        "",
        id="levels-restrict-to-h1",
    ),
    pytest.param(
        "sys.argv",
        ["-e", "txt, MD", "--no-backup", "."],
        {"intro.md": "# Intro\n", "readme.txt": "# Text\n"},
        {},
        {"[OK] intro.md: 1 change(s)", "[OK] readme.txt: 1 change(s)"},
        "Summary: scanned=2, changes=2, written=2",
        "",
        id="extensions-normalized",
    ),
    pytest.param(
        "sys.argv",
        ["--no-backup", "sub/deep.md"],
        {"sub/deep.md": "### Deep\n"},
        {},
        {"[OK] sub/deep.md: 1 change(s)"},
        "Summary: scanned=1, changes=1, written=1",
        "",
        id="explicit-file",
    ),
    pytest.param(
        "sys.argv",
        ["-e", ".rst", "."],
        {},
        {},
        set(),
        "Summary: scanned=0, changes=0, written=0",
        "[INFO] No matching files found.\n",
        id="no-matching-files",
    ),
    pytest.param(
        "argv",
        [],
        {"intro.md": "# Intro\n", "notes.markdown": "## Notes\n"},
        {"intro.md.bak": "# **Intro**\n", "notes.markdown.bak": "## **Notes**\n"},
        {"[OK] intro.md: 1 change(s)", "[OK] notes.markdown: 1 change(s)"},
        "Summary: scanned=2, changes=2, written=2",
        "",
        id="argv-empty-list-means-defaults",
    ),
    pytest.param(
        "argv",
        ["-r", "--no-backup", "."],
        {
            "intro.md": "# Intro\n",
            "notes.markdown": "## Notes\n",
            "sub/deep.md": "### Deep\n",
        },
        {},
        {
            "[OK] intro.md: 1 change(s)",
            "[OK] notes.markdown: 1 change(s)",
            "[OK] sub/deep.md: 1 change(s)",
        },
        "Summary: scanned=3, changes=3, written=3",
        "",
        id="argv-recursive-without-backups",
    ),
    pytest.param(
        "argv",
        ["--dry-run", "-L", "3", "sub/deep.md", "intro.md"],
        {},
        {},
        {"[OK] sub/deep.md: 1 change(s) (dry-run)"},
        "Summary: scanned=2, changes=1, written=0",
        "",
        id="argv-dry-run-levels-and-files",
    ),
]


@pytest.mark.parametrize(
    "via, args, changed, backups, ok_lines, summary, err", MAIN_RUNS
)
def test_main(
    via, args, changed, backups, ok_lines, summary, err, tmp_path, monkeypatch, capsys
):
    for name, text in BOOK.items():
        write(tmp_path / name, text)
    monkeypatch.chdir(tmp_path)
    if via == "argv":
        # the process arguments would scan nothing: a main() that ignores
        # its argument and reads sys.argv instead fails the row
        monkeypatch.setattr(sys, "argv", ["unbold-md-headers", "-e", ".rst", "."])
        assert m.main(args) == 0
    else:
        monkeypatch.setattr(sys, "argv", ["unbold-md-headers", *args])
        assert m.main() == 0
    out, stderr = capsys.readouterr()
    lines = out.splitlines()
    assert {line for line in lines if line.startswith("[OK]")} == ok_lines
    assert lines[-1] == summary
    assert stderr == err
    assert snapshot(tmp_path) == BOOK | changed | backups


# Each row: the arguments after the program name (run inside a tree holding
# umlaut.md only), the bytes of umlaut.md, its bytes afterwards, the "[OK]"
# lines printed, the start of the stderr
MAIN_ENCODING_RUNS = [
    pytest.param(
        ["--no-backup", "umlaut.md"],
        UMLAUT_SRC.encode("utf-8"),
        UMLAUT_EXPECTED.encode("utf-8"),
        {"[OK] umlaut.md: 1 change(s)"},
        "",
        id="utf-8-by-default",
    ),
    pytest.param(
        ["--encoding", "latin-1", "--no-backup", "umlaut.md"],
        UMLAUT_SRC.encode("latin-1"),
        UMLAUT_EXPECTED.encode("latin-1"),
        {"[OK] umlaut.md: 1 change(s)"},
        "",
        id="encoding-option-reaches-the-file",
    ),
    pytest.param(
        ["--no-backup", "umlaut.md"],
        UMLAUT_SRC.encode("latin-1"),
        UMLAUT_SRC.encode("latin-1"),
        set(),
        "[ERROR] Failed to read umlaut.md: ",
        id="file-not-in-the-encoding-is-reported-and-left-alone",
    ),
]


@pytest.mark.parametrize("args, src, after, ok_lines, err", MAIN_ENCODING_RUNS)
def test_main_encoding(args, src, after, ok_lines, err, tmp_path, monkeypatch, capsys):
    doc = tmp_path / "umlaut.md"
    doc.write_bytes(src)
    monkeypatch.chdir(tmp_path)
    assert m.main(args) == 0
    out, stderr = capsys.readouterr()
    assert {line for line in out.splitlines() if line.startswith("[OK]")} == ok_lines
    assert stderr.startswith(err)
    assert doc.read_bytes() == after


def test_main_reads_and_writes_utf8_under_c_locale(tmp_path, monkeypatch):
    """Without --encoding the file and its backup are UTF-8 whatever the
    locale: under LC_ALL=C the locale codec is ASCII and cannot carry the
    umlaut."""
    doc = tmp_path / "umlaut.md"
    doc.write_bytes(UMLAUT_SRC.encode("utf-8"))
    monkeypatch.chdir(tmp_path)
    with c_locale(monkeypatch):
        assert m.main(["umlaut.md"]) == 0
    assert doc.read_bytes() == UMLAUT_EXPECTED.encode("utf-8")
    assert (tmp_path / "umlaut.md.bak").read_bytes() == UMLAUT_SRC.encode("utf-8")


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as exit_info:
        m.main(["--help"])
    assert exit_info.value.code == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none)."""
    sections = re.split(
        r"^(?:positional arguments|options):$", help_out, maxsplit=1, flags=re.M
    )
    lines = sections[1].splitlines()
    for i, line in enumerate(lines):
        entry = line.strip()
        if re.match(re.escape(flag) + r"(?=[\s,]|$)", entry):
            parts = re.split(r"\s{2,}", entry, maxsplit=1)
            if len(parts) > 1:
                return parts[1]
            # a wide invocation pushes its text onto a deeper-indented line;
            # without text the next line is the next entry, indented alike
            following = lines[i + 1] if i + 1 < len(lines) else ""
            deeper = indentation(following) > indentation(line)
            return following.strip() if deeper else ""
    raise AssertionError(f"{flag} is not listed")


def indentation(line: str) -> int:
    return len(line) - len(line.lstrip())


# Each row: an argument whose --help entry must carry some help text; what the
# text says is not asserted (TESTING.md §14.8.1)
OPTIONS_WITH_HELP = [
    pytest.param("paths", id="paths"),
    pytest.param("-r", id="recursive"),
    pytest.param("-e", id="ext"),
    pytest.param("-L", id="levels"),
    pytest.param("--dry-run", id="dry-run"),
    pytest.param("--no-backup", id="no-backup"),
    pytest.param("--encoding", id="encoding"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))
