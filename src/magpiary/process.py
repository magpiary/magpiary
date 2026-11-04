"""Process one archived item (Balanced preset): transcript and frames on the Mac, then one record from
the owner's Gemini key, then a Markdown note. Safe to run again: a saved transcript and frames are reused.

Writes into the item's folder: transcript.json, frames/*.jpg, frames.json, record.json.
Writes a note to ~/Magpiary/notes/<folder name>.md (opens in Obsidian).
"""

import json
from datetime import datetime
from pathlib import Path

from magpiary.activity import NO_PROGRESS, Progress
from magpiary.brain import Call, build_evidence, http_call, reuse_tags, summarise
from magpiary.frames import extract
from magpiary.tools import video_seconds
from magpiary.transcribe import TranscribeFailed, has_speech, transcribe
from magpiary.config import load_json as _load  # noqa: E402  (one reader for the library's JSON files)

VIDEO = (".mp4", ".webm", ".mov", ".mkv")
MAX_IMAGES = 10
MAX_SLIDES = 10      # a carousel's videos that are read
CAROUSEL_FRAMES = 24  # frames across a whole carousel, shared between its videos




def senses(folder: Path, meta: dict, transcriber=transcribe, framer=extract,
           progress: Progress = NO_PROGRESS) -> tuple[list | None, list, str]:
    """Transcript segments (None if no video), frames, and a note of anything that went wrong."""
    videos = [folder / m for m in meta.get("media") or [] if m.endswith(VIDEO)]
    if not videos:
        return None, [], ""
    if len(videos) > 1:
        return carousel_senses(folder, meta, videos[:MAX_SLIDES], transcriber, framer, progress)
    problem = ""
    saved = _load(folder / "transcript.json", None)
    if saved is None:
        progress.step("transcribe")
        try:
            saved = transcriber(videos[0], folder / "transcript.json", meta.get("duration"),
                                on_progress=progress.percent if progress.activity else None)
        except TranscribeFailed as err:
            saved, problem = {"segments": []}, str(err)
    frames = _load(folder / "frames.json", None)
    if frames is None:
        progress.step("frames")
        speech = has_speech(saved.get("segments") or [], meta.get("duration"))
        frames = framer(videos[0], folder, meta.get("duration"), speech=speech)
        (folder / "frames.json").write_text(json.dumps(frames))
    return saved.get("segments") or [], frames, problem


def slide_times(folder: Path, videos: list[Path]) -> list[dict]:
    """Where each video of a carousel sits on one continuous timeline: [{"file", "start", "duration"}], saved as slides.json.
    The summary reads the videos back to back; the post view turns a moment on that timeline into a slide and a time."""
    saved = _load(folder / "slides.json", None)
    if saved and [s.get("file") for s in saved] == [v.name for v in videos]:
        return saved
    slides, at = [], 0.0
    for v in videos:
        length = video_seconds(v) or 0.0
        slides.append({"file": v.name, "start": round(at, 1), "duration": length})
        at += length
    (folder / "slides.json").write_text(json.dumps(slides))
    return slides


def carousel_senses(folder: Path, meta: dict, videos: list[Path], transcriber, framer, progress: Progress) -> tuple[list, list, str]:
    """Every video of a carousel, listened to and looked at on its own, joined on one timeline. Re-run for a post that was
    saved when only the first slide was read."""
    slides = slide_times(folder, videos)
    problems = []
    saved = _load(folder / "transcript.json", None)
    if saved is None or saved.get("slides") != len(videos):
        progress.step("transcribe")
        segments, engine = [], ""
        for n, (video, slide) in enumerate(zip(videos, slides, strict=True)):
            part = folder / ".slide-transcript.json"
            try:
                got = transcriber(video, part, slide["duration"] or None)
            except TranscribeFailed as err:
                problems.append(f"slide {n + 1}: {err}")
                continue
            engine = engine or got.get("engine", "")
            segments += [{**s, "start": round(s["start"] + slide["start"], 2), "end": round(s["end"] + slide["start"], 2)}
                         for s in got.get("segments") or []]
            part.unlink(missing_ok=True)
            if progress.activity:
                progress.percent((n + 1) / len(videos) * 100)
        saved = {"engine": engine or "none (no sound)", "slides": len(videos), "segments": segments}
        if not problems:  # a slide that failed is not marked as read: the whole carousel is listened to again next time
            (folder / "transcript.json").write_text(json.dumps(saved, ensure_ascii=False))
    frames = _load(folder / "frames.json", None)
    if frames is None or not all("slide" in f for f in frames):
        progress.step("frames")
        speech = has_speech(saved.get("segments") or [], sum(s["duration"] for s in slides))
        each = max(3, CAROUSEL_FRAMES // len(videos))
        frames = []
        for n, (video, slide) in enumerate(zip(videos, slides, strict=True), 1):
            sub = folder / f"slide{n:02d}"
            sub.mkdir(exist_ok=True)
            found = framer(video, sub, slide["duration"] or None, speech=speech, cap=each)
            frames += [{"at": round(f["at"] + slide["start"], 1), "path": f"slide{n:02d}/{f['path']}", "slide": n} for f in found]
        (folder / "frames.json").write_text(json.dumps(frames))
    return saved.get("segments") or [], frames, "; ".join(problems)


def process_item(item: dict, key, notes_dir: Path, call: Call = http_call,
                 transcriber=transcribe, framer=extract, store=None, progress: Progress = NO_PROGRESS) -> dict:
    """`key` is a keys.Key. Returns the record (also saved as record.json). Raises BrainFailed.
    The video itself never leaves the Mac: only the caption, transcript and frames are sent."""
    folder = Path(item["archive_dir"])
    meta = _load(folder / "meta.json", {})
    images = [folder / m for m in meta.get("media") or [] if not m.endswith(VIDEO)][:MAX_IMAGES]
    comments = _load(folder / "discussion.json", None)
    transcript, frames, problem = senses(folder, meta, transcriber, framer, progress)
    screen = _load(folder / "ocr.json", None)  # text read on the Mac, when it has been read (a re-read, or a photo post)
    known = store.known_words() if store is not None and hasattr(store, "known_words") else None
    parts = build_evidence(meta, transcript, frames, images, folder, comments, item.get("note") or "", screen, known)
    progress.step("summary")
    record = summarise(parts, key.secret, key.model, call, provider=key.provider)
    if known:
        record["suggested_tags"] = reuse_tags(record["suggested_tags"], known.get("tags") or [])[:5]
    senses_used = "local (whisper.cpp small, ffmpeg frames)"
    from magpiary.modes import current

    record["engine"] = {"preset": current(store) if store is not None else "smart", "senses": senses_used,
                        "brain": f"{key.provider}:{key.model}", "key": key.name, "problem": problem or None}
    record["processed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    record["frames"] = frames
    (folder / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
    write_note(item, meta, record, transcript, notes_dir / f"{folder.name}.md")
    return record


def _yaml(value) -> str:
    return json.dumps(value, ensure_ascii=False)  # JSON strings and lists are valid YAML


def write_note(item: dict, meta: dict, record: dict, transcript: list | None, path: Path) -> None:
    lines = ["---", f"title: {_yaml(record['title'])}", f"url: {_yaml(item['canonical_url'])}",
             f"source: {item['source']}", f"author: {_yaml(meta.get('author') or meta.get('author_handle') or '')}",
             f"type: {record['type']}", f"tags: {_yaml(record['suggested_tags'])}",
             f"saved: {_yaml(item.get('first_shared_at') or '')}", f"posted: {_yaml(meta.get('published_at') or '')}",
             "---", "", f"# {record['title']}", "", record["summary"], ""]
    if record["key_points"]:
        lines += ["## Key points", ""] + [f"- {p['text']}" + (f" ({p['at']})" if p["at"] else "") for p in record["key_points"]] + [""]
    for label, key in (("Ingredients", "ingredients"), ("Steps", "steps"), ("Takeaways", "takeaways")):
        if record["extras"].get(key):
            lines += [f"## {label}", ""] + [f"- {x}" for x in record["extras"][key]] + [""]
    named = [f"- **{k.replace('_', ' ').title()}:** {', '.join(v)}" for k, v in record["entities"].items() if v]
    if named:
        lines += ["## Mentioned", ""] + named + [""]
    if record.get("discussion_summary"):
        lines += ["## The discussion", "", record["discussion_summary"], ""]
    deep = _load(Path(item["archive_dir"]) / "deep.json", None) if item.get("archive_dir") else None
    if deep:
        from magpiary.deepdive import as_markdown

        lines += as_markdown(deep)
    if item.get("note"):
        lines += ["## My note", "", item["note"], ""]
    if meta.get("text"):
        lines += ["## Caption", "", meta["text"], ""]
    if transcript:
        lines += ["## Transcript", ""] + [f"{int(s['start']) // 60}:{int(s['start']) % 60:02d} {s['text']}" for s in transcript] + [""]
    lines += [f"[Open the original]({item['canonical_url']})", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
