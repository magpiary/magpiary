<p align="center">
  <img src="assets/magpiary-banner-on-dark.svg" alt="Magpiary. Saved is not the same as found." width="100%">
</p>

<p align="center">
  <a href="https://github.com/magpiary/magpiary/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/magpiary/magpiary?color=ff3d9a&label=release"></a>
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-5b4fe0"></a>
  <img alt="macOS 14+, Apple Silicon" src="https://img.shields.io/badge/macOS-14%2B%20%C2%B7%20Apple%20Silicon-0b0b1a">
  <img alt="No account, no telemetry" src="https://img.shields.io/badge/no%20account-no%20telemetry-2bb673">
</p>

<p align="center"><b>Your saved posts, kept on your own Mac, searchable by what you half remember.</b></p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#what-it-does">What it does</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#privacy">Privacy</a> ·
  <a href="#troubleshooting">Troubleshooting</a> ·
  <a href="https://magpiary.com">magpiary.com</a>
</p>

Share a reel, thread, video or link from your iPhone. Your Mac downloads it, transcribes it, reads it and files it into a private library you can search, browse and ask questions of. Nothing runs on a server. There is no account and no telemetry.

## How it works

```mermaid
flowchart LR
    A["📱 Share to Magpiary<br/>on your iPhone or Chrome"] --> B["💻 Your Mac downloads,<br/>transcribes and reads it"]
    B --> C["🗂️ A private library<br/>in ~/Magpiary"]
    C --> D["🔎 Search, piles, boards<br/>and Ask Magpiary"]
```

1. **Share.** Tap Share → Magpiary in any iPhone app, or save a page from Chrome. The phone queues links and hands them to your Mac over Wi-Fi.
2. **Understand.** The Mac downloads the post, transcribes speech and reads on-screen text locally, then writes a summary, key moments and tags.
3. **Find.** One search box blends words and meaning, so "that pasta video with the water trick" works.

## What it does

| | |
|---|---|
| **📥 Capture** | Instagram, Threads, YouTube, Reddit, X, LinkedIn and ordinary web pages, fetched logged out. Tracking is stripped from every link, and a link saved twice is one save. |
| **🧠 Understand** | Speech is transcribed on your Mac (whisper.cpp) and key frames and on-screen text are read there too (Apple Vision). Each save gets a summary, key moments, tags, named tools and places with their official links, and a Markdown note. |
| **🔎 Find** | Search that explains why a result matched and suggests spellings from your own library. Related posts, automatic Piles, and a Digest of what to revisit. |
| **💬 Ask** | Ask Magpiary answers questions from your library, using Claude Code, Codex or your own API key. |
| **👥 Share** | Boards you can share with friends, end-to-end encrypted, with no server of ours. |
| **🔒 Lock** | A hub lock with PIN and Touch ID. |
| **🤖 Agents** | AI agents can read the library through a CLI, an MCP server and a skill. Off until you switch it on. |

<details>
<summary><b>More about capture and AI</b></summary>

- **From your iPhone.** The phone keeps its own queue and hands it to your Mac when both are on the same Wi-Fi, even if the Mac was asleep. Each send is signed with a secret derived from the pairing key; the key itself is never sent.
- **From Chrome.** The extension saves pages from the desktop. Get it from the Chrome Web Store, or from Magpiary: Settings, Library & this Mac, Chrome, **Get the extension** copies it to `~/Magpiary/chrome-extension` and opens Chrome's extensions page (turn on Developer mode, then Load unpacked). Tick **Save what I see** (extension 0.1.5 or newer; the copy in Settings is always current, the Web Store copy follows its review) to keep a page exactly as it is on your screen, signed-in pages included. It opens on a Read tab and downloads as a PDF.
- **Instagram login.** Optional, and used only when you retry one blocked post yourself.
- **Smart mode** asks your own AI key (Gemini, OpenRouter, Claude or OpenAI) to write the summary from text and a few frames. **Private mode** uses no AI at all.
- **Phone access (early, off by default).** Settings → Phone can open your library on a paired iPhone over your home Wi-Fi. Turn it on only on a network you trust.

</details>

## Install

Needs a Mac with Apple Silicon (M1 or newer) on macOS 14 or later, an iPhone with Shortcuts, and about 1 GB free for the app and its models before your library.

**The Mac app, with no warning from macOS (easiest).** Paste this into the Terminal app. It downloads the app from GitHub, checks its checksum and opens it (macOS only warns about files a browser downloaded):

```sh
curl -fsSL https://raw.githubusercontent.com/magpiary/magpiary/main/install-app.sh | sh
```

The app then downloads about 720 MB of tools and models and opens the setup page in your browser, which walks you through pairing your iPhone. One Magpiary per Mac for now: do not install it for two accounts on the same Mac.

<details>
<summary><b>Other ways to install</b></summary>

**The disk image.** Download `Magpiary-0.1.7.dmg` from the [latest release](https://github.com/magpiary/magpiary/releases/latest), open it and drag Magpiary to Applications. The app is not signed with a paid Apple account, so macOS blocks the first open. Open Magpiary once, then go to System Settings > Privacy & Security, scroll down, click **Open Anyway** and enter your password.

**From Terminal.** The script installs for your user only (no password), downloads about 720 MB of tools and models, starts the background service and opens the setup page at `http://localhost:8765/`:

```sh
curl -fsSL https://raw.githubusercontent.com/magpiary/magpiary/main/install.sh | sh
```

See what is downloaded and why with `magpiary downloads`.

**Homebrew, the Mac app in one command** (opens with no macOS warning):

```sh
brew install --cask magpiary/tap/magpiary
```

**Homebrew, the command-line version only** (no app window):

```sh
brew install magpiary/tap/magpiary
magpiary models install && magpiary service install
```

</details>

Update with `magpiary update`. Remove with `magpiary uninstall` (your library stays unless you ask).

## Privacy

- Your library, media and notes live in one folder, `~/Magpiary`. Keys live in `~/.config/magpiary`, readable only by you.
- Videos never leave your Mac. In Smart mode only the caption, transcript and a few frames go to the AI service whose key you added. Private mode sends nothing.
- No analytics, no accounts, no relay. Stats refreshes are slow, logged out, and never use your login.
- The phone link for sending posts runs over your home Wi-Fi without encryption (HTTP). Pair on a network you trust.

## Limits and responsibility

- Downloading and archiving content may break a platform's terms of service or copyright rules. Save only what you are allowed to keep, and check each platform's terms. You are responsible for how you use Magpiary.
- Sites change often. Some posts (private, age-restricted, deleted) cannot be fetched logged out.
- Transcription is evaluated on English; other languages are untested.
- macOS and iPhone only.

## Troubleshooting

Run `magpiary doctor`. It checks the service, models, tools, keys and each site, and says what to do. The hub also has a Health check page and in-app Help.

## Develop

```sh
uv sync
uv run pytest -q
bash scripts/secret-scan.sh   # run before every push
```

Design decisions are in [docs/specs.md](docs/specs.md) and the project brief is in [CLAUDE.md](CLAUDE.md). Contributions are welcome through issues and pull requests. Please include tests and keep personal data out of fixtures.

## Licence

[MIT](LICENSE). Bundled fonts, emoji and scripts keep their own licences, in `src/magpiary/static`.
