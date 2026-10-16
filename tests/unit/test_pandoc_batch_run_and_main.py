# tests/test_pandoc_batch_run_and_main.py
import argparse
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
import manuscripta.utils.pandoc_batch as mod


class DummyProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


@pytest.fixture
def fake_pandoc(monkeypatch):
    # Pretend pandoc exists
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/pandoc")

    # Intercept subprocess.run to avoid calling real pandoc
    calls = []

    def _run(cmd, capture_output=True, text=True):
        calls.append(cmd)
        # success unless file name contains "fail"
        rc = 1 if any("fail" in str(part) for part in cmd) else 0
        return DummyProc(rc=rc, out="ok", err="")

    monkeypatch.setattr(mod.subprocess, "run", _run)
    return calls


def test_run_one_uses_temp_when_not_inplace(tmp_path, monkeypatch, fake_pandoc):
    f = tmp_path / "in.md"
    f.write_text("---\nNot blank after HR\n", encoding="utf-8")

    # Ensure temp gets created and later removed
    created_paths = []
    real_tmp = mod._create_temp_with

    def spy_create_temp_with(patched: str) -> Path:
        p = real_tmp(patched)
        created_paths.append(p)
        return p

    monkeypatch.setattr(mod, "_create_temp_with", spy_create_temp_with)

    args = argparse.Namespace(
        verbose=False,
        standalone=True,
        from_fmt="markdown",
        to="html",
        metadata_file=None,
        lang=None,
        resource_path=[],
        extra=None,
        patch_md=True,
        fix_inplace=False,
        report_patches=False,
    )
    _, rc, _ = mod.run_one(f, None, args)
    assert rc == 0
    # temp file created and cleaned
    assert created_paths, "expected a temp file"
    for p in created_paths:
        assert not p.exists(), "temp file should be removed"


def test_run_one_inplace_writes_back(tmp_path, fake_pandoc):
    f = tmp_path / "in.md"
    f.write_text("---\nNo blank\nNext\n", encoding="utf-8")

    args = argparse.Namespace(
        verbose=False,
        standalone=True,
        from_fmt="markdown",
        to="html",
        metadata_file=None,
        lang=None,
        resource_path=[],
        extra=None,
        patch_md=True,
        fix_inplace=True,
        report_patches=False,
    )
    before = f.read_text(encoding="utf-8")
    _, rc, _ = mod.run_one(f, None, args)
    after = f.read_text(encoding="utf-8")
    assert rc == 0
    assert after != before
    # Ensure there's a blank line AFTER the HR; since file starts with '---',
    # we should see '---\n\nNo blank'
    assert "---\n\nNo blank" in after


def test_main_end_to_end_test_only(tmp_path, monkeypatch, fake_pandoc, capsys):
    # Create minimal project with pyproject defaults
    root = tmp_path / "manuscript"
    (root / "chap").mkdir(parents=True)
    (root / "chap" / "a.md").write_text("# A", encoding="utf-8")
    (root / "chap" / "b.md").write_text("# B", encoding="utf-8")

    (tmp_path / "pyproject.toml").write_text(
        "[tool.pandoc_batch]\n"
        "root = 'manuscript'\n"
        "outdir = 'output'\n"
        "to = 'html'\n"
        "lang = 'de'\n",
        encoding="utf-8",
    )

    # Run in temp CWD so find_pyproject() sees our file
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(tmp_path)
        argv = ["--test-only", "--jobs", "2"]
        with pytest.raises(SystemExit) as ex:
            mod.main(argv)
        assert ex.value.code == 0

    out, err = capsys.readouterr()
    assert "Starting Pandoc for 2 file(s), format: html, jobs: 2..." in out
    assert "DONE without errors." in out
    assert err == ""


def test_main_reports_failures(tmp_path, monkeypatch, capsys):
    # Make one file whose name triggers rc=1 in fake runner
    root = tmp_path / "manuscript"
    root.mkdir()
    (root / "ok.md").write_text("ok", encoding="utf-8")
    (root / "will-fail.md").write_text("x", encoding="utf-8")

    # Avoid pyproject lookup; also make require_cmd a no-op
    monkeypatch.setattr(mod, "require_cmd", lambda _: None)
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/usr/bin/pandoc")

    def fake_run(cmd, capture_output=True, text=True):
        # Fail only on the real source path; ensure we use --no-patch-md so infile is last arg
        rc = 1 if "will-fail.md" in str(cmd[-1]) else 0
        return DummyProc(rc=rc, out="", err="boom" if rc else "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    argv = [
        "--root",
        str(root),
        "--outdir",
        str(tmp_path / "out"),
        "--to",
        "html",
        "--test-only",
        "--jobs",
        "1",
        "--no-patch-md",
    ]
    with pytest.raises(SystemExit) as ex:
        mod.main(argv)
    assert ex.value.code == 1

    out, err = capsys.readouterr()
    assert "FAIL" in out
    assert "DONE with 1 failure(s)." in err


def _args(**fields):
    """The run_one namespace of a plain --to html run, patched by ``fields``."""
    return argparse.Namespace(
        **{
            "verbose": False,
            "standalone": True,
            "from_fmt": "markdown",
            "to": "html",
            "metadata_file": None,
            "lang": None,
            "resource_path": [],
            "extra": None,
            "patch_md": True,
            "fix_inplace": False,
            "report_patches": False,
        }
        | fields
    )


def test_require_cmd_exits_127_when_the_binary_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit) as ex:
        mod.require_cmd("pandoc")
    assert ex.value.code == 127
    assert capsys.readouterr().err == "ERROR: 'pandoc' not found in PATH.\n"


PANDOC_TABLE = "[tool.pandoc_batch]\nto = 'epub'\njobs = 3\n"


def pyproject(text: str):
    """A writer putting a pyproject.toml holding ``text`` into a directory."""
    return lambda folder: (folder / "pyproject.toml").write_text(text, encoding="utf-8")


def nothing(folder: Path):
    """A writer leaving the directory without pyproject.toml."""


# Each row: the writer for the directory above the working directory, the one
# for the directory above the module file, the defaults loaded
LOAD_DEFAULTS_CASES = [
    pytest.param(
        pyproject(PANDOC_TABLE), nothing, {"to": "epub", "jobs": 3}, id="above-cwd"
    ),
    pytest.param(
        nothing,
        pyproject(PANDOC_TABLE),
        {"to": "epub", "jobs": 3},
        id="falls-back-to-module-location",
    ),
    pytest.param(
        pyproject(PANDOC_TABLE),
        pyproject("[tool.pandoc_batch]\nto = 'pdf'\n"),
        {"to": "epub", "jobs": 3},
        id="cwd-wins",
    ),
    pytest.param(nothing, nothing, {}, id="no-pyproject-anywhere"),
    pytest.param(pyproject("[tool.pandoc_batch\nbroken"), nothing, {}, id="unparsable"),
    pytest.param(pyproject("[tool.other]\nx = 1\n"), nothing, {}, id="table-absent"),
]


@pytest.mark.parametrize("above_cwd, above_module, defaults", LOAD_DEFAULTS_CASES)
def test_load_defaults(above_cwd, above_module, defaults, tmp_path, monkeypatch):
    work = tmp_path / "work"
    pkg = tmp_path / "pkg"
    (work / "deep").mkdir(parents=True)
    (pkg / "utils").mkdir(parents=True)
    above_cwd(work)
    above_module(pkg)
    monkeypatch.chdir(work / "deep")
    monkeypatch.setattr(mod, "__file__", str(pkg / "utils" / "pandoc_batch.py"))
    assert mod.load_defaults() == defaults


def test_parse_args_print_config_lists_resolved_values_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    argv = ["--print-config", "--to", "epub", "--root", "book", "--jobs", "2"]
    with pytest.raises(SystemExit) as ex:
        mod.parse_args(argv)
    assert ex.value.code == 0
    assert capsys.readouterr().out == (
        "Resolved config:\n"
        "  root: book\n"
        "  outdir: output\n"
        "  to: epub\n"
        "  from_fmt: markdown\n"
        "  metadata_file: None\n"
        "  resource_path: []\n"
        "  lang: None\n"
        "  standalone: True\n"
        "  verbose: False\n"
        "  jobs: 2\n"
        "  test_only: False\n"
        "  patch_md: True\n"
        "  fix_inplace: False\n"
        "  report_patches: False\n"
    )


def test_parse_args_requires_to(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    with pytest.raises(SystemExit) as ex:
        mod.parse_args(["--root", "book"])
    assert ex.value.code == 2
    assert (
        "--to is required (either pass it or set it under [tool.pandoc_batch] "
        "in pyproject.toml)"
    ) in capsys.readouterr().err


# Each row: the fields overriding _args(), with an output file?, what pandoc is
# handed as input ("source": the file itself, "temp": a patched copy), the
# "[PATCH]" line printed ({in}: the input file)
RUN_ONE_CASES = [
    pytest.param(
        dict(report_patches=True),
        False,
        "temp",
        "[PATCH] {in}: 1 fix(es)\n",
        id="report-patches-counts-fixes",
    ),
    pytest.param(dict(patch_md=False), False, "source", "", id="no-patch-hands-source"),
    pytest.param(
        dict(fix_inplace=True, report_patches=True),
        True,
        "source",
        "[PATCH] {in}: 1 fix(es)\n",
        id="inplace-hands-source",
    ),
    pytest.param(dict(), True, "temp", "", id="output-parent-created"),
]


@pytest.mark.parametrize("fields, with_outfile, handed, printed", RUN_ONE_CASES)
def test_run_one(fields, with_outfile, handed, printed, tmp_path, fake_pandoc, capsys):
    infile = tmp_path / "src" / "in.md"
    infile.parent.mkdir()
    infile.write_text("---\nNo blank\n", encoding="utf-8")
    outfile = (tmp_path / "out" / "deep" / "in.html") if with_outfile else None

    assert mod.run_one(infile, outfile, _args(**fields)) == (infile, 0, "ok")

    (cmd,) = fake_pandoc
    assert cmd[cmd.index("--output") + 1] == (
        os.devnull if outfile is None else str(outfile)
    )
    handed_path = Path(cmd[-1])
    assert (handed_path == infile) is (handed == "source")
    # the patched copy is removed afterwards, the source stays
    assert handed_path.exists() is (handed == "source")
    assert outfile is None or outfile.parent.is_dir()
    assert capsys.readouterr().out == printed.replace("{in}", str(infile))


def test_run_one_survives_a_failing_temp_cleanup(tmp_path, fake_pandoc):
    infile = tmp_path / "in.md"
    infile.write_text("---\nNo blank\n", encoding="utf-8")

    def refuse(self, missing_ok=False):
        raise PermissionError("busy")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "unlink", refuse)
        assert mod.run_one(infile, None, _args()) == (infile, 0, "ok")
    (cmd,) = fake_pandoc
    leftover = Path(cmd[-1])
    assert leftover != infile and leftover.exists()
    leftover.unlink()


def test_main_exits_2_without_markdown_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mod, "require_cmd", lambda _: None)
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(SystemExit) as ex:
        mod.main(["--root", str(root), "--to", "html"])
    assert ex.value.code == 2
    assert capsys.readouterr().err == f"No .md files found under {root}\n"


def test_main_mirrors_the_tree_and_prints_logs_when_verbose(
    tmp_path, monkeypatch, fake_pandoc, capsys
):
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    root = tmp_path / "book"
    outdir = tmp_path / "out"
    src = root / "part" / "a.md"
    dst = outdir / "part" / "a.epub"
    src.parent.mkdir(parents=True)
    src.write_text("# A\n", encoding="utf-8")
    argv = ["--root", str(root), "--outdir", str(outdir), "--to", "epub"]
    with pytest.raises(SystemExit) as ex:
        mod.main(argv + ["--verbose", "--no-patch-md", "--jobs", "1"])
    assert ex.value.code == 0
    assert fake_pandoc == [
        [
            "pandoc",
            "--verbose",
            "--standalone",
            "--from",
            "markdown",
            "--to",
            "epub",
            "--output",
            str(dst),
            str(src),
        ]
    ]
    assert dst.parent.is_dir()
    assert capsys.readouterr().out == (
        "Starting Pandoc for 1 file(s), format: epub, jobs: 1...\n"
        f"[OK] {src} -> {dst}\n"
        "ok\n"
        "\nDONE without errors.\n"
    )
