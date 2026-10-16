import pytest

pytestmark = pytest.mark.unit

# tests/test_convert_to_absolute_fuzz.py
from pathlib import Path
import os
import string
import hypothesis.strategies as st
from hypothesis import given, settings, HealthCheck

from manuscripta.paths.to_absolute import convert_file_to_absolute


def write(p: Path, txt: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


# Strategy for sane labels and filenames
labels = st.text(
    alphabet=st.sampled_from(list(string.ascii_letters + string.digits + " -_")),
    min_size=1,
    max_size=20,
)
# Filenames that may include parentheses and spaces
filenames = st.builds(
    lambda base, ext: f"{base}{ext}",
    base=st.text(
        alphabet=st.sampled_from(list("ab cdefghijklmnop()_-")), min_size=1, max_size=12
    ),
    ext=st.sampled_from([".png", ".jpg", ".jpeg"]),
)


# Explicit headroom above the unit-layer default timeout (tests/unit/
# conftest.py): 100 hypothesis examples under mutmut's coverage
# instrumentation flirt with a 10 s ceiling, and a spurious timeout
# failure "kills" mutants that are annotated equivalents — making the
# nightly score flap. 60 s keeps the hang-detection property without
# the flakiness.
@pytest.mark.timeout(60)
@given(labels, filenames)
@settings(
    deadline=None,
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_fuzz_relative_images_with_parentheses_and_spaces(
    tmp_path_factory, label: str, fname: str
):
    base = tmp_path_factory.mktemp("fuzzcase")
    ch = base / "manuscript" / "chapters"
    img = base / "assets" / "fuzz" / fname
    write(img, "x")

    md = ch / "doc.md"
    rel = os.path.relpath(img, start=md.parent)

    body = (
        f"![{label}]({rel})\n" f"![{label}](<{rel}>)\n" f'![{label}](<{rel}> "Cover")\n'
    )
    write(md, body)

    changed, count = convert_file_to_absolute(md)
    assert changed
    out = md.read_text(encoding="utf-8")
    assert str(img.resolve()) in out
    assert ' "Cover")' in out


# Each row: the image files under assets/, the chapter body, the expected
# (changed, count) and the text of the chapter afterwards. {rel0}/{img0} are
# the first image's path relative to the chapter and its absolute path,
# {rel1}/{img1} the second's.
BARE_URL_CASES = [
    pytest.param(
        ["has(paren) and (space).png"],
        "![p]({rel0})",
        (True, 1),
        "![p]({img0})",
        id="bare-url-with-parentheses-and-no-angle-brackets",
    ),
    pytest.param(
        ["t1(a).png", "t2(b).png"],
        "![x]({rel0} \"A\")\n![y]({rel1} 'B')",
        (True, 2),
        "![x]({img0} \"A\")\n![y]({img1} 'B')",
        id="title-single-or-double-quotes-following-bare-url",
    ),
]


@pytest.mark.parametrize("images, body, expected, after", BARE_URL_CASES)
def test_bare_url_target(images, body, expected, after, tmp_path_factory):
    base = tmp_path_factory.mktemp("bareurl")
    md = base / "manuscript" / "chapters" / "doc.md"
    fields = {}
    for i, name in enumerate(images):
        img = base / "assets" / name
        write(img, "x")
        fields[f"rel{i}"] = os.path.relpath(img, start=md.parent)
        fields[f"img{i}"] = img.resolve()
    write(md, body.format(**fields))

    assert convert_file_to_absolute(md) == expected
    assert md.read_text(encoding="utf-8") == after.format(**fields)
