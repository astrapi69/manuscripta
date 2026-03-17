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
    """Load a YAML file and return its contents as a dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
