import pytest

pytestmark = pytest.mark.unit

# tests/test_normalize_toc_links.py
import sys
import subprocess
from pathlib import Path

# Resolve the real repository root as two levels up from this test file
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "src" / "manuscripta" / "markdown" / "normalize_toc.py"


def run_script(toc_path: Path, args):
    assert SCRIPT_PATH.exists(), f"normalize_toc_links.py not found at {SCRIPT_PATH}"
    cmd = [sys.executable, str(SCRIPT_PATH), "--toc", str(toc_path), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),  # run from repo root for stable relative imports (if any)
        check=False,
    )


# Each row: the TOC lines, the arguments after ``--toc <path>``, the fragments
# the file must carry afterwards and the ones it must have lost
NORMALIZE_CASES = [
    pytest.param(
        [
            "- [Intro](chapters/01.gfm#einleitung)",
            "- [Kapitel 2](chapters/02.markdown#zweites)",
            "- [Schon Anker](#bereits-anker)",
            "- [Normales .md](chapters/03.md#drittes)",
        ],
        ["--mode", "strip-to-anchors"],
        [
            "(#einleitung)",
            "(#zweites)",
            "(#bereits-anker)",  # unchanged
            "(#drittes)",
        ],
        # ensure file paths are stripped
        ["chapters/01.gfm", "chapters/02.markdown", "chapters/03.md"],
        id="strip-to-anchors-basic",
    ),
    pytest.param(
        [
            "- [GFM](chapters/01.gfm#einleitung)",
            "- [MD](chapters/02.md#zweites)",
            "- [MARKDOWN](chapters/03.markdown#drittes)",
            "- [Nur Anker](#nur-anker)",  # should stay unchanged
        ],
        ["--mode", "replace-ext", "--ext", "md"],
        [
            "(chapters/01.md#einleitung)",
            "(chapters/02.md#zweites)",
            "(chapters/03.md#drittes)",
            "(#nur-anker)",  # untouched
        ],
        [],
        id="replace-ext-swaps-endings",
    ),
]


@pytest.mark.parametrize("lines, args, present, absent", NORMALIZE_CASES)
def test_normalize(lines, args, present, absent, tmp_path):
    # Create a temp TOC in tmp_path
    toc = tmp_path / "toc.md"
    toc.write_text("\n".join(lines), encoding="utf-8")

    res = run_script(toc, args)
    assert res.returncode == 0, res.stderr

    out = toc.read_text(encoding="utf-8")
    for fragment in present:
        assert fragment in out
    for fragment in absent:
        assert fragment not in out


def test_strip_to_anchors_idempotent(tmp_path):
    toc = tmp_path / "toc.md"
    toc.write_text(
        "- [Intro](chapters/01.gfm#einleitung)\n- [Anchor](#x)",
        encoding="utf-8",
    )

    res1 = run_script(toc, ["--mode", "strip-to-anchors"])
    assert res1.returncode == 0, res1.stderr
    first = toc.read_text(encoding="utf-8")

    res2 = run_script(toc, ["--mode", "strip-to-anchors"])
    assert res2.returncode == 0, res2.stderr
    second = toc.read_text(encoding="utf-8")

    assert first == second, "strip-to-anchors should be idempotent"
