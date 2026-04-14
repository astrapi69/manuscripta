# Migrating to manuscripta v0.8.0

## Why this release exists

manuscripta v0.1.0 through v0.7.0 shipped a latent bug: PDF builds succeeded
but images were **silently dropped** from the output. The root cause was
inherited from the extraction out of `write-book-template`: the parent
template forced `os.chdir()` into the project root at module-import time, so
`--resource-path=os.path.abspath('./assets')` always resolved to the right
place. The library dropped the `chdir` (correctly — libraries must not mutate
process state) but kept the `./assets` literal, so image resolution now
depends on the caller's current working directory with no validation and no
error when it is wrong.

v0.8.0 replaces the implicit cwd contract with an **explicit `source_dir`
parameter** on the public library API, surfaces Pandoc warnings instead of
swallowing them, and ships a typed exception hierarchy.

## What changed

### Public library API

Before (v0.7.x): no first-class library entry point — callers imported
`manuscripta.export.book` and relied on module globals + cwd.

After (v0.8.0):

```python
from pathlib import Path
from manuscripta.export.book import run_export

run_export(
    Path("/abs/path/to/book-project"),   # REQUIRED; no cwd fallback
    resource_paths=[Path("/abs/shared/assets")],  # optional extras
    formats="pdf",
    strict_images=True,                  # default; raise on missing images
)
```

`source_dir` is **required**; calling `run_export()` without it raises
`TypeError` at call time. The library never calls `os.chdir` — child
processes are launched with `cwd=source_dir`, not by mutating the parent
process.

### Exception hierarchy

```python
from manuscripta import (
    ManuscriptaError,          # base class — catch-all for any library failure
    ManuscriptaLayoutError,    # source_dir missing manuscript/ | config/ | assets/
    ManuscriptaImageError,     # strict_images=True + Pandoc couldn't fetch a resource
    ManuscriptaPandocError,    # Pandoc subprocess exited non-zero (any reason)
)
```

Catching `ManuscriptaError` is sufficient to handle any library-raised
failure; the three subclasses exist so callers that need to distinguish
layout mistakes, image-resolution failures, and Pandoc crashes can do
so without parsing messages.

`ManuscriptaImageError.unresolved` is a `list[str]` of the image
paths/URIs that Pandoc reported. `ManuscriptaPandocError` exposes
`returncode: int`, `stderr: str`, and `cmd: list[str]` for diagnostic
use; its `__str__()` format is considered diagnostic rather than
contractual per [ADR-0004](docs/decisions/0004-exception-strings-not-api.md)
— pin behaviour on the attributes, not on the rendered text.

### CLI

The CLI entry points (`export-pdf`, `export-epub`, `manuscripta-export`,
etc.) gained two flags:

- `--source-dir PATH` — the book repo root. Defaults to `Path.cwd()` **only
  at the CLI layer**. The library itself has no fallback.
- `--no-strict-images` — opt out of raising on unresolved images (default
  is strict).
- `--resource-path PATH` — repeatable; extra directories appended to
  Pandoc's `--resource-path`.

A build launched from the book project root with no new flags behaves the
same as before (except it now errors instead of silently dropping images).

### Behavior changes that can surface as new errors

- Running a CLI entry point outside a valid book layout now raises
  `ManuscriptaLayoutError` immediately, naming the missing subdirectories.
  In v0.7.x this silently proceeded and produced a broken PDF.
- A Markdown file that references a missing image now aborts the build
  with `ManuscriptaImageError`. Pass `--no-strict-images` (CLI) or
  `strict_images=False` (library) to restore the lenient behavior.

## Minimal migration snippet

### CLI consumers (e.g. the `write-book-template` Makefile)

No change required if the CLI is invoked from the project root. Optionally,
make the contract explicit:

```make
pdf:
	poetry run export-pdf --source-dir=$(CURDIR)
```

### Library consumers

```python
# Before (v0.7.x) — worked only because cwd happened to be the project root
from manuscripta.export.book import main as export_main
import sys
sys.argv = ["export-pdf", "--format", "pdf"]
export_main()

# After (v0.8.0) — explicit, works from any cwd
from pathlib import Path
from manuscripta.export.book import run_export

run_export(Path(__file__).parent, formats="pdf")
```

## Before/after evidence

Fixture: a consumer project with a single 8×8 PNG referenced as
`![pic](images/pic.png)`, built while the process cwd is the **parent** of
the project (the scenario that silently failed in v0.7.x).

### Before (v0.7.x Pandoc invocation replayed)

```
[WARNING] Could not fetch resource images/pic.png: replacing image with description

$ pdfimages -list before.pdf
page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
(no rows — no image embedded)
```

### After (v0.8.0 `run_export(source_dir=...)`)

```
$ pdfimages -list after.pdf
page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio
--------------------------------------------------------------------------------------------
   1     0 image       8     8  rgb     3   8  image  no         8  0    72    72   14B 7.3%
```

The image is embedded in the v0.8.0 output.
