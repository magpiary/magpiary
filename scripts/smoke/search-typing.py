"""Search typing check: typing never waits on a stale search. No browser needed.
Run: uv run python scripts/smoke/search-typing.py   (the live feel is checked in the installed hub)."""
import re
from pathlib import Path
src = Path(__file__).resolve().parents[2] / "src/magpiary"
js = (src / "static/hub.js").read_text()
hub = (src / "hub.py").read_text()
assert "async function getDoc(url, signal)" in js, "page fetch must accept an abort signal"
assert "navAbort?.abort()" in js and 'e.name === "AbortError"' in js, "a newer search must cancel the one in flight, quietly"
assert "opts.seq !== typeSeq" in js, "a page fetched for older text must not be drawn"
assert js.count('"quick"') >= 4 and 'opts.typing ? "quick"' in js, "typed searches must swap without the Flip measuring pass"
assert "typeSeq++; hintAbort?.abort();" in js and "signal: ac.signal" in js, "stale suggestions must be cancelled"
m = re.search(r"\}, (\d+)\);\s*const g = G\(\);\s*if \(g && input === q2\)", js)
assert m and int(m.group(1)) >= 400, "page search must wait for a real pause in typing"
assert "if not words:" in hub.split("def _search_json")[1].split("views =")[0], "type counts must only run for an empty box"
print("search typing smoke: ok")
