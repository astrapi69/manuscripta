# tests/test_print_version_build_print_pipeline.py
from __future__ import annotations

from pathlib import Path

import pytest

import manuscripta.export.print_version as bp


class DummyProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def _is_python_module_invocation(cmd: list[str]) -> bool:
    """Check if cmd is a python -m invocation."""
    if len(cmd) < 3:
        return False
    return "python" in cmd[0] and cmd[1] == "-m"


def test_pipeline_order_and_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, check=True):
        calls.append(cmd)
        return DummyProc(0)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)

    # git restore is opt-in now
    argv = ["--restore"]
    with pytest.raises(SystemExit) as ex:
        bp.main(argv)
    assert ex.value.code == 0

    # Verify order: one python -m invocation (manuscripta.export.book) and a git restore
    py = [c for c in calls if _is_python_module_invocation(c)]
    assert len(py) == 1, f"Expected exactly one python -m call, got {len(py)}: {calls}"
    assert (
        py[0][2] == "manuscripta.export.book"
    ), f"Expected manuscripta.export.book, got: {py[0]}"

    git = [c for c in calls if c and c[0] == "git"]
    assert git, "Expected a git call to restore working tree"
    assert git[-1][1:] == [
        "restore",
        ".",
    ], f"Expected final git call to be 'restore .', got: {git[-1]}"

    out, _ = capsys.readouterr()
    assert "Print version EPUB successfully generated" in out


def test_pipeline_aborts_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(cmd, check=True):
        # Fail on the module invocation
        if len(cmd) >= 3 and cmd[2] == "manuscripta.export.book":
            raise bp.subprocess.CalledProcessError(returncode=1, cmd=cmd)
        return DummyProc(0)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as ex:
        bp.main([])

    assert ex.value.code == 1, "Pipeline should abort with exit code 1 on step failure"

    out, _ = capsys.readouterr()
    assert "Build process aborted." in out
