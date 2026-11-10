# Changelog

Newest first. Plain words; the same notes are on each GitHub release.

## 0.1.7 (10 November 2026)

- **First open of the Mac app is clearer.** If Magpiary is opened from the disk image, the Desktop or Downloads, the window now says to move it to Applications first (with a way to carry on anyway), and the disk image says so too. When the background service can't be installed, the window shows the real reason instead of a generic message. Reopening the app after setup opens your library by itself.
- **Connect Instagram is one button.** Settings, AI & login has a Connect Instagram button that copies your login from Chrome and says how it went in place. If macOS refuses the background service, Open Terminal for me runs the step for you. No Terminal command to type.
- **Chrome extension setup, Welcome screen.** Show my code now shows the pairing code on the Welcome screen instead of sending you into Settings.
- **Shared boards: pages saved with Save what I see.** When you add such a page to a board you can tick Also share the page text I saved. Your friend then reads the text on their Mac even when the site (Behance, for example) won't let their Mac download it. Pictures stay on your Mac. Without the tick, they see a clear message saying what to ask for.
- **OpenRouter errors say why.** A request a model rejects (HTTP 400 or 422) is retried in plainer forms, then another key is tried, and a failed post shows the service's reason.

## 0.1.6 (10 November 2026)

- **Settings are simpler.** Six pages instead of a long list. "Saving posts" is now **Phone**, and "AI & digest" is now **AI & login** (Instagram login moved there). Chrome moved to Library & this Mac, and Shared boards joined Profile & boards. Ask Magpiary and AI agents keep their own pages. Explaining text sits behind an (i) hover, and old Settings links still work.
- **Instagram carousels save every slide.** A photo carousel whose embed is refused keeps its first slide and caption, and the rest are read from the open page when the Mac could only save part. Slides show once, with no repeated Read tab.
- **Threads photo carousels save every slide.**
- **Videos play on iPhones.** New downloads prefer H.264.
- **Chrome extension 0.1.6.** On LinkedIn, Pick a post now selects the one post you point at, not a feed tab or a hidden wrapper.
- **Phone access (new, off by default).** Settings, Phone has a switch that opens your library on a paired iPhone over your home Wi-Fi, with its own certificate and pairing code. It is early: turn it on only on a network you trust, and expect the phone layout to change.
- **Support Magpiary.** Settings, About has a Buy me a coffee link.

## 0.1.5 (5 November 2026)

- **Save what I see.** In the Chrome extension, tick it to keep a page exactly as it is on your screen: its text, its pictures and one screenshot of what you see, signed-in and member-only pages included. Nothing is saved from a page you did not tick it on. It works on any page and names no site.
- **Read tab and PDF.** A page saved this way opens on a Read tab with its words and pictures in order (rows and picture grids stay side by side), and **Download PDF** makes a PDF on your Mac in one click.
- **Posts show their website.** A post from any site shows that site's name and icon instead of "Other".
- **Signed phone sends.** Your iPhone Shortcut no longer sends its pairing key over Wi-Fi: it signs each send, and your Mac refuses anything unsigned, changed or more than ten minutes old. Install a new Shortcut (Settings, Saving posts, your phone, New install code) to use it; older Shortcuts keep working until you do, and Settings marks them.
- **macOS prompts say Magpiary.** Permission prompts name Magpiary, not Python. Help now lists every prompt Magpiary can cause and why.
- **A clearer Help page.** Chapters on the left that follow you as you read, links that really jump to their chapter, and new guides for Ask Magpiary, saving from Chrome, Save what I see, Deeper dive and backups.
- **Fixed: Featured no longer hides posts.** At medium and large tiles, three to four of your newest posts were missing from the wall.
- **Fixed:** the "Open the Nest" button was unreadable; the idle Nest button now matches Digest and Settings.
- **From the security review:** a website can no longer make your Mac start Chrome to draw PDFs, hidden page text is no longer captured, and several rare races in saving and summarising are closed.

## 0.1.4 (4 November 2026)

- Round-up posts keep every thing they recommend, each with its own link.
- Web pages give their whole text and pictures; script-drawn pages are drawn once by a browser on your Mac.
- Each post shows its shape and topic; suggested tags reuse yours.
- Long videos wait for Read it now; a video's own chapters become its key moments.
- Threads videos are saved and play again; a busy AI key hands the post to your next key.
- Search understands what you ask for.
- A new welcome guide for saving from Chrome or your iPhone.

Earlier versions: see the release pages on GitHub.
