"""What Magpiary is doing right now, for the live progress strip and the Activity page.

Two lanes work in parallel, each on one item at a time: "fetch" (details and download) and
"process" (transcript, frames, summary). Each step's start and end is also saved per item, which
gives the "how long it took" numbers.
"""

import threading
import time
from collections.abc import Callable

STEPS = {"fetch": "Reading details", "download": "Downloading", "transcribe": "Transcribing",
         "frames": "Picking frames", "summary": "Summarising", "links": "Finding links", "screen": "Reading on-screen text"}
LANES = {"fetch": "Fetching", "process": "Summarising"}


def label_for(item: dict) -> str:
    kind = item.get("kind") or {"youtube": "video"}.get(item.get("source"), "post")
    who = item.get("author") or ""
    source = {"x": "X", "youtube": "YouTube", "linkedin": "LinkedIn"}.get(item.get("source"), str(item.get("source", "")).title())
    return f"{source} {kind}" + (f" by {who}" if who else "")


class Progress:
    """Handed to the fetch and process code: `step("download")`, `percent(42.0)`."""

    def __init__(self, activity: "Activity | None" = None, lane: str = ""):
        self.activity, self.lane = activity, lane

    def step(self, name: str) -> None:
        if self.activity:
            self.activity.step(self.lane, name)

    def percent(self, value: float) -> None:
        if self.activity:
            self.activity.percent(self.lane, value)


NO_PROGRESS = Progress()


class Activity:
    def __init__(self, store, clock: Callable[[], float] = time.time):
        self.store, self.clock = store, clock
        self._lock = threading.Lock()
        self._lanes: dict[str, dict] = {}

    def begin(self, lane: str, item: dict) -> Progress:
        with self._lock:
            self._lanes[lane] = {"url": item["canonical_url"], "item_id": item.get("id") or self.store.id_for(item["canonical_url"]),
                                 "label": label_for(item), "step": "", "step_started": self.clock(), "percent": None,
                                 "started": self.clock()}
        return Progress(self, lane)

    def step(self, lane: str, name: str) -> None:
        with self._lock:
            current = self._lanes.get(lane)
            if not current:
                return
            self._close(current)
            current.update(step=name, step_started=self.clock(), percent=None)

    def percent(self, lane: str, value: float) -> None:
        with self._lock:
            if lane in self._lanes:
                self._lanes[lane]["percent"] = max(0.0, min(100.0, round(value, 1)))

    def end(self, lane: str) -> None:
        with self._lock:
            current = self._lanes.pop(lane, None)
            if current:
                self._close(current)

    def _close(self, current: dict) -> None:
        if current["step"]:
            self.store.record_timing(current["url"], current["step"], current["step_started"], self.clock())

    def busy_urls(self) -> dict[str, str]:
        with self._lock:
            return {lane["url"]: lane["step"] for lane in self._lanes.values()}

    def snapshot(self) -> dict:
        now = self.clock()
        with self._lock:
            lanes = [{"lane": name, "lane_label": LANES.get(name, name), "item_id": v["item_id"], "label": v["label"],
                      "step": v["step"], "step_label": STEPS.get(v["step"], "Starting"), "percent": v["percent"],
                      "step_seconds": round(now - v["step_started"], 1), "seconds": round(now - v["started"], 1)}
                     for name, v in sorted(self._lanes.items())]
        from magpiary import keys, modes

        waiting = self.store.waiting_counts()
        has_key = bool(modes.summarisers(self.store, keys))
        budget = self.store.summary_budget()
        stopped = budget != "all" and not budget.strip("0")
        paused_any = self.store.paused("transcribe") or self.store.paused("summary") or stopped
        return {"busy": bool(lanes), "lanes": lanes, "waiting": waiting, "has_key": has_key, "paused_any": paused_any,
                # summaries cannot start without a key, so they are not "waiting" in the strip
                "waiting_total": waiting["fetch"] + (waiting["process"] if has_key else 0)}
