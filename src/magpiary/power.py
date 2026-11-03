"""The opt-in "stay awake while plugged in" switch.

Uses macOS's own `caffeinate -s`: it stops the Mac sleeping only while it is on the charger, and
never on battery. `-w <pid>` ties it to this process, so it ends when Magpiary stops. It does not
keep a laptop awake with the lid closed.
"""

import os
import subprocess
from collections.abc import Callable


def _spawn_caffeinate():
    return subprocess.Popen(["caffeinate", "-s", "-w", str(os.getpid())],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class KeepAwake:
    def __init__(self, spawn: Callable = _spawn_caffeinate):
        self._spawn = spawn
        self._proc = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """True if the Mac is now being kept awake (also when it already was)."""
        if self.running:
            return True
        try:
            self._proc = self._spawn()
        except OSError:
            self._proc = None
        return self.running

    def stop(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
                self._proc.wait()
            self._proc = None
