# tests/test_unbold_md_headers.py
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
