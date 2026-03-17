# manuscripta

Book production pipeline for authors and self-publishers.

Multi-format export (PDF, EPUB, DOCX, HTML, Markdown), audiobook generation, translation, and manuscript tooling, powered by Pandoc.

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

## Configuration

### export-settings.yaml

Controls output formats, TOC behavior, and section ordering per book type (ebook, paperback, hardcover, audiobook).

### voice-settings.yaml

TTS configuration: language, voice, and sections to skip during audio generation.

### metadata.yaml

Pandoc metadata: title, author, date, language.

## Available Commands

### Export

| Command | Description |
|---------|-------------|
| `export-pdf` / `export-p` | Export PDF |
| `export-epub` / `export-e` | Export EPUB |
| `export-docx` / `export-d` | Export DOCX |
| `export-html` / `export-h` | Export HTML |
| `export-md` | Export Markdown |
| `export-all` | Export all formats |
| `export-all-with-cover` | Export all with cover |
| `export-pvp` | Print version (paperback) |
| `export-pvh` | Print version (hardcover) |

All export commands have a `-safe` variant (e.g. `export-pdf-safe`) that skips source preprocessing for fast, non-destructive draft builds.

### Audiobook

| Command | Description |
|---------|-------------|
| `manuscripta-audiobook` | Generate MP3 audiobook |

### Translation

| Command | Description |
|---------|-------------|
| `translate-en-de` | English to German (DeepL) |
| `translate-de-en` | German to English (DeepL) |
| `translate-book-en-de` | English to German (LMStudio) |
| `translate-book-de-en` | German to English (LMStudio) |

### Project Management

| Command | Description |
|---------|-------------|
| `manuscripta-init` | Initialize new book project |
| `create-chapters` | Create chapter files |
| `reorder-chapters` | Reorder and rename chapters |
| `manuscripta-tag` | Generate release tag message |

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

## Companion Tools

- [manuscript-tools](https://pypi.org/project/manuscript-tools/) - Validation, sanitization and metrics for Markdown manuscripts. Install separately for linting capabilities.

## License

MIT
