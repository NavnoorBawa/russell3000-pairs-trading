/* Loaded synchronously in <head>, before first paint: mark that scripts run (the CSS then
   hides the no-JavaScript notes) and apply a saved theme choice, so a returning reader
   never sees the other theme flash. Without a saved choice the CSS follows the OS. */
(function () {
  var root = document.documentElement;
  var saved = null;
  root.classList.add('js');
  try { saved = window.localStorage.getItem('theme'); } catch (e) { /* storage blocked */ }
  if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);
})();
