// Applies the saved theme before first paint. Loaded as a plain blocking script from <head> (CSP
// forbids inline scripts), so the page never flashes the wrong theme. The key and values match
// js/shell.js, which owns changing the theme.
(function () {
  try {
    var saved = localStorage.getItem('cc-theme');
    if (saved === 'light' || saved === 'dark') document.documentElement.setAttribute('data-theme', saved);
  } catch (error) {
    /* storage can be blocked; the system theme applies */
  }
})();
