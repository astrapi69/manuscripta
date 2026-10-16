import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_emojis_walk_and_cli.py
import locale
import re
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path

import manuscripta.markdown.emojis as repl

PROG = "replace-emojis"
MAP = "{'🔥': '+++', '📈': '↑', '📉': '↓'}"


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


def files_of(directory: Path) -> dict[str, str]:
    """The files of a directory with their text."""
    return {p.name: p.read_text(encoding="utf-8") for p in directory.iterdir()}


def files_below(root: Path) -> dict[str, str]:
    """Every file below root (path below root -> text)."""
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file()
    }


# Each row: the files seeded below the book directory, the sections to scan,
# the files yielded (below the book directory, in order; one file per section
# as the order inside a section is the file system's)
WALKS = [
    pytest.param(
        ["chapters/a.md", "chapters/b.md.bak"],
        ["chapters"],
        ["chapters/a.md"],
        id="skips-bak",
    ),
    pytest.param(
        ["chapters/a.md"],
        ["missing", "chapters"],
        ["chapters/a.md"],
        id="missing-section-is-skipped",
    ),
    pytest.param(
        ["back-matter/z.md", "front-matter/a.md"],
        ["front-matter", "back-matter"],
        ["front-matter/a.md", "back-matter/z.md"],
        id="sections-in-the-given-order",
    ),
    pytest.param(
        ["chapters/a.md", "chapters/notes.txt", "chapters/deep/b.md"],
        ["chapters"],
        ["chapters/a.md"],
        id="only-md-files-at-the-top-of-a-section",
    ),
]


@pytest.mark.parametrize("files, sections, yielded", WALKS)
def test_iter_md_files(files, sections, yielded, tmp_path: Path):
    root = tmp_path / "manuscript"
    seed(root, {name: "🔥" for name in files})
    found = repl.iter_md_files(root, sections)
    assert [p.relative_to(root).as_posix() for p in found] == yielded


# Each row: the files seeded below the book directory (path -> text), the
# sections to scan (in that order, so the lines come in a known order), the
# flags after --map, the lines printed, the files below the book directory
# afterwards (path -> text)
CLI_CASES = [
    pytest.param(
        {"front-matter/intro.md": "Hello 🔥 📈"},
        ["front-matter"],
        ["--report", "--dry-run"],
        [
            "[front-matter/intro.md] replacements=2",
            "",
            "Done. files_scanned=1 files_written=0 total_replacements=2",
        ],
        {"front-matter/intro.md": "Hello 🔥 📈"},
        id="dry-run-reports-and-writes-nothing",
    ),
    # REAL RUN, copy mode
    pytest.param(
        {"front-matter/intro.md": "Hello 🔥 📈"},
        ["front-matter"],
        ["--report"],
        [
            "[front-matter/intro.md] replacements=2",
            "✓ Converted: intro.md → intro-final.md",
            "",
            "Done. files_scanned=1 files_written=1 total_replacements=2",
        ],
        {
            "front-matter/intro.md": "Hello 🔥 📈",
            "front-matter/intro-final.md": "Hello +++ ↑",
        },
        id="writes-copy-when-not-dry",
    ),
    pytest.param(
        {"chapters/c1.md": "x 📉"},
        ["chapters"],
        ["--overwrite", "--report"],
        [
            "[chapters/c1.md] replacements=1",
            "✓ Overwrote: c1.md",
            "",
            "Done. files_scanned=1 files_written=1 total_replacements=1",
        ],
        {"chapters/c1.md": "x ↓"},
        id="overwrite",
    ),
    pytest.param(
        {"chapters/c1.md": "x 📉"},
        ["chapters"],
        ["--overwrite", "--no-overwrite"],
        [
            "✓ Converted: c1.md → c1-final.md",
            "",
            "Done. files_scanned=1 files_written=1 total_replacements=1",
        ],
        {"chapters/c1.md": "x 📉", "chapters/c1-final.md": "x ↓"},
        id="no-overwrite-after-overwrite-copies",
    ),
    pytest.param(
        {"front-matter/a.md": "🔥🔥", "chapters/b.md": "📈"},
        ["front-matter", "chapters"],
        ["--dry-run"],
        ["", "Done. files_scanned=2 files_written=0 total_replacements=3"],
        {"front-matter/a.md": "🔥🔥", "chapters/b.md": "📈"},
        id="dry-run-scans-every-section-and-sums-the-replacements",
    ),
    pytest.param(
        {"front-matter/a.md": "🔥🔥", "chapters/b.md": "📈", "chapters/c.md": "plain"},
        ["front-matter", "chapters"],
        ["--overwrite"],
        [
            "✓ Overwrote: a.md",
            "✓ Overwrote: b.md",
            "",
            "Done. files_scanned=3 files_written=2 total_replacements=3",
        ],
        {"front-matter/a.md": "++++++", "chapters/b.md": "↑", "chapters/c.md": "plain"},
        id="a-run-over-sections-counts-the-files-written-and-the-replacements",
    ),
]


@pytest.mark.parametrize("files, sections, flags, printed, files_after", CLI_CASES)
def test_cli(files, sections, flags, printed, files_after, tmp_path, capsys):
    root = tmp_path / "manuscript"
    seed(root, files)
    # Provide a tiny mapping via temp module file
    map_py = tmp_path / "map.py"
    map_py.write_text(f"EMOJI_MAP={MAP}", encoding="utf-8")

    code = repl.main(
        ["--book-dir", str(root), "--sections", *sections, "--map", str(map_py), *flags]
    )
    assert code == 0
    assert capsys.readouterr().out.splitlines() == printed
    assert files_below(root) == files_after


def test_cli_rejects_an_invalid_mapping_before_touching_files(tmp_path, capsys):
    root = tmp_path / "manuscript"
    seed(root, {"chapters/c1.md": "x 🔥"})
    map_py = tmp_path / "map.py"
    map_py.write_text("EMOJI_MAP = {}", encoding="utf-8")

    code = repl.main(["--book-dir", str(root), "--map", str(map_py)])
    assert code == 2
    assert capsys.readouterr().out == "❌ Invalid mapping: Mapping is empty.\n"
    assert files_of(root / "chapters") == {"c1.md": "x 🔥"}


def test_cli_without_map_uses_the_bundled_table(tmp_path, capsys):
    # 🌐 → ◯ is pinned by test_emoji_map.py
    root = tmp_path / "manuscript"
    seed(root, {"chapters/c1.md": "web 🌐"})

    code = repl.main(["--book-dir", str(root), "--overwrite"])
    assert code == 0
    assert files_of(root / "chapters") == {"c1.md": "web ◯"}
    assert capsys.readouterr().out.splitlines() == [
        "✓ Overwrote: c1.md",
        "",
        "Done. files_scanned=1 files_written=1 total_replacements=1",
    ]


def test_cli_scans_the_manuscript_directory_below_the_cwd_by_default(
    tmp_path, monkeypatch, capsys
):
    """Without --book-dir the manuscript/ directory of the book repository
    (the current working directory, as for every manuscripta command) is
    scanned, its default sections in their order."""
    monkeypatch.chdir(tmp_path)
    seed(
        tmp_path / "manuscript",
        {"chapters/c1.md": "x 🔥", "back-matter/z.md": "📈", "front-matter/a.md": "📉"},
    )
    map_py = tmp_path / "map.py"
    map_py.write_text(f"EMOJI_MAP={MAP}", encoding="utf-8")

    assert repl.main(["--map", str(map_py), "--overwrite"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "✓ Overwrote: a.md",
        "✓ Overwrote: c1.md",
        "✓ Overwrote: z.md",
        "",
        "Done. files_scanned=3 files_written=3 total_replacements=3",
    ]
    assert files_below(tmp_path / "manuscript") == {
        "chapters/c1.md": "x +++",
        "back-matter/z.md": "↑",
        "front-matter/a.md": "↓",
    }


def test_cli_reads_and_writes_utf8_by_default_under_c_locale(
    tmp_path, monkeypatch, capsys
):
    """--encoding defaults to utf-8 (so its help says), whatever the locale:
    under LC_ALL=C the locale codec is ASCII and can carry neither the
    umlauts nor the emoji."""
    root = tmp_path / "manuscript"
    (root / "chapters").mkdir(parents=True)
    (root / "chapters" / "c1.md").write_bytes("Grüße 🔥".encode("utf-8"))
    map_py = tmp_path / "map.py"
    map_py.write_text(f"EMOJI_MAP={MAP}", encoding="utf-8")

    with c_locale(monkeypatch):
        code = repl.main(["--book-dir", str(root), "--map", str(map_py), "--overwrite"])
    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "✓ Overwrote: c1.md",
        "",
        "Done. files_scanned=1 files_written=1 total_replacements=1",
    ]
    assert (root / "chapters" / "c1.md").read_bytes().decode("utf-8") == "Grüße +++"


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as exc:
        repl.parse_args(["--help"])
    assert exc.value.code == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none); an entry too long for its column carries
    the text on the indented line below."""
    lines = help_out.split("options:\n", 1)[1].splitlines()
    for line, below in zip(lines, lines[1:] + [""]):
        entry = line.strip()
        if entry != flag and not entry.startswith(flag + " "):
            continue
        parts = re.split(r"\s{2,}", entry, maxsplit=1)
        if len(parts) > 1:
            return parts[1]
        return below.strip() if below.startswith(" " * 20) else ""
    raise AssertionError(f"{flag} is not listed")


# Each row: an option whose --help entry must carry some help text; what the
# text says is not asserted (TESTING.md §14.8.1: presence, not wording)
OPTIONS_WITH_HELP = [
    pytest.param("--book-dir", id="book-dir"),
    pytest.param("--sections", id="sections"),
    pytest.param("--suffix", id="suffix"),
    pytest.param("--encoding", id="encoding"),
    pytest.param("--map", id="map"),
    pytest.param("--overwrite", id="overwrite"),
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


def test_script_run_as_main(tmp_path, monkeypatch, capsys):
    root = tmp_path / "manuscript"
    seed(root, {"chapters/c1.md": "x 🔥"})
    map_py = tmp_path / "map.py"
    map_py.write_text("EMOJI_MAP = {'🔥': '+'}", encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", [PROG, "--book-dir", str(root), "--map", str(map_py)]
    )

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(repl.__file__, run_name="__main__")
    assert exc.value.code == 0
    assert files_of(root / "chapters") == {"c1.md": "x 🔥", "c1-final.md": "x +"}
