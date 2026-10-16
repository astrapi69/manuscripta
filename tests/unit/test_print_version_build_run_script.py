import pytest

pytestmark = pytest.mark.unit

# tests/test_print_version_build_run_script.py
import sys

import manuscripta.export.print_version as bp


class DummyProc:
    def __init__(self, rc=0):
        self.returncode = rc


MODULE = "manuscripta.export.book"
CMD = f"{sys.executable} -m {MODULE}"

# Each row: the script arguments, dry run?, the exit status of the command
# (None: it is never run), the result, a line the output carries (None:
# nothing is printed)
RUN_SCRIPT_CASES = [
    pytest.param((), False, 0, True, None, id="success"),
    pytest.param(
        (), False, 1, False, f"Command failed with exit code 1: {CMD}", id="failure"
    ),
    pytest.param(
        (),
        False,
        2,
        False,
        f"Command failed with exit code 2: {CMD}",
        id="failure-reports-the-exit-code",
    ),
    pytest.param(
        ("--foo=1",),
        True,
        None,
        True,
        f"[dry-run] Would run: {CMD} --foo=1",
        id="dry-run",
    ),
]


@pytest.mark.parametrize("script_args, dry_run, rc, result, printed", RUN_SCRIPT_CASES)
def test_run_script(script_args, dry_run, rc, result, printed, monkeypatch, capsys):
    calls: list[list[str]] = []

    def fake_run(cmd, check=True):
        calls.append(cmd)
        if rc:
            raise bp.subprocess.CalledProcessError(returncode=rc, cmd=cmd)
        return DummyProc(0)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)

    assert bp.run_script(MODULE, *script_args, dry_run=dry_run) is result
    assert calls == (
        [] if rc is None else [[sys.executable, "-m", MODULE, *script_args]]
    )
    out, _ = capsys.readouterr()
    if printed is None:
        assert out == ""
    else:
        assert printed in out
