"""Smoke test for phone access: an isolated hub (temp folders, free ports, nothing of the real library) with the HTTPS door
open, driven by curl the way a phone would. Run: uv run python scripts/smoke/phone-access.py
Checks: trusted-CA connection works, unpaired and revoked phones are refused, Settings/Ask/lock are refused for a paired
phone, an AI action needs its confirm tap, and the CA key and server key are mode 0600. Spends no AI quota."""

import os
import stat
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="magpiary-smoke-"))
os.environ["MAGPIARY_CONFIG"], os.environ["MAGPIARY_HOME"] = str(tmp / "config"), str(tmp / "home")

from magpiary import access  # noqa: E402
from magpiary.receiver import make_server  # noqa: E402
from magpiary.secure_door import SecureServer  # noqa: E402
from magpiary.store import Store  # noqa: E402

store = Store(tmp / "smoke.db")
store.set_setting("setup_done", "1")
store.set_setting(access.SETTING, "1")
primary = make_server(store, "127.0.0.1", 0)
names = [access.NAME, "smoke-mac.local"]
cert, key = access.server_files(names)
secure = SecureServer(("127.0.0.1", 0), primary, names, str(cert), str(key))
for s in (primary, secure):
    threading.Thread(target=s.serve_forever, daemon=True).start()
ca = tmp / "ca-public.pem"
ca.write_bytes(access.ca_pem())
base = f"https://{access.NAME}:{secure.server_port}"
resolve = f"{access.NAME}:{secure.server_port}:127.0.0.1"
fails = []


def curl(path, cookie="", data=None):
    cmd = ["curl", "-s", "-o", "-", "-w", "\n%{http_code}", "--cacert", str(ca), "--resolve", resolve, "--max-time", "8"]
    if cookie:
        cmd += ["-H", f"Cookie: {access.COOKIE}={cookie}"]
    if data is not None:
        cmd += ["-d", data]
    cmd.append(base + path)
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    body, _, code = out.rpartition("\n")
    return int(code or 0), body


def check(label, ok):
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        fails.append(label)


for p in (access.access_dir() / "ca.key", access.access_dir() / "server.key"):
    check(f"{p.name} is mode 0600", stat.S_IMODE(p.stat().st_mode) == 0o600)
check("unpaired phone refused", curl("/")[0] == 401)
token = primary.hub.devices.new_pair_token()
proc = subprocess.run(["curl", "-s", "-i", "--cacert", str(ca), "--resolve", resolve, "-d", "name=Smoke phone", f"{base}/phone/pair/{token}"],
                      capture_output=True, text=True).stdout
cookie = next((ln.split("=", 1)[1].split(";")[0].strip() for ln in proc.splitlines() if ln.lower().startswith("set-cookie: " + access.COOKIE.lower())), "")
check("pairing gives a key", bool(cookie))
check("paired phone opens the library", curl("/", cookie)[0] == 200)
for page in ("/settings", "/settings/ai", "/ask", "/doctor"):
    check(f"phone refused {page}", curl(page, cookie)[0] == 403)
csrf = primary.hub._csrf
for path in ("/hub/keys/add", "/hub/lock/off", "/hub/settings/mode", "/hub/ask/send"):
    check(f"phone refused POST {path}", curl(path, cookie, f"csrf={csrf}")[0] == 403)
code, body = curl("/hub/again", cookie, f"csrf={csrf}&id=1")
check("AI action asks for the confirm tap", code == 200 and "Use your AI?" in body)
primary.hub.devices.revoke(primary.hub.devices.active()[0]["id"])
check("revoked phone refused", curl("/", cookie)[0] == 401)
check("a stranger's wrong CA is not trusted", subprocess.run(["curl", "-s", "--resolve", resolve, "--max-time", "5", base + "/"],
                                                             capture_output=True).returncode != 0)
print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
