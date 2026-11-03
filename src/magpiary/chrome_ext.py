"""The Chrome extension that ships inside Magpiary: copied to a stable folder, because Chrome remembers where an
unpacked extension was loaded from. Used by `magpiary extension` and by the "Get the extension" button in Settings."""

import shutil
from importlib import resources
from pathlib import Path

from magpiary import config


def target() -> Path:
    return config.data_dir() / "chrome-extension"


def prepare() -> Path:
    """Copy the bundled extension into `target()` (replacing an older copy) and return that folder."""
    folder = target()
    shutil.rmtree(folder, ignore_errors=True)
    with resources.as_file(resources.files("magpiary") / "extension") as src:
        shutil.copytree(src, folder, ignore=shutil.ignore_patterns("__pycache__"))
    return folder
