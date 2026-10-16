import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_emojis_walk_and_cli.py
import runpy
import sys
from pathlib import Path

import manuscripta.markdown.emojis as repl

PROG = "replace-emojis"


def seed(root: Path, files: dict[str, str]) -> None:
    """Write the files (path below root -> text), creating their directories."""
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def files_of(directory: Path) -> dict[str, str]:
    """The files of a directory with their text."""
    return {p.name: p.read_text(encoding="utf-8") for p in directory.iterdir()}


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


# Each row: the file below the book directory and its text, the EMOJI_MAP of
# the --map module, the flags after --map, texts the report must carry, the
# files of that section afterwards with their text
CLI_CASES = [
    pytest.param(
        "front-matter/intro.md",
        "Hello 🔥 📈",
        "{'🔥': '+++', '📈': '↑'}",
        ["--report", "--dry-run"],
        ["replacements=", "files_written=0"],
        {"intro.md": "Hello 🔥 📈"},
        id="dry-run-reports-and-writes-nothing",
    ),
    # REAL RUN, copy mode
    pytest.param(
        "front-matter/intro.md",
        "Hello 🔥 📈",
        "{'🔥': '+++', '📈': '↑'}",
        ["--report"],
        ["✓ Converted: intro.md → intro-final.md"],
        {"intro.md": "Hello 🔥 📈", "intro-final.md": "Hello +++ ↑"},
        id="writes-copy-when-not-dry",
    ),
    pytest.param(
        "chapters/c1.md",
        "x 📉",
        "{'📉': '↓'}",
        ["--overwrite", "--report"],
        ["✓ Overwrote: c1.md"],
        {"c1.md": "x ↓"},
        id="overwrite",
    ),
]


@pytest.mark.parametrize(
    "source, text, emoji_map, flags, reported, files_after", CLI_CASES
)
def test_cli(source, text, emoji_map, flags, reported, files_after, tmp_path, capsys):
    root = tmp_path / "manuscript"
    section, name = source.split("/")
    (root / section).mkdir(parents=True)
    (root / section / name).write_text(text, encoding="utf-8")

    # Provide a tiny mapping via temp module file
    map_py = tmp_path / "map.py"
    map_py.write_text(f"EMOJI_MAP={emoji_map}", encoding="utf-8")

    code = repl.main(
        ["--book-dir", str(root), "--sections", section, "--map", str(map_py), *flags]
    )
    assert code == 0
    out = capsys.readouterr().out
    for line in reported:
        assert line in out
    assert {
        p.name: p.read_text(encoding="utf-8") for p in (root / section).iterdir()
    } == files_after


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
    assert "files_scanned=1 files_written=1 total_replacements=1" in (
        capsys.readouterr().out
    )


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
