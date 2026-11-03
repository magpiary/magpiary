"""The owner's login to a site, borrowed from Chrome only when they ask (opt-in fallback, non-negotiable 5).

`magpiary login connect [site]`, run by the owner in Terminal, copies just that site's cookies out of Chrome once,
into a private file (Instagram: ~/.config/magpiary/instagram-login.txt; any other site: logins/<site>.txt; mode 0600).
It must run from Terminal: macOS guards other apps' data and lets the owner allow Terminal, but not the background
service (found 24 Oct, macOS 27). macOS asks at that moment, while the owner is there; the background never opens the
browser. A blocked post uses the copy only after the owner presses "Retry with my login" on it, and only for that
post's own site. The copy's contents are never shown, logged or printed.
"""

import os
import re
import subprocess
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from magpiary.config import config_dir
from magpiary.tools import Run, default_run, find

BROWSER = "chrome"
DEFAULT = "instagram.com"
DOMAINS = (DEFAULT,)
HEADER = "# Netscape HTTP Cookie File\n"
SETTING = "instagram_login_on"
TWO_PART = {"co", "com", "org", "net", "ac", "gov", "edu"}  # co.uk, com.au, ... : keep three labels


def site_of(url: str) -> str:
    """The site a login belongs to: the host without www, cut to its registrable part (behance.net, bbc.co.uk)."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in TWO_PART and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _valid(domain: str) -> str:
    domain = (domain or DEFAULT).strip().lower()
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+", domain):
        raise ValueError("That is not a site name. Use something like behance.net.")
    return domain


def login_path(domain: str = DEFAULT) -> Path:
    domain = _valid(domain)
    return config_dir() / ("instagram-login.txt" if domain == DEFAULT else f"logins/{domain}.txt")


def _setting(domain: str) -> str:
    return SETTING if domain == DEFAULT else f"login_on_{domain}"


def _private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    path.chmod(0o600)


def _ours(line: str, domain: str = DEFAULT) -> bool:
    host = line.split("\t", 1)[0].lstrip(".").removeprefix("#HttpOnly_").lstrip(".")
    return host == domain or host.endswith("." + domain)


def connect(store, run: Run = default_run, browser: str = BROWSER, domain: str = DEFAULT) -> str | None:
    """Copy the login to one site out of the browser. Returns an error to show, or None."""
    try:
        domain = _valid(domain)
    except ValueError as err:
        return str(err)
    binary = find("yt-dlp")
    if not binary:
        return "yt-dlp is not installed."
    scratch = config_dir() / "browser-cookies.tmp"
    _private(scratch, HEADER)
    try:
        # "--use-extractors none": read the browser's cookies and save them, without contacting any site
        result = run([binary, "--ignore-config", "--no-warnings", "--cookies-from-browser", browser,
                      "--cookies", str(scratch), "--use-extractors", "none", f"https://www.{domain}/"], 120)
        lines = [ln for ln in scratch.read_text().splitlines() if ln.strip() and not ln.startswith("# ") and _ours(ln, domain)]
    except (OSError, subprocess.SubprocessError):
        return "Could not read Chrome's cookies."
    finally:
        scratch.unlink(missing_ok=True)  # it held every site's cookies: never keep it
    if not lines or (domain == DEFAULT and not any("\tsessionid\t" in ln for ln in lines)):
        if result.returncode != 0 and "operation not permitted" in (result.stderr or "").lower():
            return ("macOS did not allow reading Chrome's data. Run this in the Terminal app and choose Allow when "
                    "asked, or turn Terminal on in System Settings → Privacy & Security → App Management.")
        if result.returncode != 0 and "keychain" in (result.stderr or "").lower():
            return "macOS did not allow access to Chrome's saved logins. Try again and choose Allow."
        return f"No {domain} login found in Chrome. Log in to {domain} in Chrome first, then try again."
    _private(login_path(domain), HEADER + "\n".join(lines) + "\n")
    store.set_setting(_setting(domain), date.today().isoformat())
    return None


def disconnect(store, domain: str = DEFAULT) -> None:
    domain = _valid(domain)
    login_path(domain).unlink(missing_ok=True)
    store.set_setting(_setting(domain), "")


def connected(store, domain: str = DEFAULT) -> str:
    """The day the login was copied, or "" when there is none."""
    try:
        domain = _valid(domain)
    except ValueError:
        return ""
    return store.get_setting(_setting(domain), "") if login_path(domain).exists() else ""


def cookie_header(domain: str) -> str:
    """The saved login as a Cookie header for a page fetch ("" when there is none or it has expired)."""
    try:
        path = login_path(domain)
        text = path.read_text()
    except (OSError, ValueError):
        return ""
    now, pairs = time.time(), []
    for ln in text.splitlines():
        fields = ln.split("\t")
        if len(fields) == 7 and not ln.startswith("# "):
            expires = fields[4]
            if expires.isdigit() and int(expires) and int(expires) < now:
                continue
            pairs.append(f"{fields[5]}={fields[6]}")
    return "; ".join(pairs)
