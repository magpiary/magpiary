# macOS permissions Magpiary can cause

Every macOS prompt Magpiary can trigger, why, and when. **Any change that adds a new one (a new system tool, a new
folder, a new kind of network use, a browser launch) must add a row here and a line to Help → Privacy → "macOS
permission prompts" (`src/magpiary/help.py`) in the same commit.**

Who macOS names: the background service runs through a small launcher inside a bundle called Magpiary
(`src/magpiary/helper/hub.c`; in the DMG it is `Magpiary.app/Contents/MacOS/magpiary-hub`; other installs build
`~/.config/magpiary/Magpiary.app` once at `magpiary service install`). macOS names the app responsible for a process,
so prompts from the hub and everything it starts say **Magpiary** with its icon. Without Apple's command line tools
the launcher can't be built and prompts say **Python 3.12** (same request). Rebuilding the launcher (only when its
source or icon changes) makes macOS ask again, because grants belong to that exact build.

| Prompt | Triggered by | When | If refused |
|---|---|---|---|
| Access data from other apps / App Management | Headless Chrome, Chromium, Edge or Brave (`reader.make_pdf`, `sources.chrome_render`), fresh empty profile, network shut for PDFs | First Download PDF; first page that needs a browser to draw it | PDF opens the print-ready page (Save as PDF); script-made pages keep their logged-out text |
| Accept incoming network connections | The receiver listening on the local network (`magpiary serve`, 0.0.0.0) | Only with the macOS firewall on | The iPhone can't send over Wi-Fi; the Chrome extension (localhost) still works |
| Notifications (named "Script Editor") | `osascript display notification` (`digest.notify`) | First digest note | No note; the digest is still made |
| Terminal: data from other apps; keychain "Chrome Safe Storage" | `magpiary login connect`, run by the owner in Terminal | Only when connecting a site login | No login copy; posts stay logged out |

Checked and not prompting: the Wi-Fi name (`networksetup`, macOS hides it rather than asking), `caffeinate`,
`launchctl`, `open`, `shortcuts sign`, `sips`/`iconutil`/`codesign` (building the launcher), files under `~/Magpiary`
and `~/.config/magpiary` (not protected folders; the service refuses to run from Documents, Desktop or Downloads).
Touch ID for the hub lock and the microphone for spoken questions are asked by the browser, not by Magpiary.
