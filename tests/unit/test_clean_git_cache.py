# tests/test_clean_git_cache.py
from pathlib import Path
import subprocess
import pytest

pytestmark = pytest.mark.unit

from manuscripta.utils.git_cache import clean_git_cache


class DummyCompleted:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


# Each row: aggressive?, the prune spec, the reflog command, the gc command
COMMAND_CASES = [
    pytest.param(
        True,
        "now",
        ["git", "reflog", "expire", "--expire=now", "--all"],
        ["git", "gc", "--prune=now", "--aggressive"],
        id="calls-commands-in-order",
    ),
    # no --aggressive
    pytest.param(
        False,
        "1.week.ago",
        ["git", "reflog", "expire", "--expire=1.week.ago", "--all"],
        ["git", "gc", "--prune=1.week.ago"],
        id="non-aggressive",
    ),
    pytest.param(
        True,
        "1.week.ago",
        ["git", "reflog", "expire", "--expire=1.week.ago", "--all"],
        ["git", "gc", "--prune=1.week.ago", "--aggressive"],
        id="aggressive-with-prune-spec",
    ),
]


@pytest.mark.parametrize("aggressive, prune, reflog, gc", COMMAND_CASES)
def test_clean_git_cache_runs_commands(
    monkeypatch, tmp_path: Path, capsys, aggressive, prune, reflog, gc
):
    calls = []

    def fake_run(cmd, cwd=None, check=True, capture_output=True, text=True):
        # record the call
        calls.append((cmd, Path(cwd) if cwd else None))
        # mimic successful git output
        return DummyCompleted(stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Act
    clean_git_cache(cwd=tmp_path, aggressive=aggressive, prune=prune)

    # Assert order & args
    assert calls == [(reflog, tmp_path), (gc, tmp_path)]

    # Ensure user-friendly prints happened
    out = capsys.readouterr().out
    assert "🧹 Cleaning Git object cache safely..." in out
    assert "✅ Git object cache cleaned successfully." in out


def test_clean_git_cache_propagates_errors(monkeypatch, tmp_path: Path):
    def fake_run_fail(cmd, cwd=None, check=True, capture_output=True, text=True):
        raise subprocess.CalledProcessError(
            returncode=128,
            cmd=cmd,
            stderr="fatal: not a git repository (or any of the parent directories): .git",
        )

    monkeypatch.setattr(subprocess, "run", fake_run_fail)

    with pytest.raises(subprocess.CalledProcessError) as exc:
        clean_git_cache(cwd=tmp_path)

    assert exc.value.returncode == 128
    assert "not a git repository" in (exc.value.stderr or "").lower()
