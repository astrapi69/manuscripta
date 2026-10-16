import pytest

pytestmark = pytest.mark.unit

# tests/test_validate_epub.py
import manuscripta.export.validation as vf


# Each row: the file exists?, epubcheck on PATH?, what run_cmd returns (None:
# it must not run), the exit status, the texts the output carries
EPUB_CASES = [
    pytest.param(True, True, (0, "OK", ""), 0, ["is valid"], id="success"),
    pytest.param(
        True, True, (1, "problems", ""), 1, ["found issues", "problems"], id="issues"
    ),
    pytest.param(True, False, None, 127, ["epubcheck not found"], id="missing-binary"),
    pytest.param(True, True, (124, "", "timeout"), 124, ["timed out"], id="timeout"),
    pytest.param(False, True, None, 2, ["EPUB file not found"], id="missing-input"),
]


@pytest.mark.parametrize("exists, has_epubcheck, result, rc, texts", EPUB_CASES)
def test_epub(monkeypatch, tmp_path, capsys, exists, has_epubcheck, result, rc, texts):
    p = tmp_path / "b.epub"
    if exists:
        p.write_text("x")
    monkeypatch.setattr(vf, "require_cmd", lambda _: has_epubcheck)

    def run_cmd(cmd, timeout=None):
        assert result is not None, "epubcheck must not run"
        return result

    monkeypatch.setattr(vf, "run_cmd", run_cmd)
    assert vf.validate_epub_with_epubcheck(str(p)) == rc
    out = capsys.readouterr().out
    for text in texts:
        assert text in out
