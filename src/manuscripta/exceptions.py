"""Exception hierarchy for the manuscripta library.

All library-specific exceptions inherit from :class:`ManuscriptaError` so that
consumers can catch any library failure with a single ``except`` clause while
still being able to distinguish specific failure modes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


class ManuscriptaError(Exception):
    """Base class for all manuscripta-raised exceptions."""


class ManuscriptaLayoutError(ManuscriptaError):
    """Raised when ``source_dir`` is missing expected subdirectories, does
    not exist, or is not a directory.

    Attributes:
        source_dir: The path that was checked.
        missing:    Names of the missing subdirectories (possibly empty).
        reason:     One of ``"nonexistent"``, ``"not_a_directory"``, or
                    ``None`` (the default, meaning subdirs are missing).
    """

    def __init__(
        self,
        source_dir: Path | str,
        missing: Iterable[str] | None = None,
        reason: str | None = None,
    ) -> None:
        self.source_dir = Path(source_dir)
        self.missing = list(missing) if missing else []
        self.reason = reason
        if reason == "nonexistent":
            msg = f"manuscripta: source_dir {self.source_dir!s} does not exist"
        elif reason == "not_a_directory":
            msg = (
                f"manuscripta: source_dir {self.source_dir!s} is not a directory"
            )
        else:
            msg = (
                f"manuscripta: source_dir {self.source_dir!s} is missing "
                f"required subdirectories: {', '.join(self.missing)}"
            )
        super().__init__(msg)

    def __reduce__(self):
        return (self.__class__, (self.source_dir, self.missing, self.reason))


class ManuscriptaPandocError(ManuscriptaError):
    """Raised when the Pandoc subprocess exits with a non-zero status.

    Attributes:
        returncode: Pandoc's exit code.
        stderr:     The stderr text captured from Pandoc (may be empty).
        cmd:        The argv that was executed.
    """

    def __init__(self, returncode: int, stderr: str, cmd: list[str] | tuple[str, ...]) -> None:
        self.returncode = returncode
        self.stderr = stderr or ""
        self.cmd = list(cmd)
        # Surface the most diagnostic line of stderr in the message.
        snippet = self.stderr.strip().splitlines()[-5:]
        super().__init__(
            f"manuscripta: pandoc failed with exit code {returncode}.\n"
            + "\n".join(snippet)
        )

    def __reduce__(self):
        return (self.__class__, (self.returncode, self.stderr, self.cmd))


class ManuscriptaImageError(ManuscriptaError):
    """Raised when Pandoc reports unresolved image resources and
    ``strict_images=True``.

    Attributes:
        unresolved: List of image paths/URIs that Pandoc could not fetch.
    """

    def __init__(self, unresolved: Iterable[str] | None = None) -> None:
        self.unresolved = list(unresolved) if unresolved else []
        super().__init__(
            f"manuscripta: Pandoc could not resolve "
            f"{len(self.unresolved)} image resource(s): "
            f"{', '.join(self.unresolved)}"
        )

    def __reduce__(self):
        return (self.__class__, (self.unresolved,))
