"""Your activity: counts kept on this Mac only, so you can see whether you come back and use what you saved. Nothing is sent anywhere."""
from __future__ import annotations

from datetime import timedelta

from magpiary.web import Response, e

KINDS = [("link", "Links opened", "Tool and place links opened from posts"),
         ("copy", "Summaries copied", "Copied to paste into notes or a brief"),
         ("board", "Posts added to boards", "Posts gathered for a project"),
         ("ask", "Questions asked", "Questions put to Ask Magpiary"),
         ("tried", "Digest picks tried", "Suggestions you marked as tried")]
DAYS = 30
CLIENT_KINDS = {"link", "copy"}  # the page reports these; the Mac counts the remaining kinds itself


class ActivityPages:
    def activity_post(self, form: dict) -> Response:
        action = form.get("action", "")
        if action == "clear":
            self.store.activity_clear()
        elif form.get("kind") in CLIENT_KINDS:
            self.store.activity_add(form["kind"])
        if form.get("next"):
            nxt = form["next"]
            return Response(303, b"", headers={"Location": nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"})
        return Response(200, b"ok", "text/plain")

    def _activity_summary(self, data: dict[str, dict[str, int]]) -> str:
        lines = [f"Magpiary activity, last {DAYS} days"]
        for key, title, _ in KINDS:
            lines.append(f"{title}: {sum(data.get(key, {}).values())}")
        return "\n".join(lines)

    def activity_group(self) -> str:
        data = self.store.activity_days(DAYS)
        today = self.store._now().date()
        days = [(today - timedelta(days=DAYS - 1 - i)).isoformat() for i in range(DAYS)]
        cells = []
        for key, title, hint in KINDS:
            per = data.get(key, {})
            total = sum(per.values())
            top = max([per.get(d, 0) for d in days] + [1])
            bars = "".join(
                f'<i style="height:{max(6, round(per.get(d, 0) / top * 100)) if per.get(d, 0) else 6}%"'
                f'{" class=on" if per.get(d, 0) else ""}></i>' for d in days)
            cells.append(f'<div class="actcell"><b>{total}</b><span>{e(title)}</span><small>{e(hint)}</small>'
                         f'<div class="actbars" aria-hidden="true">{bars}</div></div>')
        body = (f'<div class="actgrid">{"".join(cells)}</div>'
                '<div class="actrow">'
                f'<button type="button" class="btn sm" data-copycode="{e(self._activity_summary(data))}" data-copywhat="Activity summary">Copy summary</button>'
                + self._form("/hub/activity", {"action": "clear", "next": "/settings/privacy"}, "Clear activity", "btn sm danger",
                             confirm="Clear all activity counts? Your saves are not touched.")
                + "</div>")
        from magpiary.hub_settings import _group

        return _group("Your activity", body, gid="activity", cls="wide plain",
                      desc=f"The last {DAYS} days, counted on this Mac only. Nothing is sent anywhere; Copy summary gives you text to share if you choose.")
