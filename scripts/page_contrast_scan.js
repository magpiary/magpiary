(() => {
  const parse = (s) => { const srgb = s.match(/color\(srgb ([^)]+)\)/); if (srgb) { const q = srgb[1].split(/[ \/]+/).filter(Boolean).map(Number); return { r: q[0] * 255, g: q[1] * 255, b: q[2] * 255, a: q.length > 3 ? q[3] : 1 }; } const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lin = (c) => { c /= 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; };
  const L = (c) => .2126 * lin(c.r) + .7152 * lin(c.g) + .0722 * lin(c.b);
  const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
  const bgOf = (el) => { let stack = []; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none') return null; const c = parse(cs.backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a === 1) break; } } let base = { r: 255, g: 255, b: 255, a: 1 }; if (!stack.length || stack[stack.length - 1].a < 1) { const bc = parse(getComputedStyle(document.body).backgroundColor); base = bc && bc.a ? bc : base; } for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base); return base; };
  const opac = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const bad = {}; let n = 0, skipped = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const t = walker.currentNode; if (!t.textContent.trim()) continue; const el = t.parentElement; if (!el || el.closest('script,style,noscript,svg')) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const bg = bgOf(el); if (!bg) { skipped++; continue; }
    let fg = parse(cs.color); if (!fg) continue; fg = { ...fg, a: fg.a * opac(el) };
    const f = over(fg, bg); const l1 = L(f), l2 = L(bg); const ratio = (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700; const large = size >= 24 || (size >= 18.66 && bold);
    n++; if (ratio < (large ? 3 : 4.5)) { const k = (el.className || el.tagName).toString().slice(0, 30) + ' | ' + cs.color + ' on rgb(' + [bg.r, bg.g, bg.b].map(Math.round) + ')'; bad[k] = bad[k] || { ratio: +ratio.toFixed(2), n: 0, ex: t.textContent.trim().slice(0, 30) }; bad[k].n++; }
  }
  return { checked: n, skippedGradient: skipped, failing: Object.entries(bad).sort((a, b) => a[1].ratio - b[1].ratio).slice(0, 8) };
})()
