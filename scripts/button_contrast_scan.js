// Runs in the page. Measures text-on-background contrast of every button-like element in its current state.
// Called as (mode) => rows. Elements get a data-ax id the first time.
(() => {
  const parse = (s) => { const srgb = s.match(/color\(srgb ([^)]+)\)/); if (srgb) { const q = srgb[1].split(/[ \/]+/).filter(Boolean).map(Number); return { r: q[0] * 255, g: q[1] * 255, b: q[2] * 255, a: q.length > 3 ? q[3] : 1 }; } const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lin = (c) => { c /= 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; };
  const L = (c) => .2126 * lin(c.r) + .7152 * lin(c.g) + .0722 * lin(c.b);
  const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a), b: f.b * f.a + b.b * (1 - f.a), a: 1 });
  // effective background behind el's own box (own background first, then ancestors); null if an image or gradient is in the way
  const bgOf = (el) => {
    const stack = [];
    // a selected segment sits on the group's sliding thumb (a separate element behind it), so its own background is clear
    const own = parse(getComputedStyle(el).backgroundColor);
    if ((!own || own.a === 0) && el.matches('.on, [aria-checked=true], [aria-selected=true], [aria-pressed=true]')) {
      const th = el.parentElement && el.parentElement.querySelector(':scope > .thumb');
      if (th) { const tc = parse(getComputedStyle(th).backgroundColor); if (tc && tc.a === 1) return tc; }
    }
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage !== 'none') { const c0 = parse(cs.backgroundColor); if (/url\(/.test(cs.backgroundImage) || !(c0 && c0.a > 0)) return { grad: true }; }  // a gradient over a colour (the glass buttons): the colour decides, the highlight is at most ~10% white
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { stack.push(c); if (c.a === 1) break; }
    }
    let base = parse(getComputedStyle(document.body).backgroundColor); if (!base || !base.a) base = { r: 255, g: 255, b: 255, a: 1 };
    if (stack.length && stack[stack.length - 1].a === 1) base = stack.pop();
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  const opac = (el) => { let o = 1; for (let e = el; e; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity); return o; };
  const SEL = 'button, summary, [role=button], [role=tab], [role=switch], input[type=submit], input[type=button], a.btn, label.btn, .tbtn, .vb, .chip, .pill';
  const ownText = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40);
  const path = (el) => { const a = []; for (let e = el; e && e !== document.body && a.length < 4; e = e.parentElement) a.unshift(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.classList.length ? '.' + [...e.classList].slice(0, 3).join('.') : '')); return a.join(' > '); };
  const rows = [];
  let id = window.__axn || 0;
  document.querySelectorAll(SEL).forEach((el) => {
    if (!el.dataset.ax) el.dataset.ax = String(++id);
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const rendered = !!(r.width && r.height) && cs.visibility !== 'hidden' && cs.display !== 'none' && !el.closest('[hidden]');
    const bg = bgOf(el);
    let fg0 = parse(cs.color); if (!fg0) return;
    // a switch has no label: its knob (the child span) against its track is what must be seen
    if (el.matches('.sw') && el.firstElementChild) { const k = parse(getComputedStyle(el.firstElementChild).backgroundColor); if (k) fg0 = k; }
    const o = opac(el);
    if (o < 0.05 && rendered) return;  // mid-animation or deliberately invisible
    if (el.closest('.art, [aria-hidden=true]')) return;  // illustrations of a browser or phone are drawings, not controls
    const text = ownText(el);
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const icon = !text;
    if (icon && !el.querySelector('svg, img, .ico') && !el.matches('.sw')) return;  // a colour swatch or an empty box paints no glyph
    const need = (icon || large) ? 3 : 4.5;
    let ratio = null, bgs = null;
    if (bg && !bg.grad) {
      const f = over({ ...fg0, a: fg0.a * o }, bg);
      const bgEff = bg;
      const l1 = L(f), l2 = L(bgEff);
      ratio = (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05);
      bgs = 'rgb(' + [bg.r, bg.g, bg.b].map(Math.round) + ')';
    }
    rows.push({ ax: el.dataset.ax, rendered, text: text || '(icon) ' + (el.getAttribute('aria-label') || el.title || ''), fg: cs.color, opacity: +o.toFixed(2), bg: bgs, grad: !!(bg && bg.grad), ratio: ratio && +ratio.toFixed(2), need, disabled: el.matches(':disabled,[aria-disabled=true]'), path: path(el), fx: el.dataset.fx || '', cls: el.className && el.className.toString ? el.className.toString().slice(0, 60) : '' });
  });
  window.__axn = id;
  return rows;
})()
