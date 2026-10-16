# tests/test_unbold_md_headers.py
import argparse
import sys
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


# Each row: the arguments after the program name (run inside the tree root),
# the files changed (name -> text afterwards; the others keep their text), the
# backups written (name -> text), the "[OK]" lines printed, the summary line,
# the stderr
MAIN_RUNS = [
    pytest.param(
        [],
        {"intro.md": "# Intro\n", "notes.markdown": "## Notes\n"},
        {"intro.md.bak": "# **Intro**\n", "notes.markdown.bak": "## **Notes**\n"},
        {"[OK] intro.md: 1 change(s)", "[OK] notes.markdown: 1 change(s)"},
        "Summary: scanned=2, changes=2, written=2",
        "",
        id="defaults-top-level-with-backups",
    ),
    pytest.param(
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
        ["-L", "1", "-r", "--no-backup", "."],
        {"intro.md": "# Intro\n"},
        {},
        {"[OK] intro.md: 1 change(s)"},
        "Summary: scanned=3, changes=1, written=1",
        "",
        id="levels-restrict-to-h1",
    ),
    pytest.param(
        ["-e", "txt, MD", "--no-backup", "."],
        {"intro.md": "# Intro\n", "readme.txt": "# Text\n"},
        {},
        {"[OK] intro.md: 1 change(s)", "[OK] readme.txt: 1 change(s)"},
        "Summary: scanned=2, changes=2, written=2",
        "",
        id="extensions-normalized",
    ),
    pytest.param(
        ["--no-backup", "sub/deep.md"],
        {"sub/deep.md": "### Deep\n"},
        {},
        {"[OK] sub/deep.md: 1 change(s)"},
        "Summary: scanned=1, changes=1, written=1",
        "",
        id="explicit-file",
    ),
    pytest.param(
        ["-e", ".rst", "."],
        {},
        {},
        set(),
        "Summary: scanned=0, changes=0, written=0",
        "[INFO] No matching files found.\n",
        id="no-matching-files",
    ),
]


@pytest.mark.parametrize("args, changed, backups, ok_lines, summary, err", MAIN_RUNS)
def test_main(
    args, changed, backups, ok_lines, summary, err, tmp_path, monkeypatch, capsys
):
    for name, text in BOOK.items():
        write(tmp_path / name, text)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["unbold-md-headers", *args])
    assert m.main() == 0
    out, stderr = capsys.readouterr()
    lines = out.splitlines()
    assert {line for line in lines if line.startswith("[OK]")} == ok_lines
    assert lines[-1] == summary
    assert stderr == err
    assert snapshot(tmp_path) == BOOK | changed | backups
