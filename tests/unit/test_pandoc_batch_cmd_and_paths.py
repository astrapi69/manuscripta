import pytest

pytestmark = pytest.mark.unit

# tests/test_pandoc_batch_cmd_and_paths.py
from pathlib import Path
from manuscripta.utils.pandoc_batch import build_cmd, rel_output_path, EXT_BY_TO
import argparse
import os


def _ns(**kw):
    # Minimal argparse.Namespace for build_cmd
    return argparse.Namespace(
        **{
            "verbose": False,
            "standalone": True,
            "from_fmt": "markdown",
            "to": "html",
            "metadata_file": None,
            "lang": "de",
            "resource_path": [],
            "extra": None,
        }
        | kw
    )


def test_rel_output_path_maps_structure(tmp_path: Path):
    root = tmp_path / "root"
    src = root / "a" / "b" / "c.md"
    src.parent.mkdir(parents=True)
    src.write_text("# hi", encoding="utf-8")
    outdir = tmp_path / "out"
    p = rel_output_path(src, root, outdir, EXT_BY_TO["html"])
    assert p == outdir / "a" / "b" / "c.html"


def test_build_cmd_basic(tmp_path: Path):
    infile = tmp_path / "x.md"
    infile.write_text("x", encoding="utf-8")
    outfile = tmp_path / "y.html"
    args = _ns()
    cmd = build_cmd(infile, outfile, args)
    assert cmd[0] == "pandoc"
    assert "--standalone" in cmd
    assert ["--from", "markdown"] == cmd[cmd.index("--from") : cmd.index("--from") + 2]
    assert ["--to", "html"] == cmd[cmd.index("--to") : cmd.index("--to") + 2]
    assert ["--output", str(outfile)] in [cmd[i : i + 2] for i in range(len(cmd) - 1)]
    assert str(infile) == cmd[-1]


# Each row: the platform (os.name), the --resource-path value pandoc gets for
# the paths "a" and "b": pandoc separates them like PATH, ";" on Windows
# and ":" elsewhere
RESOURCE_PATH_CASES = [
    pytest.param("posix", "a:b", id="posix-colon"),
    pytest.param("nt", "a;b", id="windows-semicolon"),
]


@pytest.mark.parametrize("platform, joined", RESOURCE_PATH_CASES)
def test_build_cmd_joins_resource_paths(platform, joined, tmp_path: Path, monkeypatch):
    infile = tmp_path / "x.md"
    monkeypatch.setattr(os, "name", platform)
    assert build_cmd(infile, None, _ns(resource_path=["a", "b"])) == [
        "pandoc",
        "--standalone",
        "--from",
        "markdown",
        "--to",
        "html",
        "--metadata",
        "lang=de",
        "--resource-path",
        joined,
        "--output",
        os.devnull,
        str(infile),
    ]


# Each row: the fields overriding _ns(), with an output file?, the command
# built ({in}: the input file, {out}: the output file)
BUILD_CMD_CASES = [
    pytest.param(
        dict(verbose=True),
        True,
        [
            "pandoc",
            "--verbose",
            "--standalone",
            "--from",
            "markdown",
            "--to",
            "html",
            "--metadata",
            "lang=de",
            "--output",
            "{out}",
            "{in}",
        ],
        id="verbose-first",
    ),
    pytest.param(
        dict(metadata_file=Path("meta.yaml")),
        True,
        [
            "pandoc",
            "--standalone",
            "--from",
            "markdown",
            "--to",
            "html",
            "--metadata-file",
            "meta.yaml",
            "--metadata",
            "lang=de",
            "--output",
            "{out}",
            "{in}",
        ],
        id="metadata-file-before-lang",
    ),
    pytest.param(
        dict(standalone=False, lang=None),
        False,
        [
            "pandoc",
            "--from",
            "markdown",
            "--to",
            "html",
            "--output",
            os.devnull,
            "{in}",
        ],
        id="bare-command-to-devnull",
    ),
    pytest.param(
        dict(to="epub", from_fmt="gfm", extra=["--toc"]),
        True,
        [
            "pandoc",
            "--standalone",
            "--from",
            "gfm",
            "--to",
            "epub",
            "--metadata",
            "lang=de",
            "--output",
            "{out}",
            "{in}",
            "--toc",
        ],
        id="extra-args-after-input",
    ),
]


@pytest.mark.parametrize("fields, with_outfile, command", BUILD_CMD_CASES)
def test_build_cmd(fields, with_outfile, command, tmp_path: Path):
    infile = tmp_path / "x.md"
    outfile = (tmp_path / "x.out") if with_outfile else None
    placeholders = {"{in}": str(infile), "{out}": str(outfile)}
    expected = [placeholders.get(part, part) for part in command]
    assert build_cmd(infile, outfile, _ns(**fields)) == expected
