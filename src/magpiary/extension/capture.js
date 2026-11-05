/* "Save what I see": runs in the open tab only when the owner ticks the box and saves. It reads the page as it is drawn:
 * the main article or gallery, in reading order, as plain blocks (headings, paragraphs, lists, quotes, code, pictures,
 * videos). Things the page lays side by side (a row of tags, an author line, pictures in a grid) stay side by side.
 * Menus, headers, footers, sidebars, buttons, forms, hidden and screen-reader-only text and lone counts are left out. It changes nothing on the
 * page, makes no request, and reads no cookies or storage. The last value is the result handed to the extension. */
(() => {
  const MAX_BLOCKS = 4000, MAX_TEXT = 1500000, MIN_PICTURE = 120;
  const SKIP_TAGS = new Set(["NAV", "FOOTER", "ASIDE", "FORM", "BUTTON", "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS", "INPUT", "SELECT", "TEXTAREA", "DIALOG", "MENU"]);
  const SKIP_ROLES = /^(navigation|banner|contentinfo|complementary|dialog|alertdialog|menu|menubar|toolbar|search|form|tablist)$/;
  const SKIP_NAMES = /(^|[\s_-])(comments?|related|recommend\w*|share|sharing|social|newsletter|subscribe|promo|sidebar|footer|navbar|menu|cookie|consent|signup|sign-up|login|follow)([\s_-]|$)/i;
  const BLOCK = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "FIGURE", "FIGCAPTION", "IMG", "PICTURE", "VIDEO", "IFRAME", "DIV", "SECTION", "ARTICLE", "MAIN", "TABLE", "HR", "HEADER"]);

  const meta = (sel) => { const el = document.querySelector(sel); return el ? (el.getAttribute("content") || "").trim() : ""; };
  const tidy = (s) => String(s || "").replace(/[ \t ]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  const NOISE = /^[\d\s.,:;+%·•|()kKmM-]{0,8}$/;   // a count or a separator on its own ("62", "·") says nothing without its icon
  const http = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : ""; } catch (_) { return ""; } };

  function hidden(el) {
    if (el.getAttribute("aria-hidden") === "true" || el.hidden) return true;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0) return true;
    if (cs.display === "contents") return false;
    const r = el.getBoundingClientRect();   // text only for screen readers: a box of a pixel, or clipped away
    return (r.width <= 1 || r.height <= 1) && (cs.overflow === "hidden" || cs.position === "absolute" || cs.clip !== "auto" || cs.clipPath !== "none");
  }

  /** Whether nothing between this node and the page hides it (a picture or text inside a hidden box was never seen). */
  function shown(node) {
    for (let n = node; n && n !== document.body; n = n.parentElement) if (n.nodeType === Node.ELEMENT_NODE && hidden(n)) return false;
    return true;
  }

  /** The text of an element as seen: hidden descendants left out (innerText keeps text that is only transparent or
   *  clipped away). pre: keep the spacing, for code. */
  function seen(el, pre = false) {
    let out = "";
    for (const n of el.childNodes) {
      if (n.nodeType === Node.TEXT_NODE) out += pre ? n.textContent : n.textContent.replace(/\s+/g, " ");
      else if (n.nodeType !== Node.ELEMENT_NODE || SKIP_TAGS.has(n.tagName) || hidden(n)) continue;
      else if (n.tagName === "BR") out += "\n";
      else {
        const block = !getComputedStyle(n).display.startsWith("inline");
        out += (block ? "\n" : "") + seen(n, pre) + (block ? "\n" : "");
      }
    }
    return out;
  }

  function skip(el, keepHeader) {
    if (SKIP_TAGS.has(el.tagName)) return true;
    if (el.tagName === "HEADER" && !(keepHeader && el.querySelector("h1"))) return true;   // a page's top bar, but not an article's title block
    const role = el.getAttribute("role") || "";
    if (SKIP_ROLES.test(role)) return true;
    if ((role === "button" || role === "switch") && tidy(el.textContent).length < 40) return true;   // a control, not content
    const names = `${typeof el.className === "string" ? el.className : ""} ${el.id || ""}`;
    if (names.trim() && SKIP_NAMES.test(names)) return true;
    return hidden(el);
  }

  /** The largest picture the page offers for an <img>: its srcset (and its <picture>'s sources), else what it shows. */
  function bestSource(img) {
    const sets = [img.getAttribute("srcset") || "", img.getAttribute("data-srcset") || ""];
    const pic = img.parentElement && img.parentElement.tagName === "PICTURE" ? img.parentElement : null;
    if (pic) for (const s of pic.querySelectorAll("source")) sets.push(s.getAttribute("srcset") || "");
    let best = "", bestW = 0;
    for (const set of sets) {
      for (const part of set.split(/,\s+(?=\S)/)) {
        const [u, d] = part.trim().split(/\s+/);
        const w = d && /w$/.test(d) ? parseInt(d, 10) : d && /x$/.test(d) ? parseFloat(d) * 1000 : 1;
        if (u && http(u) && w > bestW) { best = http(u); bestW = w; }
      }
    }
    const shown = img.currentSrc && !img.currentSrc.startsWith("data:") ? http(img.currentSrc) : "";
    const lazy = http(img.getAttribute("data-src") || img.getAttribute("data-original") || "");
    return best || shown || http(img.getAttribute("src") || "") || lazy;
  }

  function bigEnough(img) {
    const r = img.getBoundingClientRect();
    return Math.max(r.width, img.naturalWidth || 0) >= MIN_PICTURE && Math.max(r.height, img.naturalHeight || 0) >= MIN_PICTURE / 2;
  }

  /** Where the article or gallery is: the <article> (or <main>) with the most to read; else, from the top of the page,
   *  the tightest block that still holds most of the paragraphs and large pictures. One pass over the page. */
  function findRoot() {
    const scores = new Map();
    const add = (el, n) => { for (let a = el.parentElement, i = 0; a && i < 40; a = a.parentElement, i++) scores.set(a, (scores.get(a) || 0) + n); };
    for (const p of document.querySelectorAll("p, li, blockquote, pre, h2, h3")) add(p, Math.min(tidy(p.textContent).length, 2000));
    for (const img of document.querySelectorAll("img")) if (bigEnough(img)) add(img, 400);
    let best = null, bestScore = 0;
    for (const el of document.querySelectorAll("article, main, [role=main]")) {
      const s = scores.get(el) || 0;
      if (s > bestScore && !hidden(el)) { best = el; bestScore = s; }
    }
    if (best && bestScore >= 600) return best;
    let el = document.body;
    for (;;) {
      const total = scores.get(el) || 0;
      const next = [...el.children].find((c) => (scores.get(c) || 0) >= total * 0.85);
      if (!next || total < 600) return el;
      el = next;
    }
  }

  const root = findRoot();
  const blocks = [];
  let text = 0, title = "";

  function push(block) {
    if (blocks.length >= MAX_BLOCKS) return;
    if (block.text !== undefined) {
      block.text = tidy(block.text);
      if (!block.text || (block.t === "p" && NOISE.test(block.text)) || text + block.text.length > MAX_TEXT) return;
      text += block.text.length;
    }
    blocks.push(block);
  }

  let group = 0;   // pictures the page shows side by side share a group number

  function picture(img, inGroup = 0) {
    const src = bestSource(img);
    if (!src || !bigEnough(img) || !shown(img) || blocks.some((b) => b.t === "img" && b.src === src)) return;
    // every other address the picture goes by: the browser's own copy of the page may hold any one of these sizes
    const also = [img.currentSrc, img.getAttribute("src"), ...(img.getAttribute("srcset") || "").split(/,\s+(?=\S)/).map((c) => c.trim().split(/\s+/)[0])]
      .map((u) => (u && !u.startsWith("data:") ? http(u) : "")).filter((u, i, all) => u && u !== src && all.indexOf(u) === i).slice(0, 8);
    push({ t: "img", src, also, alt: (img.getAttribute("alt") || "").slice(0, 500), ...(inGroup ? { group: inGroup } : {}) });
  }

  /** An item's words, leaving out the controls and hidden parts inside it (a chip's "+" button, screen-reader text). */
  function words(el) {
    let out = "";
    for (const n of el.childNodes) {
      if (n.nodeType === Node.TEXT_NODE) out += n.textContent;
      else if (n.nodeType === Node.ELEMENT_NODE && !skip(n, false)) out += (getComputedStyle(n).display.startsWith("inline") ? "" : " ") + words(n);
    }
    return out;
  }

  /** The one large picture an element holds, when it holds next to no text (a tile in a grid). */
  function onlyPicture(el) {
    if (el.tagName === "IMG") return bigEnough(el) ? el : null;
    if (tidy(el.innerText).length > 2) return null;
    const big = [...el.querySelectorAll("img")].filter(bigEnough);
    return big.length === 1 ? big[0] : null;
  }

  /** Children the page draws side by side: all on one line, or in a row that wraps (a flex row of chips). Only short
   *  items or pictures count, so a page's two big columns are still read one after the other. */
  function sideBySide(el) {
    const kids = [...el.children].filter((k) => !skip(k, false) && k.getBoundingClientRect().width > 0);
    if (kids.length < 2 || kids.length > 24) return null;
    const pics = kids.map(onlyPicture);
    const texts = kids.map((k) => tidy(words(k)).replace(/\s+/g, " "));
    const allPics = pics.every(Boolean), allShort = pics.every((p) => !p) && texts.every((w) => w.length <= 120);
    if (!allPics && !allShort) return null;
    const rs = kids.map((k) => k.getBoundingClientRect());
    const cs = getComputedStyle(el);
    const flexRow = (cs.display.includes("flex") && !cs.flexDirection.startsWith("column"))
      || (cs.display.includes("grid") && rs.some((r, i) => i && Math.abs(r.top - rs[0].top) < 4));   // a grid with more than one column
    const top = Math.max(...rs.map((r) => r.top)), bottom = Math.min(...rs.map((r) => r.bottom));
    const oneLine = bottom - top >= 4 && rs.every((r, i) => !i || r.left >= rs[i - 1].right - 2);
    if (!flexRow && !oneLine) return null;
    return allPics ? { pics } : { words: texts };
  }

  function hasBlockChild(el) {
    for (const c of el.children) if (BLOCK.has(c.tagName) && !hidden(c)) return true;
    return false;
  }

  function walk(el, depth) {
    if (depth > 60 || blocks.length >= MAX_BLOCKS || skip(el, true)) return;
    const tag = el.tagName;
    if (/^H[1-6]$/.test(tag)) {
      const t = tidy(seen(el));
      if (tag === "H1" && !title) { title = t; return; }
      push({ t: "h", level: Number(tag[1]), text: t });
      return;
    }
    if (tag === "IMG") { picture(el); return; }
    if (tag === "VIDEO") {
      const src = el.currentSrc && !el.currentSrc.startsWith("blob:") ? http(el.currentSrc) : http((el.querySelector("source") || {}).src || "");
      const poster = http(el.getAttribute("poster") || "");
      if (src || poster) push({ t: "video", src, poster });
      return;
    }
    if (tag === "IFRAME") { const src = http(el.getAttribute("src") || ""); if (src) push({ t: "embed", src }); return; }
    if (tag === "FIGCAPTION") {
      const last = blocks[blocks.length - 1];
      const t = tidy(seen(el));
      if (last && last.t === "img" && !last.caption) last.caption = t.slice(0, 2000); else push({ t: "caption", text: t });
      return;
    }
    if (tag === "PRE") { push({ t: "code", text: seen(el, true) }); return; }
    if (tag === "BLOCKQUOTE" && !hasBlockChild(el)) { push({ t: "quote", text: seen(el) }); return; }
    if (tag === "LI") {
      push({ t: "li", ordered: el.parentElement && el.parentElement.tagName === "OL", text: seen(el) });
      for (const img of el.querySelectorAll("img")) picture(img);
      return;
    }
    if (tag === "P" || (!hasBlockChild(el) && tidy(el.innerText) && !["UL", "OL", "TABLE", "FIGURE", "PICTURE"].includes(tag))) {
      for (const img of el.querySelectorAll("img")) picture(img);   // a picture set inside a paragraph keeps its place
      push({ t: "p", text: seen(el) });
      return;
    }
    const row = sideBySide(el);
    if (row && row.pics) {
      group += 1;
      for (const img of row.pics) picture(img, group);
      return;
    }
    if (row) {
      const items = row.words.filter((w) => w && !NOISE.test(w));
      if (items.length > 1) push({ t: "row", items: items.slice(0, 20).map((w) => w.slice(0, 300)) });
      else if (items.length) push({ t: "p", text: items[0] });
      return;
    }
    for (const child of el.children) walk(child, depth + 1);
  }

  walk(root, 0);
  if (!title) title = meta('meta[property="og:title"]') || tidy(document.title);
  const byEl = root.querySelector('[rel="author"], [itemprop="author"]');
  const timeEl = root.querySelector("time[datetime]");
  return {
    title: title.slice(0, 500),
    byline: (meta('meta[name="author"]') || (byEl ? tidy(byEl.innerText) : "")).slice(0, 300),
    published: (meta('meta[property="article:published_time"]') || (timeEl ? timeEl.getAttribute("datetime") : "") || "").slice(0, 40),
    site: meta('meta[property="og:site_name"]').slice(0, 200),
    lang: (document.documentElement.lang || "").slice(0, 20),
    blocks,
  };
})();
