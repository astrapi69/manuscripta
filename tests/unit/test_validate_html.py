# tests/test_validate_html.py
import pytest

pytestmark = pytest.mark.unit
import manuscripta.export.validation as vf


# Each row: the text of the file (None: no file), the exit status, a text the
# output carries
HTML_CASES = [
    pytest.param(
        "<!doctype html><html><head><title>x</title></head><body>hi</body></html>",
        0,
        "HTML exported",
        id="valid",
    ),
    pytest.param("", 1, "HTML file is empty", id="empty"),
    pytest.param(None, 2, "HTML file not found", id="missing"),
    pytest.param(
        "<head><title>no root</title></head><body>content</body>",
        1,
        "malformed",
        id="malformed-no-root-tag",
    ),
]


@pytest.mark.parametrize("text, rc, output", HTML_CASES)
def test_html(tmp_path, capsys, text, rc, output):
    p = tmp_path / "x.html"
    if text is not None:
        p.write_text(text, encoding="utf-8")
    assert vf.validate_html(str(p)) == rc
    assert output in capsys.readouterr().out


# --- CLI behaviour for HTML ---------------------------------------------------

# Each row: the file name, the arguments after the path
HTML_CLI_CASES = [
    pytest.param("auto.html", [], id="autodetect-html"),
    pytest.param(
        "weird.ext", ["--type", "html"], id="force-type-html-overrides-extension"
    ),
]


@pytest.mark.parametrize("name, argv_tail", HTML_CLI_CASES)
def test_cli_html(tmp_path, capsys, name, argv_tail):
    p = tmp_path / name
    p.write_text("<html>y</html>", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        vf.main([str(p), *argv_tail])
    assert ex.value.code == 0
    assert "HTML exported" in capsys.readouterr().out
