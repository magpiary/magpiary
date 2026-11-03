"""Meaning vectors on the Mac: multilingual-e5-small (MIT, quantised ONNX, about 130 MB) through onnxruntime.

Used to tell which saved items are about the same thing (Related, Piles), and to search by meaning (M7b). The model is downloaded once
into ~/Magpiary/models, from a pinned revision with checked SHA-256 sums. It runs in a child process
(`python -m magpiary.embed`) so its memory never stays with the service.
"""

import hashlib
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from magpiary.config import data_dir

MODEL = "multilingual-e5-small"
REPO = "Xenova/multilingual-e5-small"
REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
FILES = {"model_quantized.onnx": ("onnx/model_quantized.onnx", "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193"),
         "tokenizer.json": ("tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39")}
DIMENSIONS = 384


class EmbedFailed(Exception):
    pass


def model_dir() -> Path:
    return data_dir() / "models" / MODEL


def ensure_model(folder: Path | None = None, opener=urllib.request.urlopen) -> Path:
    """Download the model once; a file whose checksum does not match is never kept. Raises EmbedFailed."""
    folder = folder or model_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for name, (remote, sha) in FILES.items():
        target = folder / name
        if target.exists():
            continue
        part = folder / f"{name}.part"
        digest = hashlib.sha256()
        try:
            with opener(f"https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}", timeout=60) as response, \
                    part.open("wb") as out:
                while chunk := response.read(1 << 20):
                    digest.update(chunk)
                    out.write(chunk)
        except OSError as err:
            part.unlink(missing_ok=True)
            raise EmbedFailed(f"could not download the meaning model: {type(err).__name__}") from err
        if digest.hexdigest() != sha:
            part.unlink(missing_ok=True)
            raise EmbedFailed("the downloaded meaning model did not match its checksum")
        part.rename(target)
    return folder


def embed(texts: list[str], folder: Path | None = None, run=subprocess.run) -> list[list[float]]:
    """One unit-length vector per text. Raises EmbedFailed."""
    if not texts:
        return []
    folder = ensure_model(folder)
    try:
        done = run([sys.executable, "-m", "magpiary.embed", str(folder)], input=json.dumps(texts),
                   capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as err:
        raise EmbedFailed(f"the meaning model did not run: {type(err).__name__}") from err
    if done.returncode != 0:
        raise EmbedFailed(f"the meaning model stopped: {(done.stderr or '').strip()[-200:]}")
    vectors = json.loads(done.stdout)
    if len(vectors) != len(texts):
        raise EmbedFailed("the meaning model gave the wrong number of answers")
    return vectors


def _loader(folder: str):
    """Load the model once; returns a function text, prefix -> unit vector."""
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(Path(folder) / "tokenizer.json"))
    tokenizer.enable_truncation(512)
    options = ort.SessionOptions()
    options.log_severity_level = 3
    session = ort.InferenceSession(str(Path(folder) / "model_quantized.onnx"), options, providers=["CPUExecutionProvider"])
    inputs = {i.name for i in session.get_inputs()}

    def vector(text: str, prefix: str = "passage") -> list[float]:
        encoded = tokenizer.encode(f"{prefix}: {text}")  # e5 expects "passage: " for saves, "query: " for searches
        ids, mask = np.array([encoded.ids]), np.array([encoded.attention_mask])
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        out = session.run(None, feed)[0][0]
        mean = (out * mask[0][:, None]).sum(0) / mask.sum()
        return [round(float(x), 6) for x in mean / np.linalg.norm(mean)]
    return vector


class Warm:
    """The model kept loaded for searches (M7b): started by the first search, stopped after `idle` quiet seconds
    so its memory does not stay with the service. Any failure gives None, and search falls back to words."""

    def __init__(self, folder: Path | None = None, idle: float = 300, spawn=subprocess.Popen):
        self.folder, self.idle, self.spawn = folder, idle, spawn
        self._child = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def query(self, text: str) -> list[float] | None:
        with self._lock:
            try:
                if self._child is None or self._child.poll() is not None:
                    folder = self.folder or model_dir()
                    if not all((folder / name).exists() for name in FILES):
                        return None  # never downloads from a search; the worker fetches the model
                    self._child = self.spawn([sys.executable, "-m", "magpiary.embed", str(folder), "--serve"],
                                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                             text=True, bufsize=1)
                self._child.stdin.write(json.dumps({"text": text, "prefix": "query"}) + "\n")
                self._child.stdin.flush()
                line = self._child.stdout.readline()
                vector = json.loads(line) if line else None
            except (OSError, ValueError):
                vector = None
            if vector is None:
                self._stop()
            else:
                self._later()
            return vector

    def _later(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.idle, self.stop)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        if self._child is not None:
            try:
                self._child.stdin.close()
                self._child.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                self._child.kill()
            self._child = None


def _main(folder: str, serve: bool = False) -> None:
    vector = _loader(folder)
    if not serve:
        sys.stdout.write(json.dumps([vector(text) for text in json.loads(sys.stdin.read())]))
        return
    for line in sys.stdin:  # one search a line until the service closes the pipe
        ask = json.loads(line)
        sys.stdout.write(json.dumps(vector(ask["text"], ask.get("prefix", "query"))) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _main(sys.argv[1], "--serve" in sys.argv[2:])
