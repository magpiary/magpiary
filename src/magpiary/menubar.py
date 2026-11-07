"""The menu bar icon shown while phone access is on (a tiny separate process, started and stopped by the phone door).

It only reads: it opens the database read-only, shows how many phones are paired, and a click opens Settings in the
browser. It cannot change anything, and it quits by itself when access is switched off or the hub goes away.
"""

import subprocess
import sys

from magpiary import access
from magpiary.store import Store

POLL = 5  # seconds


def summary(store) -> tuple[bool, str]:
    """(access is on, the line for the menu)."""
    if not access.enabled(store):
        return False, "Phone access is off"
    n = _count(store)
    return True, f"Phone access is on · {n} phone{'' if n == 1 else 's'} paired"


def _count(store) -> int:
    with store._lock:
        return store._db.execute("SELECT COUNT(*) FROM paired_devices WHERE revoked_at IS NULL").fetchone()[0]


def run(db_path: str, settings_url: str) -> None:  # pragma: no cover - needs a screen
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSImage, NSMenu, NSMenuItem, NSObject,
                        NSStatusBar, NSVariableStatusItemLength)
    from Foundation import NSTimer

    class Delegate(NSObject):
        def openSettings_(self, _):
            subprocess.run(["open", settings_url], check=False)

        def tick_(self, _):
            try:
                on, line = summary(Store(db_path, read_only=True))
            except Exception:  # noqa: BLE001  the hub is restarting: try again next time
                return
            if not on:
                NSApplication.sharedApplication().terminate_(None)
            self.header.setTitle_(line)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = Delegate.alloc().init()
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_("iphone", "Magpiary phone access is on")
    if image:
        item.button().setImage_(image)
    else:
        item.button().setTitle_("Phone")
    menu = NSMenu.alloc().init()
    header = menu.addItemWithTitle_action_keyEquivalent_("Phone access is on", None, "")
    header.setEnabled_(False)
    delegate.header = header
    opener = menu.addItemWithTitle_action_keyEquivalent_("Open phone settings…", "openSettings:", "")
    opener.setTarget_(delegate)
    item.setMenu_(menu)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(POLL, delegate, "tick:", None, True)
    delegate.tick_(None)
    app.run()


if __name__ == "__main__":  # pragma: no cover
    run(sys.argv[1], sys.argv[2])
