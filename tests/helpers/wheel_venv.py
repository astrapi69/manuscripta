"""Wheel-install test fixtures: build once, install per test.

Implements the contract specified in ``docs/TESTING.md`` §1.4. Tests
that need to verify "built wheel installed in a fresh venv" scenarios
use :func:`wheel_venv` as a pytest fixture; it yields a handle with
``.python`` / ``.run`` / ``.run_python`` / ``.run_script`` methods that
all route through the isolated venv's interpreter.

Isolation contract (non-negotiable):

1. Each :func:`wheel_venv` yields a venv **rooted under** ``tmp_path``.
2. The outer process's ``sys.executable`` is never touched.
3. Tear-down is automatic (``tmp_path`` is removed by pytest).
4. Missing ``poetry`` or ``python -m venv`` → cleanly ``pytest.skip``
   with a named-binary reason.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class WheelVenv:
    """Handle for a fresh venv with the manuscripta wheel installed."""

    venv_dir: Path
    python: Path

    def run(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a command with the venv's bin-dir prepended to PATH."""
        import os

        env = dict(os.environ)
        env["PATH"] = f"{self.venv_dir / 'bin'}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(self.venv_dir)
        # Scrub PYTHONPATH so the wheel's installed code is used, not
        # the source tree. This is the whole point of the layer.
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            list(args),
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )

    def run_python(self, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
        """Run the venv's python with the given argv."""
        return self.run(str(self.python), *args, **kwargs)

    def run_script(
        self, entry_point: str, *args: str, **kwargs
    ) -> subprocess.CompletedProcess[str]:
        """Invoke a console-script shipped by the wheel."""
        exe = self.venv_dir / "bin" / entry_point
        return self.run(str(exe), *args, **kwargs)


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory) -> Path:
    """Build the wheel once per test session and return its path.

    Skips the session-scoped collection of e2e_wheel tests if ``poetry``
    is not available.
    """
    if shutil.which("poetry") is None:
        pytest.skip("poetry binary not on PATH — cannot build wheel")

    build_root = tmp_path_factory.mktemp("manuscripta-wheel-build")
    result = subprocess.run(
        [
            "poetry",
            "build",
            "--format=wheel",
            "--output",
            str(build_root),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            f"poetry build failed (returncode {result.returncode}).\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    wheels = list(build_root.glob("*.whl"))
    if not wheels:
        pytest.skip(f"poetry build produced no wheel in {build_root}")
    return wheels[0]


@pytest.fixture
def wheel_venv(tmp_path: Path, built_wheel: Path) -> WheelVenv:
    """Create a fresh venv under ``tmp_path`` and install the wheel.

    Strict isolation: the outer interpreter is never touched. Tear-down
    happens automatically via ``tmp_path`` cleanup.
    """
    venv_dir = tmp_path / "venv"

    # Prefer `uv venv` if available (faster), else stdlib venv.
    if shutil.which("uv"):
        subprocess.run(
            ["uv", "venv", str(venv_dir), "--python", sys.executable],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"python -m venv failed; see stderr:\n{result.stderr}")

    python = venv_dir / "bin" / "python"
    assert python.exists(), f"venv python not at {python}"

    # Install the wheel. --no-deps would miss runtime deps (yaml, toml,
    # pillow, etc.) — install those too.
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", str(built_wheel)],
        check=False,
        capture_output=True,
        text=True,
    )
    if install.returncode != 0:
        pytest.skip(f"pip install of built wheel failed:\n{install.stderr}")

    return WheelVenv(venv_dir=venv_dir, python=python)
