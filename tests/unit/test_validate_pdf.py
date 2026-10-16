import pytest

pytestmark = pytest.mark.unit

# tests/test_validate_pdf.py
import manuscripta.export.validation as vf


# Each row: the file exists?, pdfinfo on PATH?, what run_cmd returns (None: it
# must not run), the exit status, the texts the output carries
PDF_CASES = [
    pytest.param(
        True, True, (0, "Title: X\nPages: 12\n", ""), 0, ["Pages: 12"], id="success"
    ),
    pytest.param(True, True, (1, "", "broken"), 1, ["broken"], id="failure"),
    pytest.param(True, False, None, 127, ["`pdfinfo` not found"], id="no-pdfinfo"),
    pytest.param(True, True, (124, "", "timeout"), 124, ["timed out"], id="timeout"),
    pytest.param(False, True, None, 2, ["PDF file not found"], id="missing"),
]


@pytest.mark.parametrize("exists, has_pdfinfo, result, rc, texts", PDF_CASES)
def test_pdf(monkeypatch, tmp_path, capsys, exists, has_pdfinfo, result, rc, texts):
    p = tmp_path / "a.pdf"
    if exists:
        p.write_text("x")
    monkeypatch.setattr(vf, "require_cmd", lambda _: has_pdfinfo)

    def run_cmd(cmd, timeout=None):
        assert result is not None, "pdfinfo must not run"
        return result

    monkeypatch.setattr(vf, "run_cmd", run_cmd)
    assert vf.validate_pdf(str(p), timeout=1) == rc
    out = capsys.readouterr().out
    for text in texts:
        assert text in out
