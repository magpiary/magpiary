/* The first-run window. It only draws: `magpiary downloads install --json` events arrive through window.magpiaryEvent,
   and the buttons ask the app to act through send(). The same page runs in the design mock, fed by a simulator. */
(() => {
  // Short words for the list; Settings has the full story (source, size, why). Ids match downloads.catalog().
  const ABOUT = {
    ffprobe: ["ffprobe", "Measures a video's length."],
    ffmpeg: ["ffmpeg", "Pulls the sound and still frames out of videos."],
    deno: ["Deno", "Lets Magpiary open YouTube videos."],
    "meaning-model": ["Meaning model", "Lets search find what you half remember."],
    "whisper-model": ["Transcript model", "Turns what people say in videos into text you can search, right on your Mac. It's the biggest download."],
  };
  const TOUR = [
    ["Share from ", "any app.", "Tap Share on a reel, post or link. It waits on your phone until you're on Wi-Fi with this Mac."],
    ["Your Mac ", "reads it.", "It downloads the post, listens, looks, and writes down what matters. Videos never leave this Mac."],
    ["Find it ", "any time.", "Search by what was said, shown or written, even if you only half remember it."],
    ["Ask your ", "own library.", "Ask a question and get an answer from what you've saved, with the posts it came from."],
    ["It sorts ", "itself out.", "Related posts and piles gather on their own, and boards let you collect with friends."],
    ["Videos never ", "leave this Mac.", "Only the caption, transcript and a few frames go to your own AI key, or nothing at all in Private."],
  ];
  const ACCENTS = ["#ffd27a", "#c79bff", "#ff4fa3", "#8d8dff"];  // gold, purple, pink, indigo: one per story line, in turn
  // Heading for each problem, and whether trying again can help. The sentence comes from the installer.
  const PROBLEMS = {
    offline: ["No ", "connection."], disk: ["Not enough ", "room."], disk_full: ["Not enough ", "room."],
    macos: ["Not on this ", "Mac yet.", false], chip: ["Not on this ", "Mac yet.", false],
    checksum: ["A download ", "didn't check out."], server: ["Magpiary didn't ", "start."], permission: ["Magpiary can't ", "write here."],
  };
  const START_FAILED = "Everything downloaded fine, but Magpiary didn't start. Try again; if it keeps happening, open Health check from the menu bar.";

  const T0 = Date.now();
  const S = { phase: "checking", steps: [], total: 0, bytes: 0, err: null, message: "", retryUntil: 0, f: 0, hold: false, sheet: false, samples: [] };
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  let logo = "", lastKey = "", shownStep = -1;

  function send(action) {
    const native = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.magpiary;
    if (native) native.postMessage(action);
    else if (parent !== window && parent.magpiarySimAction) parent.magpiarySimAction(action);
  }

  // ---- what the installer says ------------------------------------------------------------------

  window.magpiaryEvent = (e) => {
    switch (e.event) {
      case "plan":
        if ((e.steps || []).length) {
          S.steps = e.steps.map((s) => ({ id: s.id, bytes: s.bytes || 0, name: (ABOUT[s.id] || [s.name])[0], why: (ABOUT[s.id] || [0, s.why])[1] }));
          S.total = e.total_bytes; S.bytes = 0; S.samples = [];
          S.phase = "downloading";
        }
        break;
      case "progress": S.bytes = e.overall_done; S.total = e.overall_total; S.retryUntil = 0; sample(); break;
      case "retry": S.retryUntil = Date.now() + e.wait * 1000; break;
      case "precheck": S.err = e.problems[0].kind; S.message = e.problems[0].message; S.sheet = false; break;
      case "step_error": S.err = e.kind; S.message = e.message; S.retryUntil = 0; S.sheet = false; break;
      case "starting": S.phase = "starting"; S.err = null; break;
      case "ready": S.phase = "done"; S.err = null; break;
      case "start_failed": S.err = "server"; S.message = START_FAILED; break;
      default: return;
    }
    draw();
  };

  function sample() {
    const t = Date.now();
    S.samples.push([t, S.bytes]);
    while (S.samples.length > 1 && t - S.samples[0][0] > 15000) S.samples.shift();
  }

  function stepAt(bytes) {
    let start = 0;
    for (const [i, s] of S.steps.entries()) { if (bytes < start + s.bytes) return { i, step: s, start }; start += s.bytes; }
    const last = S.steps[S.steps.length - 1];
    return { i: S.steps.length - 1, step: last, start: start - (last ? last.bytes : 0) };
  }

  // ---- words ----------------------------------------------------------------------------------

  const what = () => S.phase === "checking" ? "Checking your Mac…" : S.phase === "starting" ? "Waking Magpiary up…" : "Getting ready";
  function eta() {
    const first = S.samples[0], t = Date.now();
    if (!first || t - first[0] < 3000) return "Working out the time…";
    const speed = (S.bytes - first[1]) / ((t - first[0]) / 1000);
    if (speed < 1000) return "Waiting on the connection…";
    const secs = (S.total - S.bytes) / speed;
    return secs < 60 ? "Less than a minute left" : `About ${Math.ceil(secs / 60)} min left`;
  }
  function sub() {
    if (S.retryUntil) return `The connection dropped. Trying again in ${Math.max(0, Math.ceil((S.retryUntil - Date.now()) / 1000))}s…`;
    return S.phase === "checking" ? (Date.now() - T0 > 12000 ? "macOS checks a new app the first time it opens, which can take a couple of minutes. Please leave this window open." : "This only takes a moment.") : S.phase === "starting" ? "Almost there." : eta();
  }
  function words() {
    if (S.err) { const p = PROBLEMS[S.err] || ["That didn't ", "finish."]; return { a: p[0], b: p[1], p: esc(S.message) }; }
    if (S.phase === "done") return { a: "You're ", b: "all set.", p: "Next, pair your iPhone so anything you share lands here. It opens in your browser and takes about a minute." };
    if (S.phase === "starting") return { a: "Almost ", b: "there.", p: "Everything is here. Magpiary is waking up." };
    if (S.phase === "checking") return { a: "Checking your ", b: "Mac.", p: "Making sure there's room and everything is in order." };
    const t = TOUR[S.f];
    return { a: t[0], b: t[1], p: t[2] };
  }

  // ---- pieces, using the hub's own classes ------------------------------------------------------

  const top = () => `<div class="wintop"><span class="logo">${logo}magpiary</span></div>`;
  const wordsInner = (w) => `<h1 class="w-h">${w.a}<em>${w.b}</em></h1><p class="w-p">${w.p}</p>`;
  const head = (w) => `<div id="words" class="words">${wordsInner(w)}</div>`;
  function actions() {
    if (S.err) return `<div class="w-cta">${(PROBLEMS[S.err] || [])[2] === false ? "" : '<button class="btn dark" data-a="again">Try again</button>'}<button class="btn" data-a="quit">Quit</button></div>`;
    return '<div class="w-cta"><span class="onbutton"><img src="/static/art/land-c.webp" alt=""><button class="btn dark" data-a="continue">Continue in your browser →</button></span></div>';
  }
  // The six pictures of the tour, built from the app's own parts: tiles, the search pill, cards. All samples are fictional.
  const tile = (t, who, c) => `<div class="sct" style="--c:${c}"><b>${t}</b><span class="by"><i>${who[0]}</i>${who}</span></div>`;
  const SCENES = [
    () => `<div class="s-phone"><div class="island"></div><div class="post"><div class="pic" style="--c:#b0417c"></div><div class="auth"><i>A</i>Ada Example</div><div class="ln"></div><div class="ln short"></div></div>
      <div class="sheet"><div class="grab"></div><div class="apps2"><span><i style="background:#34c759"></i>Messages</span><span class="mg"><i>${logo}</i>Magpiary</span><span><i style="background:#0a84ff"></i>Mail</span><span><i style="background:#ffcc00"></i>Notes</span></div></div></div>`,
    () => `<div class="s-read">${tile("Ten things to do before 1,000 users", "Ada Example", "#b0417c")}<div class="card"><div class="rstep"><i></i>Fetched the post</div><div class="rstep"><i></i>Listened to what was said</div><div class="rstep"><i></i>Looked at the frames</div><div class="rstep"><i></i>Wrote down what matters</div></div></div>`,
    () => `<div class="s-find"><div class="sbox"><span class="glass">⌕</span><span class="typed">that folding desk video</span></div><div class="hit">${tile("A folding desk for tiny rooms", "Bo Sample", "#3a5f9f")}<div class="why"><small>Said at 0:42</small><p>“It <mark>folds</mark> flat against the wall, so the <mark>desk</mark> disappears.”</p></div></div></div>`,
    () => `<div class="s-ask"><div class="q">What wood did the panel post use?</div><div class="a"><span class="star">✦</span><p>Cedar, in narrow boards. The maker oils them first so the colour stays even.</p><div class="cite"><i style="--c:#9a6a2c"></i>Cedar panel wall, step by step</div></div></div>`,
    () => `<div class="s-words">${[["Small spaces", 12], ["Good food", 8], ["Design tools", 15]].map(([n, c]) => `<div><b>${n}</b><small>${c} saves</small></div>`).join("")}</div>`,
    () => `<div class="s-priv"><div class="mac"><div class="macbar"><i></i><i></i><i></i></div><div class="vid" style="--c:#6a4ab0"><span class="play">▶</span><span class="lock"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg></span></div><b>The video stays here</b></div><div class="out"><span>Caption</span><span>Transcript</span><span>A few frames</span></div><small class="keyline">Only these, and only to your own AI key</small></div>`,
  ];
  const pictures = () => `<div class="stagebox" id="demo"><div class="stageinner">${SCENES.map((s, i) => `<div class="scene${i === S.f ? " on" : ""}">${s()}</div>`).join("")}</div></div>`;
  const calm = () => S.err || S.phase === "done";
  const page = () => calm()
    ? `${S.err ? top() : ""}<div class="centered">${S.err ? "" : `<span class="logo big">${logo}magpiary</span>`}<div class="rest">${head(words())}${actions()}</div></div>`
    : `${top()}<div class="tour"><div>${head(words())}</div><div>${pictures()}</div></div>
       <div class="cbar"><div class="row"><span class="what" data-p="what"></span><span class="pct" data-p="pct"></span></div><div class="lbar"><i data-p="bar"></i></div>
       <div class="below"><span class="sub" data-p="sub"></span><button class="linkbtn" data-a="list">What's being downloaded, and why</button></div></div>`;

  function sheet() {
    const at = stepAt(S.bytes);
    const rows = S.steps.map((s, i) => {
      const finished = S.bytes >= S.total || i < at.i;
      const active = !finished && i === at.i && S.phase === "downloading";
      return `<div class="drow"><span class="dmark ${finished ? "ok" : active ? "cur" : ""}"${active ? ' data-p="ring"' : ""}>${finished ? "✓" : ""}</span><div><b>${esc(s.name)}</b><small>${esc(s.why)}</small></div></div>`;
    }).join("");
    return `<div class="dsheet" role="dialog" aria-label="What's being downloaded"><header><h3>What's being downloaded</h3><button class="btn sm" data-a="close">Close</button></header><div class="list">${rows}</div></div>`;
  }

  // ---- drawing ----------------------------------------------------------------------------------

  function draw() {
    const key = [S.err, S.phase].join("|");
    if (key !== lastKey) {
      const oldLogo = $("content").querySelector(".logo"), from = oldLogo && oldLogo.getBoundingClientRect();
      $("content").innerHTML = page(); lastKey = key;
      const big = $("content").querySelector(".logo.big");
      if (big && from && from.width && !matchMedia("(prefers-reduced-motion: reduce)").matches) {  // the logo travels from the top to the middle
        const to = big.getBoundingClientRect(), unit = to.width / big.offsetWidth;
        big.animate([{ transform: `translate(${(from.x + from.width / 2 - to.x - to.width / 2) / unit}px, ${(from.y + from.height / 2 - to.y - to.height / 2) / unit}px) scale(${from.width / to.width})` }, { transform: "none" }],
          { duration: 900, easing: "cubic-bezier(.3,.8,.2,1)" });
      }
    }
    $("sheet").hidden = !S.sheet;
    if (S.sheet) $("sheet").innerHTML = sheet();
    accent(); fitPictures(); live();
  }

  function live() {
    const set = (n, fn) => document.querySelectorAll(`[data-p="${n}"]`).forEach(fn);
    const here = stepAt(S.bytes);
    if (here.step) set("ring", (el) => { el.style.setProperty("--p", (S.bytes - here.start) / here.step.bytes * 100 + "%"); });
    if (S.sheet && here.i !== shownStep) { shownStep = here.i; $("sheet").innerHTML = sheet(); }
    const fraction = S.total ? S.bytes / S.total : 0;
    set("what", (el) => { el.textContent = what(); });
    set("pct", (el) => { el.textContent = S.phase === "downloading" ? `${Math.floor(fraction * 100)}%` : ""; });
    set("bar", (el) => { el.style.width = (S.phase === "checking" ? 0 : S.phase === "starting" ? 100 : fraction * 100) + "%"; });
    set("sub", (el) => { el.textContent = sub(); el.classList.toggle("warn", !!S.retryUntil); });
  }

  function accent() {
    const on = S.phase === "downloading" && !S.err;
    document.documentElement.style.setProperty("--acc", on ? ACCENTS[S.f % ACCENTS.length] : ACCENTS[0]);
  }

  function fitPictures() {  // the pictures are drawn at 440 px and scaled to the room they have
    const box = $("demo");
    if (box) box.querySelector(".stageinner").style.transform = `scale(${box.offsetWidth / 440})`;
  }

  function showLine(i) {
    S.f = i; accent();
    const w = $("words");
    if (S.phase === "downloading" && w) { w.innerHTML = wordsInner(words()); w.style.animation = "none"; void w.offsetWidth; w.style.animation = ""; }
    document.querySelectorAll(".scene").forEach((s, n) => s.classList.toggle("on", n === S.f));
  }
  window.magpiaryHoldLine = (i) => { S.hold = i !== null; if (i !== null) showLine(i); };

  // ---- clicks -----------------------------------------------------------------------------------

  const ACTIONS = {
    again: () => { S.err = null; S.message = ""; S.phase = "checking"; draw(); send("retry"); },
    quit: () => send("quit"), continue: () => send("continue"),
    list: () => { S.sheet = true; draw(); }, close: () => { S.sheet = false; draw(); },
  };
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-a]");
    if (a && ACTIONS[a.dataset.a]) return ACTIONS[a.dataset.a]();
    if (ev.target.id === "sheet") { S.sheet = false; draw(); }
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && S.sheet) { S.sheet = false; draw(); } });
  addEventListener("resize", () => { sizeBackground(); fitPictures(); });

  // ---- the library's moving background: the same shader as the hub's indigo.js, drawn inside the window ------------------
  const FRAG = `precision highp float;uniform vec2 r,m;uniform float t,dk;uniform vec3 c1,c2;
float h(vec2 q){q=fract(q*vec2(123.34,456.21));q+=dot(q,q+45.32);return fract(q.x*q.y);}
vec3 col;vec2 Q;float gr;
void cl(vec2 c,float R){vec2 d=Q-c;float l=length(d);float e=1.-smoothstep(R-.004,R+.004,l);
 float lit=clamp(.5+.5*dot(d/max(l,.001),normalize(vec2(-.35,.95))),0.,1.);
 float rim=smoothstep(R*.35,R,l);
 vec3 s=mix(c1*1.08,c2,lit*rim*.92);s+=(gr-.5)*.11*lit;col=mix(col,s,e);}
float star(vec2 d,float s){d=abs(d)/s;return clamp(exp(-d.x*7.)*exp(-d.y*70.)+exp(-d.y*7.)*exp(-d.x*70.)+exp(-length(d)*12.),0.,2.);}
void sq(vec2 a,float w,float y,float f,float ph){float x=Q.x-a.x;if(x<0.||x>w)return;float d=abs(Q.y-(a.y+y*sin(x*f+ph)));col=mix(col,c2*.95,(1.-smoothstep(.0015,.004,d))*.8);}
void main(){vec2 u=gl_FragCoord.xy/r;float a=r.x/r.y;Q=vec2(u.x*a,u.y);gr=h(gl_FragCoord.xy*.73+fract(t*.5)*7.);
 float dc=length((u-.5)*vec2(1.,1.1));
 col=mix(c1*.72,c1*1.16,smoothstep(.15,.85,dc));
 vec2 mm=(m-.5)*.018;vec2 D=vec2(sin(t*.09),cos(t*.07))*.012;
 Q-=mm;
 cl(vec2(.02,.0)+D,.2);cl(vec2(.2,-.04)-D,.17);cl(vec2(.0,.2)-D,.11);cl(vec2(.42,-.1)+D,.17);cl(vec2(.62,-.11)-D,.2);
 cl(vec2(a-.02,.02)-D,.24);cl(vec2(a-.26,-.03)+D,.2);cl(vec2(a-.5,-.1)-D,.17);cl(vec2(a,.28)+D,.12);
 cl(vec2(a-.1,.98)+D,.2);cl(vec2(a-.36,1.04)-D,.21);cl(vec2(a-.6,1.08)+D,.15);cl(vec2(.0,1.02)-D,.15);cl(vec2(.2,1.09)+D,.13);
 sq(vec2(.08,.28),.32,.035,22.,t*.25);sq(vec2(a-.42,.13),.3,.03,26.,-t*.2);sq(vec2(.33,.92),.3,.025,30.,t*.2);
 col+=(gr-.5)*.035;
 Q+=mm;
 col*=dk;
 vec3 g=vec3(1.,.82,.5),pk=vec3(1.,.72,.9);
 col+=pk*star(Q-vec2(a-.13,.86),.05)*(.55+.45*sin(t*1.1));
 col+=g*star(Q-vec2(.16,.16),.035)*(.55+.45*sin(t*.8+2.));
 col+=g*star(Q-vec2(a-.1,.2),.04)*(.55+.45*sin(t*1.3+4.));
 gl_FragColor=vec4(col,1.);}`;
  let gl = null;
  const U = {};
  function makeBackground() {
    gl = $("bg").getContext("webgl", { alpha: false, antialias: false, preserveDrawingBuffer: true });
    if (!gl) return;
    const mk = (ty, s) => { const o = gl.createShader(ty); gl.shaderSource(o, s); gl.compileShader(o); return o; };
    const pr = gl.createProgram();
    gl.attachShader(pr, mk(gl.VERTEX_SHADER, "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}"));
    gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, FRAG));
    gl.bindAttribLocation(pr, 0, "a"); gl.linkProgram(pr); gl.useProgram(pr);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    ["r", "m", "t", "dk", "c1", "c2"].forEach((n) => { U[n] = gl.getUniformLocation(pr, n); });
    const v = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim().split(/\s+/).map(Number);
    gl.uniform3f(U.c1, ...v("--wc1")); gl.uniform3f(U.c2, ...v("--wc2")); gl.uniform1f(U.dk, v("--wdk")[0]); gl.uniform2f(U.m, .5, .5);
  }
  function sizeBackground() {
    if (!gl) return;
    const k = Math.min(devicePixelRatio || 1, 1.25), c = $("bg"), w = Math.round(innerWidth * k), h = Math.round(innerHeight * k);
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; gl.viewport(0, 0, w, h); gl.uniform2f(U.r, w, h); }
    paint(performance.now());
  }
  const paint = (t) => { if (gl) { gl.uniform1f(U.t, t / 1000 + 40); gl.drawArrays(gl.TRIANGLES, 0, 3); } };
  let lastPaint = 0;
  const loop = (t) => { requestAnimationFrame(loop); if (document.hidden || t - lastPaint < 1000 / 24) return; lastPaint = t; paint(t); };

  // ---- run ---------------------------------------------------------------------------------------

  const calmMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  makeBackground(); sizeBackground();
  if (!calmMotion) requestAnimationFrame(loop);
  setInterval(live, 250);
  setInterval(() => { if (!S.hold && S.phase === "downloading" && !S.err) showLine((S.f + 1) % TOUR.length); }, calmMotion ? 8000 : 5000);
  fetch("/static/icon.svg").then((r) => r.text()).then((svg) => {
    logo = svg.replace(/<style>[\s\S]*?<\/style>/, "").replace(/class="k"/g, 'fill="currentColor"').replace("<svg ", '<svg class="mark" aria-hidden="true" ');
    lastKey = ""; draw();
  });
  draw();
})();
