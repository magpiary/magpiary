# S4 — text-post sources: Threads and Reddit, with discussion

**Run:** 22 Oct 2026, the owner's Mac, home connection, no cookies, no account. First pass, tiny sample (2 Threads posts fetched, 1 opened in a browser; 3 Reddit posts, 1 full RSS success). Scripts were throwaway and are not in the repo.
**Rules kept:** no CAPTCHA or bot-check bypass; nothing logged in; fetched text treated as data.

## Threads

Three levels of access, cheapest first:

| Level | How | What you get | Cost |
|---|---|---|---|
| 1. Plain page request | One GET of the post URL (any browser-like User-Agent) | **Full post text** (in `og:description`, including line breaks), author, one preview image URL. Verified on 2 posts. | ~570 KB, no dependencies |
| 2. Real browser, logged out | Load the page and read the rendered text | Level 1 plus **replies** (author, age, like counts; about 10 on the test post), the author's reply to commenters, links shown in replies, and "related threads" by the same author. Verified in the built-in browser; a "Log in" button is shown but nothing is gated. | A headless browser at install time (Chromium, 100+ MB) |
| 3. Embedded JSON | Parse the `<script type="application/json">` blobs | Not useful: those 30 blobs are site configuration. The post and replies are **not** in the static HTML and load client-side. | n/a |

Notes:
- Static HTML contains zero reply data, so level 1 can never produce a discussion summary.
- Image/video: only a single `og:image` was seen; carousels and videos on Threads are untested. yt-dlp 2026.10.21 has no Threads extractor.
- Browser output mixes the post, replies and other threads by the same author on one page, so the parser has to separate them (the reply list ends at a "Related threads" heading).
- Reply count seen was small (about 10 of a post with 46 shown replies in the counters). How far a logged-out page loads before it wants a login (scroll depth, "load more") is untested.

**Recommended Threads adapter:** level 1 for every post, level 2 (headless browser) when the post has replies worth reading, with a clean fallback to level 1 if the browser step fails.

## Reddit

| Route | Result | Notes |
|---|---|---|
| yt-dlp, logged out | ✖ "Account authentication is required" (S1, 3/3) | |
| `.json` endpoint | ✖ 403 | |
| `old.reddit.com` HTML | ✖ Bot-check page | Not pursued; we do not bypass CAPTCHAs. |
| Built-in browser pane | ✖ Refused to open reddit.com ("safety restrictions") | This is a limit of this tooling, not evidence about Reddit. Headless-browser route therefore untested. |
| **Post RSS feed** (`<post-url>/.rss`) | ✔ **200** on 1 of 3 attempts; the other 2 returned **429** | The success returned the **post (1,937 chars of body) plus 87 comments in one 76 KB Atom response**, with author and text per entry. See limits below. |
| Official API (OAuth, per-user free app) | untested | Needs the owner to register an app; would add scores, nesting, "load more", and likely media info. |

RSS limits seen:
- **Rate limiting is tight:** 429 after a couple of requests inside about a minute with a custom User-Agent. A queue that fetches Reddit serially with long gaps (and backs off on 429) is required; at backfill volume this will be slow.
- **Comments come back as a flat list** with ids and authors. No score, no clear parent/depth was checked for. Order and truncation (88 entries is probably a cap) are unverified; long threads are probably cut off.
- Image link (`i.redd.it`) appeared in the post entry of one post. Video posts (`v.redd.it`) are untested, and yt-dlp needs authentication for Reddit, so Reddit **video** download is an open problem.
- The three posts' types (text, image, video) were not recorded, so no per-type claim is made.

**Recommended Reddit adapter (provisional):** RSS as the default (no account, gets post body and most comments), serial with long jitter and back-off; optional official-API mode (user registers a free read-only app) for scores, full trees and media; the user's browser cookies stay the last-resort fallback for video. Decide after testing the API route and one `v.redd.it` video.

## What this means for the design

1. **`Post.discussion` is real.** Threads and Reddit both expose enough discussion to summarize, but via different mechanisms, with different completeness. The record needs a field saying how complete the discussion is (`complete`, `partial: N of ~M`, or `none`), so the TL;DR doesn't overclaim.
2. **Some adapters need a headless browser.** Threads replies require it. That means the installer downloads a browser (Chromium via Playwright, or reuses the user's installed Chrome). This must be explained in setup, and fall back gracefully when absent.
3. **Reddit is rate-limited to a crawl.** Treat Reddit fetches as a slow lane in the queue, separate from Instagram and YouTube.
4. **Discussion TL;DR input** per source: post text; top-level replies and the author's own replies; counts of likes/scores where available.

## Not yet tested

Threads: videos, carousels, posts with many replies (pagination), posts from private accounts, deleted posts, rate limits over many fetches. Reddit: official API, a `v.redd.it` video, nesting and scores, and whether RSS is capped at about 88 entries. X: nothing.
