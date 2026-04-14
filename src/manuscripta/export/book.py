# manuscripta/export/book.py
import logging
import os
import re
import shutil
import subprocess
import argparse
import yaml
import toml
import threading
import tempfile
from pathlib import Path
from manuscripta.enums.book_type import BookType
from manuscripta.exceptions import (
    ManuscriptaImageError,
    ManuscriptaLayoutError,
    ManuscriptaPandocError,
)
from manuscripta.export.validation import (
    validate_epub_with_epubcheck,
    validate_pdf,
    validate_markdown,
    validate_docx,
    validate_html,
)

# Replace with your data
DEFAULT_METADATA = """title: 'CHANGE TO YOUR TITLE'
author: 'YOUR NAME'
date: '2025'
lang: 'en'
"""

# All paths are relative to the current working directory (= book repo root).
# The CLI entry point is always invoked from the book repo root.
# No os.chdir() - the library must not change the process working directory.

# Define important directory and file paths
BOOK_DIR = "./manuscript"  # Location of markdown files organized by sections
OUTPUT_DIR = "./output"  # Output directory for compiled formats
BACKUP_DIR = "./output_backup"  # Backup location for previous output
# Set to None to derive from pyproject.toml automatically.
# Set a string to override the output file base name manually.
OUTPUT_FILE = ""
LOG_FILE = "export.log"  # Log file for script and Pandoc output/errors

# Supporting module paths (used via python -m instead of file paths)
_MOD_PATHS_TO_ABSOLUTE = "manuscripta.paths.to_absolute"
_MOD_PATHS_TO_RELATIVE = "manuscripta.paths.to_relative"
_MOD_PATHS_IMG_TAGS = "manuscripta.paths.img_tags"
_MOD_NORMALIZE_TOC = "manuscripta.markdown.normalize_toc"
TOC_FILE = Path(BOOK_DIR) / "front-matter" / "toc.md"

CONFIG_DIR = "./config"
METADATA_FILE = (
    Path(CONFIG_DIR) / "metadata.yaml"
)  # YAML file for Pandoc metadata (title, author, etc.)
EXPORT_SETTINGS_FILE = (
    Path(CONFIG_DIR) / "export-settings.yaml"
)  # YAML file for export configuration

# Supported output formats and their corresponding Pandoc targets
_BUILTIN_FORMATS = {
    "markdown": "gfm",  # GitHub-Flavored Markdown
    "pdf": "pdf",  # PDF format
    "epub": "epub",  # EPUB eBook format
    "docx": "docx",  # Microsoft Word format
    "html": "html",  # HTML format
}

# Built-in section orders (used as fallback when export-settings.yaml is missing)
_BUILTIN_DEFAULT_SECTION_ORDER = [
    "front-matter/toc.md",
    "front-matter/foreword.md",
    "front-matter/preface.md",
    "chapters",  # Entire chapters folder
    "back-matter/epilogue.md",
    "back-matter/glossary.md",
    "back-matter/appendix.md",
    "back-matter/acknowledgments.md",
    "back-matter/about-the-author.md",
    "back-matter/bibliography.md",
    "back-matter/imprint.md",
]

_BUILTIN_PAPERBACK_SECTION_ORDER = [
    "front-matter/toc-print.md",  # Your existing print TOC
    "front-matter/foreword.md",
    "front-matter/preface.md",
    "chapters",  # Entire chapters folder
    "back-matter/epilogue.md",
    "back-matter/glossary.md",
    "back-matter/appendix.md",
    "back-matter/acknowledgments.md",
    "back-matter/about-the-author.md",
    "back-matter/bibliography.md",
    "back-matter/imprint.md",
]

_BUILTIN_EPUB_SKIP_TOC_FILES = [
    "front-matter/toc.md",
    "front-matter/toc-print.md",
]

# Default TOC depth for auto-generated TOCs
# - Depth 2 (# ##): Recommended for most books, keeps TOC clean and navigable
# - Depth 3 (# ## ###): Good for technical/academic books with many subsections
# - Depth 1: Too shallow for most use cases
_BUILTIN_TOC_DEPTH = 2


_logger = logging.getLogger(__name__)


# --- source_dir contract (v0.8.0) --------------------------------------------

# Subdirectories that must exist in a valid manuscripta source directory.
REQUIRED_SOURCE_SUBDIRS: tuple[str, ...] = ("manuscript", "config", "assets")

# Regex for Pandoc's "could not fetch resource" warnings.
# Matches lines like:
#   [WARNING] Could not fetch resource "images/foo.png": ...
#   [WARNING] Could not fetch resource 'images/foo.png'
_UNRESOLVED_IMAGE_RE = re.compile(
    r"Could not fetch resource\s+['\"]?([^'\"\n]+?)['\"]?(?:\s*:|\s*$)",
    re.IGNORECASE,
)


def _parse_unresolved_images(stderr_text: str) -> list[str]:
    """Extract the unresolved resource paths from Pandoc's stderr."""
    seen: list[str] = []
    for match in _UNRESOLVED_IMAGE_RE.finditer(stderr_text):
        res = match.group(1).strip()
        if res and res not in seen:
            seen.append(res)
    return seen


def _validate_layout(source_dir: Path) -> None:
    """Validate that ``source_dir`` has the expected directory layout.

    Raises:
        ManuscriptaLayoutError: if ``source_dir`` does not exist or is missing
            any of :data:`REQUIRED_SOURCE_SUBDIRS`.
    """
    source_dir = Path(source_dir)
    if not source_dir.exists():
        raise ManuscriptaLayoutError(source_dir, reason="nonexistent")
    if not source_dir.is_dir():
        raise ManuscriptaLayoutError(source_dir, reason="not_a_directory")
    missing = [d for d in REQUIRED_SOURCE_SUBDIRS if not (source_dir / d).is_dir()]
    if missing:
        raise ManuscriptaLayoutError(source_dir, missing)


def _configure_paths(
    source_dir: Path,
    resource_paths: list[Path] | None = None,
) -> str:
    """Anchor module-level path globals on an explicit ``source_dir``.

    Returns the ``--resource-path`` value (``os.pathsep``-joined absolute
    directories) that should be passed to Pandoc.

    .. note::
        This mutates module-level globals. It never calls :func:`os.chdir` —
        the library must not change the process working directory.
    """
    src = Path(source_dir).resolve()

    global BOOK_DIR, OUTPUT_DIR, BACKUP_DIR, CONFIG_DIR
    global METADATA_FILE, EXPORT_SETTINGS_FILE, TOC_FILE, LOG_FILE

    BOOK_DIR = str(src / "manuscript")
    OUTPUT_DIR = str(src / "output")
    BACKUP_DIR = str(src / "output_backup")
    CONFIG_DIR = str(src / "config")
    METADATA_FILE = src / "config" / "metadata.yaml"
    EXPORT_SETTINGS_FILE = src / "config" / "export-settings.yaml"
    TOC_FILE = Path(BOOK_DIR) / "front-matter" / "toc.md"
    LOG_FILE = str(src / "export.log")

    abs_paths: list[str] = [str(src / "assets")]
    if resource_paths:
        for p in resource_paths:
            p_abs = str(Path(p).resolve())
            if p_abs not in abs_paths:
                abs_paths.append(p_abs)
    return os.pathsep.join(abs_paths)


def run_export(
    source_dir: Path | str,
    *,
    resource_paths: list[Path] | None = None,
    strict_images: bool = True,
    formats: list[str] | str | None = None,
    book_type: BookType | str = BookType.EBOOK,
    section_order: list[str] | None = None,
    cover: str | None = None,
    epub2: bool = False,
    lang: str | None = None,
    extension: str | None = None,
    output_file: str | None = None,
    no_type_suffix: bool = False,
    toc_depth: int | None = None,
    use_manual_toc: bool = False,
    skip_images: bool = False,
    keep_relative_paths: bool = False,
    copy_epub_to: str | None = None,
    output_path: Path | str | None = None,
) -> None:
    """Canonical library API for producing a book.

    Parameters:
        source_dir: Path to the book repository root. Must contain
            ``manuscript/``, ``config/``, and ``assets/`` subdirectories.
            **Required** — no cwd fallback, no environment discovery.
        resource_paths: Extra asset directories, resolved to absolute paths
            and appended after ``source_dir / "assets"`` in Pandoc's
            ``--resource-path``.
        strict_images: If ``True`` (default), raise
            :class:`ManuscriptaImageError` when Pandoc cannot resolve any
            image resource. If ``False``, log a warning and continue.
        formats: Comma-separated string or list of output formats
            (``pdf``, ``epub``, ``docx``, ``markdown``, ``html``). If
            ``None``, all built-in formats are produced.

    Raises:
        ManuscriptaLayoutError: if ``source_dir`` is missing required
            subdirectories.
        ManuscriptaImageError: if ``strict_images=True`` and Pandoc reports
            unresolved image resources.
        TypeError: if ``source_dir`` is omitted (positional-argument
            contract).
    """
    if source_dir is None:
        raise TypeError(
            "run_export() requires an explicit source_dir; there is no cwd fallback."
        )

    src = Path(source_dir).resolve()
    _validate_layout(src)
    resource_path = _configure_paths(src, resource_paths)

    # Build synthetic CLI argv to reuse existing ``main()`` pipeline logic.
    argv: list[str] = []
    if isinstance(formats, list):
        argv += ["--format", ",".join(formats)]
    elif isinstance(formats, str):
        argv += ["--format", formats]
    if section_order is not None:
        argv += ["--order", ",".join(section_order)]
    if cover is not None:
        argv += ["--cover", cover]
    if epub2:
        argv += ["--epub2"]
    if lang is not None:
        argv += ["--lang", lang]
    if extension is not None:
        argv += ["--extension", extension]
    bt_value = book_type.value if isinstance(book_type, BookType) else str(book_type)
    argv += ["--book-type", bt_value]
    if output_file is not None:
        argv += ["--output-file", output_file]
    if no_type_suffix:
        argv += ["--no-type-suffix"]
    if toc_depth is not None:
        argv += ["--toc-depth", str(toc_depth)]
    if use_manual_toc:
        argv += ["--use-manual-toc"]
    if skip_images:
        argv += ["--skip-images"]
    elif keep_relative_paths:
        argv += ["--keep-relative-paths"]
    if copy_epub_to is not None:
        argv += ["--copy-epub-to", copy_epub_to]

    _run_pipeline(
        argv=argv,
        source_dir=src,
        resource_path=resource_path,
        strict_images=strict_images,
        output_path=Path(output_path) if output_path is not None else None,
    )


# --- Config loading from export-settings.yaml --------------------------------


def load_export_settings(path=None):
    """
    Load export configuration from a YAML file.

    Returns the parsed dict, or {} if the file does not exist.
    """
    settings_path = Path(path) if path else EXPORT_SETTINGS_FILE
    if not settings_path.exists():
        return {}
    with settings_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_section_order_from_settings(settings, book_type_value):
    """
    Resolve the section order for a given book type from loaded settings.

    Fallback chain:
    - ebook   -> "ebook" key, then "default" key, then built-in default
    - paperback -> "paperback" key, then built-in paperback
    - hardcover -> "hardcover" key, then "paperback" key, then built-in paperback
    - audiobook -> "audiobook" key, then "default" key, then built-in default

    A null value in the YAML means "inherit from parent".
    Returns None if settings has no section_order at all (caller uses built-in).
    """
    orders = settings.get("section_order")
    if not orders:
        return None

    order = orders.get(book_type_value)

    # null fallback chain
    if order is None:
        if book_type_value in ("ebook", "audiobook"):
            order = orders.get("default")
        elif book_type_value == "hardcover":
            order = orders.get("paperback")

    return order


# --- Load settings and populate module-level constants -----------------------

_EXPORT_SETTINGS = load_export_settings()

FORMATS = _EXPORT_SETTINGS.get("formats", _BUILTIN_FORMATS)
DEFAULT_TOC_DEPTH = _EXPORT_SETTINGS.get("toc_depth", _BUILTIN_TOC_DEPTH)
EPUB_SKIP_TOC_FILES = _EXPORT_SETTINGS.get(
    "epub_skip_toc_files", _BUILTIN_EPUB_SKIP_TOC_FILES
)

# Section orders: prefer config, fall back to built-in
DEFAULT_SECTION_ORDER = (
    get_section_order_from_settings(_EXPORT_SETTINGS, "default")
    or _BUILTIN_DEFAULT_SECTION_ORDER
)
EBOOK_SECTION_ORDER = (
    get_section_order_from_settings(_EXPORT_SETTINGS, "ebook") or DEFAULT_SECTION_ORDER
)
PAPERBACK_SECTION_ORDER = (
    get_section_order_from_settings(_EXPORT_SETTINGS, "paperback")
    or _BUILTIN_PAPERBACK_SECTION_ORDER
)
HARDCOVER_SECTION_ORDER = (
    get_section_order_from_settings(_EXPORT_SETTINGS, "hardcover")
    or PAPERBACK_SECTION_ORDER
)


def pick_section_order(book_type: "BookType", fmt: str) -> list[str]:
    """
    Decide which section order to use if --order was not provided.
    - ebook  -> EBOOK_SECTION_ORDER
    - paperback/hardcover -> PAPERBACK/HARDCOVER_SECTION_ORDER
    Note: For non-EPUB builds of ebook (e.g., markdown or pdf drafts), we still
    stick to EBOOK_SECTION_ORDER unless user overrides.
    """
    if book_type.value == "ebook":
        return EBOOK_SECTION_ORDER
    if book_type.value == "paperback":
        return PAPERBACK_SECTION_ORDER
    if book_type.value == "hardcover":
        return HARDCOVER_SECTION_ORDER
    # Fallback
    return DEFAULT_SECTION_ORDER


def resolve_ext(fmt: str, custom_markdown_ext: str | None) -> str:
    if fmt == "markdown":
        return custom_markdown_ext if custom_markdown_ext else "md"
    return FORMATS[fmt]


def get_project_name_from_pyproject(pyproject_path="pyproject.toml"):
    """
    Extract the project name from the pyproject.toml file.

    This function reads the `[tool.poetry.name]` field from a pyproject.toml file
    and returns it as a string. This value is used as the base prefix for output filenames.

    Parameters:
    - pyproject_path (str): Path to the pyproject.toml file (default: "pyproject.toml")

    Returns:
    - str: The project name if found, otherwise a fallback value ("book")
    """
    if pyproject_path is None:
        pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        data = toml.load(pyproject_path)
        return (
            data.get("tool", {}).get("poetry", {}).get("name")
            or data.get("project", {}).get("name")
            or "book"
        )
    except Exception as e:
        print(f"⚠️ Could not read project name from {pyproject_path}: {e}")
        return "book"


def get_metadata_language():
    """Read and return the 'lang' field from metadata.yaml if present, else return None."""
    if not METADATA_FILE.exists():
        print(f"⚠️ Metadata file not found at: {METADATA_FILE}")
        return None
    with METADATA_FILE.open("r", encoding="utf-8") as f:
        try:
            metadata = yaml.safe_load(f)
            return metadata.get("language") or metadata.get("lang")
        except yaml.YAMLError as e:
            print(f"⚠️ Failed to parse {METADATA_FILE}: {e}")
            return None


def run_script(module_path, arg=None, cwd=None):
    """Run a manuscripta module with optional arguments and log output.

    Parameters:
        module_path: Dotted Python module to run via ``python3 -m``.
        arg: Optional single positional argument.
        cwd: Optional working directory to launch the subprocess in.
    """
    try:
        cmd = ["python3", "-m", module_path]
        if arg:
            cmd.append(arg)
        subprocess.run(
            cmd,
            check=True,
            cwd=cwd,
            stdout=open(LOG_FILE, "a"),
            stderr=open(LOG_FILE, "a"),
        )
        print(f"Successfully executed: {module_path} {arg if arg else ''}")
    except subprocess.CalledProcessError as e:
        print(f"Error running module {module_path}: {e}")
        raise  # Needed so tests detect the failure


def prepare_output_folder(verbose=False):
    """
    Prepares the output directory by ensuring it's empty.
    - Deletes existing backup dir if present
    - Moves current output dir to backup
    - Creates a fresh output dir
    """
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
        if verbose:
            print("📦 Deleted old backup directory.")

    if os.path.exists(OUTPUT_DIR) and os.listdir(OUTPUT_DIR):
        shutil.move(OUTPUT_DIR, BACKUP_DIR)
        if verbose:
            print("📁 Moved current output to backup directory.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if verbose:
        print("📂 Created clean output directory.")


def get_or_create_metadata_file(preferred_path: Path | str | None = None):
    """
    Return a usable metadata file path.

    - If the preferred_path exists, return it with `is_temp=False`.
    - Otherwise, create a temporary metadata YAML file with default content
      and return it with `is_temp=True`.
    """
    path = Path(preferred_path) if preferred_path else METADATA_FILE
    if path.exists():
        return path, False

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml")
    tmp.write(DEFAULT_METADATA.encode("utf-8"))
    tmp.flush()
    tmp.close()
    return Path(tmp.name), True


def ensure_metadata_file():
    """
    Ensures the metadata file exists.
    - Prevents Pandoc warnings by providing minimal metadata if missing.
    """
    if not os.path.exists(METADATA_FILE):
        print(f"⚠️ Metadata file missing! Creating default {METADATA_FILE}.")
        os.makedirs(os.path.dirname(METADATA_FILE), exist_ok=True)
        with open(METADATA_FILE, "w", encoding="utf-8") as f:
            # TODO: Replace with your data
            f.write(
                'title: "CHANGE TO YOUR TITLE"\n'
                'author: "YOUR NAME"\n'
                'date: "2025"\n'
                'lang: "en"\n'
            )


def filter_section_order_for_epub(section_order: list[str]) -> list[str]:
    """
    Remove manual TOC files from section order for EPUB ebook builds.

    Pandoc will generate the TOC automatically with the --toc flag,
    which creates proper cross-file links (chXXX.xhtml#anchor) that
    pass epubcheck validation.

    Note: This is only used for ebook EPUBs. Paperback/hardcover EPUBs
    use the existing toc-print.md file.
    """
    filtered = [s for s in section_order if s not in EPUB_SKIP_TOC_FILES]
    return filtered


def compile_book(
    format,
    section_order,
    book_type,
    cover_path=None,
    force_epub2=False,
    lang="en",
    custom_ext=None,
    toc_depth=DEFAULT_TOC_DEPTH,
    use_manual_toc=False,
    resource_path: str | None = None,
    strict_images: bool = True,
    run_cwd: str | None = None,
    output_path_override: str | None = None,
):
    """
    Compiles the book into a specific format using Pandoc.

    Parameters:
    - format: Format to compile (e.g. pdf, docx, epub)
    - section_order: Ordered list of sections to include
    - book_type: BookType enum (ebook, paperback, hardcover)
    - cover_path: Optional path to cover image (for EPUB)
    - force_epub2: Force EPUB 2 format
    - lang: Language code (e.g. en, de, fr)
    - custom_ext: Custom file extension for markdown output
    - toc_depth: Depth of auto-generated TOC (default: 2)
    - use_manual_toc: Use existing toc.md instead of auto-generating for EPUB
    """
    ext = resolve_ext(format, custom_ext)
    output_path = os.path.join(OUTPUT_DIR, f"{OUTPUT_FILE}.{ext}")

    # Determine if this is a print build (paperback/hardcover)
    is_print_build = book_type.value in ("paperback", "hardcover")

    # For EPUB + ebook only: filter out manual TOC files (Pandoc generates TOC automatically)
    # Unless --use-manual-toc is set, then use your existing toc.md
    # For EPUB + paperback/hardcover: use your existing toc-print.md
    if format == "epub" and not is_print_build and not use_manual_toc:
        effective_order = filter_section_order_for_epub(section_order)
        if len(effective_order) < len(section_order):
            print(
                "ℹ️  EPUB (ebook): Skipping manual TOC. Pandoc will generate TOC automatically."
            )
    elif format == "epub" and not is_print_build and use_manual_toc:
        effective_order = section_order
        print("ℹ️  EPUB (ebook): Using your existing toc.md (--use-manual-toc).")
    else:
        # PDF, DOCX, HTML, Markdown, or EPUB for print: use your existing files unchanged
        effective_order = section_order

    md_files = []

    # Gather markdown files from the specified order
    for section in effective_order:
        section_path = os.path.join(BOOK_DIR, section)
        if os.path.isdir(section_path):
            # Include all .md files in directory, sorted
            md_files.extend(
                sorted(
                    os.path.join(section_path, f)
                    for f in os.listdir(section_path)
                    if f.endswith(".md")
                )
            )
        elif os.path.isfile(section_path):
            # Include specific markdown file
            md_files.append(section_path)

    if not md_files:
        print(f"❌ No Markdown files found for format {format}. Skipping.")
        return

    # --resource-path: caller-supplied wins; otherwise fall back to legacy
    # "./assets" (resolved against run_cwd if provided, else current cwd).
    if resource_path is None:
        base = Path(run_cwd) if run_cwd else Path.cwd()
        resource_path = str((base / "assets").resolve())

    # Metadata file: if not absolute, resolve against run_cwd (if provided).
    metadata_file_arg = METADATA_FILE
    if run_cwd and not Path(metadata_file_arg).is_absolute():
        metadata_file_arg = str((Path(run_cwd) / metadata_file_arg).resolve())

    # Output path: caller override wins; otherwise fall back to derived path,
    # resolved against run_cwd (if provided).
    if output_path_override is not None:
        pandoc_output = str(Path(output_path_override).resolve())
        Path(pandoc_output).parent.mkdir(parents=True, exist_ok=True)
    else:
        pandoc_output = output_path
        if run_cwd and not Path(pandoc_output).is_absolute():
            pandoc_output = str((Path(run_cwd) / pandoc_output).resolve())

    # Construct Pandoc command
    pandoc_cmd = [
        "pandoc",
        "--verbose",
        "--from=markdown",
        f"--to={FORMATS[format]}",
        f"--output={pandoc_output}",
        f"--resource-path={resource_path}",  # To resolve images and assets
        f"--metadata-file={metadata_file_arg}",
    ] + md_files  # Append all markdown files to compile

    # EPUB-specific options
    if format == "epub":
        pandoc_cmd.extend(["--metadata", f"lang={lang}"])
        # Only auto-generate TOC for ebook type when --use-manual-toc is NOT set
        if not is_print_build and not use_manual_toc:
            pandoc_cmd.extend(
                [
                    "--toc",  # Generate table of contents
                    f"--toc-depth={toc_depth}",  # TOC depth (default: 2)
                    "--epub-chapter-level=1",  # Each H1 becomes a new XHTML file
                ]
            )
        if force_epub2:
            pandoc_cmd.extend(["--metadata", "epub.version=2"])
        if cover_path:
            pandoc_cmd.append(f"--epub-cover-image={cover_path}")

    # PDF-specific options
    if format == "pdf":
        pandoc_cmd.extend(
            [
                "--pdf-engine=xelatex",  # Options: xelatex, lualatex, pdflatex
                "-V",
                "mainfont=DejaVu Sans",
                "-V",
                "monofont=DejaVu Sans Mono",
            ]
        )

    # Markdown-specific options
    if format == "markdown":
        pandoc_cmd.append("--wrap=none")  # Prevent line breaks in links and paragraphs

    # HTML-specific options
    if format == "html":
        pandoc_cmd.extend(
            [
                "--standalone",  # Generate complete HTML document
                "--css=assets/style.css",  # Optional: Include CSS file (must exist)
                "--metadata",
                f"lang={lang}",
            ]
        )

    # Run Pandoc, capture stderr (for image-warning parsing), and tee to log.
    def _cleanup_partial() -> None:
        try:
            Path(pandoc_output).unlink(missing_ok=True)
        except OSError:
            pass

    try:
        completed = subprocess.run(
            pandoc_cmd,
            check=True,
            cwd=run_cwd,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        # Tee captured output to the log so the operator sees it.
        stderr_text = e.stderr if isinstance(e.stderr, str) else ""
        stdout_text = e.stdout if isinstance(e.stdout, str) else ""
        with open(LOG_FILE, "a") as log_file:
            if stdout_text:
                log_file.write(stdout_text)
            if stderr_text:
                log_file.write(stderr_text)
        _cleanup_partial()
        # If the failure was caused by an unresolvable image and strict mode
        # is on, prefer the more specific exception.
        unresolved = _parse_unresolved_images(stderr_text)
        if unresolved and strict_images:
            raise ManuscriptaImageError(unresolved) from e
        raise ManuscriptaPandocError(
            returncode=e.returncode, stderr=stderr_text, cmd=pandoc_cmd
        ) from e

    stdout_text = completed.stdout if isinstance(completed.stdout, str) else ""
    stderr_text = completed.stderr if isinstance(completed.stderr, str) else ""
    with open(LOG_FILE, "a") as log_file:
        if stdout_text:
            log_file.write(stdout_text)
        if stderr_text:
            log_file.write(stderr_text)

    unresolved = _parse_unresolved_images(stderr_text)
    if unresolved:
        if strict_images:
            _cleanup_partial()
            raise ManuscriptaImageError(unresolved)
        for u in unresolved:
            _logger.warning("manuscripta: unresolved image resource: %s", u)
        print(
            f"⚠️ Pandoc reported {len(unresolved)} unresolved image resource(s) "
            f"(strict_images=False, continuing): {', '.join(unresolved)}"
        )

    print(f"✅ Successfully generated: {pandoc_output}")


def normalize_toc_if_needed(toc_path: Path, extension: str | None = None, cwd: str | None = None):
    """
    Normalize TOC links (only for web/ebook ToC 'toc.md').

    This step is mainly for non-EPUB/non-print formats where the manual
    TOC is included in the output.
    """
    try:
        if toc_path.exists() and toc_path.name == "toc.md":
            toc_mode = "strip-to-anchors"
            toc_ext = extension if extension else "md"
            subprocess.run(
                [
                    "python3",
                    "-m",
                    _MOD_NORMALIZE_TOC,
                    "--toc",
                    str(toc_path),
                    "--mode",
                    toc_mode,
                    "--ext",
                    toc_ext,
                ],
                check=True,
                cwd=cwd,
                stdout=open(LOG_FILE, "a"),
                stderr=open(LOG_FILE, "a"),
            )
            print(f"✅ TOC normalized using mode={toc_mode}: {toc_path}")
        else:
            print(f"ℹ️  Skipping TOC normalization for {toc_path.name} (not ebook toc).")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error normalizing TOC: {e}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export your book into multiple formats."
    )
    parser.add_argument(
        "--format", type=str, help="Specify formats (comma-separated, e.g., pdf,epub)."
    )
    parser.add_argument(
        "--order",
        type=str,
        default=None,
        help="Specify document order (comma-separated). If omitted, a sane default is chosen based on --book-type.",
    )
    parser.add_argument(
        "--cover", type=str, help="Optional path to cover image (for EPUB export)."
    )
    parser.add_argument(
        "--epub2",
        action="store_true",
        help="Force EPUB 2 export (for epubli compatibility).",
    )
    parser.add_argument(
        "--lang", type=str, help="Language code for metadata (e.g. en, de, fr)"
    )
    parser.add_argument(
        "--extension",
        type=str,
        help="Custom file extension for markdown export (default: md)",
    )
    parser.add_argument(
        "--book-type",
        type=str,
        choices=[bt.value for bt in BookType],
        default=None,
        help="Specify the book type (ebook, paperback, hardcover). Default: ebook, or from export-settings.yaml.",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Custom output file base name (overrides project name)",
    )
    parser.add_argument(
        "--no-type-suffix",
        action="store_true",
        help="Do not append '-{book_type}' to the output base name.",
    )
    parser.add_argument(
        "--toc-depth",
        type=int,
        default=DEFAULT_TOC_DEPTH,
        help=f"Depth of auto-generated TOC for EPUB and print PDF (default: {DEFAULT_TOC_DEPTH}). "
        "Use 2 for most books, 3 for technical books with many subsections.",
    )
    parser.add_argument(
        "--use-manual-toc",
        action="store_true",
        help="Use your existing toc.md instead of auto-generating TOC for EPUB ebook.",
    )

    parser.add_argument(
        "--copy-epub-to",
        type=str,
        nargs="?",
        const="~/Downloads",
        default=None,
        help="Copy the generated EPUB file to the specified directory (default: ~/Downloads). "
        "Use without value for ~/Downloads, or provide a custom path.",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--skip-images",
        action="store_true",
        help="Skip all image-related steps (no path rewrites, no tag transforms).",
    )
    group.add_argument(
        "--keep-relative-paths",
        action="store_true",
        help="Do not rewrite image/URL paths to absolute and back; keeps relative paths (skips Steps 1 and 4).",
    )

    return parser


def _run_pipeline(
    *,
    argv: list[str],
    source_dir: Path,
    resource_path: str,
    strict_images: bool,
    output_path: Path | None = None,
) -> None:
    """Full export pipeline. Anchors all paths on ``source_dir``.

    This function does NOT call ``os.chdir``. Child processes that need a
    working directory are launched with ``cwd=source_dir``.
    """
    parser = _build_arg_parser()
    # argparse handles --help/-h here and exits before we do any validation,
    # so CLI short-circuit flags work from any cwd. See fix(cli) commit.
    args = parser.parse_args(argv)

    # Validate layout AFTER argparse so --help/-h can short-circuit even
    # outside a valid book project. run_export() validates earlier for its
    # library contract; this second call is a cheap no-op for valid layouts
    # and the only call on the CLI path.
    _validate_layout(source_dir)

    run_cwd = str(source_dir)

    # Load export settings (already loaded at module level, but re-read for
    # CLI-overridable defaults that live under an "export_defaults" key)
    settings = load_export_settings(EXPORT_SETTINGS_FILE)
    config = settings.get("export_defaults", {})

    # Log --copy-epub-to early so user sees it was recognized
    copy_epub_to = args.copy_epub_to or config.get("copy_epub_to", None)
    if copy_epub_to:
        resolved_dest = Path(copy_epub_to).expanduser().resolve()
        print(f"EPUB copy requested -> {resolved_dest}")

    # Book type: CLI > config > default
    book_type_str = args.book_type or config.get("book_type", BookType.EBOOK.value)
    book_type = BookType(book_type_str)

    # Decide section order: CLI > auto by book type
    if args.order:
        section_order = args.order.split(",")
    else:
        section_order = None

    # Set global output filename: CLI > config > pyproject.toml name
    global OUTPUT_FILE
    no_type_suffix = args.no_type_suffix or config.get("no_type_suffix", False)
    add_type_suffix = not no_type_suffix
    output_file_arg = args.output_file or config.get("output_file", None)
    if output_file_arg:
        op = Path(output_file_arg)
        OUTPUT_FILE = op.stem
    elif OUTPUT_FILE is None or OUTPUT_FILE == "":
        project_name = get_project_name_from_pyproject(
            str(Path(run_cwd) / "pyproject.toml") if run_cwd else "pyproject.toml"
        )
        OUTPUT_FILE = project_name

    if add_type_suffix:
        OUTPUT_FILE = f"{OUTPUT_FILE}_{book_type.value}"

    print(f"Output file base name set to: {OUTPUT_FILE}")

    # Determine language: CLI > config > metadata.yaml > fallback
    metadata_lang = get_metadata_language()
    cli_lang = args.lang or config.get("lang", None)

    if cli_lang:
        if metadata_lang and cli_lang != metadata_lang:
            print(
                f"\nLANGUAGE MISMATCH: metadata says '{metadata_lang}', configured is '{cli_lang}'. Using configured value."
            )
        lang = cli_lang
    elif metadata_lang:
        lang = metadata_lang
        print(f"Using language from metadata.yaml: '{lang}'")
    else:
        lang = "en"
        print("No language set. Defaulting to 'en'")

    # Resolve remaining options: CLI > config > defaults
    cover = args.cover or config.get("cover", None)
    epub2 = args.epub2 or config.get("epub2", False)
    extension = args.extension or config.get("extension", None)
    toc_depth = (
        args.toc_depth
        if args.toc_depth != DEFAULT_TOC_DEPTH
        else config.get("toc_depth", DEFAULT_TOC_DEPTH)
    )
    use_manual_toc = args.use_manual_toc or config.get("use_manual_toc", False)
    skip_images = args.skip_images or config.get("skip_images", False)
    keep_relative_paths = args.keep_relative_paths or config.get(
        "keep_relative_paths", False
    )
    format_arg = args.format or config.get("format", None)

    # Step 1a: Normalize TOC (for non-EPUB/non-print formats where manual TOC is used)
    # Note: For EPUB and print PDF, the manual TOC is skipped anyway
    try:
        if TOC_FILE.exists():
            toc_mode = "strip-to-anchors"
            toc_ext = extension if extension else "md"
            subprocess.run(
                [
                    "python3",
                    "-m",
                    _MOD_NORMALIZE_TOC,
                    "--toc",
                    str(TOC_FILE),
                    "--mode",
                    toc_mode,
                    "--ext",
                    toc_ext,
                ],
                check=True,
                cwd=run_cwd,
                stdout=open(LOG_FILE, "a"),
                stderr=open(LOG_FILE, "a"),
            )
            print(f"✅ TOC normalized using mode={toc_mode}")
        else:
            print(f"ℹ️  No TOC file at {TOC_FILE}; skipping TOC normalization.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error normalizing TOC: {e}")

    # Step 1: Convert image paths to absolute
    # Run pre-processing scripts unless user opts out or wants to keep relative paths
    if not skip_images and not keep_relative_paths:
        run_script(_MOD_PATHS_TO_ABSOLUTE, cwd=run_cwd)
        run_script(_MOD_PATHS_IMG_TAGS, "--to-absolute", cwd=run_cwd)
    elif skip_images:
        print("⏭️  Skipping Step 1 (skip-images).")
    else:
        print("⏭️  Skipping Step 1 (keep relative paths).")

    # Step 2: Prepare environment
    prepare_output_folder()  # Prepare folders and backup if needed
    global METADATA_FILE
    METADATA_FILE, _is_temp_metadata = get_or_create_metadata_file(
        METADATA_FILE
    )  # Make sure metadata exists

    # Step 3: Compile the book in requested formats
    selected_formats = format_arg.split(",") if format_arg else FORMATS.keys()

    for fmt in selected_formats:
        if fmt not in FORMATS:
            print(f"⚠️ Skipping unknown format: {fmt}")
            continue

        effective_order = (
            section_order
            if section_order is not None
            else pick_section_order(book_type, fmt)
        )

        # Warning if print TOC file is missing (only relevant for non-auto-TOC builds)
        if "front-matter/toc-print.md" in effective_order:
            toc_print_path = Path(BOOK_DIR) / "front-matter" / "toc-print.md"
            if not toc_print_path.exists():
                print(
                    "⚠️ Print ToC file missing: manuscript/front-matter/toc-print.md "
                    "(will use auto-generated TOC instead)"
                )
                # Remove the missing file from order
                idx = effective_order.index("front-matter/toc-print.md")
                effective_order = effective_order.copy()
                effective_order.pop(idx)

        # TOC normalization only for formats that use manual TOC
        # (EPUB and print PDF use auto-generated TOC, so this is skipped for them)
        if fmt not in ("epub",) and not (
            fmt == "pdf" and book_type.value in ("paperback", "hardcover")
        ):
            toc_candidate = (
                Path(BOOK_DIR)
                / "front-matter"
                / (
                    "toc.md"
                    if "front-matter/toc.md" in effective_order
                    else "toc-print.md"
                )
            )
            if toc_candidate.exists():
                normalize_toc_if_needed(toc_candidate, extension, cwd=run_cwd)

        compile_book(
            fmt,
            effective_order,
            book_type,
            cover,
            epub2,
            lang,
            extension,
            toc_depth,
            use_manual_toc,
            resource_path=resource_path,
            strict_images=strict_images,
            run_cwd=run_cwd,
            output_path_override=str(output_path) if output_path else None,
        )

    # Step 4: Restore original image paths
    # Revert any image/URL changes made before compilation unless we kept relative paths
    if not skip_images and not keep_relative_paths:
        run_script(_MOD_PATHS_TO_RELATIVE, cwd=run_cwd)
        run_script(_MOD_PATHS_IMG_TAGS, "--to-relative", cwd=run_cwd)
    elif skip_images:
        print("⏭️  Skipping Step 4 (skip-images).")
    else:
        print("⏭️  Skipping Step 4 (keep relative paths).")

    # Step 5: Start background validation for each generated format
    threads = []

    for fmt in selected_formats:
        ext_for_fmt = resolve_ext(fmt, extension if fmt == "markdown" else None)
        output_path = os.path.join(OUTPUT_DIR, f"{OUTPUT_FILE}.{ext_for_fmt}")

        if fmt == "epub":
            thread = threading.Thread(
                target=validate_epub_with_epubcheck,
                args=(output_path,),
                name=f"Validate-{fmt.upper()}",
                daemon=False,
            )
            print("🧩 EPUB generated. Validation running in background...")
        elif fmt == "pdf":
            thread = threading.Thread(
                target=validate_pdf,
                args=(output_path,),
                name=f"Validate-{fmt.upper()}",
                daemon=False,
            )
            print("🧩 PDF generated. Validation running in background...")
        elif fmt == "docx":
            thread = threading.Thread(
                target=validate_docx,
                args=(output_path,),
                name=f"Validate-{fmt.upper()}",
                daemon=False,
            )
            print("🧩 DOCX generated. Validation running in background...")
        elif fmt == "markdown":
            thread = threading.Thread(
                target=validate_markdown,
                args=(output_path,),
                name=f"Validate-{fmt.upper()}",
                daemon=False,
            )
            print("🧩 Markdown generated. Validation running in background...")
        elif fmt == "html":
            thread = threading.Thread(
                target=validate_html,
                args=(output_path,),
                name="Validate-HTML",
                daemon=False,
            )
            print("🧩 HTML generated. Validation running in background...")
        else:
            continue  # Skip unknown formats

        thread.start()
        threads.append(thread)

    # Step 5b: Copy EPUB to target directory if requested
    if copy_epub_to:
        epub_output = Path(OUTPUT_DIR) / f"{OUTPUT_FILE}.epub"
        epub_output_abs = epub_output.resolve()
        print(f"📋 Looking for EPUB: {epub_output_abs}")

        if epub_output_abs.is_file():
            target_dir = Path(copy_epub_to).expanduser().resolve()
            target_path = target_dir / epub_output.name
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(epub_output_abs, target_path)
                print(f"✅ EPUB copied to: {target_path}")
            except OSError as e:
                print(f"❌ Failed to copy EPUB to {target_dir}: {e}")
        else:
            print(f"⚠️ EPUB not found at {epub_output_abs}, nothing to copy.")
            if "epub" not in selected_formats:
                print(
                    f"   Hint: EPUB was not in the selected formats ({', '.join(selected_formats)}). "
                    "Use --format epub or a target that includes EPUB."
                )

    # Final messages
    print("\n🚀 Export completed. Background validation in progress...")
    print("📁 Outputs: ./output/")
    print("📄 Logs: ./export.log")
    print("🔍 Validation results will appear shortly.")

    if _is_temp_metadata:
        try:
            METADATA_FILE.unlink(missing_ok=True)
            print(f"🗑️ Deleted temporary metadata file: {METADATA_FILE}")
        except OSError as e:
            print(f"⚠️ Could not delete temporary metadata file {METADATA_FILE}: {e}")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Parses ``--source-dir`` and ``--strict-images`` / ``--no-strict-images``
    at the CLI layer. If ``--source-dir`` is omitted, the current working
    directory is used as the source_dir. **Only the CLI layer is allowed to
    fall back to cwd — the library API (:func:`run_export`) never does.**
    """
    import sys

    argv_in = list(sys.argv[1:]) if argv is None else list(argv)

    # Peel off --source-dir and strict-images toggles before delegating to the
    # full parser. We do this with a small parser rather than adding them to
    # the main parser so that argv parsing stays shared with run_export().
    cli = argparse.ArgumentParser(add_help=False)
    cli.add_argument("--source-dir", type=str, default=None)
    cli.add_argument(
        "--resource-path",
        action="append",
        default=None,
        help="Extra resource directory (repeatable).",
    )
    strict_group = cli.add_mutually_exclusive_group()
    strict_group.add_argument(
        "--strict-images", dest="strict_images", action="store_true", default=None
    )
    strict_group.add_argument(
        "--no-strict-images", dest="strict_images", action="store_false"
    )
    ns, remaining = cli.parse_known_args(argv_in)

    source_dir = Path(ns.source_dir) if ns.source_dir else Path.cwd()
    resource_paths = [Path(p) for p in (ns.resource_path or [])] or None
    strict_images = True if ns.strict_images is None else ns.strict_images

    # NOTE: _validate_layout is deliberately NOT called here. It must run
    # only after _run_pipeline's argparse has had a chance to handle short-
    # circuit flags (--help/-h), otherwise ``manuscripta-export --help``
    # fails from any cwd that isn't a valid book project. See
    # fix(cli): defer layout validation past argparse short-circuit flags.
    # _configure_paths below is side-effecting but cheap and has no failure
    # mode that affects --help; leaving it here keeps module-global setup
    # symmetric with run_export().
    resource_path = _configure_paths(source_dir, resource_paths)

    _run_pipeline(
        argv=remaining,
        source_dir=source_dir.resolve(),
        resource_path=resource_path,
        strict_images=strict_images,
    )


# Entry point
if __name__ == "__main__":
    main()
