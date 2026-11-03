# M7 handover: the real hub

Written 24 Oct 2026, for the session that starts M7. Read this first, then `docs/specs.md` (the source of truth) and
`CLAUDE.md`. Nothing for M7 is built yet.

## 1. Where things stand

| Milestone | State |
|---|---|
| M0 to M3.5 | Done: phone → Mac delivery, fetch and archive (6 sites), transcripts and frames on the Mac, summaries, links |
| M4 | Done: Related content and Piles (every save in a pile, made on the Mac) |
| M5 | Done: `install.sh`, Homebrew formula (published at M8), update banner, uninstall, first-run guide, `magpiary doctor` + Health check page, Instagram login fallback (`magpiary login connect`, per-post button) |
| M6 | Done: two modes, **Smart** (Gemini, OpenRouter, Claude, OpenAI keys, free or paid) and **Private** (no AI). Local AI deferred (plan in specs.md, "Later: a local AI model") |
| M7 | Next: this document |
| M8 | Later: open-source release (public repo, README, Homebrew tap with bottles, demo) |

Historical baseline: 353 tests passed. The local hub address is `http://localhost:8765/`.
Private library counts and AI-account preferences are omitted.

## 2. What M7 is

The M7 plan in `docs/specs.md` lists: semantic search, collections and type views,
ask-my-saves, a digest, correction learning, Tailscale access from the phone, and backfill from the Instagram data
export. Since then, two things changed the picture:

- **Collections are done** (Piles, M4), and **type views** are partly there (filters by source, tag, links).
- **The UI exploration** produced a chosen design, **C1+**, that the real hub should become (section 3).

**Proposed split** (to confirm tomorrow):
- **M7a, the hub merge:** the C1+ design becomes the real hub, page by page, with nothing lost.
- **M7b, search by meaning:** the meaning model from Piles already gives every save two meaning fingerprints, so a
  search can find saves by idea, not just by word. Cheap to add once the new search box exists.
- **M7c and later, decided one by one:** ask-my-saves (questions answered from your library; uses AI quota),
  a digest, correction learning, Tailscale (open the hub from your phone away from home), Instagram export backfill.

## 3. The UI exploration (what is being merged)

Lives in `docs/ui-directions/`: mockups only, separate from the real hub (`src/magpiary/hub.py`).

- **Chosen design:** `c1-plus.html` (with `c1-welcome.js`, `c1-motion.js`, shared `data.js`, `c-common.css/js`).
  Other files (`a-reading-room`, `b-console`, `c-wall`, `c1-gallery`, `c2-cinema`, `c3-studio`) are rejected
  alternatives, kept for reference.
- **Preview:** from Terminal, `cd docs/ui-directions && python3 -m http.server 8790`, then open
  `http://localhost:8790/c1-plus.html`. The `thumbs/` folder holds real thumbnails and is git-ignored (personal).
- **Stack (decided):** server-rendered HTML from the Python service, plain JavaScript modules, GSAP + Flip vendored
  in the repo (no CDN, no build step, no React/Next/Tailwind). Revisit (Preact + Vite) only if the hub's own
  JavaScript passes about 3,000-4,000 lines.

**Decided in C1+:**
- Bright gallery, same-size square tiles, three tile sizes. Piles / Everything switch. Time sections (Today, This
  week, Earlier). The wall heading rotates through 7 lines, with no item count.
- Top bar in three tiers: add a post via the search box | Library · Archive · Trash | sizes, the Nest (egg-in-nest
  icon) and Settings, all 40 px. A quiet dark "on the go" strip opens the Nest. The Nest holds what the Activity
  page holds today (progress, pause/resume, waiting items).
- A post opens in one near-full-screen card: video about 40% wide at near full height, info 60%, in tabs
  (Summary · Links · Related · Details). Caption first in Summary (short = large, long = folded); counts and Refresh
  under the title. No "More like this" on tiles.
- No AI key: tiles stay full colour (source-coloured label, caption as title, "✦ Summarise" badge).
- First run: a guided full-screen setup (welcome with privacy, pair the phone with live checks, choose Smart or
  Private, live first share). No sample wall.
- Boxed layout above 1920 px wide, with a width setting. Light and dark themes.

**The product moved on after the last mockup sync** (these exist in the real hub but not in C1+ yet):
- Smart / Private panel, OpenRouter, Claude and OpenAI keys with a model choice per key.
- The update banner, the Health check page, the Instagram login panel and the "Try with my Instagram login" button.
- The first-run guide as a checklist page (`/welcome`), not yet the full-screen guided setup.
- Piles revised: every save in a pile, subtitles, "N new", Regroup.

## 4. How the merge would work (proposal)

1. **Gap audit (me).** Map every C1+ screen and state to the real feature behind it, and every real feature to its
   place in C1+. The output is a short list: what matches, what the design lacks, and where the two disagree.
2. **Decisions on the gaps (you).** One round of clickable questions: for each disagreement, design or product wins.
3. **Foundations (me).** The design's colours, type, spacing and themes as shared styles in the hub; GSAP vendored;
   `hub.py` (about 1,100 lines today) split into smaller page modules so the merge stays readable.
4. **Page by page (me), each followed by your review:**
   1. The top bar and the wall (tiles, sizes, Piles/Everything, time sections, filters, search).
   2. The post card (video and tabs).
   3. The Nest (replaces the Activity page and the live strip).
   4. Settings (modes, keys, login, health check, appearance).
   5. The first-run guided setup (replaces the `/welcome` checklist).
   6. Pile pages, Archive and Trash.
5. **Motion and polish (me):** GSAP transitions, reduced-motion support, phone width, keyboard use, both themes.
6. **Final pass together** on your real library, then the old pages are removed.

Each page is switched to the new design only when it does everything the old one did, so the hub keeps working the
whole time. Tests are updated as each page moves.

## 5. When you come in, and when I work alone

| When | You | Me |
|---|---|---|
| Start of the session | Answer the planning questions (section 6) | Ask them, then write the M7 plan into specs.md |
| After the gap audit | Decide each disagreement (design or product wins) | Prepare the list with screenshots |
| After each page (5 or 6 times) | Look at it on your real library in the browser, approve or note tweaks (a few minutes each) | Build, test, deploy, show screenshots, then apply your tweaks |
| New pages the mockup never had (Health check, login, keys) | Say whether you want to see a mockup first or let me design them in the C1+ style | Design them to match |
| End | One full pass, including on your phone if Tailscale is in scope | Remove the old pages, update the spec |

Between those points I work without stopping you: building, testing, checking both themes and phone width, and
keeping every existing feature working.

## 6. Questions for tomorrow's planning round

1. Confirm the split: M7a (hub merge) first, then M7b (search by meaning), then the rest one by one?
2. Where does the merge happen: in this project session, with the exploration session stopping? Or does the
   exploration session keep refining mockups, with this session following it?
3. For pages C1+ never drew (Health check, Instagram login, keys and models, update banner): mockup first, or design
   them directly in the C1+ style?
4. Should the new hub replace the old one page by page (recommended), or be built side by side under a new address
   and switched over all at once?
5. Search by meaning: blended into the one search box (recommended), or a separate "by idea" switch?
6. Of the remaining M7 items (ask-my-saves, digest, correction learning, Tailscale, Instagram export backfill), which
   matter now, and which wait for M8 or later?
7. How many review points do you want: after every page (about 6), or fewer, larger ones?

## 7. Things to know

- **Ports:** the hub is on 8765; the mockup preview uses 8790; another app on this Mac uses 8799.
- **Tests assert page text,** so each moved page updates its tests in the same step.
- **Never spend the owner's AI quota on tests** without asking; test on one or two items, not the whole library
  (see memory, "Spend limits carefully").
- **Memory notes to read:** UI direction (decisions above), AI modes, Move faster, Spend limits carefully.
- **Deploying:** `uv tool install --reinstall .` then `~/.local/bin/magpiary service install`.
