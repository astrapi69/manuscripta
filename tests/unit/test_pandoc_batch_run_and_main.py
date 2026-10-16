# tests/test_pandoc_batch_run_and_main.py
import argparse
import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
import manuscripta.utils.pandoc_batch as mod


class DummyProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def which(cmd: str):
    """A PATH lookup finding pandoc and nothing else."""
    return "/usr/bin/pandoc" if cmd == "pandoc" else None


@pytest.fixture
def fake_pandoc(monkeypatch):
    # Pretend pandoc exists
    monkeypatch.setattr(mod.shutil, "which", which)

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
    # Make two files whose names trigger rc=1 in fake runner
    root = tmp_path / "manuscript"
    root.mkdir()
    (root / "ok.md").write_text("ok", encoding="utf-8")
    (root / "will-fail.md").write_text("x", encoding="utf-8")
    (root / "also-fail.md").write_text("y", encoding="utf-8")

    monkeypatch.setattr(mod.shutil, "which", which)

    def fake_run(cmd, capture_output=True, text=True):
        # Fail only on the real source path; ensure we use --no-patch-md so infile is last arg
        rc = 1 if "fail.md" in str(cmd[-1]) else 0
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
    # every file gets its status line; a failure's log follows its line
    assert f"[OK] {root / 'ok.md'}\n" in out
    assert f"[FAIL] {root / 'will-fail.md'}\nboom\n" in out
    assert f"[FAIL] {root / 'also-fail.md'}\nboom\n" in out
    assert err == "\nDONE with 2 failure(s).\n"


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


def exit_code(call):
    """The SystemExit code ``call`` ends with (None when it returns)."""
    try:
        call()
    except SystemExit as ex:
        return ex.code
    return None


# Each row: the binary required, the exit code (None: the call returns) and
# what is printed to stderr, with a PATH holding pandoc only
REQUIRE_CMD_CASES = [
    pytest.param("pandoc", None, "", id="present-returns"),
    pytest.param(
        "ffmpeg", 127, "ERROR: 'ffmpeg' not found in PATH.\n", id="missing-exits-127"
    ),
]


@pytest.mark.parametrize("name, code, err", REQUIRE_CMD_CASES)
def test_require_cmd(monkeypatch, capsys, name, code, err):
    monkeypatch.setattr(mod.shutil, "which", which)
    assert exit_code(lambda: mod.require_cmd(name)) == code
    assert capsys.readouterr().err == err


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
    pytest.param(
        pyproject("[build-system]\nrequires = []\n"), nothing, {}, id="no-tool-table"
    ),
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


# A [tool.pandoc_batch] table setting every key it knows
TABLE = {
    "root": "book",
    "outdir": "dist",
    "to": "epub",
    "from": "gfm",
    "metadata_file": "meta.yaml",
    "lang": "de",
    "standalone": False,
    "verbose": True,
    "jobs": 3,
    "test_only": True,
}


def resolved(**fields):
    """The namespace of a run without a [tool.pandoc_batch] table on a
    six-core machine, patched by ``fields``: the manuscript folder goes to
    output as standalone, patched markdown with one job per core."""
    return {
        "root": Path("manuscript"),
        "outdir": Path("output"),
        "to": None,
        "from_fmt": "markdown",
        "metadata_file": None,
        "resource_path": [],
        "lang": None,
        "standalone": True,
        "verbose": False,
        "jobs": 6,
        "test_only": False,
        "patch_md": True,
        "fix_inplace": False,
        "report_patches": False,
        "extra": None,
        "print_config": False,
    } | fields


# Each row: the [tool.pandoc_batch] table, the argv, the namespace parsed
PARSE_ARGS_CASES = [
    pytest.param(
        {}, ["--to", "html"], resolved(to="html"), id="fallbacks-without-a-table"
    ),
    pytest.param(
        TABLE | {"resource_path": ["img", "css"]},
        [],
        resolved(
            root=Path("book"),
            outdir=Path("dist"),
            to="epub",
            from_fmt="gfm",
            metadata_file=Path("meta.yaml"),
            resource_path=["img", "css"],
            lang="de",
            standalone=False,
            verbose=True,
            jobs=3,
            test_only=True,
        ),
        id="table-feeds-every-default",
    ),
    pytest.param(
        TABLE | {"standalone": True, "verbose": False, "test_only": False},
        [
            "--root",
            "r",
            "--outdir",
            "o",
            "--to",
            "pdf",
            "--from",
            "rst",
            "--metadata-file",
            "m.yaml",
            "--resource-path",
            "a",
            "--resource-path",
            "b",
            "--lang",
            "en",
            "--no-standalone",
            "--verbose",
            "--jobs",
            "2",
            "--test-only",
            "--no-patch-md",
            "--fix-inplace",
            "--report-patches",
            "--extra",
            "--toc",
            "--css",
            "x.css",
        ],
        resolved(
            root=Path("r"),
            outdir=Path("o"),
            to="pdf",
            from_fmt="rst",
            metadata_file=Path("m.yaml"),
            resource_path=["a", "b"],
            lang="en",
            standalone=False,
            verbose=True,
            jobs=2,
            test_only=True,
            patch_md=False,
            fix_inplace=True,
            report_patches=True,
            extra=["--toc", "--css", "x.css"],
        ),
        id="cli-overrides-the-table",
    ),
    pytest.param(
        {"to": "html", "standalone": False},
        ["--standalone", "--patch-md"],
        resolved(to="html"),
        id="flags-switch-on-what-the-table-switched-off",
    ),
    pytest.param(
        {"to": "html", "resource_path": ["img", "css"]},
        ["--resource-path", "a", "--resource-path", "b"],
        resolved(to="html", resource_path=["a", "b"]),
        id="cli-resource-paths-replace-the-table-list",
    ),
]


@pytest.mark.parametrize("table, argv, namespace", PARSE_ARGS_CASES)
def test_parse_args(monkeypatch, table, argv, namespace):
    monkeypatch.setattr(mod, "load_defaults", lambda: dict(table))
    monkeypatch.setattr(mod.os, "cpu_count", lambda: 6)
    assert vars(mod.parse_args(argv)) == namespace


# Each row: the argv and a fragment of the usage error; both exit with 2
PARSE_ARGS_ERRORS = [
    pytest.param(
        ["--root", "book"],
        "--to is required (either pass it or set it under [tool.pandoc_batch] "
        "in pyproject.toml)",
        id="to-missing",
    ),
    pytest.param(
        ["--to", "bogus"],
        "argument --to: invalid choice: 'bogus'",
        id="to-outside-the-formats",
    ),
]


@pytest.mark.parametrize("argv, fragment", PARSE_ARGS_ERRORS)
def test_parse_args_rejects(monkeypatch, capsys, argv, fragment):
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    with pytest.raises(SystemExit) as ex:
        mod.parse_args(argv)
    assert ex.value.code == 2
    assert fragment in capsys.readouterr().err


def help_output(monkeypatch, capsys) -> str:
    """The --help page, rendered wide enough that no entry wraps."""
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    with pytest.raises(SystemExit) as ex:
        mod.parse_args(["--help"])
    assert ex.value.code == 0
    return capsys.readouterr().out


def option_help_text(help_out: str, flag: str) -> str:
    """The help text argparse attached to the listing entry of ``flag`` (""
    when the entry carries none); an entry too long for its column carries
    the text on the indented line below."""
    lines = help_out.split("options:\n", 1)[1].splitlines()
    for line, below in zip(lines, lines[1:] + [""]):
        entry = line.strip()
        if entry != flag and not entry.startswith(flag + " "):
            continue
        parts = re.split(r"\s{2,}", entry, maxsplit=1)
        if len(parts) > 1:
            return parts[1]
        return below.strip() if below.startswith(" " * 20) else ""
    raise AssertionError(f"{flag} is not listed")


# Each row: an option whose --help entry must carry some help text; what the
# text says is not asserted
OPTIONS_WITH_HELP = [
    pytest.param("--root", id="root"),
    pytest.param("--outdir", id="outdir"),
    pytest.param("--to", id="to"),
    pytest.param("--from", id="from"),
    pytest.param("--metadata-file", id="metadata-file"),
    pytest.param("--resource-path", id="resource-path"),
    pytest.param("--lang", id="lang"),
    pytest.param("--standalone", id="standalone"),
    pytest.param("--verbose", id="verbose"),
    pytest.param("--jobs", id="jobs"),
    pytest.param("--test-only", id="test-only"),
    pytest.param("--extra", id="extra"),
    pytest.param("--print-config", id="print-config"),
    pytest.param("--patch-md", id="patch-md"),
    pytest.param("--no-patch-md", id="no-patch-md"),
    pytest.param("--fix-inplace", id="fix-inplace"),
    pytest.param("--report-patches", id="report-patches"),
]


@pytest.mark.parametrize("flag", OPTIONS_WITH_HELP)
def test_every_option_has_help_text(flag, monkeypatch, capsys):
    assert option_help_text(help_output(monkeypatch, capsys), flag) != ""


def test_help_has_a_description_paragraph(monkeypatch, capsys):
    out = help_output(monkeypatch, capsys)
    paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
    assert not paragraphs[1].startswith(("positional arguments:", "options:"))


# Each row: the fields overriding _args(), the output file (None: test-only,
# "fresh": in a directory still to be created, "existing": next to the
# source), what pandoc is handed as input ("source": the file itself, "temp":
# a patched copy), the "[PATCH]" line printed ({in}: the input file)
RUN_ONE_CASES = [
    pytest.param(
        dict(report_patches=True),
        None,
        "temp",
        "[PATCH] {in}: 1 fix(es)\n",
        id="report-patches-counts-fixes",
    ),
    pytest.param(dict(patch_md=False), None, "source", "", id="no-patch-hands-source"),
    pytest.param(
        dict(fix_inplace=True, report_patches=True),
        "fresh",
        "source",
        "[PATCH] {in}: 1 fix(es)\n",
        id="inplace-hands-source",
    ),
    pytest.param(dict(), "fresh", "temp", "", id="output-parent-created"),
    pytest.param(dict(), "existing", "temp", "", id="output-parent-kept"),
]


@pytest.mark.parametrize("fields, out, handed, printed", RUN_ONE_CASES)
def test_run_one(fields, out, handed, printed, tmp_path, fake_pandoc, capsys):
    infile = tmp_path / "src" / "in.md"
    infile.parent.mkdir()
    infile.write_text("---\nNo blank\n", encoding="utf-8")
    outfile = {
        None: None,
        "fresh": tmp_path / "out" / "deep" / "in.html",
        "existing": infile.with_suffix(".html"),
    }[out]

    assert mod.run_one(infile, outfile, _args(**fields)) == (infile, 0, "ok")

    (cmd,) = fake_pandoc
    assert cmd[cmd.index("--output") + 1] == (
        os.devnull if outfile is None else str(outfile)
    )
    handed_path = Path(cmd[-1])
    assert (handed_path == infile) is (handed == "source")
    # the patched copy is removed afterwards, the source stays
    assert handed_path.exists() is (handed == "source")
    # a copy left behind by a failed cleanup is recognisable as this tool's
    # and still a markdown file
    assert handed == "source" or (
        handed_path.name.startswith("pandoc_patch_") and handed_path.suffix == ".md"
    )
    assert outfile is None or outfile.parent.is_dir()
    assert capsys.readouterr().out == printed.replace("{in}", str(infile))


# Each row: what pandoc wrote to stdout and stderr (None: nothing captured),
# the log run_one returns: stdout, then stderr, one newline between them
# when both are present
RUN_ONE_LOG_CASES = [
    pytest.param("ok", "", "ok", id="stdout-alone"),
    pytest.param("", "warn", "warn", id="stderr-alone"),
    pytest.param("out", "err", "out\nerr", id="both-joined-by-newline"),
    pytest.param(None, None, "", id="nothing-captured"),
]


@pytest.mark.parametrize("stdout, stderr, log", RUN_ONE_LOG_CASES)
def test_run_one_log(monkeypatch, tmp_path, stdout, stderr, log):
    infile = tmp_path / "in.md"
    infile.write_text("# A\n", encoding="utf-8")
    monkeypatch.setattr(
        mod.subprocess, "run", lambda cmd, **kw: DummyProc(0, stdout, stderr)
    )
    assert mod.run_one(infile, None, _args(patch_md=False)) == (infile, 0, log)


def test_run_one_rejects_a_source_that_is_not_utf8(tmp_path, fake_pandoc):
    """Patching decodes strictly: a byte sequence that is not UTF-8 is an
    error, not a silently replaced character."""
    infile = tmp_path / "in.md"
    infile.write_bytes(b"# Gr\xfc\xdfe\n")  # Latin-1 umlauts
    with pytest.raises(UnicodeDecodeError):
        mod.run_one(infile, None, _args())
    assert fake_pandoc == []


def test_run_one_utf8_round_trip_under_c_locale(tmp_path, fake_pandoc, monkeypatch):
    """The source is read and written back as UTF-8 whatever the locale:
    under LC_ALL=C the locale codec is ASCII and cannot carry the umlauts."""
    import locale

    saved = locale.setlocale(locale.LC_ALL)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LANG", "C")
    locale.setlocale(locale.LC_ALL, "C")
    try:
        infile = tmp_path / "in.md"
        infile.write_bytes("---\nGrüße\n".encode("utf-8"))
        assert mod.run_one(infile, None, _args(fix_inplace=True)) == (infile, 0, "ok")
        assert infile.read_bytes().decode("utf-8") == "---\n\nGrüße\n"
    finally:
        locale.setlocale(locale.LC_ALL, saved)


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


# Each row: the --jobs argument, the worker count of the pool: as asked, but
# at least one worker
POOL_CASES = [
    pytest.param(["--jobs", "3"], 3, id="jobs-as-asked"),
    pytest.param(["--jobs", "0"], 1, id="at-least-one-worker"),
]


@pytest.mark.parametrize("argv, workers", POOL_CASES)
def test_main_sizes_the_pool_by_jobs(tmp_path, monkeypatch, fake_pandoc, argv, workers):
    monkeypatch.setattr(mod, "load_defaults", lambda: {})
    root = tmp_path / "book"
    root.mkdir()
    (root / "a.md").write_text("# A\n", encoding="utf-8")
    seen = []

    class SpyPool(mod.ThreadPoolExecutor):
        def __init__(self, max_workers=None, **kw):
            seen.append(max_workers)
            super().__init__(max_workers=max_workers, **kw)

    monkeypatch.setattr(mod, "ThreadPoolExecutor", SpyPool)
    with pytest.raises(SystemExit) as ex:
        mod.main(["--root", str(root), "--to", "html", "--test-only", *argv])
    assert ex.value.code == 0
    assert seen == [workers]


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
