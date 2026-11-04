"""Where Magpiary keeps things. Both folders can be moved with an environment variable (tests do)."""

import os
from pathlib import Path


def data_dir() -> Path:
    """The visible folder with the database (later media and notes)."""
    return Path(os.environ.get("MAGPIARY_HOME") or Path.home() / "Magpiary")


def config_dir() -> Path:
    """Settings and secrets; keys in here are mode 0600."""
    return Path(os.environ.get("MAGPIARY_CONFIG") or Path.home() / ".config" / "magpiary")


def db_path() -> Path:
    return data_dir() / "magpiary.db"


def load_json(path: Path, default=None):
    """A JSON file of the library, or `default` when it is missing or broken (one reader for every module; not cached)."""
    import json

    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default
