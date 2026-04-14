# manuscripta

Book production pipeline for authors and self-publishers.

Multi-format export (PDF, EPUB, DOCX, HTML, Markdown), audiobook generation, translation, and manuscript tooling,
powered by Pandoc.

## Installation

```bash
pip install manuscripta
```

Or with Poetry:

```bash
poetry add manuscripta
```

## Requirements

- Python 3.11+
- [Pandoc](https://pandoc.org/installing.html) installed and available on PATH
- For audiobook generation: internet connection (Edge TTS) or local TTS engine

## Quick Start

Inside your book repository root:

```bash
# Export to PDF
export-pdf

# Export to EPUB with cover
export-ewc --cover assets/covers/cover.jpg

# Export all formats
export-all

# Safe export (no source modifications, good for drafts)
export-pdf-safe

# Generate audiobook
manuscripta-audiobook --engine edge --voice en-US-JennyNeural

# Initialize a new book project
manuscripta-init
```

## Book Repository Structure

Each book repository should follow this layout:

```
my-book/
  manuscript/
    front-matter/
      toc.md
      toc-print.md
      foreword.md
      preface.md
    chapters/
      01-chapter-one.md
      02-chapter-two.md
    back-matter/
      epilogue.md
      glossary.md
      acknowledgments.md
      about-the-author.md
      bibliography.md
      imprint.md
  config/
    metadata.yaml
    export-settings.yaml
    voice-settings.yaml
  assets/
    covers/
    images/
    fonts/
    templates/
  output/
  pyproject.toml
```

## Using images (v0.8.0+)

Images referenced from your Markdown (`![alt](images/foo.png)`) are resolved
against the book repository's `assets/` directory. As of v0.8.0 the library
has an **explicit contract** about where that directory lives — the caller
passes it in, there is no cwd fallback inside the library.

### From the CLI

Invoke from the project root (default behavior — cwd is used as the source
dir at the CLI layer):

```bash
export-pdf
```

Or pass `--source-dir` explicitly to build from anywhere:

```bash
export-pdf --source-dir=/path/to/my-book
```

Missing images fail the build by default. Opt out with `--no-strict-images`
to continue with warnings. Extra asset directories can be appended with
`--resource-path` (repeatable).

### From Python

```python
from pathlib import Path
from manuscripta.export.book import run_export
from manuscripta import ManuscriptaImageError, ManuscriptaLayoutError

try:
    run_export(
        Path("/abs/path/to/my-book"),  # REQUIRED — no cwd fallback
        formats="pdf",
        resource_paths=[Path("/abs/shared/assets")],
        strict_images=True,            # default
    )
except ManuscriptaLayoutError as e:
    print(f"Bad project layout: missing {e.missing}")
except ManuscriptaImageError as e:
    print(f"Unresolved images: {e.unresolved}")
```

`source_dir` must contain `manuscript/`, `config/`, and `assets/` — a
`ManuscriptaLayoutError` is raised otherwise, naming the missing pieces.

Migrating from v0.7.x? See [MIGRATION.md](MIGRATION.md).

## Configuration

### export-settings.yaml

Controls output formats, TOC behavior, and section ordering per book type (ebook, paperback, hardcover, audiobook).

### voice-settings.yaml

TTS configuration: language, voice, and sections to skip during audio generation.

### metadata.yaml

Pandoc metadata: title, author, date, language.

## Available Commands

### Export

| Command                    | Description               |
|----------------------------|---------------------------|
| `export-pdf` / `export-p`  | Export PDF                |
| `export-epub` / `export-e` | Export EPUB               |
| `export-docx` / `export-d` | Export DOCX               |
| `export-html` / `export-h` | Export HTML               |
| `export-md`                | Export Markdown           |
| `export-all`               | Export all formats        |
| `export-all-with-cover`    | Export all with cover     |
| `export-pvp`               | Print version (paperback) |
| `export-pvh`               | Print version (hardcover) |

All export commands have a `-safe` variant (e.g. `export-pdf-safe`) that skips source preprocessing for fast,
non-destructive draft builds.

### Audiobook

| Command                 | Description            |
|-------------------------|------------------------|
| `manuscripta-audiobook` | Generate MP3 audiobook |

### Translation

| Command                | Description                   |
|------------------------|-------------------------------|
| `translate-en-de`      | English to German (DeepL)     |
| `translate-de-en`      | German to English (DeepL)     |
| `translate-en-es`      | English to Spanish (DeepL)    |
| `translate-de-es`      | German to Spanish (DeepL)     |
| `translate-book-en-de` | English to German (LMStudio)  |
| `translate-book-de-en` | German to English (LMStudio)  |
| `translate-book-en-es` | English to Spanish (LMStudio) |
| `translate-book-en-fr` | English to French (LMStudio)  |

### Markdown Tools

| Command                    | Description                    |
|----------------------------|--------------------------------|
| `fix-german-quotes`        | Fix German quotation marks     |
| `replace-md-bullet-points` | Replace markdown bullet points |
| `unbold-md-headers`        | Remove bold from headers       |
| `replace-emojis`           | Replace emojis in markdown     |
| `strip-links`              | Strip links from markdown      |
| `normalize-toc`            | Normalize TOC links            |

### Path Tools

| Command                     | Description                        |
|-----------------------------|------------------------------------|
| `convert-paths-to-absolute` | Convert relative paths to absolute |
| `convert-paths-to-relative` | Convert absolute paths to relative |

### Image Tools

| Command                  | Description                   |
|--------------------------|-------------------------------|
| `convert-images`         | Convert image formats         |
| `generate-images`        | Generate images               |
| `generate-images-deepai` | Generate images via DeepAI    |
| `inject-images`          | Inject images into manuscript |

### Project Management

| Command                  | Description                  |
|--------------------------|------------------------------|
| `manuscripta-init`       | Initialize new book project  |
| `create-chapters`        | Create chapter files         |
| `reorder-chapters`       | Reorder and rename chapters  |
| `update-metadata-values` | Update metadata values       |
| `manuscripta-tag`        | Generate release tag message |

### Utilities

| Command           | Description                 |
|-------------------|-----------------------------|
| `pandoc-batch`    | Batch pandoc conversion     |
| `bulk-change-ext` | Bulk change file extensions |
| `clean-git-cache` | Clean git cache             |

## Module Structure

```
manuscripta/
  export/        # PDF, EPUB, DOCX, HTML, Markdown export
  audiobook/     # TTS-based audiobook generation
    tts/         # Pluggable TTS backends (Edge, gTTS, pyttsx3, ElevenLabs)
  translation/   # DeepL and LMStudio translation
  markdown/      # Markdown processing (quotes, links, emojis, TOC)
  paths/         # Path conversion (absolute/relative, image tags)
  images/        # Image conversion, generation, injection
  project/       # Project init, chapters, metadata, tagging
  config/        # Config file loading
  enums/         # Book type enum
  utils/         # Pandoc batch, git cache, bulk operations
  data/          # Emoji/symbol maps, JSON data files
```

## Development

### Setup

```bash
git clone https://github.com/astrapi69/manuscripta.git
cd manuscripta
make lock-install
```

### Make Targets

Run `make help` for a full list. Key targets:

| Target              | Description                                   |
|---------------------|-----------------------------------------------|
| `make install`      | Install project with all dependencies         |
| `make lock-install` | Lock and install project dependencies         |
| `make update`       | Update dependencies                           |
| `make hooks`        | Install pre-commit hooks                      |
| `make test`         | Run all tests                                 |
| `make test-v`       | Run all tests (verbose)                       |
| `make test-fast`    | Run tests without coverage (faster)           |
| `make test-cov`     | Run tests with coverage report                |
| `make lint`         | Run ruff linter                               |
| `make lint-fix`     | Run ruff linter with auto-fix                 |
| `make format`       | Format code with black                        |
| `make format-check` | Check formatting without changes              |
| `make typecheck`    | Run MyPy type checks                          |
| `make codespell`    | Run codespell                                 |
| `make precommit`    | Run all pre-commit hooks                      |
| `make ci`           | Full CI pipeline (lint + format-check + test) |
| `make bump-patch`   | Bump patch version (0.1.0 -> 0.1.1)           |
| `make bump-minor`   | Bump minor version (0.1.0 -> 0.2.0)           |
| `make bump-major`   | Bump major version (0.1.0 -> 1.0.0)           |
| `make tag-message`  | Generate tag message and create tag           |
| `make build`        | Build distribution package                    |
| `make publish`      | Run CI, build and publish to PyPI             |
| `make publish-test` | Run CI, build and publish to TestPyPI         |
| `make clean`        | Remove build artifacts and caches             |
| `make clean-venv`   | Remove Poetry virtualenv                      |

### Running Tests

```bash
# All tests with coverage
make test

# Quick run without coverage
make test-fast

# Full CI check before committing
make ci
```

### Publishing

```bash
# Test release
make publish-test

# Production release
make publish
```

Both targets run the full CI pipeline (lint, format-check, tests) before building and publishing.

## Companion Tools

- [manuscript-tools](https://pypi.org/project/manuscript-tools/) - Validation, sanitization and metrics for Markdown
  manuscripts. Install separately for linting capabilities.

## License

MIT
