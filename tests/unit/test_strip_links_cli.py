import pytest

pytestmark = pytest.mark.unit

# tests/test_strip_links_cli.py
import manuscripta.markdown.strip_links as sl

# Each row: the text of toc.md (None: the file is missing), the flags after
# --file, the exit status, texts the output must carry, the files of the
# directory afterwards with their text
CLI_CASES = [
    pytest.param(None, [], 1, ["File not found"], {}, id="missing-file-returns-1"),
    # no new file
    pytest.param(
        "See [X](Y)",
        ["--dry-run", "--report"],
        0,
        ["links_stripped=1", "dry-run"],
        {"toc.md": "See [X](Y)"},
        id="dry-run-reports-and-writes-nothing",
    ),
    pytest.param(
        "Link [A](B)",
        ["--report"],
        0,
        ["→ toc-nolinks.md"],
        {"toc.md": "Link [A](B)", "toc-nolinks.md": "Link A"},
        id="copy-mode-writes-suffix",
    ),
    pytest.param(
        "Link [A](B)",
        ["--overwrite", "--report"],
        0,
        ["in place"],
        {"toc.md": "Link A"},
        id="overwrite",
    ),
]


@pytest.mark.parametrize("text, flags, code, reported, files_after", CLI_CASES)
def test_cli(text, flags, code, reported, files_after, tmp_path, capsys):
    f = tmp_path / "toc.md"
    if text is not None:
        f.write_text(text, encoding="utf-8")

    assert sl.main(["--file", str(f), *flags]) == code
    out, _ = capsys.readouterr()
    for line in reported:
        assert line in out
    assert {
        p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()
    } == files_after
