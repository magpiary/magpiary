"""The Terminal installer installs one reviewed release, named by its exact commit, never a moving branch."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_installer_is_pinned_to_a_release_commit():
    text = (ROOT / "install.sh").read_text()
    commit = re.search(r'^RELEASE_COMMIT="([0-9a-f]*)"$', text, re.M)
    release = re.search(r'^RELEASE="([0-9.]+)"$', text, re.M)
    assert commit and len(commit.group(1)) == 40 and release
    assert "magpiary/magpiary@$RELEASE_COMMIT" in text and "git+https://github.com/magpiary/magpiary}" not in text
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert tuple(map(int, release.group(1).split("."))) <= tuple(map(int, version.split(".")))
