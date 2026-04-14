# tests/test_print_version_build_run_script.py
import manuscripta.export.print_version as bp


class DummyProc:
    def __init__(self, rc=0):
        self.returncode = rc


def test_run_script_success(monkeypatch):
    def fake_run(cmd, check=True):
        assert "python3" in cmd[0]
        assert "-m" in cmd
        assert "manuscripta.export.book" in cmd
        return DummyProc(0)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)

    assert bp.run_script("manuscripta.export.book") is True


def test_run_script_failure(monkeypatch, capsys):
    def fake_run(cmd, check=True):
        raise bp.subprocess.CalledProcessError(returncode=1, cmd=cmd)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)

    assert bp.run_script("manuscripta.export.book") is False
    out, _ = capsys.readouterr()
    assert "Command failed with exit code" in out


def test_run_script_dry_run(monkeypatch, capsys):
    called = {"run": False}

    def fake_run(*a, **k):
        called["run"] = True
        return DummyProc(0)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)
    assert bp.run_script("manuscripta.export.book", "--foo=1", dry_run=True) is True
    assert called["run"] is False
    out, _ = capsys.readouterr()
    assert "[dry-run] Would run:" in out
