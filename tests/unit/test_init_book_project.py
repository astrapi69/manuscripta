# tests/test_init_book_project.py
from pathlib import Path
import yaml
import toml

from manuscripta.project.init import run_init_book_project

DUMMY_FULL_EXPORT = """# dummy
OUTPUT_FILE = "book"                            # Base name for the output files #TODO replace with your data
with open("config/metadata.yaml","w",encoding="utf-8") as f:
    f.write("title: 'CHANGE TO YOUR TITLE'\\nauthor: 'YOUR NAME'\\ndate: '2025'\\nlang: 'en'\\n") #TODO replace with your data
"""


def test_init_writes_nested_isbn_and_updates_files(tmp_path: Path):
    # Arrange: minimal files that the init script expects to edit
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "full_export_book.py").write_text(
        DUMMY_FULL_EXPORT, encoding="utf-8"
    )

    pyproject_min = {
        "tool": {
            "poetry": {
                "name": "template-name",
                "version": "0.1.0",
                "description": "template description",
                "authors": ["You <you@example.com>"],
            }
        }
    }
    (tmp_path / "pyproject.toml").write_text(
        toml.dumps(pyproject_min), encoding="utf-8"
    )

    # Act
    run_init_book_project(
        project_name="currency-of-mind-storybook",
        project_description="A book about intangible wealth.",
        book_title="The Currency of the Mind",
        author_name="Draven Quantum",
        year="2025",
        lang="en",
        base_dir=tmp_path,
    )

    # Assert: metadata.yaml has nested isbn mapping
    meta_yaml_path = tmp_path / "config" / "metadata.yaml"
    assert meta_yaml_path.exists(), "metadata.yaml should be created"
    meta = yaml.safe_load(meta_yaml_path.read_text(encoding="utf-8"))
    assert "isbn" in meta and isinstance(meta["isbn"], dict), "isbn must be a mapping"
    assert set(meta["isbn"].keys()) == {"ebook", "paperback", "hardcover"}
    assert meta["isbn"]["ebook"] == ""

    # Assert: metadata_values.json is NOT created (legacy, removed)
    meta_json_path = tmp_path / "config" / "metadata_values.json"
    assert not meta_json_path.exists(), "metadata_values.json should not be created"

    # Assert: pyproject updated
    updated_pyproject = toml.load(tmp_path / "pyproject.toml")
    assert updated_pyproject["tool"]["poetry"]["name"] == "currency-of-mind-storybook"
    assert (
        updated_pyproject["tool"]["poetry"]["description"]
        == "A book about intangible wealth."
    )

    # Assert: full_export_book.py updated (placeholders replaced)
    fe_content = (tmp_path / "scripts" / "full_export_book.py").read_text(
        encoding="utf-8"
    )
    assert 'OUTPUT_FILE = "currency-of-mind-storybook"' in fe_content
    assert "The Currency of the Mind" in fe_content
    assert "Draven Quantum" in fe_content


def test_init_removes_legacy_metadata_values_json(tmp_path: Path):
    """If metadata_values.json already exists, init-bp should delete it."""
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    legacy_path = tmp_path / "config" / "metadata_values.json"
    legacy_path.write_text('{"old": "data"}', encoding="utf-8")

    pyproject_min = {
        "project": {
            "name": "test-book",
            "description": "test",
        }
    }
    (tmp_path / "pyproject.toml").write_text(
        toml.dumps(pyproject_min), encoding="utf-8"
    )

    run_init_book_project(
        project_name="test-book",
        project_description="test",
        book_title="Test",
        author_name="Test Author",
        base_dir=tmp_path,
    )

    assert not legacy_path.exists(), "Legacy metadata_values.json should be deleted"
