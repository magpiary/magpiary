# S1 — logged-out fetch rate

**Run:** 22 Oct 2026, the owner's Mac (M1 Pro), home connection, yt-dlp 2026.10.21, no cookies, serial with 3–8 s jitter. 18 real links the owner saved. No X links yet.
**Harness:** `spikes/S1/probe.py`; per-link data in `spikes/S1/results.jsonl` (cleaned URLs only).
**Caveat:** 18 links is a small sample, one run, one day, one IP. Treat rates as a first signal, not a guarantee.

## Result

| Source | Links | yt-dlp, logged out | Notes |
|---|---|---|---|
| Instagram (4 reels + 1 `/p/` post) | 5 | **5/5** (4 first try, 1 after a retry) | The failed one returned "empty media response", then succeeded on an immediate retry, so treat it as transient. Metadata, caption and formats came back for all. |
| YouTube Shorts | 5 | **5/5** | Caption, duration, 89–186 formats each. A JS-runtime warning appeared (see below). |
| Threads | 5 | **0/5** | yt-dlp 2026.10.21 has no Threads extractor ("Unsupported URL"). Not a block: the pages themselves load (below). |
| Reddit | 3 | **0/3** | yt-dlp: "Account authentication is required". See below. |
| X | 0 | not tested | the owner isn't using X yet. |

## Findings

1. **Instagram logged-out works** for these 5 (video posts). That supports non-negotiable #5. The sample is small, so keep the opt-in cookie fallback and the retry-once rule.
2. **Instagram metadata has no `duration`** in yt-dlp's output. Get duration from `ffprobe` after download.
3. **Share-link expansion works logged out.** All 5 `threads.com/share/…` and all 3 `reddit.com/r/…/s/…` links resolved to full post URLs with a plain redirect-following GET (HTTP 200). The Mac-side expander in the handover is viable.
4. **Threads needs its own fetcher.** A plain GET of a Threads post page returned 200 (~570 KB). It had a 482-character `og:description` and embedded reply-count data. So post text, and probably replies, are reachable logged out from the page. This is S4's job; whether the page embeds the replies themselves, and how stable the format is, are not yet checked.
5. **Reddit blocks logged-out scripted access.** `.json` returned 403 and `old.reddit.com` returned a bot-check page ("Welcome to Reddit", CAPTCHA markers). We do not bypass CAPTCHAs. Routes still to test: (a) a headless browser, which may or may not pass the check; (b) Reddit's official API with a free app registration per user (read-only, OAuth, no password in our code), which would also give full comment trees; (c) the user's browser cookies as the opt-in fallback. This means Reddit is probably the source that needs the most setup, which matters for the "five minutes to install" goal.
6. **YouTube warns about a missing JavaScript runtime.** yt-dlp enables only `deno` by default. Metadata worked anyway on all 5, but formats may be incomplete. the owner has `node` and `bun` but not `deno`. The installer should provide a runtime or pass `--js-runtimes`.
7. **Speed:** 1.5–4.6 s per link, so no throttling problem at this volume.

## Requirement from the owner, 22 Oct 2026

For Threads, X and Reddit the discussion matters as much as the post: replies and comments carry the useful information. So the pipeline needs, for those sources, (a) the post and as much of the reply/comment tree as can be read, and (b) a TL;DR of the discussion (consensus, disagreements, corrections, notable links). For Reddit, the post body, media and comments are all in scope. How much each platform lets us read logged out is the open question; the findings above are the first data.

## What this changes

- `Post` gets an optional `discussion` (replies/comments with author, score, depth, text) and the Brain gets a discussion summary field.
- Reddit moves from "adapter we get free from yt-dlp" to "adapter with its own access route", with the official API as the leading candidate.
- Threads is the next thing to prove (S4): parse the page, extract text, images and replies.

## Not yet tested

X; carousels; private or deleted posts; behaviour after many requests (rate limiting at backfill volume); the Reddit headless-browser and API routes; whether Instagram's transient "empty media response" becomes more frequent at volume.
