"""Small coverage fills for export.validation and images.inject.

Targets lines that the existing monkeypatch-heavy tests bypass:
- run_cmd's real subprocess code path (FileNotFoundError, timeout,
  generic exception)
- require_cmd (True and False)
- validate_*'s CLI dispatch (main) for every supported format
- images.inject.parse_args and main's argv routing
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from manuscripta.export import validation as vmod
from manuscripta.images import inject as imod


# --- run_cmd: the real subprocess code paths ------------------------------


def test_run_cmd_success_on_real_binary():
    rc, out, err = vmod.run_cmd(["true"])
    assert rc == 0
    assert err == ""


def test_run_cmd_file_not_found_returns_127():
    rc, out, err = vmod.run_cmd(["nonexistent-binary-xyzzy-12345"])
    assert rc == 127
    assert err == "command not found"


def test_run_cmd_timeout_returns_124():
    rc, out, err = vmod.run_cmd(["sleep", "2"], timeout=1)
    assert rc == 124
    assert err == "timeout"


# --- require_cmd -----------------------------------------------------------


def test_require_cmd_true_for_existing_binary():
    assert vmod.require_cmd("true") is True


def test_require_cmd_false_for_missing_binary():
    assert vmod.require_cmd("nonexistent-binary-xyzzy-12345") is False


# --- validation CLI main() --------------------------------------------------


def _stub(monkeypatch, name, rc):
    """Replace a validate_* entrypoint with one that records and returns ``rc``."""
    calls = []

    def fake(path, **kw):
        calls.append(path)
        return rc

    monkeypatch.setattr(vmod, name, fake)
    return calls


@pytest.mark.parametrize(
    "suffix, target",
    [
        (".epub", "validate_epub_with_epubcheck"),
        (".pdf", "validate_pdf"),
        (".docx", "validate_docx"),
        (".md", "validate_markdown"),
        (".markdown", "validate_markdown"),
        (".html", "validate_html"),
        (".htm", "validate_html"),
    ],
)
def test_main_dispatches_by_extension(tmp_path, monkeypatch, suffix, target):
    calls = _stub(monkeypatch, target, rc=0)
    p = tmp_path / f"a{suffix}"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        vmod.main([str(p)])
    assert ex.value.code == 0
    assert calls == [str(p)]


def test_main_unknown_extension_returns_1(tmp_path, capsys):
    p = tmp_path / "file.weird"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        vmod.main([str(p)])
    assert ex.value.code == 1
    assert "Unknown type" in capsys.readouterr().out


def test_main_forced_type_overrides_extension(tmp_path, monkeypatch):
    calls = _stub(monkeypatch, "validate_markdown", rc=0)
    p = tmp_path / "x.weird"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        vmod.main([str(p), "--type", "md"])
    assert calls == [str(p)]


# --- validate_markdown / validate_html edge cases -------------------------


def test_validate_markdown_empty_returns_1(tmp_path, capsys):
    p = tmp_path / "empty.md"
    p.write_text("", encoding="utf-8")
    assert vmod.validate_markdown(str(p)) == 1
    assert "empty" in capsys.readouterr().out.lower()


def test_validate_html_empty_returns_1(tmp_path, capsys):
    p = tmp_path / "empty.html"
    p.write_text("", encoding="utf-8")
    assert vmod.validate_html(str(p)) == 1
    assert "empty" in capsys.readouterr().out.lower()


# --- images.inject.parse_args and main ------------------------------------


def test_inject_parse_args_defaults():
    ns = imod.parse_args([])
    assert isinstance(ns, argparse.Namespace)
    assert ns.chapter_dir == Path("manuscript/chapters")
    assert ns.image_dir == Path("assets/illustrations")
    assert ns.prompt_file == Path("config/data/image_prompts.json")
    assert ns.dry_run is False


def test_inject_parse_args_overrides():
    ns = imod.parse_args(
        [
            "--chapter-dir",
            "alt-chapters",
            "--image-dir",
            "alt-images",
            "--prompt-file",
            "alt.json",
            "--dry-run",
        ]
    )
    assert ns.chapter_dir == Path("alt-chapters")
    assert ns.image_dir == Path("alt-images")
    assert ns.prompt_file == Path("alt.json")
    assert ns.dry_run is True


def test_inject_main_success_returns_zero(tmp_path, monkeypatch):
    # Shim inject.process so we don't touch the filesystem at module scale.
    recorded = {}

    def fake(chapters, images, prompts, dry_run):
        recorded["args"] = (chapters, images, prompts, dry_run)
        return []

    monkeypatch.setattr(imod, "process", fake)

    rc = imod.main(
        [
            "--chapter-dir",
            str(tmp_path / "c"),
            "--image-dir",
            str(tmp_path / "i"),
            "--prompt-file",
            str(tmp_path / "p.json"),
        ]
    )
    assert rc == 0
    assert recorded["args"][0] == tmp_path / "c"
    assert recorded["args"][3] is False


def test_inject_main_missing_file_returns_2(tmp_path, monkeypatch, capsys):
    def fake(*a, **kw):
        raise FileNotFoundError("prompts.json missing")

    monkeypatch.setattr(imod, "process", fake)
    rc = imod.main(
        ["--prompt-file", str(tmp_path / "nope.json")]
    )
    assert rc == 2
    out = capsys.readouterr().out
    assert "prompts.json missing" in out


def test_inject_main_value_error_returns_2(tmp_path, monkeypatch, capsys):
    def fake(*a, **kw):
        raise ValueError("bad prompt structure")

    monkeypatch.setattr(imod, "process", fake)
    rc = imod.main([])
    assert rc == 2
    assert "bad prompt structure" in capsys.readouterr().out
