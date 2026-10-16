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
import sys
from pathlib import Path

import pytest

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


@pytest.fixture(autouse=True)
def _log_file_in_tmp(tmp_path, monkeypatch):
    """compile_book appends Pandoc's output to bm.LOG_FILE; keep that out of
    the repository's export.log and out of other tests' directories."""
    monkeypatch.setattr(bm, "LOG_FILE", str(tmp_path / "export.log"))


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


def _file(path: Path) -> Path:
    """A file at ``path``; returns the path."""
    path.write_text("x", encoding="utf-8")
    return path


def _dir(path: Path) -> Path:
    """An empty directory at ``path``; returns the path."""
    path.mkdir()
    return path


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


# Each row: the format, the custom Markdown extension, the extension resolved
RESOLVE_EXT_CASES = [
    pytest.param("markdown", None, "md", id="markdown-default"),
    pytest.param("markdown", "gfm", "gfm", id="markdown-custom-extension"),
    # Non-markdown formats use the FORMATS mapping regardless of custom_ext.
    pytest.param("pdf", "something-else", "pdf", id="non-markdown-ignores-custom"),
    pytest.param("epub", None, "epub", id="epub-from-mapping"),
    pytest.param("docx", None, "docx", id="docx-from-mapping"),
]


@pytest.mark.parametrize("fmt, custom, expected", RESOLVE_EXT_CASES)
def test_resolve_ext(fmt, custom, expected):
    assert bm.resolve_ext(fmt, custom) == expected


# Each row: the book type and the section order picked for it
PICK_SECTION_ORDER_CASES = [
    pytest.param(BookType.EBOOK, bm.EBOOK_SECTION_ORDER, id="ebook"),
    pytest.param(BookType.PAPERBACK, bm.PAPERBACK_SECTION_ORDER, id="paperback"),
    pytest.param(BookType.HARDCOVER, bm.HARDCOVER_SECTION_ORDER, id="hardcover"),
]


@pytest.mark.parametrize("book_type, expected", PICK_SECTION_ORDER_CASES)
def test_pick_section_order(book_type, expected):
    assert bm.pick_section_order(book_type, "pdf") == expected


# Each row: the pyproject.toml text, the project name read, a line printed
# (None: nothing to check)
PROJECT_NAME_CASES = [
    pytest.param(
        '[tool.poetry]\nname = "alpha"\n', "alpha", None, id="reads-tool-poetry-name"
    ),
    pytest.param('[project]\nname = "beta"\n', "beta", None, id="reads-project-name"),
    pytest.param(
        "not valid toml = = =", "book", "Could not read", id="fallback-on-error"
    ),
    pytest.param("", "book", None, id="fallback-when-missing"),
]


@pytest.mark.parametrize("text, expected, printed", PROJECT_NAME_CASES)
def test_get_project_name_from_pyproject(text, expected, printed, tmp_path, capsys):
    p = tmp_path / "pyproject.toml"
    p.write_text(text, encoding="utf-8")
    assert bm.get_project_name_from_pyproject(str(p)) == expected
    if printed is not None:
        assert printed in capsys.readouterr().out


# --------------------------------------------------------------------------
# get_metadata_language
# --------------------------------------------------------------------------


# Each row: the metadata.yaml text (None: no file), the language read, a line
# printed (None: nothing to check)
METADATA_LANGUAGE_CASES = [
    pytest.param('lang: "fr"\n', "fr", None, id="reads-lang-field"),
    pytest.param('language: "es"\n', "es", None, id="falls-back-to-language"),
    pytest.param(None, None, "Metadata file not found", id="missing-file-returns-none"),
    pytest.param(
        "this: is: not: valid: yaml: [",
        None,
        "Failed to parse",
        id="yaml-error-returns-none",
    ),
]


@pytest.mark.parametrize("text, expected, printed", METADATA_LANGUAGE_CASES)
def test_get_metadata_language(text, expected, printed, tmp_path, monkeypatch, capsys):
    md = tmp_path / "metadata.yaml"
    if text is not None:
        md.write_text(text, encoding="utf-8")
    monkeypatch.setattr(bm, "METADATA_FILE", md)
    assert bm.get_metadata_language() == expected
    if printed is not None:
        assert printed in capsys.readouterr().out


# --------------------------------------------------------------------------
# load_export_settings
# --------------------------------------------------------------------------


# Each row: the settings text (None: no file) and the settings loaded
LOAD_EXPORT_SETTINGS_CASES = [
    pytest.param(None, {}, id="missing-returns-empty"),
    pytest.param(
        "formats:\n  pdf: pdf\n", {"formats": {"pdf": "pdf"}}, id="reads-yaml"
    ),
]


@pytest.mark.parametrize("text, expected", LOAD_EXPORT_SETTINGS_CASES)
def test_load_export_settings(text, expected, tmp_path):
    p = tmp_path / "settings.yaml"
    if text is not None:
        p.write_text(text, encoding="utf-8")
    assert bm.load_export_settings(p) == expected


# Each row: the settings, the book type and the section order resolved
# (None: the caller uses the built-in order)
SECTION_ORDER_FALLBACK_CASES = [
    pytest.param(
        {"section_order": {"ebook": None, "default": ["x"]}},
        "ebook",
        ["x"],
        id="ebook-falls-back-to-default",
    ),
    pytest.param(
        {"section_order": {"audiobook": None, "default": ["x"]}},
        "audiobook",
        ["x"],
        id="audiobook-falls-back-to-default",
    ),
    pytest.param(
        {"section_order": {"hardcover": None, "paperback": ["y"]}},
        "hardcover",
        ["y"],
        id="hardcover-falls-back-to-paperback",
    ),
    pytest.param(
        {"section_order": {"paperback": None, "default": ["x"]}},
        "paperback",
        None,
        id="paperback-has-no-fallback",
    ),
    pytest.param({}, "ebook", None, id="no-section-order-is-none"),
]


@pytest.mark.parametrize("settings, book_type, expected", SECTION_ORDER_FALLBACK_CASES)
def test_get_section_order_from_settings_null_fallback_chain(
    settings, book_type, expected
):
    assert bm.get_section_order_from_settings(settings, book_type) == expected


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


# Each row: the files in output/, the files in an old backup/ (None: no
# backup yet), verbose?, whether backup/ exists afterwards, a line printed
# (None: nothing to check). output/ is always recreated empty.
PREPARE_OUTPUT_FOLDER_CASES = [
    pytest.param(["a.txt"], None, True, True, None, id="moves-content-to-backup"),
    # Old backup replaced, then new backup contains only the moved files.
    pytest.param(
        ["a.txt"],
        ["old.txt"],
        True,
        True,
        "Deleted old backup",
        id="removes-existing-backup",
    ),
    pytest.param([], None, False, False, None, id="skips-backup-when-output-empty"),
]


@pytest.mark.parametrize(
    "output_files, backup_files, verbose, expect_bak, printed",
    PREPARE_OUTPUT_FOLDER_CASES,
)
def test_prepare_output_folder(
    output_files,
    backup_files,
    verbose,
    expect_bak,
    printed,
    tmp_path,
    monkeypatch,
    capsys,
):
    out = tmp_path / "output"
    bak = tmp_path / "backup"
    out.mkdir()
    for name in output_files:
        (out / name).write_text("x", encoding="utf-8")
    if backup_files is not None:
        bak.mkdir()
        for name in backup_files:
            (bak / name).write_text("old", encoding="utf-8")
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(bm, "BACKUP_DIR", str(bak))

    bm.prepare_output_folder(verbose=verbose)
    assert out.exists()
    assert not any(out.iterdir())
    assert bak.exists() is expect_bak
    for name in output_files:
        assert (bak / name).exists()
    for name in backup_files or []:
        assert not (bak / name).exists()
    if printed is not None:
        assert printed in capsys.readouterr().out


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


# Each row: the format, extra compile_book arguments ({tmp} in a value is the
# project directory), tokens the Pandoc argv must contain, texts some token
# must contain, prefixes no token may start with
COMPILE_BOOK_ARGV_CASES = [
    pytest.param(
        "pdf",
        {"resource_path": "{tmp}/assets"},
        ["--pdf-engine=xelatex", "mainfont=DejaVu Sans"],
        [],
        [],
        id="pdf-includes-pdf-engine-flags",
    ),
    pytest.param(
        "markdown", {}, ["--wrap=none"], [], [], id="markdown-includes-wrap-none"
    ),
    pytest.param(
        "html",
        {"lang": "fr"},
        ["--standalone", "--css=assets/style.css", "lang=fr"],
        [],
        [],
        id="html-includes-standalone-and-css",
    ),
    pytest.param(
        "epub",
        {},
        ["--toc", "--split-level=1"],
        ["--toc-depth="],
        ["--epub-chapter-level"],
        id="epub-ebook-includes-toc-and-split-level",
    ),
    pytest.param(
        "epub",
        {"force_epub2": True},
        ["epub.version=2"],
        [],
        [],
        id="epub2-sets-metadata",
    ),
    pytest.param(
        "epub",
        {"cover_path": "cover.jpg"},
        ["--epub-cover-image=cover.jpg"],
        [],
        [],
        id="epub-cover-image-included",
    ),
]


@pytest.mark.parametrize(
    "fmt, kwargs, present, fragments, absent_prefixes", COMPILE_BOOK_ARGV_CASES
)
def test_compile_book_argv(
    fmt, kwargs, present, fragments, absent_prefixes, monkeypatch, tmp_path
):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    kwargs = {
        k: v.format(tmp=tmp_path) if isinstance(v, str) else v
        for k, v in kwargs.items()
    }

    argv = _compile_and_capture(monkeypatch, format=fmt, **kwargs)
    assert argv is not None
    for token in present:
        assert token in argv
    for text in fragments:
        assert any(text in a for a in argv)
    for prefix in absent_prefixes:
        assert not any(a.startswith(prefix) for a in argv)


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


def test_compile_book_wraps_calledprocesserror_as_pandoc_error(monkeypatch, tmp_path):
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
        bm.compile_book("pdf", ["chapters/ch1.md"], BookType.EBOOK, strict_images=True)


def test_compile_book_lenient_mode_logs_and_continues(monkeypatch, tmp_path, caplog):
    import logging

    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    def fake_run(cmd, **kw):
        return _CP(stderr='[WARNING] Could not fetch resource "images/missing.png"\n')

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    with caplog.at_level(logging.WARNING, logger="manuscripta.export.book"):
        bm.compile_book("pdf", ["chapters/ch1.md"], BookType.EBOOK, strict_images=False)
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


# Each row: the run_export keyword arguments, (flag, value) pairs the argv
# must carry side by side, tokens it must contain, tokens it must not
RUN_EXPORT_ARGV_CASES = [
    pytest.param(
        {
            "formats": ["pdf", "epub"],
            "section_order": ["front-matter/foreword.md", "chapters"],
            "cover": "cover.jpg",
            "epub2": True,
            "lang": "de",
            "extension": "gfm",
            "book_type": BookType.PAPERBACK,
            "output_file": "custom",
            "no_type_suffix": True,
            "toc_depth": 3,
            "use_manual_toc": True,
            "skip_images": True,
            "copy_epub_to": "/tmp/out",
        },
        [],
        [
            "--format",
            "pdf,epub",
            "--order",
            "--cover",
            "cover.jpg",
            "--epub2",
            "--lang",
            "de",
            "--extension",
            "gfm",
            "--book-type",
            "paperback",
            "--output-file",
            "custom",
            "--no-type-suffix",
            "--toc-depth",
            "3",
            "--use-manual-toc",
            "--skip-images",
            "--copy-epub-to",
        ],
        [],
        id="builds-argv-with-every-option",
    ),
    pytest.param(
        {"formats": "pdf"}, [("--format", "pdf")], [], [], id="formats-as-string"
    ),
    pytest.param(
        {"formats": "pdf", "keep_relative_paths": True},
        [],
        ["--keep-relative-paths"],
        ["--skip-images"],
        id="keep-relative-paths-when-not-skip-images",
    ),
    pytest.param(
        {"formats": "pdf", "book_type": "hardcover"},
        [("--book-type", "hardcover")],
        [],
        [],
        id="book-type-string-is-accepted",
    ),
]


@pytest.mark.parametrize("kwargs, pairs, present, absent", RUN_EXPORT_ARGV_CASES)
def test_run_export_argv(kwargs, pairs, present, absent, tmp_path, monkeypatch):
    _valid_project(tmp_path)
    captured = _capture_pipeline(monkeypatch)
    bm.run_export(tmp_path, **kwargs)
    argv = captured["argv"]
    for flag, value in pairs:
        assert argv[argv.index(flag) + 1] == value
    for token in present:
        assert token in argv
    for token in absent:
        assert token not in argv


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
    assert seen["cmd"][0] == sys.executable
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


# Each row: the Pandoc stderr and the unresolved image paths parsed from it
PARSE_UNRESOLVED_CASES = [
    pytest.param(
        '[WARNING] Could not fetch resource "images/a.png": not found\n',
        ["images/a.png"],
        id="extracts-double-quoted",
    ),
    pytest.param(
        "[WARNING] Could not fetch resource 'images/b.png'\n",
        ["images/b.png"],
        id="extracts-single-quoted",
    ),
    pytest.param(
        '[WARNING] Could not fetch resource "x.png"\n'
        '[WARNING] Could not fetch resource "x.png"\n',
        ["x.png"],
        id="deduplicates",
    ),
    pytest.param("no warnings here", [], id="empty-on-no-match"),
]


@pytest.mark.parametrize("stderr, expected", PARSE_UNRESOLVED_CASES)
def test_parse_unresolved_images(stderr, expected):
    assert bm._parse_unresolved_images(stderr) == expected


# --------------------------------------------------------------------------
# _validate_layout
# --------------------------------------------------------------------------


# Each row: builds the path under tmp_path, the reason of the
# ManuscriptaLayoutError (None: subdirectories missing) and the
# subdirectories it lists
VALIDATE_LAYOUT_REJECTS = [
    pytest.param(lambda t: t / "nope", "nonexistent", [], id="rejects-missing"),
    pytest.param(
        lambda t: _file(t / "file.txt"), "not_a_directory", [], id="rejects-file"
    ),
    pytest.param(
        lambda t: _dir(t / "empty"),
        None,
        ["manuscript", "config", "assets"],
        id="rejects-empty-directory",
    ),
]


@pytest.mark.parametrize("build, reason, missing", VALIDATE_LAYOUT_REJECTS)
def test_validate_layout_rejects(build, reason, missing, tmp_path):
    with pytest.raises(ManuscriptaLayoutError) as ex:
        bm._validate_layout(build(tmp_path))
    assert ex.value.reason == reason
    assert ex.value.missing == missing


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

    for name in (
        "validate_pdf",
        "validate_epub_with_epubcheck",
        "validate_docx",
        "validate_markdown",
        "validate_html",
    ):
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
    for name in (
        "validate_pdf",
        "validate_epub_with_epubcheck",
        "validate_docx",
        "validate_markdown",
        "validate_html",
    ):
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


# --------------------------------------------------------------------------
# Built-in section orders and the "not in section order" warning
# --------------------------------------------------------------------------


# Each row: a built-in section order, an entry, the entries it sits between
BUILTIN_ORDER_SLOTS = [
    pytest.param(
        bm._BUILTIN_DEFAULT_SECTION_ORDER,
        "back-matter/other-publications.md",
        "back-matter/about-the-author.md",
        "back-matter/imprint.md",
        id="default-order-has-other-publications-slot",
    ),
    pytest.param(
        bm._BUILTIN_PAPERBACK_SECTION_ORDER,
        "back-matter/other-publications-print.md",
        "back-matter/about-the-author.md",
        "back-matter/imprint.md",
        id="paperback-order-has-other-publications-print-slot",
    ),
]


@pytest.mark.parametrize("order, entry, before, after", BUILTIN_ORDER_SLOTS)
def test_builtin_order_slot(order, entry, before, after):
    assert order.index(before) < order.index(entry) < order.index(after)


def test_compile_book_skips_missing_other_publications_file(monkeypatch, tmp_path):
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "ch1.md").write_text("# x", encoding="utf-8")
    (tmp_path / "back-matter").mkdir()
    (tmp_path / "back-matter" / "imprint.md").write_text("# i", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    captured = {}

    def fake_run(cmd, **kw):
        captured["argv"] = list(cmd)
        return _CP()

    monkeypatch.setattr(bm.subprocess, "run", fake_run)
    bm.compile_book(
        "pdf",
        [
            "chapters",
            "back-matter/other-publications.md",
            "back-matter/imprint.md",
        ],
        BookType.EBOOK,
    )
    argv = captured["argv"]
    md_args = [a for a in argv if a.endswith(".md")]
    assert [Path(a).name for a in md_args] == ["ch1.md", "imprint.md"]


def test_compile_book_warns_about_markdown_not_in_section_order(
    monkeypatch, tmp_path, capsys
):
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "ch1.md").write_text("# x", encoding="utf-8")
    (tmp_path / "chapters" / "drafts").mkdir()
    (tmp_path / "chapters" / "drafts" / "idea.md").write_text("# d", encoding="utf-8")
    (tmp_path / "back-matter").mkdir()
    (tmp_path / "back-matter" / "next-in-series.md").write_text("# n", encoding="utf-8")
    (tmp_path / "back-matter" / "notes.md.bak").write_text("# b", encoding="utf-8")
    (tmp_path / "front-matter").mkdir()
    (tmp_path / "front-matter" / "toc.md").write_text("# t", encoding="utf-8")
    (tmp_path / "front-matter" / "toc-print.md").write_text("# t", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr(bm.subprocess, "run", lambda cmd, **kw: _CP())
    monkeypatch.setattr(bm, "OUTPUT_FILE", "book")

    bm.compile_book("pdf", ["chapters"], BookType.EBOOK)

    out = capsys.readouterr().out
    assert (
        "⚠️  Not in section order, skipped: "
        "back-matter/next-in-series.md, chapters/drafts/idea.md" in out
    )
    # The manual TOC files are dropped on purpose and never reported.
    assert "toc.md" not in out
    assert "toc-print.md" not in out
    assert "notes.md.bak" not in out


def test_compile_book_no_warning_when_every_markdown_file_is_used(
    monkeypatch, tmp_path, capsys
):
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "ch1.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(bm, "BOOK_DIR", str(tmp_path))
    monkeypatch.setattr(bm, "OUTPUT_DIR", str(tmp_path / "output"))
    _compile_and_capture(monkeypatch, format="pdf")
    assert "Not in section order" not in capsys.readouterr().out


def test_report_unlisted_markdown_returns_relative_sorted_paths(tmp_path, capsys):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "z.md").write_text("", encoding="utf-8")
    (tmp_path / "a.md").write_text("", encoding="utf-8")
    (tmp_path / "used.md").write_text("", encoding="utf-8")
    (tmp_path / "skip.md").write_text("", encoding="utf-8")

    result = bm.report_unlisted_markdown(
        str(tmp_path), [str(tmp_path / "used.md")], skip_files=["skip.md"]
    )

    assert result == ["a.md", "b/z.md"]
    assert "Not in section order, skipped: a.md, b/z.md" in capsys.readouterr().out


def test_report_unlisted_markdown_uses_epub_skip_list_by_default(
    monkeypatch, tmp_path, capsys
):
    (tmp_path / "front-matter").mkdir()
    (tmp_path / "front-matter" / "custom-toc.md").write_text("", encoding="utf-8")
    monkeypatch.setattr(bm, "EPUB_SKIP_TOC_FILES", ["front-matter/custom-toc.md"])
    assert bm.report_unlisted_markdown(str(tmp_path), []) == []
    assert capsys.readouterr().out == ""


def test_report_unlisted_markdown_nonexistent_dir_is_silent(tmp_path, capsys):
    assert bm.report_unlisted_markdown(str(tmp_path / "missing"), []) == []
    assert capsys.readouterr().out == ""
