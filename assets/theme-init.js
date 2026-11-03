/* Loaded synchronously in <head>, before first paint: mark that scripts run (the CSS then
   hides the no-JavaScript notes) and apply a saved theme choice, so a returning reader
   never sees the other theme flash. Without a saved choice the CSS follows the OS. */
(function () {
  var root = document.documentElement;
  var saved = null;
  root.classList.add('js');
  try { saved = window.localStorage.getItem('theme'); } catch (e) { /* storage blocked */ }
  if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);

  // A link to something in a closed disclosure (#bottom-line) opens it as the page is read,
  // before the first paint, rather than later in site.js with the page moving under the reader.
  var id = location.hash.slice(1);
  try { id = decodeURIComponent(id); } catch (e) { id = ''; }
  if (!id || id.indexOf('n=') === 0 || !window.MutationObserver) return;
  var seen = new MutationObserver(function () {
    var el = document.getElementById(id);
    if (!el) return;
    seen.disconnect();
    for (var d = el; d; d = d.parentElement) if (d.tagName === 'DETAILS') d.open = true;
  });
  seen.observe(root, {childList: true, subtree: true});
  document.addEventListener('DOMContentLoaded', function () { seen.disconnect(); });
})();
