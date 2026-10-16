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


# Each row: the command, its timeout, the status and stderr run_cmd returns
RUN_CMD_CASES = [
    pytest.param(["true"], None, 0, "", id="success-on-real-binary"),
    pytest.param(
        ["nonexistent-binary-xyzzy-12345"],
        None,
        127,
        "command not found",
        id="file-not-found-returns-127",
    ),
    pytest.param(["sleep", "2"], 1, 124, "timeout", id="timeout-returns-124"),
]


@pytest.mark.parametrize("cmd, timeout, rc, err", RUN_CMD_CASES)
def test_run_cmd(cmd, timeout, rc, err):
    status, _, stderr = vmod.run_cmd(cmd, timeout=timeout)
    assert status == rc
    assert stderr == err


# --- require_cmd -----------------------------------------------------------


# Each row: a command name and whether require_cmd finds it
REQUIRE_CMD_CASES = [
    pytest.param("true", True, id="true-for-existing-binary"),
    pytest.param(
        "nonexistent-binary-xyzzy-12345", False, id="false-for-missing-binary"
    ),
]


@pytest.mark.parametrize("name, expected", REQUIRE_CMD_CASES)
def test_require_cmd(name, expected):
    assert vmod.require_cmd(name) is expected


# --- validation CLI main() --------------------------------------------------


def _stub(monkeypatch, name, rc):
    """Replace a validate_* entrypoint with one that records and returns ``rc``."""
    calls = []

    def fake(path, **kw):
        calls.append(path)
        return rc

    monkeypatch.setattr(vmod, name, fake)
    return calls


# Each row: the file suffix, the arguments after the path and the validate_*
# entry point main() dispatches to
DISPATCH_CASES = [
    pytest.param(".epub", [], "validate_epub_with_epubcheck", id="epub"),
    pytest.param(".pdf", [], "validate_pdf", id="pdf"),
    pytest.param(".docx", [], "validate_docx", id="docx"),
    pytest.param(".md", [], "validate_markdown", id="md"),
    pytest.param(".markdown", [], "validate_markdown", id="markdown"),
    pytest.param(".html", [], "validate_html", id="html"),
    pytest.param(".htm", [], "validate_html", id="htm"),
    pytest.param(
        ".weird",
        ["--type", "md"],
        "validate_markdown",
        id="forced-type-overrides-extension",
    ),
]


@pytest.mark.parametrize("suffix, extra, target", DISPATCH_CASES)
def test_main_dispatches(tmp_path, monkeypatch, suffix, extra, target):
    calls = _stub(monkeypatch, target, rc=0)
    p = tmp_path / f"a{suffix}"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        vmod.main([str(p), *extra])
    assert ex.value.code == 0
    assert calls == [str(p)]


def test_main_unknown_extension_returns_1(tmp_path, capsys):
    p = tmp_path / "file.weird"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        vmod.main([str(p)])
    assert ex.value.code == 1
    assert "Unknown type" in capsys.readouterr().out


# --- validate_markdown / validate_html edge cases -------------------------


# Each row: an empty file's name and the validator that rejects it with 1
EMPTY_FILE_CASES = [
    pytest.param("empty.md", vmod.validate_markdown, id="validate-markdown"),
    pytest.param("empty.html", vmod.validate_html, id="validate-html"),
]


@pytest.mark.parametrize("name, validator", EMPTY_FILE_CASES)
def test_empty_file_returns_1(name, validator, tmp_path, capsys):
    p = tmp_path / name
    p.write_text("", encoding="utf-8")
    assert validator(str(p)) == 1
    assert "empty" in capsys.readouterr().out.lower()


# --- images.inject.parse_args and main ------------------------------------


# Each row: the arguments and the chapter dir, image dir, prompt file and
# dry-run flag parsed
INJECT_PARSE_ARGS_CASES = [
    pytest.param(
        [],
        Path("manuscript/chapters"),
        Path("assets/illustrations"),
        Path("config/data/image_prompts.json"),
        False,
        id="defaults",
    ),
    pytest.param(
        [
            "--chapter-dir",
            "alt-chapters",
            "--image-dir",
            "alt-images",
            "--prompt-file",
            "alt.json",
            "--dry-run",
        ],
        Path("alt-chapters"),
        Path("alt-images"),
        Path("alt.json"),
        True,
        id="overrides",
    ),
]


@pytest.mark.parametrize(
    "argv, chapter_dir, image_dir, prompt_file, dry_run", INJECT_PARSE_ARGS_CASES
)
def test_inject_parse_args(argv, chapter_dir, image_dir, prompt_file, dry_run):
    ns = imod.parse_args(argv)
    assert isinstance(ns, argparse.Namespace)
    assert ns.chapter_dir == chapter_dir
    assert ns.image_dir == image_dir
    assert ns.prompt_file == prompt_file
    assert ns.dry_run is dry_run


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


# Each row: the arguments ({tmp} is a temporary directory) and the error
# process() raises; main() prints its message and returns 2
INJECT_MAIN_ERROR_CASES = [
    pytest.param(
        ["--prompt-file", "{tmp}/nope.json"],
        FileNotFoundError("prompts.json missing"),
        id="missing-file-returns-2",
    ),
    pytest.param([], ValueError("bad prompt structure"), id="value-error-returns-2"),
]


@pytest.mark.parametrize("argv, error", INJECT_MAIN_ERROR_CASES)
def test_inject_main_error(argv, error, tmp_path, monkeypatch, capsys):
    def fake(*a, **kw):
        raise error

    monkeypatch.setattr(imod, "process", fake)
    rc = imod.main([a.format(tmp=tmp_path) for a in argv])
    assert rc == 2
    assert str(error) in capsys.readouterr().out
