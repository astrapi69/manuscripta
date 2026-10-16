import pytest

pytestmark = pytest.mark.unit

# tests/test_bulk_change_extension.py
from pathlib import Path
import re
import subprocess
import sys

from manuscripta.utils.bulk_extension import change_extension, main  # <- fixed import

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
    pytest.param(
        {
            "a.png": DATA,
            "a.jpg": b"old",
            "b.png": DATA,
            "b.jpg": b"old",
            "n.txt": DATA,
            "z.png": DATA,
        },
        "png",
        "jpg",
        dict(overwrite=False),
        {
            "processed": 6,
            "renamed": 1,
            "skipped_conflict": 2,
            "skipped_nonmatch": 3,
            "planned": 1,
            "errors": 0,
        },
        {
            "a.png": DATA,
            "a.jpg": b"old",
            "b.png": DATA,
            "b.jpg": b"old",
            "n.txt": DATA,
            "z.jpg": DATA,
        },
        id="every-conflict-and-nonmatch-counted-later-files-still-renamed",
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


def test_to_dict_stringifies_changed_paths(tmp_path: Path):
    make_files(tmp_path, {"a.png": DATA, "n.txt": DATA})
    assert change_extension(tmp_path, "png", "jpg").to_dict() == {
        "processed": 2,
        "renamed": 1,
        "skipped_conflict": 0,
        "skipped_nonmatch": 1,
        "errors": 0,
        "planned": 1,
        "changed_paths": [(str(tmp_path / "a.png"), str(tmp_path / "a.jpg"))],
    }


def test_file_instead_of_directory_is_error(tmp_path: Path, capsys):
    target = tmp_path / "file.png"
    target.write_bytes(DATA)
    res = change_extension(target, "png", "jpg")
    assert (res.errors, res.processed) == (1, 0)
    assert capsys.readouterr().err == f"❌ Not a directory: {target}\n"
    assert tree(tmp_path) == {"file.png": DATA}


def complete(renamed: int, conflicts: int = 0, errors: int = 0) -> str:
    """The summary line of a real run."""
    return (
        f"✅ Rename complete: {renamed} file(s) changed. "
        f"{conflicts} conflict(s) skipped. {errors} error(s)."
    )


def refusing(message: str):
    """A Path method that fails with PermissionError(``message``)."""

    def method(self, *args, **kwargs):
        raise PermissionError(message)

    return method


# Each row: the files, the Path method failing, overwrite?, the "❌" line
# printed to stderr ({dir}: the directory), the RenameResult fields expected,
# the files afterwards
FILESYSTEM_FAILURES = [
    pytest.param(
        {"a.png": DATA},
        "rename",
        False,
        "❌ Failed to rename '{dir}/a.png' → '{dir}/a.jpg': read-only\n",
        {"planned": 1, "renamed": 0, "errors": 1},
        {"a.png": DATA},
        id="rename-fails",
    ),
    pytest.param(
        {"a.png": DATA, "a.jpg": b"old"},
        "unlink",
        True,
        "❌ Failed to remove existing target '{dir}/a.jpg': read-only\n",
        {"planned": 0, "renamed": 0, "errors": 1},
        {"a.png": DATA, "a.jpg": b"old"},
        id="overwrite-cannot-remove-target",
    ),
    pytest.param(
        {"a.png": DATA, "b.png": DATA},
        "rename",
        False,
        "❌ Failed to rename '{dir}/a.png' → '{dir}/a.jpg': read-only\n"
        "❌ Failed to rename '{dir}/b.png' → '{dir}/b.jpg': read-only\n",
        {"planned": 2, "renamed": 0, "errors": 2},
        {"a.png": DATA, "b.png": DATA},
        id="every-failed-rename-counted",
    ),
    pytest.param(
        {"a.png": DATA, "a.jpg": b"old", "b.png": DATA, "b.jpg": b"old"},
        "unlink",
        True,
        "❌ Failed to remove existing target '{dir}/a.jpg': read-only\n"
        "❌ Failed to remove existing target '{dir}/b.jpg': read-only\n",
        {"planned": 0, "renamed": 0, "errors": 2},
        {"a.png": DATA, "a.jpg": b"old", "b.png": DATA, "b.jpg": b"old"},
        id="every-unremovable-target-counted",
    ),
]


@pytest.mark.parametrize(
    "files, method, overwrite, err, fields, files_after", FILESYSTEM_FAILURES
)
def test_filesystem_failures_are_counted(
    files, method, overwrite, err, fields, files_after, tmp_path, monkeypatch, capsys
):
    make_files(tmp_path, files)
    monkeypatch.setattr(Path, method, refusing("read-only"))
    res = change_extension(tmp_path, "png", "jpg", overwrite=overwrite)
    assert {name: getattr(res, name) for name in fields} == fields
    out, stderr = capsys.readouterr()
    assert stderr == err.replace("{dir}", str(tmp_path))
    assert out == complete(0, errors=fields["errors"]) + "\n"
    assert tree(tmp_path) == files_after


# Each row: the files, the arguments after the program name ({dir}: the
# directory), the exit code, the files afterwards, the last line printed ("":
# nothing printed), the stderr
MAIN_RUNS = [
    pytest.param(
        {"one.png": DATA, "two.PNG": DATA, "keep.jpg": b"k"},
        ["{dir}", "--from", "png", "--to", "jpg"],
        0,
        {"one.jpg": DATA, "two.jpg": DATA, "keep.jpg": b"k"},
        complete(2),
        "",
        id="png-to-jpg",
    ),
    pytest.param(
        {"a.png": DATA, "sub/b.png": DATA},
        ["{dir}", "--from", ".png", "--to", ".jpeg", "-r"],
        0,
        {"a.jpeg": DATA, "sub/b.jpeg": DATA},
        complete(2),
        "",
        id="recursive",
    ),
    pytest.param(
        {"a.png": DATA, "b.PNG": DATA},
        ["{dir}", "--from", "png", "--to", "jpg", "--case-sensitive"],
        0,
        {"a.jpg": DATA, "b.PNG": DATA},
        complete(1),
        "",
        id="case-sensitive",
    ),
    pytest.param(
        {"a.png": DATA},
        ["{dir}", "--from", "png", "--to", "jpg", "--dry-run"],
        0,
        {"a.png": DATA},
        "✅ Dry-run complete: 1 file(s) would be changed.",
        "",
        id="dry-run",
    ),
    pytest.param(
        {"a.png": DATA, "a.jpg": b"old"},
        ["{dir}", "--from", "png", "--to", "jpg"],
        0,
        {"a.png": DATA, "a.jpg": b"old"},
        complete(0, conflicts=1),
        "",
        id="conflict-skipped",
    ),
    pytest.param(
        {"a.png": DATA, "a.jpg": b"old"},
        ["{dir}", "--from", "png", "--to", "jpg", "--overwrite"],
        0,
        {"a.jpg": DATA},
        complete(1),
        "",
        id="overwrite",
    ),
    pytest.param(
        {},
        ["{dir}/missing", "--from", "png", "--to", "jpg"],
        1,
        {},
        "",
        "❌ Directory does not exist: {dir}/missing\n",
        id="missing-directory-exits-1",
    ),
]


@pytest.mark.parametrize("files, args, code, files_after, last_line, err", MAIN_RUNS)
def test_main(files, args, code, files_after, last_line, err, tmp_path, capsys):
    make_files(tmp_path, files)
    assert main([a.replace("{dir}", str(tmp_path)) for a in args]) == code
    out, stderr = capsys.readouterr()
    assert (out.splitlines() or [""])[-1] == last_line
    assert stderr == err.replace("{dir}", str(tmp_path))
    assert tree(tmp_path) == files_after


def test_main_reads_sys_argv_when_called_without_arguments(tmp_path, monkeypatch):
    make_files(tmp_path, {"x.png": DATA})
    argv = ["bulk-change-extension", str(tmp_path), "--from", "png", "--to", "gif"]
    monkeypatch.setattr(sys, "argv", argv)
    assert main() == 0
    assert tree(tmp_path) == {"x.gif": DATA}


# Each row: the arguments after the directory, the option argparse reports as
# missing
MISSING_OPTIONS = [
    pytest.param(["--from", "png"], "--to", id="to-missing"),
    pytest.param(["--to", "jpg"], "--from", id="from-missing"),
]


@pytest.mark.parametrize("args, missing", MISSING_OPTIONS)
def test_main_requires_both_extensions(args, missing, tmp_path: Path, capsys):
    with pytest.raises(SystemExit) as ex:
        main([str(tmp_path), *args])
    assert ex.value.code == 2
    required = f"the following arguments are required: {missing}"
    assert required in capsys.readouterr().err


def test_dry_run_lists_every_planned_rename_in_order(tmp_path: Path, capsys):
    make_files(tmp_path, {"b.png": DATA, "a.png": DATA, "sub/c.PNG": DATA})
    args = [str(tmp_path), "--from", "png", "--to", "jpg", "--dry-run", "-r"]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "🔎 (dry-run) a.png → a.jpg",
        "🔎 (dry-run) b.png → b.jpg",
        "🔎 (dry-run) sub/c.PNG → sub/c.jpg",
        "✅ Dry-run complete: 3 file(s) would be changed.",
    ]
    assert tree(tmp_path) == {"b.png": DATA, "a.png": DATA, "sub/c.PNG": DATA}


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as ex:
        main(["--help"])
    assert ex.value.code == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none)."""
    sections = re.split(
        r"^(?:positional arguments|options):$", help_out, maxsplit=1, flags=re.M
    )
    for line in sections[1].splitlines():
        entry = line.strip()
        if entry.startswith(flag):
            parts = re.split(r"\s{2,}", entry, maxsplit=1)
            return parts[1] if len(parts) > 1 else ""
    raise AssertionError(f"{flag} is not listed")


# Each row: an argument whose --help entry must carry some help text; what the
# text says is not asserted
OPTIONS_WITH_HELP = [
    pytest.param("directory", id="directory"),
    pytest.param("--from", id="from"),
    pytest.param("--to", id="to"),
    pytest.param("-r, --recursive", id="recursive"),
    pytest.param("--case-sensitive", id="case-sensitive"),
    pytest.param("--dry-run", id="dry-run"),
    pytest.param("--overwrite", id="overwrite"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))
