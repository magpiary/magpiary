// Runs in a hub page. Reads every CSS rule that styles a button-like element and builds a throwaway copy of the DOM each rule
// needs (the ancestors in the selector, then the button), plus the usual variants (dark, danger, ghost, ...). Buttons that only
// appear in some states (banners, dialogs, toasts, the ticket) are checked this way without having to reach those states.
(usedList) => {
  const used = usedList ? new Set(usedList) : null;
  const SUBJECT = /btn|chip|pill|swatch|\bsw\b|\btab\b|\bvb\b|^button$|^summary$|\[role=/;
  const sels = [];
  const walk = (rules) => { for (const r of rules) { if (r.selectorText !== undefined) sels.push(r.selectorText); else if (r.cssRules && !(r instanceof CSSKeyframesRule)) walk(r.cssRules); } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) {} }
  const splitTop = (s, ch) => { const out = []; let d = 0, cur = ''; for (const c of s) { if ('([' .includes(c)) d++; if (')]'.includes(c)) d--; if (c === ch && d === 0) { out.push(cur); cur = ''; } else cur += c; } out.push(cur); return out; };
  // :is(a, b) / :where(a, b) -> each alternative; :not(...), :has(...), pseudo-classes and pseudo-elements are dropped
  const expand = (s, depth = 0) => {
    const m = s.match(/:(is|where)\(/); if (!m || depth > 3) return [s];
    const start = m.index, open = start + m[0].length - 1; let d = 0, end = open;
    for (let i = open; i < s.length; i++) { if (s[i] === '(') d++; if (s[i] === ')') { d--; if (!d) { end = i; break; } } }
    const alts = splitTop(s.slice(open + 1, end), ',');
    return alts.flatMap((a) => expand(s.slice(0, start) + a + s.slice(end + 1), depth + 1));
  };
  const strip = (s) => { let o = ''; for (let i = 0; i < s.length; i++) { if (s[i] === ':') { if (s[i + 1] === ':') return null; let j = i + 1; while (j < s.length && /[a-z-]/.test(s[j])) j++; if (s[j] === '(') { let d = 0; for (; j < s.length; j++) { if (s[j] === '(') d++; if (s[j] === ')') { d--; if (!d) { j++; break; } } } } i = j - 1; continue; } o += s[i]; } return o; };
  const compound = (c) => { const tag = (c.match(/^[a-z][a-z0-9]*/) || ['div'])[0]; const el = document.createElement(tag === 'a' || tag === 'button' || tag === 'summary' || tag === 'span' || tag === 'div' || tag === 'label' || tag === 'form' || tag === 'nav' || tag === 'li' || tag === 'ul' || tag === 'section' || tag === 'aside' || tag === 'header' || tag === 'main' ? tag : 'div'); for (const m of c.matchAll(/\.([\w-]+)/g)) el.classList.add(m[1]); const id = c.match(/#([\w-]+)/); if (id) el.id = 'ax-' + id[1]; for (const m of c.matchAll(/\[([\w-]+)(?:[~|^$*]?=["']?([^\]"']*)["']?)?\]/g)) { if (m[1] === 'data-theme' || m[1] === 'hidden' || m[1] === 'disabled') continue; try { el.setAttribute(m[1], m[2] || ''); } catch (e) {} } return el; };
  const box = document.createElement('div'); box.id = 'ax-fixtures'; box.style.cssText = 'position:absolute;left:0;top:0;width:900px;pointer-events:none;z-index:-5';
  const seen = new Set(); let n = 0;
  const VARIANTS = [[], ['dark'], ['danger'], ['ghost'], ['primary'], ['cta'], ['sm', 'dark']];
  for (const full of sels) for (const one of splitTop(full, ',')) for (const alt of expand(one.trim())) {
    if (/html|:root|body/.test(alt.split(/[\s>+~]+/).pop())) continue;
    if (/\.(chrome|art|phone-art)\b/.test(alt)) continue;  // drawings of a browser or phone in the setup guide, not controls
    const s = strip(alt.replace(/(^|[\s>+~])(:root|html|body)(\[[^\]]*\])*(?=[\s>+~]|$)/g, '$1')); if (!s || !s.trim()) continue;
    const parts = s.trim().split(/\s*[>+~]\s*|\s+/).filter(Boolean);
    const last = parts[parts.length - 1]; if (!SUBJECT.test(last)) continue;
    const key = parts.join(' '); if (seen.has(key)) continue; seen.add(key);
    if (used && !(s.match(/\.[\w-]+/g) || []).every((c) => used.has(c.slice(1)))) continue;  // a rule for a class no markup uses (dead CSS) is not a button anyone sees
    for (const extra of VARIANTS) {
      let root = null, cur = null;
      for (const p of parts) { const el = compound(p); if (cur) cur.appendChild(el); else root = el; cur = el; }
      if (!cur.matches('a,button,summary,[role=button],input')) { const b = document.createElement('button'); b.className = cur.className; cur.className = ''; cur.appendChild(b); cur = b; }
      if (/(^|\s)(ibtn|pedbtn|draghandle|sw|swatch|hclose|vb)(\s|$)/.test(cur.className)) { cur.innerHTML = '<svg class="ico" viewBox="0 0 10 10"><path d="M1 1L9 9" stroke="currentColor"/></svg>'; if (cur.classList.contains('sw')) cur.innerHTML = '<span></span>'; }
      else if (!cur.textContent) cur.textContent = 'Label';
      if (extra.length && !cur.classList.contains('btn')) continue;
      extra.forEach((c) => cur.classList.add(c));
      cur.dataset.fx = key + (extra.length ? ' +' + extra.join('+') : '');
      box.appendChild(root); n++; if (n > 6000) break;
    }
  }
  // surfaces that set their own colours (the profile ticket, banners, dialogs, toasts): every variant of the plain button inside each
  const CONTEXTS = ['person', 'update', 'banner', 'dlg', 'pop', 'pover', 'selbar', 'pickbar', 'qrbox', 'srows', 'dgcard', 'toast', 'wel', 'askp', 'setpane', 'pavpop', 'bmember', 'tile', 'folder'];
  for (const ctx of CONTEXTS) for (const extra of VARIANTS) {
    const root = document.createElement('div'); root.className = ctx; const b = document.createElement('button'); b.className = 'btn ' + extra.join(' '); b.textContent = 'Label';
    b.dataset.fx = '.' + ctx + ' > button.btn' + (extra.length ? ' +' + extra.join('+') : ''); root.appendChild(b); box.appendChild(root); n++;
  }
  document.body.appendChild(box);
  return n;
}