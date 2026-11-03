<p align="center">
  <img src="brand/logo/final/lockup-horizontal.svg" alt="Magpiary" width="360">
</p>

<p align="center"><b>Your saved posts, kept on your own Mac, searchable by what you half remember.</b></p>

Share a reel, thread, video or link from your iPhone. Your Mac downloads it, transcribes it, reads it, and files it into a private library you can search, browse and ask questions of. Nothing runs on a server; there is no account and no telemetry.

## What it does

**Capture**
- Share to Magpiary from any iPhone app. The phone queues links and hands them to your Mac when both are on the same Wi-Fi, even if the Mac was asleep.
- Sources: Instagram, Threads, YouTube, Reddit, X, LinkedIn and ordinary web pages, fetched logged out. An optional Instagram login is used only when you retry one blocked post yourself.
- A Chrome extension saves pages from the desktop. It comes with Magpiary: Settings, Phones, Chrome, **Get the extension** copies it to `~/Magpiary/chrome-extension` and opens Chrome's extensions page (turn on Developer mode, then Load unpacked).
- Tracking is stripped from every link, and a link saved twice is one save.

**Understand**
- Video stays on your Mac. Speech is transcribed locally (whisper.cpp), key frames and on-screen text are read locally (Apple Vision).
- Each save gets a summary, key moments, tags, named tools and places with their official links, and a Markdown note.
- Smart mode asks your own AI key (Gemini, OpenRouter, Claude or OpenAI) to write the summary from text and a few frames. Private mode uses no AI at all.

**Find and reuse**
- One search box blends words and meaning, explains why a result matched, and suggests spellings from your own library.
- Related posts, automatic Piles, and Boards you can share with friends (end-to-end encrypted, no server of ours).
- Ask Magpiary: questions answered from your library, with Claude Code, Codex or your own API key.
- A Digest of what to revisit, a most-popular / trending order, and a hub lock with PIN and Touch ID.
- AI agents can read the library through a CLI, an MCP server and a skill. This is off until you switch it on.

## Install

Requires macOS (Apple Silicon recommended), an iPhone with Shortcuts, and about 1 GB free for the app and its models before your library.

**The Mac app, with no warning from macOS (easiest).** Paste this into the Terminal app (it downloads the app from GitHub, checks its checksum and opens it; macOS only warns about files a browser downloaded):

```sh
curl -fsSL https://raw.githubusercontent.com/magpiary/magpiary/main/install-app.sh | sh
```

**Or the disk image.** Download `Magpiary-0.1.3.dmg` from the [latest release](https://github.com/magpiary/magpiary/releases/latest), open it and drag Magpiary to Applications. The app is not signed with a paid Apple account, so macOS blocks the first open. Open Magpiary once, then go to System Settings > Privacy & Security, scroll down, click **Open Anyway** and enter your password. The app then downloads about 720 MB of tools and models and opens the setup page in your browser. One Magpiary per Mac for now: do not install it for two accounts on the same Mac.

**Or from Terminal:**

```sh
curl -fsSL https://raw.githubusercontent.com/magpiary/magpiary/main/install.sh | sh
```

The script installs for your user only (no password), downloads about 720 MB of tools and models, starts the background service and opens the setup page at `http://localhost:8765/`, which walks you through pairing your iPhone. See what is downloaded and why with `magpiary downloads`.

Or with Homebrew, the Mac app in one command (opens with no macOS warning):

```sh
brew install --cask magpiary/tap/magpiary
```

Or the command-line version only, without the app window:

```sh
brew install magpiary/tap/magpiary
magpiary models install && magpiary service install
```

Update with `magpiary update`; remove with `magpiary uninstall` (your library stays unless you ask).

## Privacy

- Your library, media and notes live in one folder, `~/Magpiary`. Keys live in `~/.config/magpiary`, readable only by you.
- Videos never leave your Mac. In Smart mode only the caption, transcript and a few frames go to the AI service whose key you added. Private mode sends nothing.
- No analytics, no accounts, no relay. Stats refreshes are slow, logged out, and never use your login.
- The phone link runs over your home Wi-Fi without encryption (HTTP). Pair on a network you trust.

## Limits and responsibility

- Downloading and archiving content may break a platform's terms of service or copyright rules. Save only what you are allowed to keep, and check each platform's terms. You are responsible for how you use Magpiary.
- Sites change often; some posts (private, age-restricted, deleted) cannot be fetched logged out.
- Transcription is evaluated on English; other languages are untested.
- macOS and iPhone only. The Chrome extension is loaded manually and is not on the Chrome Web Store.

## Troubleshooting

Run `magpiary doctor`. It checks the service, models, tools, keys and each site, and says what to do. The hub also has a Health check page and in-app Help.

## Develop

```sh
uv sync
uv run pytest -q
bash scripts/secret-scan.sh   # run before every push
```

Design decisions are in [docs/specs.md](docs/specs.md); the project brief is in [CLAUDE.md](CLAUDE.md). Contributions are welcome through issues and pull requests; please include tests and keep personal data out of fixtures.

## License

[MIT](LICENSE). Bundled fonts, emoji and scripts keep their own licences, in `src/magpiary/static`.
