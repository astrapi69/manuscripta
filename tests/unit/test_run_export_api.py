"""Contract tests for the v0.8.0 public library API.

These tests avoid invoking Pandoc unless it is installed on the host; the
image-embedding end-to-end check is gated by ``pytest.importorskip`` style
availability checks.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

from manuscripta import ManuscriptaImageError, ManuscriptaLayoutError
from manuscripta.export import book as book_mod


# ---------------------------------------------------------------------------
# Fixture builders (create a consumer-shaped project in tmp_path)
# ---------------------------------------------------------------------------


def _write_png(path: Path) -> None:
    """Write a minimal 1x1 red PNG to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),  # 1x1 RGB
    )
    raw = b"\x00\xff\x00\x00"  # filter byte + R,G,B
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    path.write_bytes(signature + ihdr + idat + iend)


def _make_consumer_project(
    root: Path, *, with_image: bool = True, image_ref: str = "images/pic.png"
) -> Path:
    """Build a minimal manuscripta-shaped project rooted at ``root``."""
    (root / "manuscript" / "chapters").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "assets" / "images").mkdir(parents=True)

    (root / "config" / "metadata.yaml").write_text(
        'title: "Fixture Book"\nauthor: "Tester"\nlang: "en"\n',
        encoding="utf-8",
    )
    (root / "manuscript" / "chapters" / "ch01.md").write_text(
        f"# Chapter One\n\nHello world.\n\n![pic]({image_ref})\n",
        encoding="utf-8",
    )
    if with_image:
        _write_png(root / "assets" / image_ref)
    return root


# ---------------------------------------------------------------------------
# Contract: source_dir is required
# ---------------------------------------------------------------------------


def test_run_export_requires_source_dir():
    """Calling without source_dir must fail with TypeError at call time."""
    with pytest.raises(TypeError):
        book_mod.run_export()  # type: ignore[call-arg]


def test_run_export_rejects_none_source_dir():
    with pytest.raises(TypeError):
        book_mod.run_export(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Contract: layout validation
# ---------------------------------------------------------------------------


def test_run_export_layout_error_lists_missing(tmp_path):
    # Create only one of the three required dirs so we can assert what's missing.
    (tmp_path / "manuscript").mkdir()
    with pytest.raises(ManuscriptaLayoutError) as excinfo:
        book_mod.run_export(tmp_path)
    err = excinfo.value
    assert set(err.missing) == {"config", "assets"}
    assert err.source_dir == tmp_path.resolve() or err.source_dir == tmp_path


def test_run_export_layout_error_when_source_dir_missing(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(ManuscriptaLayoutError):
        book_mod.run_export(nonexistent)


# ---------------------------------------------------------------------------
# Contract: _configure_paths + resource_paths
# ---------------------------------------------------------------------------


def test_configure_paths_anchors_on_source_dir(tmp_path):
    _make_consumer_project(tmp_path)
    extras = [tmp_path / "assets" / "images"]
    resource_path = book_mod._configure_paths(tmp_path, extras)

    parts = resource_path.split(os.pathsep)
    assert Path(parts[0]) == (tmp_path / "assets").resolve()
    assert Path(parts[1]) == (tmp_path / "assets" / "images").resolve()
    assert Path(book_mod.OUTPUT_DIR) == (tmp_path / "output").resolve()
    assert Path(book_mod.BOOK_DIR) == (tmp_path / "manuscript").resolve()


# ---------------------------------------------------------------------------
# Contract: strict_images behavior (mocks Pandoc)
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, stderr: str = "", stdout: str = ""):
        self.stderr = stderr
        self.stdout = stdout


def _unresolved_stderr() -> str:
    return (
        "[INFO] Running pandoc\n"
        '[WARNING] Could not fetch resource "images/missing.png": '
        "PandocResourceNotFound\n"
    )


def test_strict_images_raises_on_pandoc_warning(tmp_path, monkeypatch):
    _make_consumer_project(tmp_path, with_image=False, image_ref="images/missing.png")

    # Have subprocess.run (the pandoc call inside compile_book) return a
    # faked completed process with a resource-warning in stderr.
    def fake_run(cmd, **kwargs):
        # We only intercept the pandoc invocation (has --from=markdown).
        if cmd and cmd[0] == "pandoc":
            return _FakeCompleted(stderr=_unresolved_stderr())
        # Any other subprocess call (run_script helpers) is a no-op pass.
        return _FakeCompleted()

    monkeypatch.setattr(book_mod.subprocess, "run", fake_run)

    # Avoid background validation threads doing real I/O.
    monkeypatch.setattr(book_mod, "validate_pdf", lambda *a, **k: None)

    with pytest.raises(ManuscriptaImageError) as excinfo:
        book_mod.run_export(
            tmp_path,
            formats="pdf",
            strict_images=True,
            skip_images=True,  # skip in-place path rewrite scripts
        )
    assert "missing.png" in str(excinfo.value)
    assert excinfo.value.unresolved == ["images/missing.png"]


def test_lenient_images_does_not_raise(tmp_path, monkeypatch, capsys):
    _make_consumer_project(tmp_path, with_image=False, image_ref="images/missing.png")

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "pandoc":
            return _FakeCompleted(stderr=_unresolved_stderr())
        return _FakeCompleted()

    monkeypatch.setattr(book_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(book_mod, "validate_pdf", lambda *a, **k: None)

    book_mod.run_export(
        tmp_path,
        formats="pdf",
        strict_images=False,
        skip_images=True,
    )
    # Stderr is surfaced as stdout-print warning in lenient mode.
    assert "missing.png" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Contract: library does not chdir (behavior check)
# ---------------------------------------------------------------------------


def test_run_export_does_not_change_cwd(tmp_path, monkeypatch):
    _make_consumer_project(tmp_path)
    elsewhere = tmp_path.parent
    monkeypatch.chdir(elsewhere)
    before = Path.cwd()

    def fake_run(cmd, **kwargs):
        return _FakeCompleted()

    monkeypatch.setattr(book_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(book_mod, "validate_pdf", lambda *a, **k: None)

    book_mod.run_export(
        tmp_path,
        formats="pdf",
        strict_images=False,
        skip_images=True,
    )

    assert Path.cwd() == before


# ---------------------------------------------------------------------------
# CLI layer: cwd fallback at CLI only
# ---------------------------------------------------------------------------


def test_cli_main_uses_cwd_when_source_dir_omitted(tmp_path, monkeypatch):
    _make_consumer_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    called = {}

    def fake_pipeline(*, argv, source_dir, resource_path, strict_images):
        called["source_dir"] = source_dir
        called["resource_path"] = resource_path
        called["strict_images"] = strict_images

    monkeypatch.setattr(book_mod, "_run_pipeline", fake_pipeline)
    book_mod.main(["--format", "pdf"])

    assert called["source_dir"] == tmp_path.resolve()
    assert called["strict_images"] is True
    assert "assets" in called["resource_path"]


def test_cli_main_honors_source_dir_flag(tmp_path, monkeypatch):
    _make_consumer_project(tmp_path)
    elsewhere = tmp_path.parent
    monkeypatch.chdir(elsewhere)

    called = {}

    def fake_pipeline(*, argv, source_dir, resource_path, strict_images):
        called["source_dir"] = source_dir

    monkeypatch.setattr(book_mod, "_run_pipeline", fake_pipeline)
    book_mod.main(["--source-dir", str(tmp_path), "--format", "pdf"])
    assert called["source_dir"] == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Integration: real Pandoc build with pdfimages verification
# ---------------------------------------------------------------------------


def _tool(name: str) -> bool:
    return shutil.which(name) is not None


@pytest.mark.skipif(
    not (_tool("pandoc") and _tool("pdfimages") and _tool("xelatex")),
    reason="pandoc + xelatex + pdfimages required for the embedded-image check",
)
def test_image_is_embedded_in_pdf_when_called_from_outside_repo(tmp_path, monkeypatch):
    project = tmp_path / "book"
    _make_consumer_project(project)
    monkeypatch.chdir(tmp_path)  # invoke from OUTSIDE the project

    book_mod.run_export(
        project,
        formats="pdf",
        strict_images=True,
        skip_images=True,  # don't rely on path-rewrite helpers
    )

    pdf = project / "output" / "book_ebook.pdf"
    # OUTPUT_FILE may be derived from project name; fall back to any pdf in output/
    if not pdf.exists():
        candidates = list((project / "output").glob("*.pdf"))
        assert candidates, "No PDF produced"
        pdf = candidates[0]

    result = subprocess.run(
        ["pdfimages", "-list", str(pdf)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Header + at least one image row.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) >= 3, f"pdfimages -list did not show an embedded image:\n{result.stdout}"
