"""The Mac app's menu-bar panel: its page ships in the app, and /panel.json and /hub/panel/save feed it."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "packaging" / "app" / "panel"
STATIC = ROOT / "src" / "magpiary" / "static"


def test_every_hub_file_the_page_asks_for_exists_and_the_build_includes_it():
    html = (PAGE / "index.html").read_text() + (PAGE / "panel.js").read_text()
    assert all((STATIC / name).exists() for name in re.findall(r"/static/([\w./-]+)", html))
    script = (ROOT / "packaging" / "app" / "build-app.sh").read_text()
    assert '"$HERE/panel"' in script and "Panel.swift" in script


def test_uninstall_is_gone_from_the_panel():
    assert "ninstall" not in (PAGE / "panel.js").read_text()
