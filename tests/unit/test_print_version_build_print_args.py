import pytest

pytestmark = pytest.mark.unit

# tests/test_print_version_build_print_args.py
import manuscripta.export.print_version as bp

# Each row: the arguments, the book type and the export format parsed, dry
# run?, restore?, a text the output carries (None: nothing is printed)
PARSE_ARGS_CASES = [
    pytest.param(
        ["--book-type", "hardcover"],
        "hardcover",
        "epub",
        False,
        False,
        None,
        id="valid-type",
    ),
    pytest.param(
        ["--book-type", "stone-tablet"],
        "paperback",
        "epub",
        False,
        False,
        "Invalid book type: stone-tablet. Falling back to 'paperback'.",
        id="invalid-type-falls-back",
    ),
    pytest.param(
        ["--dry-run", "--restore", "--export-format", "epub"],
        "paperback",
        "epub",
        True,
        True,
        None,
        id="defaults-and-flags",
    ),
    pytest.param([], "paperback", "epub", False, False, None, id="defaults"),
    pytest.param(
        ["--book-type", "h"], "hardcover", "epub", False, False, None, id="short-type"
    ),
    pytest.param(
        ["--export-format", "pdf"], "paperback", "pdf", False, False, None, id="pdf"
    ),
    # --format is the backward-compatible alias of --export-format
    pytest.param(
        ["--format", "pdf"], "paperback", "pdf", False, False, None, id="format-alias"
    ),
]


@pytest.mark.parametrize(
    "argv, book_type, export_format, dry_run, restore, printed", PARSE_ARGS_CASES
)
def test_parse_args(argv, book_type, export_format, dry_run, restore, printed, capsys):
    ns = bp.parse_args(argv)
    assert ns.book_type == book_type
    assert ns.export_format == export_format
    assert ns.dry_run is dry_run
    assert ns.restore is restore
    out, _ = capsys.readouterr()
    if printed is None:
        assert out == ""
    else:
        assert printed in out
