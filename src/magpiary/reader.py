"""A page saved as the owner saw it in Chrome ("Save what I see"), drawn from its article.json: for the Read tab and for
its PDF. Built from the blocks only (every word escaped, pictures from the post's own folder), never the page's HTML.

The PDF is made on this Mac by the browser it already has (headless Chrome, Chromium, Edge or Brave), from a file with
every picture inside it and the network shut: nothing is requested while it is drawn."""

import base64
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from magpiary import ui
from magpiary.web import e

MIME = {".jpg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}


def byline(article: dict) -> str:
    return " · ".join(x for x in (article.get("byline", ""), article.get("site", ""),
                                  ui.day(article.get("published") or "") or "") if x)


def blocks_html(article: dict, folder: Path, src: Callable[[str], str], embed: Callable[[str], str] | None = None,
                videos: bool = True) -> str:
    """The blocks in reading order. `src` turns a file in the post's folder into an address (a hub link, or the picture
    itself for a PDF); `embed` draws a link to something embedded on the page."""
    out, items, ordered = [], [], False
    gallery: list[str] = []
    gallery_id = None

    def close_list():
        nonlocal items
        if items:
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            items = []

    def close_gallery():
        nonlocal gallery, gallery_id
        if len(gallery) > 1:
            out.append(f'<div class="rdgal" style="--n:{min(len(gallery), 4)}">{"".join(gallery)}</div>')
        else:
            out.extend(gallery)
        gallery, gallery_id = [], None

    for b in article.get("blocks") or []:
        kind = b.get("t") if isinstance(b, dict) else None
        if kind != "li":
            close_list()
        if not (kind == "img" and b.get("group") and b.get("group") == gallery_id):
            close_gallery()
        if kind == "h":
            level = min(max(int(b.get("level") or 2), 2), 4)
            out.append(f'<h{level + 1}>{e(b.get("text", ""))}</h{level + 1}>')
        elif kind == "p":
            out.append(f'<p>{e(b.get("text", ""))}</p>')
        elif kind == "row":
            out.append('<p class="rdrow">' + "".join(f"<span>{e(i)}</span>" for i in b.get("items") or [] if isinstance(i, str)) + "</p>")
        elif kind == "li":
            if not items:
                ordered = b.get("ordered") is True
            items.append(f'<li>{e(b.get("text", ""))}</li>')
        elif kind == "quote":
            out.append(f'<blockquote>{e(b.get("text", ""))}</blockquote>')
        elif kind == "code":
            out.append(f'<pre><code>{e(b.get("text", ""))}</code></pre>')
        elif kind == "caption":
            out.append(f'<p class="rdcap">{e(b.get("text", ""))}</p>')
        elif kind in ("img", "video") and b.get("file") and (folder / Path(str(b["file"])).name).is_file():
            name = Path(str(b["file"])).name
            if name.endswith(".mp4"):
                if not videos:
                    continue
                media = f'<video src="{e(src(name))}" controls preload="metadata"></video>'
            else:
                media = f'<img src="{e(src(name))}" alt="{e(b.get("alt", ""))}" loading="lazy">'
            cap = f'<figcaption>{e(b.get("caption", ""))}</figcaption>' if b.get("caption") else ""
            if kind == "img" and b.get("group"):  # shown side by side on the page: kept together
                gallery_id = b["group"]
                gallery.append(f"<figure>{media}{cap}</figure>")
            else:
                out.append(f"<figure>{media}{cap}</figure>")
        elif kind == "embed" and embed and str(b.get("src", "")).startswith(("https://", "http://")):
            out.append(f'<p class="rdcap">{embed(str(b["src"]))}</p>')
    close_list()
    close_gallery()
    return "".join(out)


PRINT_CSS = """
@page { size: A4; margin: 18mm 18mm 20mm; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font: 11.5pt/1.6 Georgia, "Iowan Old Style", "Times New Roman", serif; color: #161616; margin: 0; }
.top { font: 9pt/1.4 -apple-system, "Helvetica Neue", sans-serif; color: #777; border-bottom: 1px solid #e4e4e4;
       padding-bottom: 8px; margin-bottom: 18px; word-break: break-all; }
h1 { font: 700 22pt/1.2 -apple-system, "Helvetica Neue", sans-serif; margin: 0 0 6px; }
.by { font: 10pt/1.4 -apple-system, "Helvetica Neue", sans-serif; color: #666; margin: 0 0 22px; }
h3, h4, h5 { font-family: -apple-system, "Helvetica Neue", sans-serif; line-height: 1.3; margin: 20px 0 8px; break-after: avoid; }
h3 { font-size: 15pt; } h4 { font-size: 13pt; } h5 { font-size: 11.5pt; }
p { margin: 0 0 11px; orphans: 3; widows: 3; }
ul, ol { margin: 0 0 11px; padding-left: 20px; } li { margin: 3px 0; }
blockquote { margin: 0 0 11px; padding: 1px 0 1px 12px; border-left: 3px solid #ddd; color: #555; font-style: italic; }
pre { background: #f5f5f3; border-radius: 6px; padding: 9px 11px; font: 9pt/1.45 Menlo, monospace; white-space: pre-wrap; margin: 0 0 11px; }
figure { margin: 16px 0; break-inside: avoid; }
figure img { display: block; max-width: 100%; max-height: 125mm; width: auto; height: auto; object-fit: contain; margin: 0 auto; border-radius: 4px; }
.rdrow { display: flex; flex-wrap: wrap; gap: 6px; font: 9.5pt/1.3 -apple-system, "Helvetica Neue", sans-serif; margin: 0 0 12px; }
.rdrow span { border: 1px solid #e2e2e2; border-radius: 999px; padding: 3px 10px; color: #444; }
.rdgal { display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: 8px; margin: 16px 0; break-inside: avoid; }
.rdgal figure { margin: 0; } .rdgal figure img { width: 100%; max-height: 90mm; object-fit: cover; }
figcaption, .rdcap { font: 9pt/1.4 -apple-system, "Helvetica Neue", sans-serif; color: #777; text-align: center; margin-top: 6px; }
.note { font: 10pt -apple-system, sans-serif; background: #fff4d6; padding: 10px 14px; border-radius: 8px; margin-bottom: 18px; }
@media print { .note { display: none; } }
"""


def print_html(article: dict, folder: Path, url: str, note: str = "") -> str:
    """One self-contained page for the PDF: every picture inside it, so drawing it needs no network."""
    def inline(name: str) -> str:
        path = folder / name
        return f"data:{MIME.get(path.suffix, 'application/octet-stream')};base64,{base64.b64encode(path.read_bytes()).decode()}"

    title = article.get("title") or ""
    return (f'<!doctype html><html lang="{e(article.get("lang") or "en")}"><head><meta charset="utf-8">'
            # no script runs and nothing loads but the pictures inside the page (headless Chrome won't print with scripts off)
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'">'
            f'<title>{e(title or "Saved page")}</title><style>{PRINT_CSS}</style></head><body>'
            + (f'<div class="note">{note}</div>' if note else "")
            + f'<div class="top">{e(url)}</div>'
            + (f"<h1>{e(title)}</h1>" if title else "")
            + (f'<p class="by">{e(byline(article))}</p>' if byline(article) else "")
            + blocks_html(article, folder, inline, embed=lambda u: e(u), videos=False)
            + "</body></html>")


def filename(article: dict) -> str:
    """A tidy file name from the title: letters, digits and dashes only."""
    words = re.sub(r"[^A-Za-z0-9]+", "-", article.get("title") or "").strip("-")[:80].strip("-")
    return f"{words or 'saved-page'}.pdf"


def make_pdf(html: str, browsers: tuple[str, ...] | None = None) -> bytes | None:
    """The page as a PDF, drawn by a browser on this Mac with a fresh empty profile and every request refused.
    None when no browser is there or it failed (the caller then offers the browser's own Save as PDF)."""
    from magpiary.sources import BROWSERS

    binary = next((b for b in (browsers or BROWSERS) if Path(b).exists()), None)
    if not binary:
        return None
    work = Path(tempfile.mkdtemp(prefix="magpiary-pdf-"))  # 0700 by mkdtemp
    try:
        page, out = work / "page.html", work / "page.pdf"
        page.write_text(html)
        page.chmod(0o600)
        result = subprocess.run([binary, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                                 "--disable-extensions", "--mute-audio", f"--user-data-dir={work / 'profile'}",
                                 "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>",  # nothing leaves
                                 "--no-pdf-header-footer",
                                 f"--print-to-pdf={out}", page.as_uri()],
                                capture_output=True, timeout=90)
        data = out.read_bytes() if result.returncode == 0 and out.exists() else b""
        return data if data.startswith(b"%PDF") else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
