"""The first-run page ships inside the app (packaging/app/installer) and uses the hub's own files."""

import re
from pathlib import Path

from magpiary import downloads

PAGE = Path(__file__).parent.parent / "packaging" / "app" / "installer"
STATIC = Path(__file__).parent.parent / "src" / "magpiary" / "static"


def test_every_download_has_short_words_on_the_page():
    script = (PAGE / "installer.js").read_text()
    about = script[script.index("const ABOUT"):script.index("const TOUR")]
    for entry in downloads.catalog():
        assert re.search(rf'"?{re.escape(entry.id)}"?:\s*\[', about), entry.id


def test_every_hub_file_the_page_asks_for_exists():
    html = (PAGE / "index.html").read_text() + (PAGE / "installer.js").read_text()
    wanted = set(re.findall(r"/static/([\w./-]+)", html))
    assert wanted >= {"hub.css", "indigo.css", "icon.svg", "art/land-c.webp"}
    assert all((STATIC / name).exists() for name in wanted)


def test_the_app_build_includes_the_page():
    script = (PAGE.parent / "build-app.sh").read_text()
    assert '"$HERE/installer"' in script and "InstallerWindow.swift" in script
