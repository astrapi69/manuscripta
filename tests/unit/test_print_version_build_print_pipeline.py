# tests/test_print_version_build_print_pipeline.py
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import manuscripta.export.print_version as bp


class DummyProc:
    def __init__(self, returncode: int = 0):
        self.returncode = returncode


def _is_python_module_invocation(cmd: list[str]) -> bool:
    """Check if cmd is a python -m invocation."""
    if len(cmd) < 3:
        return False
    return "python" in cmd[0] and cmd[1] == "-m"


EXPORT_ARGS = ["--format=epub", "--book-type=paperback", "--skip-images"]

# Each row: the arguments, the exit status of the export step, the exit status
# of main(), the arguments the export is run with, the commands run after it
# (git restore is opt-in), a text the output carries
PIPELINE_CASES = [
    pytest.param(
        ["--restore"],
        0,
        0,
        EXPORT_ARGS,
        [["git", "restore", "."]],
        "Print version EPUB successfully generated",
        id="order-and-success",
    ),
    # Pipeline should abort with exit code 1 on step failure
    pytest.param(
        [],
        1,
        1,
        EXPORT_ARGS,
        [],
        "Build process aborted.",
        id="aborts-on-failure",
    ),
    pytest.param(
        [],
        0,
        0,
        EXPORT_ARGS,
        [],
        "Print version EPUB successfully generated",
        id="restore-is-opt-in",
    ),
    pytest.param(
        ["--export-format", "pdf", "--book-type", "hardcover", "--lang=de"],
        0,
        0,
        ["--format=pdf", "--book-type=hardcover", "--skip-images", "--lang=de"],
        [],
        "Print version PDF successfully generated",
        id="pdf-hardcover-forwards-the-rest",
    ),
]


@pytest.mark.parametrize(
    "argv, export_rc, code, export_args, after, text", PIPELINE_CASES
)
def test_pipeline(
    argv,
    export_rc,
    code,
    export_args,
    after,
    text,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, check=True):
        calls.append(cmd)
        if _is_python_module_invocation(cmd) and export_rc:
            raise bp.subprocess.CalledProcessError(returncode=export_rc, cmd=cmd)
        return DummyProc(0)

    monkeypatch.setattr(bp.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as ex:
        bp.main(argv)
    assert ex.value.code == code

    # The export runs first, as python -m manuscripta.export.book; the commands
    # after it are exactly the ones expected (so no second export either)
    assert _is_python_module_invocation(calls[0]), calls
    assert calls[0][2:] == ["manuscripta.export.book", *export_args]
    assert calls[1:] == after

    out, _ = capsys.readouterr()
    assert text in out
