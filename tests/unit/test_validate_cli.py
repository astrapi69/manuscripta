# tests/test_validate_cli.py
import pytest

pytestmark = pytest.mark.unit
import manuscripta.export.validation as vf


# Each row: the file name, the arguments after the path, the exit status, the
# stream and a text it carries
CLI_CASES = [
    pytest.param("a.md", [], 0, "out", "Markdown exported", id="autodetect-md"),
    # force md; should work
    pytest.param(
        "a.weird",
        ["--type", "md"],
        0,
        "out",
        "Markdown exported",
        id="forced-type-overrides-extension",
    ),
    # argparse rejects the type before main runs
    pytest.param(
        "a.weird", ["--type", "xyz"], 2, "err", "invalid choice", id="unknown-type"
    ),
]


@pytest.mark.parametrize("name, argv_tail, code, stream, text", CLI_CASES)
def test_cli(tmp_path, capsys, name, argv_tail, code, stream, text):
    p = tmp_path / name
    p.write_text("x")
    with pytest.raises(SystemExit) as ex:
        vf.main([str(p), *argv_tail])
    assert ex.value.code == code
    assert text in getattr(capsys.readouterr(), stream)
