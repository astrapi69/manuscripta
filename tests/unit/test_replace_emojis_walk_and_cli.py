import pytest

pytestmark = pytest.mark.unit

# tests/test_replace_emojis_walk_and_cli.py
from pathlib import Path

import manuscripta.markdown.emojis as repl


def test_iter_md_files_skips_bak(tmp_path: Path):
    root = tmp_path / "manuscript"
    (root / "chapters").mkdir(parents=True)
    (root / "chapters" / "a.md").write_text("A 🔥", encoding="utf-8")
    (root / "chapters" / "b.md.bak").write_text("B 🔥", encoding="utf-8")
    files = list(repl.iter_md_files(root, ["chapters"]))
    names = sorted(p.name for p in files)
    assert names == ["a.md"]


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
