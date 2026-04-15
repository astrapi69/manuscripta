"""Contract tests for the v0.8.0 public library API.

These tests avoid invoking Pandoc unless it is installed on the host; the
image-embedding end-to-end check is gated by ``pytest.importorskip`` style
availability checks.
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

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
# Regression pins for fix(cli): argparse short-circuit flags must bypass
# layout validation. The only short-circuit flag in the current parser is
# --help / -h; if --version or --list-formats is added later, extend this
# parametrisation rather than adding separate tests.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_main_help_succeeds_outside_valid_project(tmp_path, monkeypatch, capsys, flag):
    """--help / -h must exit 0 from any cwd, even one missing the
    manuscripta layout subdirs."""
    monkeypatch.chdir(tmp_path)  # empty dir, no manuscript/config/assets
    with pytest.raises(SystemExit) as exc_info:
        book_mod.main([flag])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    # argparse default help text — a minimal pin that the parser actually ran.
    assert "usage:" in out.lower()
    assert "--format" in out  # known flag from _build_arg_parser


def test_main_build_fails_outside_valid_project(tmp_path, monkeypatch):
    """A build invocation (no short-circuit flag) must still raise
    ManuscriptaLayoutError when cwd lacks the required subdirs. Pins
    that the fix did not weaken the CLI's validation contract — it only
    deferred validation past argparse."""
    monkeypatch.chdir(tmp_path)  # empty dir
    with pytest.raises(ManuscriptaLayoutError) as exc_info:
        book_mod.main(["--format", "pdf"])
    missing = set(exc_info.value.missing)
    assert missing == {"manuscript", "config", "assets"}
