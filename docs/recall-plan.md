# Magpiary vs Recall: what we take

Plan from the 28 Oct 2026 comparison report, after a 30-question grilling with the owner. Effort and impact are estimates.

## The short version

- Recall already does what Magpiary's headline does: it takes Reels, carousels and Threads, and calls itself local-first. We cannot win by saying we handle social posts.
- Where we are different is the real video and transcript on your Mac, explained Related posts, piles you can fix, boards, and the Digest. Recall leans on chat, a graph and quizzes.
- The report's three priorities are first value, trust, and a next action on every post. Most of this plan is those three.
- Your direction: a personal reference library for creative work. Adoption means people come back and use what they saved.
- Release gate, in your words: easy install for a stranger, plus the magic moment (Ask about these saves).

## How to read this

- **Effort.** S is under a day. M is two to four days. L is one to two weeks. For one person working with Claude; estimates, not promises.
- **Impact.** How much it should help someone find, trust or use a save. High means it changes whether a new person keeps using it.
- **Changes the product by.** Polish: looks and feel only. Usability: easier to do something it already does. How it works: new behaviour, data or processing. Positioning: changes what Magpiary is or promises.

## Tier 1: High impact, low effort

Do these first. Together about one to two weeks.

| # | Change | What it does | Effort | Impact | Changes the product by | Effect on the product | Needs first |
|---|---|---|---|---|---|---|---|
| 1.1 | **Main-resource button** | Under the summary: “Open Cedar Panels ↗” for the tool the post is about, or “Find the link” when none is known. Later the same idea for places (Maps) and products. | S | High | Usability | Uses the links we already find. Moves the main reuse step from the third tab to the first screen. | none |
| 1.2 | **Say where each block came from** | Small plain labels: AI summary (and which AI), Caption by the creator, Your note, Spoken. | S | High | Polish | Makes it obvious what is the creator's, the AI's and yours. Prepares the ground for cited answers. | none |
| 1.3 | **Say why a result matched** | One line on each search result: “Matches what was said”, “Matches the caption”, “Related topic”, with the matching words highlighted. Never a score. | S–M | High | Usability | Search already finds both words and meaning; this explains it. Later also “Matches text on screen”. | none |
| 1.4 | **“Did you mean?”** | Typo help in search, built from words already in your library. | S–M | Medium | Usability | A search that fails on a misspelt name is the commonest dead end. | none |
| 1.5 | **Copy with source** | One button: the summary, the original link and the moment's timestamp, ready to paste into a brief or notes. | S | Medium | Usability | Turns a save into something you can drop straight into work. | 1.2 |
| 1.6 | **Add to board from the post** | A visible button on the post, not only inside the … menu. | S | Medium | Usability | Boards are the project step. Today that step is hidden. | none |
| 1.7 | **Say what each thing is** | One plain line under Piles, Boards, Library and Archive (“Piles are made by Magpiary. Boards are made by you.”), plus a one-time step in the checklist. | S | Medium | Usability | Type, pile, board and shelf are four ideas that currently share one visual vocabulary. | 2.3 for the one-time part |
| 1.8 | **Privacy in one sentence** | At the AI-key choice and at “share a board”, say exactly what leaves the Mac. No absolute claims such as “everything stays on your Mac”. | S | High | Positioning | Keeps the promise honest today and leaves room if a hosted version ever happens. | none |
| 1.9 | **A “Loose” shelf** | Posts that sit alone stop being one-post piles. They live in a quiet Loose area on the Piles page. | S–M | Medium | Usability | Fixes the “every save is in a pile” line that is not true for single posts. | none |
| 1.10 | **“Where is my save?” in the hub** | Four plain states: Waiting on the phone, Received by the Mac, Reading it, Ready. Never “Saved” when only the link arrived. | S | Medium | Usability | Delivery is the part users cannot see. The phone side of this is in 2.5. | none |

## Tier 2: High impact, high effort

Plan carefully. These make or break the release.

| # | Change | What it does | Effort | Impact | Changes the product by | Effect on the product | Needs first |
|---|---|---|---|---|---|---|---|
| 2.1 | **Ask about these saves** | Pick a pile, a board or one post and ask a question. The answer uses only those saves, links to the moment or transcript line it came from, and says so when it does not know. Needs the user's AI key. | L | High | Positioning | Your “magic moment” for release. Moves from “after release” in the plan to “before release”. | 1.1, 1.2; 2.4 helps |
| 2.2 | **Piles that nest** | A big pile (AI) with smaller piles inside it (Claude Code). Better names. Starts with research into how Instagram-style labelling and related-post logic work, then a scoped rebuild. | L | High | How it works | Changes how posts are grouped and how Related is chosen. Biggest change to existing behaviour. | research first; 1.9 |
| 2.3 | **First-run checklist and key walkthrough** | A small replayable checklist that opens the real parts of the first post: watch a moment, open the link, add a note, search for it, how saves are organised. The AI-key step can be skipped; it shows what summaries add, then offers a free Gemini key walkthrough inside the hub. | M–L | High | Usability | Phone pairing stays first (your decision). This is what makes the first ten minutes land. | 1.7 |
| 2.4 | **Read on-screen text** | OCR on the Mac for every post, Private mode included, so what you see in a video is searchable. | M | Medium | How it works | A new processing step per post, a little more time and disk. Makes silent videos findable. | none |
| 2.5 | **Easy install and a real test** | Make install work for a stranger. Run it on a clean Mac with one or two people while you watch. Add the phone-side delivery acknowledgements. | L | High | Positioning | This is the release gate along with 2.1. Everything else is polish if this fails. | 1.10 |
| 2.6 | **Digest controls and “I tried this”** | Dismiss, how often, and a way to mark a suggestion as tried. Counted on the Mac only. | M | Medium | How it works | Turns the Digest into a come-back loop you can measure without telemetry. | 3.1 |

## Tier 3: Lower impact or middling effort

Pick up when you are in the area.

| # | Change | What it does | Effort | Impact | Changes the product by | Effect on the product | Needs first |
|---|---|---|---|---|---|---|---|
| 3.1 | **A private “Your activity” view** | Counts on the Mac only: links opened, summaries copied, posts added to boards, questions asked. Shows whether people come back and use what they saved. | S–M | Medium | Positioning | Your adoption measure, with no telemetry. A friend can send you a screenshot. | none |
| 3.2 | **Replay the checklist from Help** | The first-run checklist can be reopened from Help. | S | Medium | Usability | Costs almost nothing once 2.3 exists. | 2.3 |
| 3.3 | **Export a pile or board as a reference sheet** | A Markdown or PDF page of posts, summaries, links and your notes for a project. | M | Medium | How it works | A way to take your saves out into a brief. | 1.5 |

## Parked or later

- **Share a post by message or another app.** WhatsApp, Messages, Notion, Figma, Things. First decide where people want to send things and what goes in the message. A good grilling topic.
- **Ask in plain language and get posts back.** After Ask about these saves works. Same machinery, different box.
- **Said versus seen on key moments, and a cited sentence-by-sentence summary.** Later trust work.
- **A short video of the product.** For the app or for marketing. Record it close to release.
- **Graph, quiz, listen, MCP and API.** Parked for the creative-reference audience. The API may fit later because everything is local.
- **Title-first list view, transcript editing, a sample post.** Considered and set aside for now.
- **Mac-first setup order.** The report's top idea. You chose phone-first. Revisit if testers stall before their first post.

## Where we differ from the report

- **Phone pairing stays first.** The report advises showing value on the Mac before the phone. You chose to keep the phone first. The risk is the one the report ranks highest: setup friction. The answer is 2.3 and 2.5 (a clear checklist, then watching a real person try).
- **Ask about these saves comes before release.** The report and the project plan put it after. You want it as the magic moment. It needs 1.1 and 1.2 first, so answers can point at real evidence.
- **The tagline leans on finding, not on the Mac.** “Never lose a reel again”, with finding what you half remember at the centre. Local ownership stays a supporting point, because the product may one day be public. Note: CLAUDE.md still says nothing runs on a server we host. That is unchanged; if the scope really widens, that rule needs its own conversation.
- **We skip three of the report's ideas.** A list view, transcript editing and a sample post. The report suggested them; your answers set them aside for now.

## Suggested order

| Phase | Theme | Items | What it gets you |
|---|---|---|---|
| Phase 1 | Trust and next action | 1.1, 1.2, 1.5, 1.6, 1.7, 1.8, 1.10, 1.9 | A post tells you what it is, where each part came from and what to do next. Mostly small, so it ships in pieces. |
| Phase 2 | Search and the magic moment | 1.3, 1.4, 2.4, then 2.1 | Search explains itself; on-screen text is searchable; Ask about these saves is built on top of 1.1 and 1.2. |
| Phase 3 | A stranger can start | 2.3, 3.2, 2.5, 3.1 | The checklist and key walkthrough, then a clean-Mac test with one or two people. 3.1 shows whether they come back. |
| Phase 4 | Better grouping | Research, then 2.2, 2.6, 3.3 | The Instagram-style tagging study runs alongside earlier phases; the rebuild waits until the release gate is met. |

## Already done this week

- Your note sits under the summary (was at the bottom).
- Junk link titles such as “One moment, please…” fall back to the website's name.
- A tool with no link shows “No link found yet” with a Find it button.
- Tools and people the post mentions sit as chips under the summary.
- The detail view keeps the video, key moments and original link in view; counts sit under the title; copy summary with “Written by”.

## Scale for “changes the product by”

- **Polish:** looks and feel only
- **Usability:** easier to do something it already does
- **How it works:** new behaviour, data or processing
- **Positioning:** changes what Magpiary is or promises
