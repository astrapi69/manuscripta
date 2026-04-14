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


def test_cli_dry_run_reports_and_writes_only_when_not_dry(
    tmp_path: Path, capsys, monkeypatch
):
    root = tmp_path / "manuscript"
    (root / "front-matter").mkdir(parents=True)
    (root / "front-matter" / "intro.md").write_text("Hello 🔥 📈", encoding="utf-8")

    # Provide a tiny mapping via temp module file
    map_py = tmp_path / "map.py"
    map_py.write_text("EMOJI_MAP={'🔥': '+++', '📈': '↑'}", encoding="utf-8")

    # DRY RUN
    code = repl.main(
        [
            "--book-dir",
            str(root),
            "--sections",
            "front-matter",
            "--map",
            str(map_py),
            "--report",
            "--dry-run",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "replacements=" in out
    assert "files_written=0" in out

    # REAL RUN, copy mode
    code = repl.main(
        [
            "--book-dir",
            str(root),
            "--sections",
            "front-matter",
            "--map",
            str(map_py),
            "--report",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "✓ Converted: intro.md → intro-final.md" in out
    copied = root / "front-matter" / "intro-final.md"
    assert copied.read_text(encoding="utf-8") == "Hello +++ ↑"


def test_cli_overwrite(tmp_path: Path, capsys):
    root = tmp_path / "manuscript"
    (root / "chapters").mkdir(parents=True)
    f = root / "chapters" / "c1.md"
    f.write_text("x 📉", encoding="utf-8")

    map_py = tmp_path / "map.py"
    map_py.write_text("EMOJI_MAP={'📉': '↓'}", encoding="utf-8")

    code = repl.main(
        [
            "--book-dir",
            str(root),
            "--sections",
            "chapters",
            "--map",
            str(map_py),
            "--overwrite",
            "--report",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "✓ Overwrote: c1.md" in out
    assert f.read_text(encoding="utf-8") == "x ↓"
