/* "Save what I see": runs in the open tab only when the owner ticks the box and saves. It reads the page as it is drawn:
 * the main article or gallery, in reading order, as plain blocks (headings, paragraphs, lists, quotes, code, pictures,
 * videos). Menus, headers, footers, sidebars, buttons, forms and hidden parts are left out. It changes nothing on the
 * page, makes no request, and reads no cookies or storage. The last value is the result handed to the extension. */
(() => {
  const MAX_BLOCKS = 4000, MAX_TEXT = 1500000, MIN_PICTURE = 120;
  const SKIP_TAGS = new Set(["NAV", "FOOTER", "ASIDE", "FORM", "BUTTON", "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS", "INPUT", "SELECT", "TEXTAREA", "DIALOG", "MENU"]);
  const SKIP_ROLES = /^(navigation|banner|contentinfo|complementary|dialog|alertdialog|menu|menubar|toolbar|search|form|tablist)$/;
  const SKIP_NAMES = /(^|[\s_-])(comments?|related|recommend\w*|share|sharing|social|newsletter|subscribe|promo|sidebar|footer|navbar|menu|cookie|consent|signup|sign-up|login|follow)([\s_-]|$)/i;
  const BLOCK = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "FIGURE", "FIGCAPTION", "IMG", "PICTURE", "VIDEO", "IFRAME", "DIV", "SECTION", "ARTICLE", "MAIN", "TABLE", "HR", "HEADER"]);

  const meta = (sel) => { const el = document.querySelector(sel); return el ? (el.getAttribute("content") || "").trim() : ""; };
  const tidy = (s) => String(s || "").replace(/[ \t ]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  const http = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : ""; } catch (_) { return ""; } };

  function hidden(el) {
    if (el.getAttribute("aria-hidden") === "true" || el.hidden) return true;
    const cs = getComputedStyle(el);
    return cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) === 0;
  }

  function skip(el, keepHeader) {
    if (SKIP_TAGS.has(el.tagName)) return true;
    if (el.tagName === "HEADER" && !(keepHeader && el.querySelector("h1"))) return true;   // a page's top bar, but not an article's title block
    const role = el.getAttribute("role") || "";
    if (SKIP_ROLES.test(role)) return true;
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
      if (!block.text || text + block.text.length > MAX_TEXT) return;
      text += block.text.length;
    }
    blocks.push(block);
  }

  function picture(img) {
    const src = bestSource(img);
    if (!src || !bigEnough(img) || blocks.some((b) => b.t === "img" && b.src === src)) return;
    // every other address the picture goes by: the browser's own copy of the page may hold any one of these sizes
    const also = [img.currentSrc, img.getAttribute("src"), ...(img.getAttribute("srcset") || "").split(/,\s+(?=\S)/).map((c) => c.trim().split(/\s+/)[0])]
      .map((u) => (u && !u.startsWith("data:") ? http(u) : "")).filter((u, i, all) => u && u !== src && all.indexOf(u) === i).slice(0, 8);
    push({ t: "img", src, also, alt: (img.getAttribute("alt") || "").slice(0, 500) });
  }

  function hasBlockChild(el) {
    for (const c of el.children) if (BLOCK.has(c.tagName) && !hidden(c)) return true;
    return false;
  }

  function walk(el, depth) {
    if (depth > 60 || blocks.length >= MAX_BLOCKS || skip(el, true)) return;
    const tag = el.tagName;
    if (/^H[1-6]$/.test(tag)) {
      const t = tidy(el.innerText);
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
      const t = tidy(el.innerText);
      if (last && last.t === "img" && !last.caption) last.caption = t.slice(0, 2000); else push({ t: "caption", text: t });
      return;
    }
    if (tag === "PRE") { push({ t: "code", text: el.innerText }); return; }
    if (tag === "BLOCKQUOTE" && !hasBlockChild(el)) { push({ t: "quote", text: el.innerText }); return; }
    if (tag === "LI") {
      push({ t: "li", ordered: el.parentElement && el.parentElement.tagName === "OL", text: el.innerText });
      for (const img of el.querySelectorAll("img")) picture(img);
      return;
    }
    if (tag === "P" || (!hasBlockChild(el) && tidy(el.innerText) && !["UL", "OL", "TABLE", "FIGURE", "PICTURE"].includes(tag))) {
      for (const img of el.querySelectorAll("img")) picture(img);   // a picture set inside a paragraph keeps its place
      push({ t: "p", text: el.innerText });
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
