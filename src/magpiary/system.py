"""Small questions about this Mac. Every one fails soft: an empty answer, never an error."""

import re
import socket
import subprocess


def local_name() -> str:
    """The Mac's Bonjour name, e.g. my-macbook.local. The phone reaches the Mac by this name."""
    try:
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip() + ".local"
    except (OSError, subprocess.SubprocessError):
        pass
    return socket.gethostname()


def current_wifi_name() -> str:
    """A suggestion only: macOS often hides the network name from programs, and it can be a carrier label."""
    try:
        out = subprocess.run(["networksetup", "-getairportnetwork", "en0"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.match(r"Current Wi-Fi Network: (.+)", out)
    name = match.group(1).strip() if match else ""
    return "" if "redacted" in name.lower() else name
