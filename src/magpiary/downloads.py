"""Everything Magpiary downloads after it is installed: one list, read by the installer, `magpiary downloads`
and Settings → About, so what people are told is what actually happens.

Each entry says what it is, where it comes from, how big it is, why Magpiary needs it and whether it is already here.
The tools and models themselves are still fetched by `tools.py`, `embed.py` and pywhispercpp; their pinned
URLs and checksums are read from here only for display, never copied, so they cannot drift apart.
"""

import platform
from dataclasses import asdict, dataclass
from pathlib import Path

from magpiary import embed, tools
from magpiary.transcribe import MODEL as WHISPER_MODEL

# ggml-small.bin from whisper.cpp's Hugging Face repository; the checksum is the file's published SHA-256.
WHISPER_URL = f"https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{WHISPER_MODEL}.bin"
WHISPER_SHA256 = "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b"
WHISPER_BYTES = 487_601_967

# Download sizes in bytes, measured from the pinned files (Apple Silicon builds). None where not measured.
_SIZES = {("ffmpeg", "arm64"): 28_395_699, ("ffprobe", "arm64"): 28_317_701, ("deno", "arm64"): 38_770_795}

# Inside the app already, so not downloaded: shown in Settings → About next to what is downloaded.
INCLUDED = [
    ("Python 3.12", "Runs Magpiary and everything it does."),
    ("Magpiary and its libraries", "The app itself, plus the maths and security libraries it uses."),
    ("yt-dlp", "Fetches the post, its video and pictures from Instagram, Threads, YouTube and other sites. "
               "It is updated daily, because sites change often; updates go in your Magpiary folder, not the app."),
]


@dataclass(frozen=True)
class Download:
    id: str
    name: str
    source: str  # who publishes it, in plain words
    url: str
    bytes: int | None
    sha256: str | None  # None where a package installer checks the files itself
    why: str
    installed: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _arch() -> str:
    return "arm64" if platform.machine() == "arm64" else "x86_64"


def _whisper_here() -> bool:
    try:
        from pywhispercpp.constants import MODELS_DIR
    except ImportError:
        return False
    return (Path(MODELS_DIR) / f"ggml-{WHISPER_MODEL}.bin").exists()


def _meaning_here() -> bool:
    return all((embed.model_dir() / name).exists() for name in embed.FILES)


def catalog() -> list[Download]:
    """Everything that may be downloaded, in the order it is fetched, with whether each is already here."""
    arch = _arch()
    meaning_url = f"https://huggingface.co/{embed.REPO}"
    meaning_bytes = None if arch != "arm64" else 118_308_185 + 17_082_730
    ffmpeg_url, ffmpeg_sha = tools.STANDALONE[("ffmpeg", arch)]
    ffprobe_url, ffprobe_sha = tools.STANDALONE[("ffprobe", arch)]
    deno_url, deno_sha = tools.STANDALONE[("deno", arch)]
    return [
        Download("ffmpeg", "ffmpeg", "Martin Riedl's macOS builds", ffmpeg_url, _SIZES.get(("ffmpeg", arch)), ffmpeg_sha,
                 "Pulls the sound and still frames out of videos so they can be transcribed and read.",
                 installed=bool(tools.find("ffmpeg"))),
        Download("ffprobe", "ffprobe", "Martin Riedl's macOS builds", ffprobe_url, _SIZES.get(("ffprobe", arch)), ffprobe_sha,
                 "Measures a video's length, which the scene and transcript steps need.",
                 installed=bool(tools.find("ffprobe"))),
        Download("deno", "Deno", "the Deno project (GitHub)", deno_url, _SIZES.get(("deno", arch)), deno_sha,
                 "A small JavaScript runtime that yt-dlp needs to open YouTube videos.",
                 installed=bool(tools.find("deno") or tools.find("node"))),
        Download("meaning-model", "Meaning model (multilingual-e5-small)", "Hugging Face", meaning_url, meaning_bytes,
                 "; ".join(sha for _, sha in embed.FILES.values()),
                 "Turns saves into meaning vectors so search finds what you half remember and Related and Piles can group them. "
                 "It runs on your Mac.", installed=_meaning_here()),
        Download("whisper-model", f"Transcript model (Whisper {WHISPER_MODEL})", "whisper.cpp on Hugging Face", WHISPER_URL,
                 WHISPER_BYTES, WHISPER_SHA256,
                 "Turns what people say in a video into text on your Mac, so videos can be searched by what was said.",
                 installed=_whisper_here()),
    ]


def total_bytes(entries: list[Download], only_missing: bool = False) -> int:
    return sum(e.bytes or 0 for e in entries if not (only_missing and e.installed))


def human_size(count: int | None) -> str:
    if count is None:
        return "size varies"
    return f"{count / 1_000_000_000:.1f} GB" if count >= 1_000_000_000 else f"{round(count / 1_000_000)} MB"
