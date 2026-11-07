"""Hub media responses: archived files, byte ranges, thumbnails and the profile photo.

Routes and the local-access and lock checks stay in Hub. Files are still resolved
inside the configured library before a response is streamed by the receiver.
"""

import os
import re
from pathlib import Path
from urllib.parse import quote

from magpiary import phone_video, thumbs
from magpiary.store import Store
from magpiary.web import Response

MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MEDIA_NAME = re.compile(r"^(media-\d{2,3}\.[a-z0-9]{2,4}|thumbnail\.jpg|screen\.jpg)$")

THUMB_WIDTH = 600
THUMB_VERSION = 2  # in the address: browsers keep a tile's picture for a year, so a better copy needs a new address
MEDIA_CACHE_SECONDS = 3600
PHOTO_CACHE_SECONDS = 365 * 24 * 3600


class MediaPages:
    store: Store
    library: Path | None

    def _media(
        self, item_id: int, name: str, range_header: str, width: str = "", user_agent: str = "", if_range: str = ""
    ) -> Response:
        item = self.store.item_by_id(item_id)
        if (
            not item
            or not item.get("archive_dir")
            or not MEDIA_NAME.match(name)
            or self.library is None
        ):
            return Response(404, b"not found", "text/plain")
        folder = Path(item["archive_dir"]).resolve()
        path = (folder / name).resolve()
        if (
            not folder.is_relative_to(self.library.resolve())
            or path.parent != folder
            or not path.is_file()
        ):
            return Response(404, b"not found", "text/plain")
        if phone_video.is_iphone(user_agent) and re.fullmatch(r"media-\d{2,3}\.mp4", name):
            state = phone_video.ensure(path)
            if state == "converting":
                return Response(503, b"Getting this video ready for your iPhone. Try again in a minute.", "text/plain",
                                headers={"Retry-After": "20"})
        if (
            width.isdigit()
            and not range_header
            and (copy := thumbs.small(path, int(width)))
        ):
            path = copy
        try:
            f = open(path, "rb")  # one open file: its size and its bytes can never come from two different files
        except OSError:
            return Response(404, b"not found", "text/plain")
        response = self._ranged(f, path, range_header, if_range)
        if response.stream is None:
            f.close()
        return response

    @staticmethod
    def _ranged(f, path: Path, range_header: str, if_range: str) -> Response:
        """Answer from the open file `f`: the whole file, or the part Range asks for. A conversion that swaps the
        path afterwards cannot change what this answer sends."""
        info = os.fstat(f.fileno())
        size = info.st_size
        etag = f'"{size:x}-{info.st_mtime_ns:x}"'  # strong validator: changes whenever the bytes are replaced
        start, end = 0, size - 1
        status = 200
        if if_range and if_range.strip() != etag:
            range_header = ""  # the caller's copy is another version: send all of this one
        if m := re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip()):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            elif m.group(2):
                start = max(size - int(m.group(2)), 0)
            if start > end or start >= size:
                return Response(416, b"", "text/plain", headers={"Content-Range": f"bytes */{size}"})
            status = 206
        headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": f"private, max-age={MEDIA_CACHE_SECONDS}",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        response = Response(status, b"", MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"), headers)
        response.stream = (f, start, end - start + 1)
        return response

    def _profile_photo(self) -> Response:
        from magpiary import identity

        try:
            data = identity.photo_path().read_bytes()
        except OSError:
            return Response(404, b"not found", "text/plain")
        return Response(
            200,
            data,
            "image/jpeg",
            {
                "Cache-Control": f"private, max-age={PHOTO_CACHE_SECONDS}",
                "X-Content-Type-Options": "nosniff",
            },
        )

    def _media_url(self, item: dict, name: str) -> str:
        return f"/media/{item['id']}/{quote(name)}"

    def thumb_url(self, item: dict) -> str:
        """A tile's picture: a 600 px copy, not the full-size one."""
        return (
            self._media_url(item, item["thumb"]) + f"?w={THUMB_WIDTH}&v={THUMB_VERSION}"
            if item.get("thumb") and item.get("archive_dir")
            else ""
        )
