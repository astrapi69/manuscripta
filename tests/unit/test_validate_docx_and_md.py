import pytest

pytestmark = pytest.mark.unit

# tests/test_validate_docx_and_md.py
import zipfile
import manuscripta.export.validation as vf


def _zip_with(member: str):
    """A writer that makes the path a zip whose only member is ``member``."""

    def write(p):
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(member, "<Types/>")

    return write


# Each row: how to write x.docx (a no-op leaves it missing), the exit status
DOCX_CASES = [
    # minimal docx-like zip with [Content_Types].xml
    pytest.param(_zip_with("[Content_Types].xml"), 0, id="valid"),
    pytest.param(_zip_with("foo.txt"), 1, id="invalid-structure"),
    pytest.param(lambda p: p.write_text("not a zip"), 1, id="corrupted"),
    pytest.param(lambda p: None, 2, id="missing"),
]


@pytest.mark.parametrize("write, rc", DOCX_CASES)
def test_docx(tmp_path, write, rc):
    p = tmp_path / "x.docx"
    write(p)
    assert vf.validate_docx(str(p)) == rc


# Each row: the text of x.md (None: no file), the exit status, a text the
# lower-cased output carries
MARKDOWN_CASES = [
    pytest.param("# ok", 0, "exported", id="nonempty"),
    pytest.param("", 1, "file is empty", id="empty"),
    pytest.param(None, 2, "not found", id="missing"),
]


@pytest.mark.parametrize("text, rc, output", MARKDOWN_CASES)
def test_md(tmp_path, capsys, text, rc, output):
    p = tmp_path / "x.md"
    if text is not None:
        p.write_text(text)
    assert vf.validate_markdown(str(p)) == rc
    assert output in capsys.readouterr().out.lower()
