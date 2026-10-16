import pytest

pytestmark = pytest.mark.unit

# tests/test_bulk_change_extension.py
from pathlib import Path
import subprocess
import sys

from manuscripta.utils.bulk_extension import change_extension  # <- fixed import

DATA = b"data"


def make_files(base: Path, files: dict[str, bytes]):
    base.mkdir(parents=True, exist_ok=True)
    for n, content in files.items():
        p = base / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)


def tree(base: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(base)): p.read_bytes() for p in base.rglob("*") if p.is_file()
    }


# Each row: the files with their bytes, the source and the target extension, the
# keyword options, the RenameResult fields expected, the files afterwards with
# their bytes
CHANGE_EXTENSION_CASES = [
    pytest.param(
        {"a.png": DATA, "b.PNG": DATA, "c.jpg": DATA, "note.txt": DATA},
        ".png",
        ".jpg",
        dict(recursive=False),
        {"renamed": 2, "errors": 0},
        {"a.jpg": DATA, "b.jpg": DATA, "c.jpg": DATA, "note.txt": DATA},
        id="happy-path-png-to-jpg",
    ),
    pytest.param(
        {"A.png": DATA, "B.PNG": DATA, "C.PnG": DATA},
        ".png",
        ".jpg",
        dict(recursive=False, case_insensitive=False),
        {"renamed": 1},
        {"A.jpg": DATA, "B.PNG": DATA, "C.PnG": DATA},
        id="case-sensitive-only-exact-match",
    ),
    pytest.param(
        {"a.png": DATA, "sub/inner.png": DATA, "sub/deeper/leaf.PNG": DATA},
        "png",
        "jpg",
        dict(recursive=True),
        {"renamed": 3},
        {"a.jpg": DATA, "sub/inner.jpg": DATA, "sub/deeper/leaf.jpg": DATA},
        id="recursive-subdirs",
    ),
    pytest.param(
        {"x.png": DATA, "x.jpg": DATA},
        "png",
        "jpg",
        dict(overwrite=False),
        {"renamed": 0, "skipped_conflict": 1},
        {"x.png": DATA, "x.jpg": DATA},
        id="conflict-skips-when-overwrite-false",
    ),
    pytest.param(
        {"y.png": DATA, "y.jpg": b"old"},
        "png",
        "jpg",
        dict(overwrite=True),
        {"renamed": 1},
        {"y.jpg": DATA},
        id="conflict-overwrite-true",
    ),
    pytest.param(
        {"d1.png": DATA, "d2.PNG": DATA},
        "png",
        "jpg",
        dict(dry_run=True),
        {"planned": 2, "renamed": 0},
        {"d1.png": DATA, "d2.PNG": DATA},
        id="dry-run-does-not-change-files",
    ),
]


@pytest.mark.parametrize(
    "files, source_ext, dest_ext, options, fields, files_after", CHANGE_EXTENSION_CASES
)
def test_change_extension(
    files, source_ext, dest_ext, options, fields, files_after, tmp_path: Path
):
    make_files(tmp_path, files)
    res = change_extension(tmp_path, source_ext, dest_ext, **options)
    assert {name: getattr(res, name) for name in fields} == fields
    assert tree(tmp_path) == files_after


def test_directory_does_not_exist_is_error(tmp_path: Path):
    missing = tmp_path / "nope"
    res = change_extension(missing, "png", "jpg")
    assert res.errors == 1
    assert res.renamed == 0


def test_cli_smoke(tmp_path: Path):
    src = tmp_path / "cli"
    src.mkdir()
    (src / "one.png").write_bytes(b"x")
    cmd = [
        sys.executable,
        "-m",
        "manuscripta.utils.bulk_extension",  # <- run as a module from scripts
        str(src),
        "--from",
        "png",
        "--to",
        "jpg",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0
    assert (src / "one.jpg").exists()
