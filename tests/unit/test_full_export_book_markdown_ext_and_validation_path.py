import pytest

pytestmark = pytest.mark.unit

# tests/test_full_export_book_markdown_ext_and_validation_path.py
from manuscripta.export import book as feb


def test_module_exposes_formats_and_resolve_ext():
    # Sanity: module must expose FORMATS and resolve_ext
    assert hasattr(feb, "FORMATS"), "FORMATS not found in module"
    assert hasattr(feb, "resolve_ext"), "resolve_ext not found in module"


# Each row: the format, the custom Markdown extension and the extension resolved
RESOLVE_EXT_CASES = [
    # markdown defaults to 'md'
    pytest.param("markdown", None, "md", id="markdown-default"),
    # custom ext for markdown
    pytest.param("markdown", "markdown", "markdown", id="markdown-custom-markdown"),
    pytest.param("markdown", "mdown", "mdown", id="markdown-custom-mdown"),
    pytest.param("markdown", "gfm", "gfm", id="markdown-custom-gfm"),
    # others come from mapping
    pytest.param("pdf", None, feb.FORMATS["pdf"], id="pdf-from-mapping"),
    pytest.param("epub", None, feb.FORMATS["epub"], id="epub-from-mapping"),
    pytest.param("docx", None, feb.FORMATS["docx"], id="docx-from-mapping"),
]


@pytest.mark.parametrize("fmt, custom, expected", RESOLVE_EXT_CASES)
def test_resolve_ext(fmt, custom, expected):
    assert feb.resolve_ext(fmt, custom) == expected


# Each row: the format, the custom Markdown extension and the name of the
# output file the validator gets for OUTPUT_FILE "mybook-ebook"
OUTPUT_NAME_CASES = [
    # default markdown -> .md
    pytest.param("markdown", None, "mybook-ebook.md", id="markdown-default"),
    # custom markdown extension -> respected
    pytest.param("markdown", "gfm", "mybook-ebook.gfm", id="markdown-custom-gfm"),
    pytest.param(
        "markdown", "markdown", "mybook-ebook.markdown", id="markdown-custom-markdown"
    ),
    # other formats unchanged
    pytest.param("pdf", None, "mybook-ebook.pdf", id="pdf"),
    pytest.param("epub", None, "mybook-ebook.epub", id="epub"),
    pytest.param("docx", None, "mybook-ebook.docx", id="docx"),
]


@pytest.mark.parametrize("fmt, custom, expected", OUTPUT_NAME_CASES)
def test_validator_path_uses_resolved_ext(fmt, custom, expected, tmp_path):
    """Simulate how the exporter computes output paths for validation:
    markdown uses the resolved extension (default or custom)."""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = feb.resolve_ext(fmt, custom if fmt == "markdown" else None)
    assert (output_dir / f"mybook-ebook.{ext}").name == expected
