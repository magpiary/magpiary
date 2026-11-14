// Contextual post tabs (views.py, hub_views.py). Session A owns this file; the foundation only closes the More menu
// after a tab in it is chosen (hub.js switches the pane: every [data-tab] in a card is a tab).
(() => {
  "use strict";
  document.addEventListener("click", (ev) => {
    const a = ev.target instanceof Element ? ev.target.closest(".pvmore a[data-tab]") : null;
    const tabs = ev.target instanceof Element ? ev.target.closest(".pvtabs") : null;
    if (!tabs) return;
    const more = tabs.querySelector(".pvmore");
    if (!more) return;
    if (a) { more.open = false; more.classList.add("on"); }
    else if (ev.target.closest("a[data-tab]")) more.classList.remove("on");
  });
})();
