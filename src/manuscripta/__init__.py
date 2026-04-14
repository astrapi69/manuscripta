"""manuscripta - Book production pipeline for authors and self-publishers."""

from manuscripta.exceptions import (
    ManuscriptaError,
    ManuscriptaImageError,
    ManuscriptaLayoutError,
    ManuscriptaPandocError,
)

__version__ = "0.1.0"

__all__ = [
    "ManuscriptaError",
    "ManuscriptaImageError",
    "ManuscriptaLayoutError",
    "ManuscriptaPandocError",
    "__version__",
]
