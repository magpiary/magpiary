/* Link cleaner: the same rules as the Mac's cleaner.py (and the phone Shortcut), so a link is cleaned before it leaves the browser.
 * The Mac cleans again as a second check. Pure functions, no network. Short links (Threads /t/, Reddit /s/, redd.it, Instagram
 * /share/, t.co, lnkd.in) come back with needsExpansion: the Mac follows them. */
(function (root) {
  const CODE = /^[A-Za-z0-9_-]+$/;
  const TRACKING = new Set(["igsh", "igshid", "xmt", "si", "s", "t", "fbclid", "gclid", "share_id",
    "ref", "ref_src", "ref_url", "referrer", "referer", "mc_cid", "mc_eid", "_ga", "_gl", "gbraid", "wbraid", "msclkid", "yclid", "dclid", "twclid", "li_fat_id", "spm", "mkt_tok", "trk", "trkid", "trkinfo", "vero_id", "oly_enc_id", "oly_anon_id", "rb_clickid", "cmpid"]);
  const FIRST_LINK = /https?:\/\/[^\s<>"']+/i;

  class Unsupported extends Error {}

  function extractLink(text) {
    const m = FIRST_LINK.exec(text || "");
    if (!m) throw new Unsupported("no link found");
    return m[0].replace(/[.,;:!?)\]}>'"]+$/, "");
  }

  function instagram(segments) {
    if (segments[0] === "share") {
      if (segments.length >= 2 && CODE.test(segments[segments.length - 1]))
        return { url: "https://www.instagram.com/" + segments.join("/") + "/", source: "instagram", needsExpansion: true };
      throw new Unsupported("instagram share link without a code");
    }
    for (let i = 0; i < segments.length - 1; i++) {
      const seg = segments[i];
      if (["reel", "reels", "p", "tv"].includes(seg) && CODE.test(segments[i + 1])) {
        const kind = { reel: "reel", reels: "reel", p: "post", tv: "tv" }[seg];
        const path = { reel: "reel", post: "p", tv: "tv" }[kind];
        return { url: `https://www.instagram.com/${path}/${segments[i + 1]}/`, source: "instagram", kind };
      }
    }
    throw new Unsupported("not an instagram post, reel or tv link");
  }

  function threads(segments) {
    if (segments[0] === "share" || segments[0] === "t") {
      if (segments.length >= 2 && CODE.test(segments[1]))
        return { url: `https://www.threads.com/${segments[0]}/${segments[1]}/`, source: "threads", needsExpansion: true };
      throw new Unsupported("threads short link without a code");
    }
    if (segments.length >= 3 && segments[0].startsWith("@") && segments[1] === "post" && CODE.test(segments[2]))
      return { url: `https://www.threads.com/${segments[0]}/post/${segments[2]}/`, source: "threads", kind: "post" };
    throw new Unsupported("not a threads post link");
  }

  function x(segments, host) {
    if (host === "t.co") {
      if (segments.length === 1 && CODE.test(segments[0])) return { url: `https://t.co/${segments[0]}`, source: "x", needsExpansion: true };
      throw new Unsupported("t.co link without a code");
    }
    if (segments.length >= 3 && ["status", "statuses"].includes(segments[1]) && /^\d+$/.test(segments[2]))
      return { url: `https://x.com/${segments[0]}/status/${segments[2]}`, source: "x", kind: "post" };
    throw new Unsupported("not an x post link");
  }

  function reddit(segments, host) {
    if (host === "redd.it") {
      if (segments.length === 1 && CODE.test(segments[0])) return { url: `https://redd.it/${segments[0]}`, source: "reddit", needsExpansion: true };
      throw new Unsupported("redd.it link without a code");
    }
    if (segments.length >= 4 && segments[0] === "r" && segments[2] === "s" && CODE.test(segments[3]))
      return { url: `https://www.reddit.com/r/${segments[1]}/s/${segments[3]}`, source: "reddit", needsExpansion: true };
    if (segments.length >= 4 && segments[0] === "r" && segments[2] === "comments" && /^[a-z0-9]+$/.test(segments[3].toLowerCase()))
      return { url: `https://www.reddit.com/r/${segments[1].toLowerCase()}/comments/${segments[3].toLowerCase()}/`, source: "reddit", kind: "post" };
    throw new Unsupported("not a reddit post link");
  }

  function linkedin(segments, host) {
    if (host === "lnkd.in") {
      if (segments.length === 2 && segments[0] === "p" && CODE.test(segments[1])) return { url: `https://lnkd.in/p/${segments[1]}`, source: "linkedin", needsExpansion: true };
      throw new Unsupported("lnkd.in link without a code");
    }
    if (segments.length && ["posts", "feed", "pulse", "events"].includes(segments[0]))
      return { url: "https://www.linkedin.com/" + segments.join("/") + "/", source: "linkedin", kind: "post" };
    throw new Unsupported("not a linkedin post link");
  }

  function other(u) {
    if (!["http:", "https:"].includes(u.protocol) || !u.hostname) throw new Unsupported("not a web link");
    const kept = [];
    for (const [k, v] of u.searchParams) if (!TRACKING.has(k.toLowerCase()) && !k.toLowerCase().startsWith("utm_")) kept.push([k, v]);
    let url = `${u.protocol}//${u.host.toLowerCase()}${u.pathname}`;
    if (kept.length) url += "?" + new URLSearchParams(kept).toString();
    return { url, source: "other" };
  }

  const HANDLERS = [
    [["instagram.com"], instagram], [["threads.net", "threads.com"], threads], [["x.com", "twitter.com", "t.co"], x],
    [["reddit.com", "redd.it"], reddit], [["linkedin.com", "lnkd.in"], linkedin],
  ];

  /** Clean a link (or text holding one). Returns {url, source, kind?, needsExpansion?} or {error}. Never throws. */
  function clean(text) {
    try {
      const u = new URL(extractLink(text));
      const host = u.hostname.toLowerCase();
      const segments = u.pathname.split("/").filter(Boolean);
      for (const [domains, handler] of HANDLERS)
        if (domains.some((d) => host === d || host.endsWith("." + d))) return handler(segments, host, u.searchParams);
      return other(u);
    } catch (err) {
      return { error: err instanceof Unsupported ? err.message : "not a web link" };
    }
  }

  root.MagpiaryClean = { clean };
  if (typeof module !== "undefined") module.exports = root.MagpiaryClean;
})(typeof globalThis !== "undefined" ? globalThis : this);
