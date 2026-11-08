/* "Save what I see" for an Instagram carousel: runs in the open Instagram post only when the owner ticks the box and saves.
 * Instagram keeps just the slide on screen and its neighbours in the page, so a plain reading finds two or three of a dozen.
 * This steps through the post with its own Next button, notes each new slide picture as it appears, then steps back to
 * the first slide. It reads only the post's picture list (never the comments, avatars or the "more posts" grid), makes no
 * request, and reads no cookies or storage. The last value is a promise of the page in the same shape capture.js hands over;
 * with nothing found it has no blocks, and the extension saves the link as before. */
(async () => {
  const MAX_SLIDES = 20, BIG = 300, WAIT = 1800, STEP = 120;
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const meta = (sel) => { const el = document.querySelector(sel); return el ? (el.getAttribute("content") || "").trim() : ""; };
  const http = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : ""; } catch (_) { return ""; } };
  const name = (u) => { try { return new URL(u).pathname; } catch (_) { return u; } };   // a picture's file, whatever its query says
  const empty = { title: "", byline: "", published: "", site: "Instagram", lang: "", blocks: [] };

  const tall = (img) => Math.max(img.getBoundingClientRect().height, img.naturalHeight || 0) >= BIG;
  /** The list that holds the post's slide pictures: in the page's main part, with a tall picture that is not a link to another post. */
  function list() {
    const main = document.querySelector("main") || document.body;
    for (const img of main.querySelectorAll("ul img")) {
      if (tall(img) && !img.closest("a[href]")) return img.closest("ul");
    }
    return null;
  }
  const button = (re) => [...document.querySelectorAll("main button, main [role=button]")].find((b) => re.test(b.getAttribute("aria-label") || ""));
  const next = () => button(/^next$/i);
  const back = () => button(/^(go back|previous)$/i);

  const root = list();
  if (!root) return empty;
  const slides = [];
  const have = new Set();
  function note() {
    const ul = list();
    if (!ul) return 0;
    let added = 0;
    for (const img of ul.querySelectorAll("img")) {
      const src = http(img.currentSrc || img.getAttribute("src") || "");
      if (!src || !tall(img) || have.has(name(src))) continue;
      have.add(name(src));
      slides.push({ src, alt: (img.getAttribute("alt") || "").slice(0, 500) });
      added += 1;
    }
    return added;
  }

  note();
  let clicks = 0, stalled = 0;
  while (slides.length < MAX_SLIDES && clicks < MAX_SLIDES * 2) {
    const go = next();
    if (!go) break;                              // the last slide has no Next
    go.click();
    clicks += 1;
    let found = 0;
    for (let waited = 0; waited < WAIT && !found; waited += STEP) {   // the new neighbour draws a moment after the click
      await sleep(STEP);
      found = note();
    }
    if (found) { stalled = 0; continue; }
    if (!next()) break;
    if (++stalled >= 2) break;                   // Instagram stopped giving new pictures: keep what there is
  }
  for (let i = 0; i < MAX_SLIDES * 2 && back(); i++) { back().click(); await sleep(60); }   // leave the post on its first slide

  const text = meta('meta[property="og:description"]');
  const blocks = slides.map((s) => ({ t: "img", src: s.src, also: [], alt: s.alt }));
  if (blocks.length && text) blocks.push({ t: "p", text });
  return { ...empty, title: meta('meta[property="og:title"]') || document.title, lang: (document.documentElement.lang || "").slice(0, 20), blocks };
})();
