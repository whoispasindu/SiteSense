// Runs before the app renders so the page never flashes the wrong theme.
// Same-origin file (not inline) so the strict Content-Security-Policy still applies.
(function () {
  var pref = "system";
  try {
    pref = localStorage.getItem("sitesense-theme") || "system";
  } catch (e) {
    /* storage blocked: follow the system setting */
  }
  var dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();
