# tests/test_clean_git_cache.py
"""Unit tests for manuscripta.utils.git_cache. No real git runs: subprocess.run
is replaced in the module's namespace by a recorder that answers with scripted
output or raises, and records every command with its keyword arguments."""
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

import manuscripta.utils.git_cache as git_cache
from manuscripta.utils.git_cache import clean_git_cache, main, run_git_command

REFLOG_EXPIRE_NOW = ["git", "reflog", "expire", "--expire=now", "--all"]
GC_AGGRESSIVE_NOW = ["git", "gc", "--prune=now", "--aggressive"]
RUN_KWARGS = {"check": True, "capture_output": True, "text": True}


class FakeRun:
    """Stands in for subprocess.run: answers every command with the given
    stdout and stderr, or raises CalledProcessError with the given return
    code and stderr; records every command with its keyword arguments."""

    def __init__(self, stdout="", stderr="", fail=None):
        self.stdout = stdout
        self.stderr = stderr
        self.fail = fail
        self.calls: list = []
        self.kwargs: list = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        self.kwargs.append(kwargs)
        if self.fail is not None:
            returncode, stderr = self.fail
            raise subprocess.CalledProcessError(returncode, list(cmd), stderr=stderr)
        return subprocess.CompletedProcess(list(cmd), 0, self.stdout, self.stderr)


def fake_git(monkeypatch, **answer) -> FakeRun:
    fake = FakeRun(**answer)
    monkeypatch.setattr(git_cache.subprocess, "run", fake)
    return fake


# ---------------------------------------------------------------------------
# run_git_command
# ---------------------------------------------------------------------------
# Each row: git's stdout and stderr, the lines printed after the Running line,
# the text written to stderr
OUTPUT_FORWARDING = [
    pytest.param("", "", [], "", id="silent-git-prints-only-the-command"),
    pytest.param(
        "Enumerating objects: 5\n",
        "",
        ["Enumerating objects: 5"],
        "",
        id="stdout-is-echoed-stripped",
    ),
    pytest.param(
        "",
        "warning: reflog is empty\n",
        [],
        "warning: reflog is empty\n",
        id="stderr-is-forwarded-with-one-newline",
    ),
    pytest.param("done", "note", ["done"], "note\n", id="both-streams"),
]


@pytest.mark.parametrize("stdout, stderr, out_lines, err", OUTPUT_FORWARDING)
def test_run_git_command_forwards_the_output(
    stdout, stderr, out_lines, err, monkeypatch, capsys
):
    git = fake_git(monkeypatch, stdout=stdout, stderr=stderr)
    completed = run_git_command(["git", "gc"])
    out, captured_err = capsys.readouterr()
    assert out.splitlines() == ["🔧 Running: git gc", *out_lines]
    assert captured_err == err
    assert completed.stdout == stdout
    assert git.calls == [["git", "gc"]]


# Each row: the cwd given (REPO stands for tmp_path/repo) and the cwd keyword
# subprocess.run receives
CWD_FORWARDING = [
    pytest.param(None, None, id="no-cwd-is-passed-as-none"),
    pytest.param("REPO", "REPO", id="a-path-is-passed-as-a-string"),
]


@pytest.mark.parametrize("given, forwarded", CWD_FORWARDING)
def test_run_git_command_passes_cwd_and_the_robust_defaults(
    given, forwarded, monkeypatch, tmp_path
):
    git = fake_git(monkeypatch)
    repo = tmp_path / "repo"
    run_git_command(("git", "status"), cwd=repo if given else None)
    assert git.calls == [["git", "status"]]
    assert git.kwargs == [{"cwd": str(repo) if forwarded else None, **RUN_KWARGS}]


# ---------------------------------------------------------------------------
# clean_git_cache
# ---------------------------------------------------------------------------
# Each row: aggressive?, the prune spec, the reflog command, the gc command
COMMAND_CASES = [
    pytest.param(
        True,
        "now",
        REFLOG_EXPIRE_NOW,
        GC_AGGRESSIVE_NOW,
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
    git = fake_git(monkeypatch, stdout="ok")

    clean_git_cache(cwd=tmp_path, aggressive=aggressive, prune=prune)

    # Assert order & args
    assert git.calls == [reflog, gc]
    assert [kw["cwd"] for kw in git.kwargs] == [str(tmp_path), str(tmp_path)]

    # Ensure user-friendly prints happened
    out = capsys.readouterr().out
    assert "🧹 Cleaning Git object cache safely..." in out
    assert "✅ Git object cache cleaned successfully." in out


def test_clean_git_cache_propagates_errors(monkeypatch, tmp_path: Path):
    git = fake_git(
        monkeypatch,
        fail=(
            128,
            "fatal: not a git repository (or any of the parent directories): .git",
        ),
    )

    with pytest.raises(subprocess.CalledProcessError) as exc:
        clean_git_cache(cwd=tmp_path)

    assert exc.value.returncode == 128
    assert "not a git repository" in (exc.value.stderr or "").lower()
    # the gc step is not reached
    assert git.calls == [REFLOG_EXPIRE_NOW]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
PACKAGE_ROOT = str(Path(git_cache.__file__).resolve().parent.parent)


def test_main_cleans_the_repository_above_the_package_aggressively(monkeypatch, capsys):
    git = fake_git(monkeypatch)
    main()
    assert git.calls == [REFLOG_EXPIRE_NOW, GC_AGGRESSIVE_NOW]
    assert [kw["cwd"] for kw in git.kwargs] == [PACKAGE_ROOT, PACKAGE_ROOT]
    assert "✅ Git object cache cleaned successfully." in capsys.readouterr().out


# Each row: git's return code and stderr on failure (None: nothing captured),
# the ❌ line printed; main exits with that return code
MAIN_FAILURES = [
    pytest.param(
        128,
        "fatal: not a git repository\n",
        "❌ Error: fatal: not a git repository",
        id="git-stderr-is-reported",
    ),
    pytest.param(
        3,
        None,
        f"❌ Error: Command '{REFLOG_EXPIRE_NOW}' returned non-zero exit status 3.",
        id="without-stderr-the-error-itself-is-reported",
    ),
]


@pytest.mark.parametrize("returncode, stderr, line", MAIN_FAILURES)
def test_main_reports_the_failure_and_exits_with_its_code(
    returncode, stderr, line, monkeypatch, capsys
):
    git = fake_git(monkeypatch, fail=(returncode, stderr))
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == returncode
    assert line in capsys.readouterr().out.splitlines()
    assert git.calls == [REFLOG_EXPIRE_NOW]


def test_script_run_as_main(monkeypatch, capsys):
    git = fake_git(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["clean-git-cache"])
    runpy.run_path(git_cache.__file__, run_name="__main__")
    assert git.calls == [REFLOG_EXPIRE_NOW, GC_AGGRESSIVE_NOW]
    assert [kw["cwd"] for kw in git.kwargs] == [PACKAGE_ROOT, PACKAGE_ROOT]
    assert "✅ Git object cache cleaned successfully." in capsys.readouterr().out
