"""Configuration loading for manuscripta.

All config files are loaded relative to the current working directory,
which is expected to be the book repository root.
"""

from pathlib import Path
from typing import Any, Optional

import yaml


CONFIG_DIR = Path("config")
EXPORT_SETTINGS_FILE = CONFIG_DIR / "export-settings.yaml"
VOICE_SETTINGS_FILE = CONFIG_DIR / "voice-settings.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file whose top-level node is a mapping and return it as a
    dict; an empty document gives an empty dict.

    Raises ValueError, naming the file, when the top-level node is anything
    else (a sequence or a scalar).
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: the top-level YAML node must be a mapping, "
            f"not {type(data).__name__}"
        )
    return data


def load_export_settings(path: Optional[Path] = None) -> dict[str, Any]:
    """Load export settings from YAML. Returns empty dict if file not found."""
    target = path or EXPORT_SETTINGS_FILE
    if target.exists():
        return load_yaml(target)
    return {}


def load_voice_settings(path: Optional[Path] = None) -> dict[str, Any]:
    """Load voice/TTS settings from YAML. Returns empty dict if file not found."""
    target = path or VOICE_SETTINGS_FILE
    if target.exists():
        return load_yaml(target)
    return {}
