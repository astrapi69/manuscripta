"""Coverage-uplift tests for manuscripta.export.book.

Focus: the argv-builder in run_export, format-specific pandoc-argv
construction in compile_book, the exception-wrapping branches
(CalledProcessError -> ManuscriptaPandocError), metadata / settings
error paths, and the pure helpers (resolve_ext, pick_section_order,
get_project_name_from_pyproject, etc.).

Every test asserts on an observable outcome (captured argv, returned
value, raised exception) — not just "the function was called".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

from manuscripta import (
    ManuscriptaImageError,
    ManuscriptaLayoutError,
    ManuscriptaPandocError,
)
from manuscripta.enums.book_type import BookType
from manuscripta.export import book as bm


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


class _CP:
    """Minimal stand-in for a subprocess.CompletedProcess."""

    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _valid_project(root: Path) -> Path:
    (root / "manuscript" / "chapters").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "assets").mkdir()
    (root / "config" / "metadata.yaml").write_text(
        'title: "T"\nauthor: "A"\nlang: "de"\n', encoding="utf-8"
    )
    (root / "manuscript" / "chapters" / "ch1.md").write_text(
        "# Hello\n", encoding="utf-8"
    )
    return root


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def test_resolve_ext_markdown_default():
    assert bm.resolve_ext("markdown", None) == "md"


def test_resolve_ext_markdown_custom_extension():
    assert bm.resolve_ext("markdown", "gfm") == "gfm"


def test_resolve_ext_non_markdown_ignores_custom():
    # Non-markdown formats use the FORMATS mapping regardless of custom_ext.
    assert bm.resolve_ext("pdf", "something-else") == "pdf"


def test_pick_section_order_ebook():
    assert bm.pick_section_order(BookType.EBOOK, "pdf") == bm.EBOOK_SECTION_ORDER


def test_pick_section_order_paperback():
    assert bm.pick_section_order(BookType.PAPERBACK, "pdf") == bm.PAPERBACK_SECTION_ORDER


def test_pick_section_order_hardcover():
    assert bm.pick_section_order(BookType.HARDCOVER, "pdf") == bm.HARDCOVER_SECTION_ORDER


def test_get_project_name_from_pyproject_reads_tool_poetry_name(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[tool.poetry]\nname = "alpha"\n', encoding="utf-8")
    assert bm.get_project_name_from_pyproject(str(p)) == "alpha"


def test_get_project_name_from_pyproject_reads_project_name(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text('[project]\nname = "beta"\n', encoding="utf-8")
    assert bm.get_project_name_from_pyproject(str(p)) == "beta"


def test_get_project_name_from_pyproject_fallback_on_error(tmp_path, capsys):
    p = tmp_path / "pyproject.toml"
    p.write_text("not valid toml = = =", encoding="utf-8")
    assert bm.get_project_name_from_pyproject(str(p)) == "book"
    assert "Could not read" in capsys.readouterr().out


def test_get_project_name_from_pyproject_fallback_when_missing(tmp_path):
    p = tmp_path / "empty.toml"
    p.write_text("", encoding="utf-8")
    assert bm.get_project_name_from_pyproject(str(p)) == "book"


# --------------------------------------------------------------------------
# get_metadata_language
# --------------------------------------------------------------------------


def test_get_metadata_language_reads_lang_field(tmp_path, monkeypatch):
    md = tmp_path / "metadata.yaml"
    md.write_text('lang: "fr"\n', encoding="utf-8")
    monkeypatch.setattr(bm, "METADATA_FILE", md)
    assert bm.get_metadata_language() == "fr"


def test_get_metadata_language_falls_back_to_language(tmp_path, monkeypatch):
    md = tmp_path / "metadata.yaml"
    md.write_text('language: "es"\n', encoding="utf-8")
    monkeypatch.setattr(bm, "METADATA_FILE", md)
    assert bm.get_metadata_language() == "es"


def test_get_metadata_language_missing_file_returns_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bm, "METADATA_FILE", tmp_path / "nope.yaml")
    assert bm.get_metadata_language() is None
    assert "Metadata file not found" in capsys.readouterr().out


def test_get_metadata_language_yaml_error_returns_none(tmp_path, monkeypatch, capsys):
    md = tmp_path / "metadata.yaml"
    md.write_text("this: is: not: valid: yaml: [", encoding="utf-8")
    monkeypatch.setattr(bm, "METADATA_FILE", md)
    assert bm.get_metadata_language() is None
    assert "Failed to parse" in capsys.readouterr().out


# --------------------------------------------------------------------------
# load_export_settings
# --------------------------------------------------------------------------


def test_load_export_settings_missing_returns_empty(tmp_path):
    assert bm.load_export_settings(tmp_path / "nope.yaml") == {}


def test_load_export_settings_reads_yaml(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text("formats:\n  pdf: pdf\n", encoding="utf-8")
    settings = bm.load_export_settings(p)
    assert settings == {"formats": {"pdf": "pdf"}}


def test_get_section_order_from_settings_null_fallback_chain():
    # ebook -> default
    settings = {"section_order": {"ebook": None, "default": ["x"]}}
    assert bm.get_section_order_from_settings(settings, "ebook") == ["x"]
    # hardcover -> paperback
    settings = {"section_order": {"hardcover": None, "paperback": ["y"]}}
    assert bm.get_section_order_from_settings(settings, "hardcover") == ["y"]
    # no section_order -> None
    assert bm.get_section_order_from_settings({}, "ebook") is None


# --------------------------------------------------------------------------
# get_or_create_metadata_file
# --------------------------------------------------------------------------


def test_get_or_create_metadata_file_uses_existing(tmp_path):
    md = tmp_path / "metadata.yaml"
    md.write_text("x", encoding="utf-8")
    path, is_tmp = bm.get_or_create_metadata_file(md)
    assert path == md
    assert is_tmp is False


def test_get_or_create_metadata_file_creates_temp_when_missing(tmp_path):
    path, is_tmp = bm.get_or_create_metadata_file(tmp_path / "missing.yaml")
    try:
        assert is_tmp is True
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "title" in content.lower()
    finally:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# ensure_metadata_file
# --------------------------------------------------------------------------


def test_ensure_metadata_file_creates_when_missing(tmp_path, monkeypatch, capsys):
    target = tmp_path / "config" / "metadata.yaml"
    monkeypatch.setattr(bm, "METADATA_FILE", target)
    bm.ensure_metadata_file()
    assert target.exists()
    assert "title" in target.read_text(encoding="utf-8").lower()
    assert "Metadata file missing" in capsys.readouterr().out


# --------------------------------------------------------------------------
# prepare_output_folder
# --------------------------------------------------------------------------


def test_prepare_output_folder_moves_content_to_backup(tmp_path, monkeypatch):
    out = tmp_path / "output"
    bak = tmp_path / "backup"
    out.mkdir()
    (out / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(bm, "BACKUP_DIR", str(bak))

    bm.prepare_output_folder(verbose=True)
    assert out.exists()
    assert not any(out.iterdir())
    assert (bak / "a.txt").exists()


def test_prepare_output_folder_removes_existing_backup(tmp_path, monkeypatch, capsys):
    out = tmp_path / "output"
    bak = tmp_path / "backup"
    out.mkdir()
    (out / "a.txt").write_text("x", encoding="utf-8")
    bak.mkdir()
    (bak / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(bm, "BACKUP_DIR", str(bak))

    bm.prepare_output_folder(verbose=True)
    # Old backup replaced, then new backup contains only the moved files.
    assert (bak / "a.txt").exists()
    assert not (bak / "old.txt").exists()
    assert "Deleted old backup" in capsys.readouterr().out


def test_prepare_output_folder_skips_backup_when_output_empty(tmp_path, monkeypatch):
    out = tmp_path / "output"
    bak = tmp_path / "backup"
    out.mkdir()
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(bm, "BACKUP_DIR", str(bak))

    bm.prepare_output_folder()
    assert out.exists()
    assert not bak.exists()


# --------------------------------------------------------------------------
# compile_book: format-specific argv construction
# --------------------------------------------------------------------------


def _compile_and_capture(monkeypatch, *, format, **kwargs):
    """Run compile_book with the subprocess.run intercepted; return argv."""
    captured = {}

    def fake_run(cmd, **kw):
        captured["argv"] = list(cmd)
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)

    # Tiny section fixture — a single markdown file the gather loop can find.
    # Default OUTPUT_FILE is "", so force one.
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    bm.compile_book(
        format,
        ["chapters/ch1.md"],
        BookType.EBOOK,
        **kwargs,
    )
    return captured.get("argv")


def test_compile_book_pdf_includes_pdf_engine_flags(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))

    argv = _compile_and_capture(
        monkeypatch, format="pdf", resource_path=str(tmp_path / "assets")
    )
    assert argv is not None
    assert "--pdf-engine=xelatex" in argv
    assert "mainfont=DejaVu Sans" in argv


def test_compile_book_markdown_includes_wrap_none(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    argv = _compile_and_capture(monkeypatch, format="markdown")
    assert "--wrap=none" in argv


def test_compile_book_html_includes_standalone_and_css(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    argv = _compile_and_capture(monkeypatch, format="html", lang="fr")
    assert "--standalone" in argv
    assert any("style.css" in a for a in argv)
    assert any("lang=fr" in a for a in argv)


def test_compile_book_epub_ebook_includes_toc_and_chapter_level(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    argv = _compile_and_capture(monkeypatch, format="epub")
    assert "--toc" in argv
    assert any("--toc-depth=" in a for a in argv)
    assert "--epub-chapter-level=1" in argv


def test_compile_book_epub2_sets_metadata(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    argv = _compile_and_capture(monkeypatch, format="epub", force_epub2=True)
    assert any("epub.version=2" in a for a in argv)


def test_compile_book_epub_cover_image_included(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    argv = _compile_and_capture(monkeypatch, format="epub", cover_path="cover.jpg")
    assert any(a.startswith("--epub-cover-image=") and "cover.jpg" in a for a in argv)


def test_compile_book_no_markdown_files_returns_early(monkeypatch, tmp_path, capsys):
    # BOOK_DIR exists but contains nothing matching the section_order entries.
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))

    captured = {}

    def fake_run(*a, **kw):
        captured["called"] = True
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    bm.compile_book("pdf", ["no-such-section"], BookType.EBOOK)
    assert "called" not in captured
    assert "No Markdown files" in capsys.readouterr().out


# --------------------------------------------------------------------------
# compile_book: exception-wrapping branches
# --------------------------------------------------------------------------


def test_compile_book_wraps_calledprocesserror_as_pandoc_error(
    monkeypatch, tmp_path
):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(
            returncode=17, cmd=cmd, output="", stderr="! LaTeX Error: blah\n"
        )

    monkeypatch.setattr(bm.subprocess, "run", fake_run)

    with pytest.raises(ManuscriptaPandocError) as ex:
        bm.compile_book("pdf", ["chapters/ch1.md"], BookType.EBOOK)
    assert ex.value.returncode == 17
    assert "LaTeX Error" in ex.value.stderr


def test_compile_book_strict_image_error_beats_pandoc_error(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=cmd,
            output="",
            stderr='[WARNING] Could not fetch resource "images/missing.png"\n',
        )

    monkeypatch.setattr(bm.subprocess, "run", fake_run)

    with pytest.raises(ManuscriptaImageError):
        bm.compile_book(
            "pdf", ["chapters/ch1.md"], BookType.EBOOK, strict_images=True
        )


def test_compile_book_lenient_mode_logs_and_continues(
    monkeypatch, tmp_path, caplog
):
    import logging

    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    def fake_run(cmd, **kw):
        return _CP(
            stderr='[WARNING] Could not fetch resource "images/missing.png"\n'
        )

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        bm.compile_book(
            "pdf", ["chapters/ch1.md"], BookType.EBOOK, strict_images=False
        )
    assert any(
        "unresolved image" in r.getMessage() and "missing.png" in r.getMessage()
        for r in caplog.records
    )


def test_compile_book_output_path_override_resolves_absolute(monkeypatch, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))

    captured = {}

    def fake_run(cmd, **kw):
        captured["argv"] = cmd
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)

    out = tmp_path / "elsewhere" / "named.pdf"
    bm.compile_book(
        "pdf",
        ["chapters/ch1.md"],
        BookType.EBOOK,
        output_path_override=str(out),
    )
    assert out.parent.exists()  # parent created
    assert any(a.endswith("named.pdf") for a in captured["argv"])


# --------------------------------------------------------------------------
# run_export argv-building branches
# --------------------------------------------------------------------------


def _capture_pipeline(monkeypatch):
    captured = {}

    def fake(*, argv, source_dir, resource_path, strict_images, output_path=None):
        captured["argv"] = argv
        captured["source_dir"] = source_dir
        captured["strict_images"] = strict_images
        captured["output_path"] = output_path

    monkeypatch.setattr(bm, "_run_pipeline", fake)
    return captured


def test_run_export_builds_argv_with_every_option(tmp_path, monkeypatch):
    _valid_project(tmp_path)
    captured = _capture_pipeline(monkeypatch)
    bm.run_export(
        tmp_path,
        formats=["pdf", "epub"],
        section_order=["front-matter/foreword.md", "chapters"],
        cover="cover.jpg",
        epub2=True,
        lang="de",
        extension="gfm",
        book_type=BookType.PAPERBACK,
        output_file="custom",
        no_type_suffix=True,
        toc_depth=3,
        use_manual_toc=True,
        skip_images=True,
        copy_epub_to="/tmp/out",
    )
    argv = captured["argv"]
    assert "--format" in argv and "pdf,epub" in argv
    assert "--order" in argv
    assert "--cover" in argv and "cover.jpg" in argv
    assert "--epub2" in argv
    assert "--lang" in argv and "de" in argv
    assert "--extension" in argv and "gfm" in argv
    assert "--book-type" in argv and "paperback" in argv
    assert "--output-file" in argv and "custom" in argv
    assert "--no-type-suffix" in argv
    assert "--toc-depth" in argv and "3" in argv
    assert "--use-manual-toc" in argv
    assert "--skip-images" in argv
    assert "--copy-epub-to" in argv


def test_run_export_formats_as_string(tmp_path, monkeypatch):
    _valid_project(tmp_path)
    captured = _capture_pipeline(monkeypatch)
    bm.run_export(tmp_path, formats="pdf")
    assert "--format" in captured["argv"]
    idx = captured["argv"].index("--format")
    assert captured["argv"][idx + 1] == "pdf"


def test_run_export_keep_relative_paths_when_not_skip_images(tmp_path, monkeypatch):
    _valid_project(tmp_path)
    captured = _capture_pipeline(monkeypatch)
    bm.run_export(tmp_path, formats="pdf", keep_relative_paths=True)
    assert "--keep-relative-paths" in captured["argv"]
    assert "--skip-images" not in captured["argv"]


def test_run_export_book_type_string_is_accepted(tmp_path, monkeypatch):
    _valid_project(tmp_path)
    captured = _capture_pipeline(monkeypatch)
    bm.run_export(tmp_path, formats="pdf", book_type="hardcover")
    idx = captured["argv"].index("--book-type")
    assert captured["argv"][idx + 1] == "hardcover"


def test_run_export_none_source_dir_raises_typeerror():
    with pytest.raises(TypeError):
        bm.run_export(None)


# --------------------------------------------------------------------------
# filter_section_order_for_epub
# --------------------------------------------------------------------------


def test_filter_section_order_for_epub_removes_toc_files():
    orig = ["front-matter/toc.md", "chapters", "front-matter/toc-print.md"]
    out = bm.filter_section_order_for_epub(orig)
    assert "front-matter/toc.md" not in out
    assert "front-matter/toc-print.md" not in out
    assert "chapters" in out


# --------------------------------------------------------------------------
# normalize_toc_if_needed
# --------------------------------------------------------------------------


def test_normalize_toc_if_needed_skips_non_toc_md(tmp_path, capsys):
    # A file whose name is not toc.md should be skipped with an info message.
    p = tmp_path / "other.md"
    p.write_text("# x", encoding="utf-8")
    bm.normalize_toc_if_needed(p)
    assert "Skipping TOC normalization" in capsys.readouterr().out


def test_normalize_toc_if_needed_runs_subprocess_for_toc_md(tmp_path, monkeypatch):
    p = tmp_path / "toc.md"
    p.write_text("# TOC", encoding="utf-8")
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    bm.normalize_toc_if_needed(p)
    assert seen["cmd"][0] == "python3"
    assert "--toc" in seen["cmd"]


def test_normalize_toc_if_needed_handles_subprocess_failure(
    tmp_path, monkeypatch, capsys
):
    p = tmp_path / "toc.md"
    p.write_text("# TOC", encoding="utf-8")

    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    bm.normalize_toc_if_needed(p)  # must not raise
    assert "Error normalizing TOC" in capsys.readouterr().out


# --------------------------------------------------------------------------
# _parse_unresolved_images
# --------------------------------------------------------------------------


def test_parse_unresolved_images_extracts_double_quoted():
    stderr = '[WARNING] Could not fetch resource "images/a.png": not found\n'
    assert bm._parse_unresolved_images(stderr) == ["images/a.png"]


def test_parse_unresolved_images_extracts_single_quoted():
    stderr = "[WARNING] Could not fetch resource 'images/b.png'\n"
    assert bm._parse_unresolved_images(stderr) == ["images/b.png"]


def test_parse_unresolved_images_deduplicates():
    stderr = (
        '[WARNING] Could not fetch resource "x.png"\n'
        '[WARNING] Could not fetch resource "x.png"\n'
    )
    assert bm._parse_unresolved_images(stderr) == ["x.png"]


def test_parse_unresolved_images_empty_on_no_match():
    assert bm._parse_unresolved_images("no warnings here") == []


# --------------------------------------------------------------------------
# _validate_layout
# --------------------------------------------------------------------------


def test_validate_layout_rejects_missing(tmp_path):
    with pytest.raises(ManuscriptaLayoutError) as ex:
        bm._validate_layout(tmp_path / "nope")
    assert ex.value.reason == "nonexistent"


def test_validate_layout_rejects_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(ManuscriptaLayoutError) as ex:
        bm._validate_layout(f)
    assert ex.value.reason == "not_a_directory"


def test_validate_layout_accepts_valid_project(tmp_path):
    _valid_project(tmp_path)
    bm._validate_layout(tmp_path)  # must not raise


# --------------------------------------------------------------------------
# _configure_paths
# --------------------------------------------------------------------------


def test_configure_paths_joins_resource_paths_with_pathsep(tmp_path, monkeypatch):
    extra = tmp_path / "extra"
    extra.mkdir()
    _valid_project(tmp_path)
    rp = bm._configure_paths(tmp_path, [extra])
    import os as _os

    parts = rp.split(_os.pathsep)
    assert Path(parts[0]) == (tmp_path / "assets").resolve()
    assert Path(parts[1]) == extra.resolve()


def test_run_pipeline_with_toc_and_copy_epub_to(tmp_path, monkeypatch, capsys):
    """Drive _run_pipeline end-to-end with fakes to cover Step 1a
    (TOC normalize) and Step 5b (copy-epub-to).
    """
    project = _valid_project(tmp_path)
    (project / "manuscript" / "front-matter").mkdir(exist_ok=True)
    (project / "manuscript" / "front-matter" / "toc.md").write_text(
        "[a](#b)", encoding="utf-8"
    )

    # Stub subprocess.run but have the pandoc call write a fake EPUB at its
    # --output target so the copy-epub-to branch fires after
    # prepare_output_folder has wiped the output dir.
    def fake_run(cmd, **kw):
        for arg in cmd:
            if isinstance(arg, str) and arg.startswith("--output="):
                p = Path(arg.split("=", 1)[1])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"fake-epub")
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)

    for name in ("validate_pdf", "validate_epub_with_epubcheck", "validate_docx",
                 "validate_markdown", "validate_html"):
        monkeypatch.setattr(bm, name, lambda *a, **k: None)

    copy_dest = tmp_path / "dest"

    bm.run_export(
        project,
        formats="epub",
        skip_images=True,
        copy_epub_to=str(copy_dest),
        output_file="book",
    )

    # Copy-epub-to target must have received the EPUB.
    assert any(copy_dest.rglob("*.epub")), "copy-epub-to did not produce output"


def test_run_pipeline_copy_epub_to_when_epub_missing_warns(
    tmp_path, monkeypatch, capsys
):
    project = _valid_project(tmp_path)

    def fake_run(*a, **kw):
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    for name in ("validate_pdf", "validate_epub_with_epubcheck", "validate_docx",
                 "validate_markdown", "validate_html"):
        monkeypatch.setattr(bm, name, lambda *a, **k: None)

    bm.run_export(
        project,
        formats="pdf",  # no epub produced
        skip_images=True,
        copy_epub_to=str(tmp_path / "dest"),
        output_file="book",
    )
    out = capsys.readouterr().out
    assert "EPUB not found" in out
    assert "was not in the selected formats" in out


def test_configure_paths_deduplicates_resource_paths(tmp_path, monkeypatch):
    _valid_project(tmp_path)
    # Same path added twice should appear only once.
    rp = bm._configure_paths(tmp_path, [tmp_path / "assets", tmp_path / "assets"])
    import os as _os

    parts = rp.split(_os.pathsep)
    assert parts.count(str((tmp_path / "assets").resolve())) == 1
