# tests/test_convert_to_relative.py
import importlib.util
from pathlib import Path
import os
import pytest

pytestmark = pytest.mark.unit

# Import the implementation from your repo (tests/.. = project root)
MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "manuscripta"
    / "paths"
    / "to_relative.py"
)


def import_ctr(module_path: Path):
    spec = importlib.util.spec_from_file_location(
        "convert_to_relative", str(module_path)
    )
    assert spec is not None, "ModuleSpec is None"
    assert spec.loader is not None, "ModuleSpec.loader is None"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


@pytest.fixture()
def temp_project(tmp_path: Path):
    project = tmp_path
    (project / "manuscript" / "chapters").mkdir(parents=True)
    (project / "manuscript" / "front-matter").mkdir(parents=True)
    (project / "manuscript" / "back-matter").mkdir(parents=True)
    (project / "assets" / "img").mkdir(parents=True)
    return project


def point_at(mod, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the module to the temp project structure."""
    targets = {
        "PROJECT_ROOT": project.resolve(),
        "MANUSCRIPT_DIR": project / "manuscript",
        "ASSETS_DIR": project / "assets",
        "MD_DIRECTORIES": [
            project / "manuscript" / "chapters",
            project / "manuscript" / "front-matter",
            project / "manuscript" / "back-matter",
        ],
    }
    for name, value in targets.items():
        monkeypatch.setattr(mod, name, value, raising=False)


# Each row: the file under the project, the text of the chapter
# manuscript/chapters/p.md and the text after conversion (None: unchanged).
# {pic} is the file's absolute POSIX path, {rel} its POSIX path relative to
# the chapter.
CONVERT_TEXT_CASES = [
    pytest.param(
        "assets/img/cover (v1).png",
        '# Intro\n![Cover](<{pic}> "title")\nInline: ![x]({pic})',
        '# Intro\n![Cover](<{rel}> "title")\nInline: ![x]({rel})',
        id="markdown-image-absolute-to-relative",
    ),
    pytest.param(
        "assets/img/p.png",
        '<img src="{pic}"> <a href="{pic}">link</a>',
        '<img src="{rel}"> <a href="{rel}">link</a>',
        id="html-img-and-a-tags",
    ),
    pytest.param(
        "notassets/p.png",
        "[web](https://example.com)\n[anchor](#sec)\n![outside]({pic})\nrel ok",
        None,
        id="skip-urls-anchors-and-non-assets",
    ),
]


@pytest.mark.parametrize("file, text, after", CONVERT_TEXT_CASES)
def test_convert_paths_in_text(file, text, after, temp_project, monkeypatch):
    project = temp_project
    mod = import_ctr(MODULE_PATH)
    point_at(mod, project, monkeypatch)

    chapter = project / "manuscript" / "chapters" / "p.md"
    pic = project / file
    write(pic, "png")
    fields = {
        "pic": pic.as_posix(),
        "rel": Path(os.path.relpath(pic, start=chapter.parent)).as_posix(),
    }
    write(chapter, text.format(**fields))

    out = mod.convert_paths_in_text(chapter.read_text(encoding="utf-8"), chapter)
    expected = (
        chapter.read_text(encoding="utf-8") if after is None else after.format(**fields)
    )
    assert out == expected


def test_idempotency(temp_project, monkeypatch):
    project = temp_project
    mod = import_ctr(MODULE_PATH)
    point_at(mod, project, monkeypatch)

    chapter = project / "manuscript" / "chapters" / "p.md"
    pic = project / "assets" / "img" / "p.png"
    write(pic, "png")
    rel = Path(os.path.relpath(pic, start=chapter.parent)).as_posix()
    write(chapter, f"![x]({rel})")

    once = mod.convert_paths_in_text(chapter.read_text(encoding="utf-8"), chapter)
    twice = mod.convert_paths_in_text(once, chapter)
    assert once == twice
