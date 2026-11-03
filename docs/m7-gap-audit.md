# M7a gap audit: C1+ against the real hub

Written 24 Oct 2026. Compares the chosen mockup (`docs/ui-directions/c1-plus.html`, `c1-welcome.js`) with the real
hub (`hub.py`, `hub_piles.py`, `hub_welcome.py`). Decisions taken on the open points are recorded in `specs.md`.

## Matches (built as drawn)
- Top bar: Add a post, Library · Archive · Trash, tile sizes, Nest, Settings. Search covers title, author, caption,
  tags, note, summary, transcript, named things and link names, with the matching line on each tile.
- Wall: Piles / Everything, time sections, source menu, Has links, Needs you, tag filter. Pile cards with name,
  count, "N new" and subtitle; Regroup everything.
- Pile page: overview, rename, merge, split off ticked, remove, delete.
- Post card: caption first, counts with Refresh, Summary · Links · Related · Details tabs, key moments that jump
  the video, named things, tags, note, transcript, timing, details; Archive, Remove, Restore, Summarise again,
  Retry; Not related; the piles a post is in.
- Archive and Trash with Restore, days left and Empty trash.
- Nest: what is being read now, waiting, needs you, pause switches (transcribing, summarising, finding links),
  keep awake. Average time per step and recently finished are in the mockup's styles too.
- Settings: AI keys in order with status and model, Add a key with guides, summary limit, problems, Brave key,
  phones with install codes and QR, keep awake, library folder, Trash, appearance (boxed width, tile size).

## The product wins (already decided; the mockup is out of date)
- **Private** is no AI at all, not a model on the Mac: the mockup's download box, model size and "when to read"
  are dropped. Private settings show what still works (transcripts, piles, related, search, links).
- **Tags are always added by the AI**: the "only suggest" choice is dropped.
- **Keys:** Gemini, OpenRouter, Claude and OpenAI, each with a model choice (the mockup shows only Gemini).
- The no-key banner's "Read them on this Mac" button goes (that was the local model).

## Not in C1+, designed directly in its style (owner's decision)
- Update banner (top of the wall), Health check (Settings → This Mac, with "Run live checks"), Instagram login
  (Settings → Links and sources, with the `magpiary login connect` command), "Try with my Instagram login" on a
  post that needs a login, Smart / Private panel with the reason summaries are waiting.
- Theme: light, dark or follow the Mac (Appearance). The mockup only follows the Mac.

## Technical choices (mine)
- The post card opens over the wall, and `/item/N` still opens it directly (shareable, reload-safe). Without
  JavaScript every page still works as plain links and forms.
- Fonts (Bricolage Grotesque, DM Sans; both under the Open Font License) are stored in the repo, not loaded from
  Google: the hub makes no outside requests.
- `/queue` folds into the Nest; `/setup` (pairing and QR) folds into Settings → Phones. Old addresses redirect.
- The wall heading rotates (one of seven lines a day), with the "new today" line kept small.

## Decided by the owner (24 Oct)
Mockup types, mapped without AI · 4 first-run screens keeping every step · the wall opens on Everything · Private
tiles in source colours without a badge. The questions as they were asked:

1. **Post types and tile colours.** The mockup colours tiles by type (How-to, News & opinion, Tool, Design,
   Explainer, Discussion, Recipe); the AI actually sorts into recipe, tool, place, media, how-to, news & opinion,
   entertainment, other. The mockup's set reads better ("media" was wrong for both saves in the Nemotron test).
2. **First-run steps.** The mockup has 3 screens (pair, choose, share); the real guide needs 7 steps (phone ready,
   pair, allow once, Wi-Fi automation, test share, keep the Mac ready, choose Smart or Private).
3. **The wall's first view.** The mockup opens on Everything; Piles is one click away.
4. **Tiles in Private mode** (no AI type): coloured by source like the mockup's no-key state, without the
   "✦ Summarise" badge, since Private never summarises.
