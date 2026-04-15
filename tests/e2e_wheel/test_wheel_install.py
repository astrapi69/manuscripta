"""Layer-4 e2e_wheel: build the wheel, install into a fresh venv, exercise it.

Three tests exactly, per TESTING.md §1.4 / ADR-0003:

1. Fresh-venv PDF build from the dsk-like fixture, verified with pdfimages.
2. Package-data audit: files shipped via the wheel match what the source
   claims to ship, so importlib.resources consumers are not surprised at
   runtime.
3. CLI smoke: a Poetry-script entry point works from the installed wheel.

Isolation contract (see TESTING.md §1.4): every test runs in its own
fresh venv rooted under tmp_path; the developer's active venv is
never touched.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.e2e_wheel

from helpers.wheel_venv import WheelVenv, built_wheel, wheel_venv  # noqa: F401


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SRC = REPO_ROOT / "tests" / "fixtures" / "dsk_like"


def _copy_fixture(tmp_path: Path) -> Path:
    """Copy the dsk-like fixture into tmp_path/book so writes don't mutate
    the checked-in tree."""
    target = tmp_path / "book"
    shutil.copytree(FIXTURE_SRC, target)
    return target


# =========================================================================
# Test 1: build wheel, install, PDF with embedded image, verified externally
# =========================================================================


@pytest.mark.requires_pandoc
@pytest.mark.requires_latex
def test_wheel_install_produces_pdf_with_embedded_image(
    tmp_path,
    wheel_venv: WheelVenv,  # noqa: F811 — pytest fixture injection by parameter name
):
    if shutil.which("pdfimages") is None:
        pytest.skip("pdfimages binary not on PATH")

    project = _copy_fixture(tmp_path)

    # Drive the library API via the *installed* wheel's Python. We
    # intentionally do NOT import manuscripta in this process — the whole
    # point of the layer is to catch "works in source, broken when
    # packaged" regressions.
    script = dedent(
        f"""
        from pathlib import Path
        from manuscripta.export.book import run_export
        run_export(
            Path({str(project)!r}),
            formats="pdf",
            strict_images=True,
            skip_images=True,
            no_type_suffix=True,
            output_file="dsk",
        )
        """
    )
    result = wheel_venv.run_python("-c", script, check=False)
    if result.returncode != 0:
        pytest.fail(
            f"run_export via wheel failed (rc={result.returncode}).\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    pdf = project / "output" / "dsk.pdf"
    assert pdf.exists(), f"PDF not produced at {pdf}"

    listed = subprocess.run(
        ["pdfimages", "-list", str(pdf)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Header (2 lines) + at least one image row.
    rows = [ln for ln in listed.stdout.splitlines() if ln.strip()]
    assert (
        len(rows) >= 3
    ), f"pdfimages -list did not show an embedded image:\n{listed.stdout}"


# =========================================================================
# Test 2: package-data audit — files shipped in the wheel match source
# =========================================================================


def test_wheel_package_data_audit(
    built_wheel: Path,  # noqa: F811 — pytest fixture injection by parameter name
):
    """Every .py under src/manuscripta/ (except test-only files) must
    also appear in the wheel. Catches ``[tool.poetry.packages]`` /
    ``include`` mis-configuration that would hide modules from
    consumers.
    """
    # Enumerate .py files in the source tree.
    src_root = REPO_ROOT / "src" / "manuscripta"
    source_modules = set()
    for p in src_root.rglob("*.py"):
        # Skip __pycache__ (never shipped).
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(src_root.parent)  # -> "manuscripta/..."
        source_modules.add(rel.as_posix())

    # Enumerate .py files actually inside the wheel zip.
    with zipfile.ZipFile(built_wheel) as zf:
        wheel_modules = {
            name
            for name in zf.namelist()
            if name.startswith("manuscripta/") and name.endswith(".py")
        }

    missing = source_modules - wheel_modules
    assert not missing, (
        f"Wheel {built_wheel.name} is missing {len(missing)} source module(s) "
        f"that exist in src/manuscripta/:\n  " + "\n  ".join(sorted(missing))
    )

    # Also verify package metadata is present.
    with zipfile.ZipFile(built_wheel) as zf:
        names = zf.namelist()
    assert any(
        n.endswith(".dist-info/METADATA") for n in names
    ), f"Wheel {built_wheel.name} missing METADATA"
    assert any(
        n.endswith(".dist-info/WHEEL") for n in names
    ), f"Wheel {built_wheel.name} missing WHEEL"


# =========================================================================
# Test 3: CLI smoke — an entry point invoked from the installed wheel
# =========================================================================


def test_wheel_cli_entry_point_smoke(
    wheel_venv: WheelVenv,  # noqa: F811 — pytest fixture injection by parameter name
):
    """The ``manuscripta-export`` console script installed by the wheel
    must at least respond to ``--help`` with a zero exit code. This is
    intentionally minimal — full CLI feature coverage belongs in unit
    tests that drive ``main()`` with synthetic argv."""
    entry = wheel_venv.venv_dir / "bin" / "manuscripta-export"
    if not entry.exists():
        pytest.fail(
            f"Expected console script not installed by wheel: {entry}. "
            f"Check [project.scripts] in pyproject.toml."
        )

    result = wheel_venv.run_script("manuscripta-export", "--help", check=False)
    assert result.returncode == 0, (
        f"manuscripta-export --help failed (rc={result.returncode}).\n"
        f"stderr:\n{result.stderr}"
    )
    assert (
        "--format" in result.stdout or "--format" in result.stderr
    ), "Expected --format option in help text"
