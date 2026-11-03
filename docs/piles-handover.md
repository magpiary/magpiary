# Piles — feature handover

A self-contained brief for working on Piles (and Related, which Piles is built on) in a fresh session.
Written 24 Oct 2026. Source of truth for decisions stays `docs/specs.md` (section "M4: Related content and
Piles" and the decisions log); this file explains them in one place.

## 1. Two different things called "piles" — read this first

| | Mockup piles (`docs/ui-directions/`) | Real piles (the product, M4) |
|---|---|---|
| Where | `c3-studio.html:112`, `c1-plus.html:317` (`const TOPICS`) | `src/magpiary/related.py`, `store.py`, `hub_piles.py` |
| How items were grouped | **By hand.** Claude picked six themes from the sample items' tags and titles to show what the screen could look like | **Automatically on the Mac**, from a local meaning model plus shared named things and tags |
| Names / blurbs | Written by hand ("Workshop projects", "Making at home"…) | Worked out from the names and words the pile's items share |
| Status | Illustration only; no logic behind it | Built, tested (315 tests pass), deployed on the owner's library |

The mockup's six piles, for the record (sample item IDs from `data.js`):

- Workshop projects → 16, 4, 3, 5, 15
- Design inspiration → 17, 13, 11, 6, 8
- Making at home → 15, 2, 7, 16
- Community & reuse → 14, 3
- Kitchen → 10
- Curious ideas → 9

They break real rules on purpose to fill the screen: "Kitchen" and "Curious ideas" have one item, and
"Community & reuse" has two, where the real product needs **3 or more**. Items 3, 15 and 16 sit in two
piles each, which the real product also allows. The `fresh` count ("2 new") and the cover stack of three
thumbnails are design ideas that the real hub doesn't have yet.

**The rest of this document is about the real logic.**

## 2. What Piles is, in plain words

Saves that share a topic gather into piles by themselves, across sources (an Instagram reel, a YouTube
video and a Reddit thread about the same thing land together). Everything is worked out on the Mac: no AI
key, no quota, nothing sent anywhere. The owner can rename, merge, split, remove items from and delete piles,
and those edits survive every automatic rebuild.

"Piles" is the owner's name for what older docs call **Topics**.

## 3. Decisions (fixed; ask the owner before changing)

From the `docs/specs.md` decisions log, 24 Oct 2026:

1. Piles are made automatically when **3 or more** items share a topic.
2. The owner can **rename, merge, split, remove items and delete** piles.
3. Names are worked out **on the Mac**, from shared named things and words. **No AI** is used for naming.
4. **An item can be in several piles.**
5. **Pile page:** a short overview made on the Mac (what the items share, sources, date range), then the
   items as cards, with rename, merge, split and delete.
6. **"Not related"** hides a pair from Related for good. If both items are in one pile, the other item
   leaves it, and that pair is never suggested again.
7. **Meaning model:** small, fast and multilingual (multilingual-e5-small, MIT, about 135 MB).
8. **Screens:** built plain in the current hub style for now. They get restyled later to the C1+ direction
   (Piles / Everything switch on the wall), as part of the merge plan the owner hasn't asked for yet.
9. These project rules apply too: nothing leaves the Mac, there's no telemetry, stages are idempotent, the
   pipeline is unattended, and fetched text is data, never instructions.

## 4. How grouping works, step by step

### 4.1 What is looked at
`Store.related_rows()` (`store.py:794`) returns every item that is `status='archived'` and not in the
Trash. For each item it includes:

- title and AI title;
- caption and summary;
- the AI's suggested tags and the owner's tags;
- link names (the names that M3.5 found links for);
- transcript, date and source.

The named things come from `record.json` → `entities`: tools, products, books, places, people and so on.
Link URLs are left out, but the names the links were found for count.

### 4.2 Meaning vectors (`embed.py`, `related.refresh_vectors`)
- **What the model reads** (`item_text`): title, then summary (or the caption if there's no summary), then
  tags, then named things. With no summary it also reads the first 1,500 characters of the transcript.
  The whole text is capped at 4,000 characters.
- **When an item is read again:** the text is hashed (SHA-256, first 16 characters). An item is read again
  only when that hash changes, for example when a summary arrives or tags change. Vectors are stored in the
  `vectors` table (url, model, text_hash, float32 blob).
- **How the model runs:** a quantised ONNX model under onnxruntime, in a child process, in batches of 32.
  - It is downloaded once into `~/Magpiary/models/multilingual-e5-small`, from a pinned revision
    (`761b726…`) with SHA-256 sums checked.
  - A file with the wrong checksum is deleted, not kept.
  - Speed is about 0.015 s per item on the M1 Pro.
- **If the model is missing or broken,** `EmbedFailed` is logged and the worker moves on. The pipeline is
  never blocked.

### 4.3 One score per pair (`related.load`)
Each pair of items gets one number. It is built from three parts that are added together.

**1. Topic: how much closer than usual.**
- It starts from the cosine similarity of the two vectors.
- That similarity is turned into a z-score against **this library's own** spread:
  `z = (sim − mean of all off-diagonal sims) / max(std, 0.02)`.
- Negative values are clipped at −1.
- This is why it still separates topics in a library that is mostly about one subject (for example, a fictional collection about paper craft).
- The 0.02 floor keeps a tiny library from blowing up the z-scores.

**2. Shared named things.**
- The score adds `min(3.0, 1.5 × Σ weight)` over the names the two items share.
- **Weight = rarity:** `log((n+1)/count) / log(n+1)`.
  - A name only two items have is worth close to 1.
  - A name every item has is worth close to 0.

**3. Shared tags.**
- The score adds `min(2.0, Σ weight)` over shared tags (the owner's tags plus the AI's suggestions).
- Tags use the same rarity weight.
- Tags count for less than named things.

**What does not count:**
- **The same creator** is deliberately not a signal.
- A **"Not related"** pair is set to −1,000,000 (`BLOCKED`).
- An item paired with itself is also `BLOCKED`.

Names and tags are normalised by `_norm`: lowercased, punctuation stripped except `+ # . & -`, spaces
collapsed.

**Related** (the panel on each item) uses the same scores. A pair is shown when it scores **1.2 or more**,
best first, with the top 6 on the item page. Each one gets a reason:

- "Both mention X and Y" when a shared name has weight ≥ 0.3;
- otherwise "Both tagged #x" when a shared tag has weight ≥ 0.3;
- otherwise "Similar topic".

### 4.4 Forming piles (`related.clusters`)
This is **average-linkage agglomerative clustering** over the pair scores:

1. Every item starts as its own group.
2. Take the two groups with the highest average score between them. If that score is **below 2.0**
   (`PILE_MIN`), stop.
3. Otherwise merge them. The scores are updated with the Lance–Williams average-linkage formula
   (a size-weighted mean of the two rows).
4. Groups of **3 or more** (`PILE_SIZE`) become piles. Smaller groups are dropped.
5. **Overlap step:** an item outside a pile joins it as well when two things hold:
   - its average score to the pile's members is **2.5 or more** (`PILE_MIN + 0.5`);
   - it has no "Not related" mark against any member.

   This is how one item can be in several piles.

Fewer than 3 items in the library means no piles.

Why average linkage rather than single linkage? With single linkage, one strong link can chain unrelated
items together. Average linkage needs the whole group to hang together.

### 4.5 Naming a pile (`related.pile_name`)
The name should be the thing most of the pile shares and the rest of the library mostly doesn't.

**Candidates** come from three places: the pile's named things, its tags, and the words in its titles.
- Title words have 4 or more letters, are not on a stop-word list, and have their own rarity weight.

**Filter.** A candidate must appear in at least `max(2, ceil(size/2))` members.

**Score.** `boost × (share of members that have it) × (0.25 + rarity)`. The boost depends on the
candidate's kind:

| Candidate kind | Boost |
|---|---|
| Named thing | 1.3 |
| Tag | 1.1 |
| Title word | 1.0 |

**Building the name.**
- The top candidate is the name. It keeps the way the item wrote it, and tags or words of 3 letters or
  fewer are upper-cased ("AI").
- A second candidate is added as "First & Second" when all of these hold:
  - it scores at least 70% of the top one;
  - its own rarity is at least 0.3;
  - neither name contains the other.
- If there are no candidates at all, the name is "Similar saves".

Fictional naming example: "Paper & Making".

### 4.6 Keeping the owner's edits (`related.rebuild_piles` → `_rebuild`)
Piles are rebuilt from scratch each time, then matched to the piles that existed before:

1. The new groups are taken largest first. Each is compared with every existing pile, live or deleted, by
   Jaccard overlap of members. For an existing pile, "members" here includes the items the owner removed.
2. **Overlap ≥ 0.5, the old pile is live:** the new group keeps that pile's id.
   - The automatic members are updated. Items the owner removed stay out, and items the owner added stay in.
   - The automatic name is updated, but the shown name is not if the owner renamed the pile.
3. **Overlap ≥ 0.5, the old pile was deleted:** nothing is made. A deleted pile is a tombstone and is
   never recreated.
4. **No match:** a new pile is made.
5. Old piles that matched nothing:
   - those the owner touched (renamed, made, merged into, or given members) stay, with only the owner's
     items;
   - automatic ones nobody touched are dropped.

A lock (`_REBUILD`) stops the worker and the hub's edit buttons from rebuilding at the same time.

### 4.7 When it runs
`worker.related_due` (`worker.py:229`) is called from the receiver's background loop
(`receiver.py:282`). It does two things:

1. It makes vectors for new or changed items.
2. It rebuilds piles if any vectors were made, or if the `piles_dirty` setting is "1".

`piles_dirty` is set when an item moves shelf (trash, archive and so on). Tag edits need no flag: they
change the text hash, so the item gets a new vector, and that triggers the rebuild. Every edit the owner
makes to a pile in the hub rebuilds straight away.

The hub caches the loaded `Library` and loads it again only when `related_signature()` changes. That
signature covers vector count and rowids, Not-related count, trash count and archived count.

## 5. Data model (`store.py:77-84`)

```sql
vectors     (canonical_url PK, model, text_hash, vector BLOB)
not_related (a, b)  PK (a, b)            -- urls, stored sorted
piles       (id PK, name, auto_name, owner_named, owner_made, deleted, created_at)
pile_items  (pile_id, canonical_url, origin 'auto'|'owner', removed 0|1)  PK (pile_id, canonical_url)
```

- `name` is what is shown. `auto_name` is what the Mac would call the pile. They differ once `owner_named`
  is 1.
- `removed = 1` with `origin = 'owner'` means the owner took the item out. That row keeps it out on every
  rebuild.
- Items are keyed by **canonical URL** (the project's identity rule), never by rowid.

## 6. The owner's edits (`hub_piles.py:185`, `store.py:894-940`)

| Action | Route (POST, CSRF-checked) | Effect |
|---|---|---|
| Rename | `/hub/pile/rename` | sets `name`, `owner_named=1` (max 60 characters, whitespace collapsed) |
| Delete | `/hub/pile/delete` | `deleted=1`; kept as a tombstone, so it's never remade |
| Merge | `/hub/pile/merge` (`pile`, `into`) | the source's members are added to the target as owner items; target gets `owner_made=1`; source becomes a tombstone |
| Split off ticked | `/hub/pile/split` (`item_N` checkboxes, `name`) | ticked items leave the pile and form a new owner pile (name defaults to "Part of …"); you can't split off every item |
| Remove item | `/hub/pile/remove` | marks the item removed in that pile, for good |
| Not related | `/hub/not-related` (`id`, `other`) | blocks the pair forever; if both share a pile, `other` leaves it |

Each action rebuilds the piles, then redirects back with a 303.

## 7. Screens today (plain hub style)

- **Library:** a pile chip row above the inbox, and "More like this →" under every card.
- **`/piles`:** all piles.
- **`/pile/N`:** the overview, from `related.overview`:
  - item count and sources with counts;
  - first and last date;
  - up to 8 things at least 2 items share (names and #tags).

  Then the items, with the edit forms.
- **Item page:** a Related panel under the media. It shows:
  - the top 6, each with its reason and a Not related button;
  - "See all";
  - the piles the item is in.
- **`/item/N/related`:** the full Related list.

Restyling to C1+ is not done yet. The target is the Piles / Everything switch on the wall, pile cards with
a cover stack, the pile page as a tile grid, and motion via GSAP Flip. Wait for the owner's merge go-ahead.

## 8. Tuning knobs (`related.py:28-32`)

| Constant | Value | Meaning |
|---|---|---|
| `RELATED_MIN` | 1.2 | pair score needed to show as Related |
| `PILE_MIN` | 2.0 | average score to keep merging groups (pile tightness) |
| `PILE_SIZE` | 3 | smallest pile |
| overlap join | `PILE_MIN + 0.5` = 2.5 | extra item joins a second pile |
| `SHOWN` | 6 | Related items on the item page |
| `MIN_SPREAD` | 0.02 | floor on the library's similarity spread |
| names cap / tags cap | 3.0 / 2.0 | most a pair gets from shared names / tags |

Rough guide: lower `PILE_MIN` for bigger, looser piles; raise it for fewer, tighter ones. The values were
tuned on a small test library. Private pile names, counts and membership are omitted. Retune as the
library grows, and re-check against representative test items rather than guessing.

## 9. Tests (`tests/test_related.py`)

The tests use a fake embedder, never the real model, and cover:

- Related ranking by topic, names and tags, with reasons;
- Not related lasting for good;
- vectors made once, and again only when the text changes;
- piles of 3+ named from what they share;
- the owner's edits surviving a rebuild;
- split and merge;
- the worker surviving a missing model;
- a downloaded file with a bad checksum being rejected;
- the item page and pile pages end to end.

Run them with `uv run pytest tests/test_related.py`.

## 10. Known limits and open questions

- **Small libraries:** the z-score has little to work from. With very few items, piles depend mostly on
  shared names and tags.
- **Thresholds are fixed numbers** tuned on 17 items. They will need retuning as the library grows.
  Decide whether that happens by hand or as a per-library rule.
- **Piles depend on summaries.** Without an AI key (the Private preset, or no key), the model reads the
  caption and transcript and there are no AI tags or named things. Piles will be weaker there. This hasn't
  been measured yet.
- **No "fresh" count** ("2 new since you last looked") and no cover stack yet. Both appear in the C1+
  mockup, and both need product decisions before building.
- The rebuild is O(n³) in the worst case: a dense n×n matrix with a repeated argmax. That's fine for
  thousands of items. Revisit only if a library gets far beyond that.

## 11. Files

- `src/magpiary/related.py`: scores, Related, clustering, naming, rebuild, overview
- `src/magpiary/embed.py`: model download, checksum and child-process embedding
- `src/magpiary/store.py:77-84, 792-940`: tables and pile and vector methods
- `src/magpiary/worker.py:229`: `related_due`
- `src/magpiary/receiver.py:282`: background loop hook
- `src/magpiary/hub_piles.py`: screens and edit routes
- `tests/test_related.py`
- `docs/specs.md`: "M4: Related content and Piles" and the decisions log, 24 Oct
- `docs/ui-directions/c1-plus.html`: the target look (hand-made sample piles)
