// Install Magpiary as an app window (Chrome, Edge, Brave; Safari: File > Add to Dock).
// Only on this Mac's first-account address: an installed app belongs to one origin, and a phone gets this later with HTTPS.
(function () {
  var here = (location.hostname === "localhost" || location.hostname === "127.0.0.1") && (document.querySelector('meta[name="pwa-port"]') || {}).content === location.port;
  if (!here) { show("Available on the first Mac account's hub (localhost:8765) only."); return; }
  var link = document.createElement("link");
  link.rel = "manifest"; link.href = "/manifest.webmanifest";
  document.head.appendChild(link);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});

  var standalone = matchMedia("(display-mode: standalone)").matches;
  var saved = null;
  var safari = /Safari\//.test(navigator.userAgent) && !/Chrome\/|Chromium\/|Edg\/|OPR\//.test(navigator.userAgent);
  window.addEventListener("beforeinstallprompt", function (event) { event.preventDefault(); saved = event; refresh(); });
  window.addEventListener("appinstalled", function () { saved = null; standalone = true; refresh(); });

  function show(text) {
    document.querySelectorAll("[data-pwa-status]").forEach(function (el) { el.textContent = text; });
  }
  function refresh() {
    var buttons = document.querySelectorAll("[data-pwa-install]");
    buttons.forEach(function (b) { b.hidden = !saved; });
    if (standalone) show("You're using Magpiary as an app.");
    else if (saved) show("Opens in its own window with its own Dock icon.");
    else if (safari) show("In Safari: File > Add to Dock.");
    else show("Not offered by this browser right now. If you installed it already, find Magpiary in Launchpad.");
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-pwa-install]");
    if (!button || !saved) return;
    var prompt = saved; saved = null; refresh();
    prompt.prompt();
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", refresh); else refresh();
})();
