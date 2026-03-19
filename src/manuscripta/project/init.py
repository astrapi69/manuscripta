# manuscripta/project/init.py
"""
Book project initializer.

Reads structure definitions from config/init-settings.yaml when available.
Falls back to built-in defaults if the file is missing or unreadable.
Logs every action (created / already exists) and provides a summary.
Supports --clean to interactively remove excluded items from disk.
"""

import argparse
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml
import yaml

log = logging.getLogger("manuscripta.init")

# ---------------------------------------------------------------------------
# Defaults (used as fallback when init-settings.yaml is absent)
# ---------------------------------------------------------------------------

_DEFAULT_DIRECTORIES = [
    "manuscript/chapters",
    "manuscript/front-matter",
    "manuscript/back-matter",
    "assets/covers",
    "assets/author",
    "assets/figures/diagrams",
    "assets/figures/infographics",
    "config",
    "config/data",
    "output",
]

_DEFAULT_FILES = [
    "manuscript/chapters/01-chapter.md",
    "manuscript/chapters/02-chapter.md",
    "manuscript/front-matter/foreword.md",
    "manuscript/front-matter/preface.md",
    "manuscript/front-matter/toc.md",
    "manuscript/front-matter/toc-print.md",
    "manuscript/back-matter/about-the-author.md",
    "manuscript/back-matter/acknowledgments.md",
    "manuscript/back-matter/appendix.md",
    "manuscript/back-matter/bibliography.md",
    "manuscript/back-matter/epilogue.md",
    "manuscript/back-matter/glossary.md",
    "manuscript/back-matter/imprint.md",
    "config/amazon-kdp-info.md",
    "config/book-description.html",
    "config/cover-back-page-author-introduction.md",
    "config/cover-back-page-author-introduction.txt",
    "config/cover-back-page-description.md",
    "config/cover-back-page-description.txt",
    "config/keywords.md",
    "config/styles.css",
    "README.md",
    "LICENSE",
]

INIT_SETTINGS_FILE = "config/init-settings.yaml"

# Keep working directory handling simple for CLI; tests can pass base_dir explicitly.
PROJECT_ROOT = Path.cwd()


# ---------------------------------------------------------------------------
# Stats tracker
# ---------------------------------------------------------------------------


@dataclass
class InitStats:
    """Tracks what the initializer did during a run."""

    dirs_created: list[str] = field(default_factory=list)
    dirs_existed: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    files_existed: list[str] = field(default_factory=list)
    excluded_exist_on_disk: list[str] = field(default_factory=list)

    def log_summary(self):
        total_created = len(self.dirs_created) + len(self.files_created)
        total_existed = len(self.dirs_existed) + len(self.files_existed)
        log.info(
            "Summary: %d created (%d dirs, %d files), %d already existed.",
            total_created,
            len(self.dirs_created),
            len(self.files_created),
            total_existed,
        )
        if self.excluded_exist_on_disk:
            log.warning(
                "%d excluded items still exist on disk. "
                "Run with --clean to remove them.",
                len(self.excluded_exist_on_disk),
            )
            for p in self.excluded_exist_on_disk:
                log.warning("  excluded but present: %s", p)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _build_default_init_settings() -> dict[str, Any]:
    """Return a dict matching the init-settings.yaml schema with all defaults."""
    return {
        "directories": list(_DEFAULT_DIRECTORIES),
        "files": list(_DEFAULT_FILES),
        "exclude": [],
    }


def load_init_settings(base_dir: Path) -> dict[str, Any]:
    """Load init-settings.yaml from base_dir/config/.

    Returns the parsed config dict on success.
    Falls back to built-in defaults on any error and logs what happened.
    """
    settings_path = base_dir / INIT_SETTINGS_FILE
    defaults = _build_default_init_settings()

    if not settings_path.exists():
        log.info("No %s found, using built-in defaults.", INIT_SETTINGS_FILE)
        return defaults

    try:
        raw = settings_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning(
            "Could not read %s (%s), falling back to defaults.",
            settings_path,
            exc,
        )
        return defaults

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        log.error(
            "Failed to parse %s (%s), falling back to defaults.",
            settings_path,
            exc,
        )
        return defaults

    if not isinstance(data, dict):
        log.error(
            "%s does not contain a YAML mapping (got %s), falling back to defaults.",
            settings_path,
            type(data).__name__,
        )
        return defaults

    log.info("Loaded project structure from %s", settings_path)
    return _resolve_settings(data, defaults)


def _resolve_settings(data: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Merge user settings with defaults.

    Supported keys in init-settings.yaml:
      directories  - list of directories to create (replaces defaults)
      files        - list of files to create (replaces defaults)
      exclude      - list of paths to remove from defaults
      include_directories - extra directories appended to defaults
      include_files       - extra files appended to defaults

    Priority:
      - If 'directories' or 'files' are present, they replace the defaults entirely.
      - If only 'exclude', 'include_directories', or 'include_files' are present,
        they modify the defaults.
    """
    result_dirs = list(defaults["directories"])
    result_files = list(defaults["files"])

    # Full replacement if explicitly provided
    has_custom_dirs = "directories" in data and data["directories"] is not None
    has_custom_files = "files" in data and data["files"] is not None

    if has_custom_dirs:
        result_dirs = _as_list(data["directories"], "directories")
        log.info("Using custom directories list (%d entries).", len(result_dirs))

    if has_custom_files:
        result_files = _as_list(data["files"], "files")
        log.info("Using custom files list (%d entries).", len(result_files))

    # Additive includes (appended to defaults or custom list)
    include_dirs = _as_list(data.get("include_directories"), "include_directories")
    include_files = _as_list(data.get("include_files"), "include_files")

    for d in include_dirs:
        if d not in result_dirs:
            result_dirs.append(d)
            log.info("  + directory: %s", d)
    for f in include_files:
        if f not in result_files:
            result_files.append(f)
            log.info("  + file: %s", f)

    # Exclusions (applied last, works on both defaults and custom lists)
    exclude = _as_list(data.get("exclude"), "exclude")
    exclude_set = set(exclude)
    if exclude_set:
        before_dirs = len(result_dirs)
        before_files = len(result_files)
        result_dirs = [d for d in result_dirs if d not in exclude_set]
        result_files = [f for f in result_files if f not in exclude_set]
        removed_dirs = before_dirs - len(result_dirs)
        removed_files = before_files - len(result_files)
        if removed_dirs or removed_files:
            log.info(
                "Excluded %d directories and %d files.", removed_dirs, removed_files
            )

    return {
        "directories": result_dirs,
        "files": result_files,
        "exclude": exclude,
    }


def _as_list(value: Any, name: str) -> list[str]:
    """Safely coerce a YAML value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    log.warning("'%s' should be a list, got %s. Ignoring.", name, type(value).__name__)
    return []


def write_default_init_settings(base_dir: Path) -> Path:
    """Write the default init-settings.yaml to config/. Returns the path."""
    settings_path = base_dir / INIT_SETTINGS_FILE
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    content = _build_init_settings_yaml(_DEFAULT_DIRECTORIES, _DEFAULT_FILES)
    settings_path.write_text(content, encoding="utf-8")
    log.info("Created default %s", settings_path)
    return settings_path


def _build_init_settings_yaml(directories: list[str], files: list[str]) -> str:
    """Build the YAML content for init-settings.yaml with comments."""
    lines = [
        "# init-settings.yaml",
        "# Defines which directories and files are created by init-bp.",
        "#",
        "# To customize, edit the lists below.",
        "# To add to defaults without replacing: use include_directories,",
        "# include_files, and exclude instead of directories/files.",
        "#",
        "# Examples:",
        "#   include_directories:",
        "#     - manuscript/exercises",
        "#     - assets/audio",
        "#",
        "#   include_files:",
        "#     - manuscript/chapters/03-chapter.md",
        "#",
        "#   exclude:",
        "#     - manuscript/back-matter/appendix.md",
        "#     - config/amazon-kdp-info.md",
        "",
        "directories:",
    ]
    for d in directories:
        lines.append(f"  - {d}")
    lines.append("")
    lines.append("files:")
    for f in files:
        lines.append(f"  - {f}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Create with logging
# ---------------------------------------------------------------------------


def create_directories(base_path: Path, directories: list[str], stats: InitStats):
    for dir_path in directories:
        full = base_path / dir_path
        if full.exists():
            log.info("Directory already exists: %s", dir_path)
            stats.dirs_existed.append(dir_path)
        else:
            full.mkdir(parents=True, exist_ok=True)
            log.info("Created directory: %s", dir_path)
            stats.dirs_created.append(dir_path)


def create_files(base_path: Path, files: list[str], stats: InitStats):
    for file_path in files:
        p = base_path / file_path
        if p.exists():
            log.info("File already exists: %s", file_path)
            stats.files_existed.append(file_path)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
            log.info("Created file: %s", file_path)
            stats.files_created.append(file_path)


# ---------------------------------------------------------------------------
# Clean excluded items
# ---------------------------------------------------------------------------


def check_excluded_on_disk(base_path: Path, exclude: list[str], stats: InitStats):
    """Check if any excluded paths still exist on disk."""
    for item in exclude:
        full = base_path / item
        if full.exists():
            stats.excluded_exist_on_disk.append(item)


def clean_excluded(base_path: Path, excluded_items: list[str]):
    """Interactively delete excluded items that exist on disk."""
    if not excluded_items:
        return

    print("\nThe following excluded items still exist on disk:")
    for item in excluded_items:
        full = base_path / item
        kind = "dir" if full.is_dir() else "file"
        print(f"  - {item} ({kind})")

    answer = input("\nDelete these items? [y/N]: ").strip().lower()
    if answer != "y":
        print("Skipped. No items deleted.")
        return

    for item in excluded_items:
        full = base_path / item
        try:
            if full.is_dir():
                shutil.rmtree(full)
                log.info("Deleted directory: %s", item)
            elif full.is_file():
                full.unlink()
                log.info("Deleted file: %s", item)
            print(f"  Deleted: {item}")
        except OSError as exc:
            log.error("Failed to delete %s: %s", item, exc)
            print(f"  Error deleting {item}: {exc}")


# ---------------------------------------------------------------------------
# Helpers (unchanged)
# ---------------------------------------------------------------------------


def update_pyproject(project_name: str, description: str, base_dir: Path):
    """Update project name and description in pyproject.toml"""
    pyproject_path = base_dir / "pyproject.toml"
    if not pyproject_path.exists():
        log.warning("pyproject.toml not found, skipping update.")
        return
    data = toml.load(pyproject_path)
    # Support both [project] (PEP 621) and [tool.poetry] formats
    if "project" in data:
        data["project"]["name"] = project_name
        data["project"]["description"] = description
    if "tool" in data and "poetry" in data["tool"]:
        if "name" in data["tool"]["poetry"]:
            data["tool"]["poetry"]["name"] = project_name
        if "description" in data["tool"]["poetry"]:
            data["tool"]["poetry"]["description"] = description
    pyproject_path.write_text(toml.dumps(data), encoding="utf-8")
    log.info("Updated pyproject.toml with name='%s'.", project_name)


def update_full_export_script(
    output_file: str, title: str, author: str, year: str, lang: str, base_dir: Path
):
    """Update constants in scripts/full_export_book.py (legacy, skipped if not present)."""
    path = base_dir / "scripts/full_export_book.py"
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    content = content.replace(
        'OUTPUT_FILE = "book"                            # Base name for the output files #TODO replace with your data',
        f'OUTPUT_FILE = "{output_file}"                            # Base name for the output files',
    ).replace(
        "f.write(\"title: 'CHANGE TO YOUR TITLE'\\nauthor: 'YOUR NAME'\\ndate: '2025'\\nlang: 'en'\\n\") #TODO replace with your data",
        f"f.write(\"title: '{title}'\\nauthor: '{author}'\\ndate: '{year}'\\nlang: '{lang}'\\n\")",
    )
    path.write_text(content, encoding="utf-8")
    log.info("Updated full_export_book.py with metadata.")


def write_readme(readme_path: Path):
    readme_path.write_text(
        "# Book Project\nThis is the book project structure.\n", encoding="utf-8"
    )


def write_image_prompt_generation_template(json_path: Path):
    json_content = {
        "project_name": "your_project_name",
        "description": "Your description",
        "author": "Asterios Raptis",
        "language": "en",
        "structure": {
            "source_format": "Markdown",
            "chapter_path": "manuscript/chapters/",
            "assets_path": "assets/figures/",
            "cover_file": "assets/covers/cover.png",
            "image_prompt_file": "config/data/image_prompts.json",
        },
        "output_formats": ["epub", "epub2", "pdf", "docx", "md"],
        "image_generation": {
            "engine": "Stable Diffusion / DALL-E / Midjourney",
            "prompt_file": "config/data/image_prompts.json",
            "target_path": "assets/figures/",
            "style": "cinematic, sci-fi realism, moody lighting",
        },
        "tasks": [
            {
                "name": "Validate image prompts",
                "description": "Check each chapter has a matching prompt.",
            },
            {
                "name": "Insert illustrations",
                "description": "Add images to Markdown below the title.",
            },
            {
                "name": "Export final book",
                "description": "Run `poetry run full-export`.",
            },
            {
                "name": "Translate",
                "description": "Use DeepL / LM Studio for translations.",
            },
        ],
        "notes": "Cover is generated. Keep prompt-file mapping stable.",
    }
    json_path.write_text(
        json.dumps(json_content, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def build_metadata_yaml_content(
    book_title: str, author_name: str, project_description: str, year: str, lang: str
) -> str:
    """Returns YAML text with nested ISBN mapping."""
    return f"""\
title: "{book_title}"
subtitle: ""
author: "{author_name}"
isbn:
  ebook: ""
  paperback: ""
  hardcover: ""
edition: "1"
publisher: ""
date: "{year}"
language: "{lang}"
description: "{project_description}"
keywords: []
cover_image: "assets/covers/cover.png"
output_formats: ["pdf", "epub", "docx"]
kdp_enabled: false
"""


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def run_init_book_project(
    project_name: str,
    project_description: str,
    book_title: str,
    author_name: str,
    year: str = "2025",
    lang: str = "en",
    base_dir: Path | None = None,
    clean: bool = False,
):
    """Idempotent, testable entrypoint."""
    base = base_dir or PROJECT_ROOT
    stats = InitStats()

    # Load structure from config or fall back to defaults
    settings = load_init_settings(base)
    directories = settings["directories"]
    files = settings["files"]
    exclude = settings.get("exclude", [])

    # Create folders and files
    create_directories(base, directories, stats)
    create_files(base, files, stats)

    # Write generated content files (only if their parent dirs exist)
    readme_path = base / "README.md"
    if readme_path.parent.exists() and not readme_path.exists():
        write_readme(readme_path)

    # Remove legacy metadata_values.json (no longer needed, metadata.yaml is written directly)
    metadata_json_path = base / "config/metadata_values.json"
    if metadata_json_path.exists():
        metadata_json_path.unlink()
        log.info("Removed legacy file: config/metadata_values.json")

    template_path = base / "config/data/image_prompt_generation_template.json"
    if template_path.parent.exists() and not template_path.exists():
        write_image_prompt_generation_template(template_path)

    # Write init-settings.yaml if it does not exist yet
    settings_path = base / INIT_SETTINGS_FILE
    if not settings_path.exists():
        write_default_init_settings(base)

    # Write metadata.yaml
    metadata_path = base / "config/metadata.yaml"
    if metadata_path.parent.exists():
        metadata_path.write_text(
            build_metadata_yaml_content(
                book_title, author_name, project_description, year, lang
            ),
            encoding="utf-8",
        )

    # Update pyproject.toml
    update_pyproject(project_name, project_description, base)
    update_full_export_script(
        output_file=project_name,
        title=book_title,
        author=author_name,
        year=year,
        lang=lang,
        base_dir=base,
    )

    # Check for excluded items that still exist on disk
    check_excluded_on_disk(base, exclude, stats)

    # Print summary
    stats.log_summary()
    print(
        f"\nDone: {len(stats.dirs_created)} dirs created, "
        f"{len(stats.files_created)} files created, "
        f"{len(stats.dirs_existed) + len(stats.files_existed)} already existed."
    )

    if stats.excluded_exist_on_disk:
        if clean:
            clean_excluded(base, stats.excluded_exist_on_disk)
        else:
            print(
                f"\n{len(stats.excluded_exist_on_disk)} excluded item(s) "
                "still exist on disk. Run with --clean to remove them."
            )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Initialize a new book project structure."
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Interactively delete excluded items that still exist on disk.",
    )
    args = parser.parse_args()

    project_name = input("Enter your project name (e.g., 'ai-for-everyone'): ").strip()
    project_description = input("Enter a short description of your project: ").strip()
    book_title = input("Enter your book title: ").strip()
    author_name = input("Enter the author's name: ").strip()
    year = input("Enter publication year [2025]: ").strip() or "2025"
    lang = input("Enter language code [en]: ").strip() or "en"

    run_init_book_project(
        project_name=project_name,
        project_description=project_description,
        book_title=book_title,
        author_name=author_name,
        year=year,
        lang=lang,
        base_dir=PROJECT_ROOT,
        clean=args.clean,
    )


if __name__ == "__main__":
    main()
