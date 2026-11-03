# S5: transcription speed and accuracy on the owner's M1 Pro

**Run:** 22 Oct 2026, MacBook Pro M1 Pro 16 GB, macOS 27.0.1. English reels and Shorts only.
**Data:** one 60 s clip for speed per engine; ten real clips (34 to 156 s, 650 s total, five Instagram and five YouTube Shorts from the owner's own links) for accuracy across models.
**Caveats:** one machine, English only, ten clips. There is no human ground truth: "WER" below is the word difference from full large-v3, which turned out to be wrong on one clip (see loops).

The original links and transcript excerpts are omitted; aggregate measurements are retained.

## Verdict

| Question | Answer |
|---|---|
| Is transcription fast enough? | Yes, by a wide margin. `small` transcribes a minute of audio in 2 to 3 s (whisper.cpp 2.8 s, mlx 1.9 s). A 10-minute batch takes under a minute. |
| Which model by default? | **`small`** (466 MB). It preserved the product names, had the lowest difference from large-v3 overall (8.0%), and never looped on these clips. `tiny` and `base` garbled some names. |
| Is a bigger model worth it? | Not on this data. `large-v3-turbo` was no better than `small` (11.0% vs 8.0%) and 3x slower; full `large-v3` is 2x realtime (309 s for 650 s of audio) and also looped. Offer turbo-q5_0 (574 MB) only as an optional "higher accuracy" pack, and test it on the clips first. |
| Which engine? | **whisper.cpp** for the shipped default: a 38 MB environment plus the model file, nothing else. mlx-whisper is about 1.4x faster at `small` (1.9 s vs 2.8 s) but pulls in `torch` (1.0 GB environment). faster-whisper (CPU) is slowest (9.6 s) and 178 MB. |

## Speed, 60 s clip, warm run

| Engine | tiny | base | small | large-v3-turbo | Environment size |
|---|---|---|---|---|---|
| mlx-whisper (Metal) | 0.6 s | 0.9 s | **1.9 s** | 3.7 s | 1.0 GB (torch, numba, scipy) |
| whisper.cpp via pywhispercpp | not run | not run | 2.8 s | 3.7 s (q5_0) | **38 MB** |
| faster-whisper (CPU int8) | 2.4 s | 3.4 s | 9.6 s | not run | 178 MB |

Model sizes: tiny 71 MB, base 137 MB, small 459 to 466 MB, turbo 1.5 GB (q5_0: 574 MB), full large-v3 2.9 GB.
First-run cost is mostly the model download (small: 50 to 90 s on this connection).

## Accuracy sweep (word difference vs full large-v3, 10 clips, 650 s)

| Model | Difference | Transcribe time (650 s of audio) |
|---|---|---|
| tiny | 12.3% | 7 s (90x realtime) |
| base | 10.5% | 10 s (64x) |
| **small** | **8.0%** | 22 s (30x) |
| large-v3-turbo | 11.0% | 74 s (9x) |
| large-v3 (reference) | 0% | 309 s (2x) |

Part of every difference is spelling and punctuation ("customise" vs "customize"), not mistakes.

## Finding: Whisper can get stuck in a loop and repeat itself

- Full **large-v3 looped on c07**: it wrote 215 words (the same phrase over and over) where the other models wrote 143 and read the clip correctly. So large-v3 is a poor reference for that clip, and every model's score on c07 (34 to 38%) is mostly large-v3's fault.
- **large-v3-turbo looped on c10**: 354 words ending in a repeated short sentence, against 278 to 279 for the others.
- `small` did not loop on any of the ten clips (luck is possible with ten).
- **Design consequence:** the pipeline needs a repetition guard that detects repeated phrases or an abnormal length, then re-runs with other settings (no conditioning on previous text, a higher temperature) or a different model, and records that on the item. Bigger models are not safer here.

## Install footprint for the product

- Core product needs none of this. Transcription is an optional add-on, downloaded on demand into one Magpiary folder (engine plus model, about 0.5 GB with `small`).
- A new Mac has Python 3.9 only: the installer brings its own Python 3.12 (71 MB), yt-dlp (about 12 MB), ffmpeg (about 52 to 85 MB plus libraries) and `uv` (39 MB).
- Installing whisper.cpp from Homebrew would add libomp, ggml and llama.cpp and upgrade three other packages. Prefer a bundled wheel or a pinned binary in Magpiary's own folder.

## Not tested (open)

- Non-English audio (Hindi, Hinglish, others), noisy or music-heavy clips, very long videos.
- whisper.cpp tiny/base, and the q5_0 turbo on all ten clips.
- Real ground truth (a human transcript) for a few clips.
- Speaker labels, timestamps and subtitles-first shortcuts (YouTube's own captions) were not part of S5.

## Cleanup

The internal download ledger is omitted from this public snapshot. No test media or model downloads are included.
