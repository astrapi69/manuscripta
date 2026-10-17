import pytest

pytestmark = pytest.mark.unit

# tests/test_strip_links_cli.py
import locale
import re
from contextlib import contextmanager

import manuscripta.markdown.strip_links as sl


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
    pytest.param(
        "plain text",
        [],
        0,
        ["No links to strip"],
        {"toc.md": "plain text"},
        id="no-links-writes-nothing",
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


def test_main_defaults_to_the_front_matter_toc(tmp_path, monkeypatch):
    """Without --file the TOC at manuscript/front-matter/toc.md below the
    working directory is processed."""
    toc = tmp_path / "manuscript" / "front-matter" / "toc.md"
    toc.parent.mkdir(parents=True)
    toc.write_text("Link [A](B)", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert sl.main(["--overwrite"]) == 0
    assert toc.read_text(encoding="utf-8") == "Link A"


# Each row: the flags after --file, the files afterwards with their text
UTF8_UNDER_C_LOCALE = [
    pytest.param(["--overwrite"], {"toc.md": "Über Ärger grün"}, id="in-place"),
    pytest.param(
        [],
        {"toc.md": "Über [Ärger](x) grün", "toc-nolinks.md": "Über Ärger grün"},
        id="copy",
    ),
]


@pytest.mark.parametrize("flags, files_after", UTF8_UNDER_C_LOCALE)
def test_main_reads_and_writes_utf8_under_c_locale(
    flags, files_after, tmp_path, monkeypatch
):
    """Without --encoding the file and its copy are UTF-8 whatever the
    locale: under LC_ALL=C the locale codec is ASCII and cannot carry the
    umlauts."""
    f = tmp_path / "toc.md"
    f.write_bytes("Über [Ärger](x) grün".encode("utf-8"))
    with c_locale(monkeypatch):
        assert sl.main(["--file", str(f), *flags]) == 0
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {
        name: text.encode("utf-8") for name, text in files_after.items()
    }


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as exit_info:
        sl.main(["--help"])
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


# Each row: an option whose --help entry must carry some help text; what the
# text says is not asserted (TESTING.md §14.8.1)
OPTIONS_WITH_HELP = [
    pytest.param("--file", id="file"),
    pytest.param("--overwrite", id="overwrite"),
    pytest.param("--suffix", id="suffix"),
    pytest.param("--encoding", id="encoding"),
    pytest.param("--dry-run", id="dry-run"),
    pytest.param("--report", id="report"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))
