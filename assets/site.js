/* Page behaviour: theme toggle, contents highlighting, and mounting the exhibits.
 * Charts are drawn from assets/study.json by assets/exhibits.js, redrawn when the theme
 * or a chart's width changes. Everything here is progressive: without JavaScript the
 * page keeps its text, numbers and tables, and each chart's no-script note shows. */
(function () {
  'use strict';

  var root = document.documentElement;
  var darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function css(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function theme() { return root.getAttribute('data-theme') || (darkQuery && darkQuery.matches ? 'dark' : 'light'); }

  // ── theme toggle ──────────────────────────────────────────────────────────
  var toggle = document.getElementById('theme-toggle');
  function syncTheme() {
    if (toggle) toggle.setAttribute('aria-pressed', theme() === 'dark' ? 'true' : 'false');
    var paper = css('--paper');
    document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) { m.setAttribute('content', paper); });
  }
  if (toggle) {
    toggle.addEventListener('click', function () {
      var next = theme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { window.localStorage.setItem('theme', next); } catch (e) { /* storage blocked: choice lasts this visit */ }
      syncTheme();
      redrawAll();
    });
  }
  if (darkQuery && darkQuery.addEventListener) {
    darkQuery.addEventListener('change', function () {
      if (!root.hasAttribute('data-theme')) { syncTheme(); redrawAll(); }
    });
  }
  syncTheme();

  // ── contents: current section, collapsed on narrow screens ────────────────
  var tocDetails = document.querySelector('.toc-d');
  var wide = window.matchMedia('(min-width: 1081px)');
  function syncToc() { if (tocDetails) tocDetails.open = wide.matches; }
  syncToc();
  if (wide.addEventListener) wide.addEventListener('change', syncToc);
  var links = {};
  document.querySelectorAll('.toc a[href^="#"]').forEach(function (a) {
    links[a.getAttribute('href').slice(1)] = a;
    a.addEventListener('click', function () { if (!wide.matches && tocDetails) tocDetails.open = false; });
  });
  if ('IntersectionObserver' in window) {
    var visible = {};
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { visible[e.target.id] = e.isIntersecting; });
      var current = null;
      document.querySelectorAll('main > section[id]').forEach(function (s) { if (!current && visible[s.id]) current = s.id; });
      if (!current) return;
      Object.keys(links).forEach(function (id) {
        if (id === current) links[id].setAttribute('aria-current', 'true');
        else links[id].removeAttribute('aria-current');
      });
    }, {rootMargin: '-72px 0px -55% 0px'});
    document.querySelectorAll('main > section[id]').forEach(function (s) { io.observe(s); });
  }

  // ── exhibits ──────────────────────────────────────────────────────────────
  var study = null;
  var figures = Array.prototype.slice.call(document.querySelectorAll('figure[data-exhibit]'));
  var drawnWidth = new WeakMap();

  function tokens() {
    return {
      ink: css('--ink'), ink2: css('--ink-2'), ink3: css('--ink-3'), paper: css('--paper'), surface: css('--surface'),
      rule2: css('--rule-2'), grid: css('--grid'), axis: css('--axis'),
      s1: css('--series-1'), s2: css('--series-2'), s3: css('--series-3'), neutral: css('--neutral-series'),
      pos: css('--pos'), neg: css('--neg'), mid: css('--div-mid'),
      ord1: css('--ord-1'), ord2: css('--ord-2'), ord3: css('--ord-3'), ord4: css('--ord-4')
    };
  }

  function legend(el, items) {
    if (!el) return;
    el.replaceChildren();
    (items || []).forEach(function (it) {
      var span = document.createElement('span');
      span.className = 'lg';
      if (it.kind !== 'none') {
        var key = document.createElement('span');
        key.className = 'lg-key ' + it.kind;
        key.style.color = 'var(' + it.color + ')';
        if (it.kind !== 'line' && it.kind !== 'rule') key.style.background = 'var(' + it.color + ')';
        key.setAttribute('aria-hidden', 'true');
        span.appendChild(key);
      }
      span.appendChild(document.createTextNode(it.label));
      el.appendChild(span);
    });
  }

  function message(fig, text) {
    var chart = fig.querySelector('.ex-chart');
    if (!chart || fig.classList.contains('is-pending')) return;
    var p = document.createElement('p');
    p.className = 'ex-error';
    p.textContent = text;
    chart.replaceChildren(p);
  }

  function draw(fig) {
    var name = fig.getAttribute('data-exhibit');
    var fn = window.Exhibits && window.Exhibits[name];
    var chart = fig.querySelector('.ex-chart');
    if (!fn || !chart || !study) return;
    var width = Math.floor(chart.clientWidth);
    if (width < 50) return;
    var result;
    try {
      result = fn(study, {width: width, narrow: width < 560, t: tokens(), figure: fig});
    } catch (err) {
      message(fig, 'This chart could not be drawn (' + err.message + '); its data are in assets/study.json.');
      return;
    }
    if (!result) return;                  // data not available yet: keep the pending panel
    if (fig.classList.contains('is-pending')) {
      fig.classList.remove('is-pending');
      chart.setAttribute('role', 'img');
      if (result.label) chart.setAttribute('aria-label', result.label);
    }
    chart.replaceChildren.apply(chart, result.nodes);
    // The container is the accessible image (role="img" + label) and the data table is
    // its long description; Plot's per-mark aria-labels on <g> elements are redundant there.
    chart.querySelectorAll('svg [aria-label], svg [aria-description]').forEach(function (n) {
      n.removeAttribute('aria-label');
      n.removeAttribute('aria-description');
    });
    if (result.mount) result.mount(chart);
    legend(fig.querySelector('[data-legend]'), result.legend);
    var slot = fig.querySelector('[data-table]');
    if (slot && result.table && !slot.hasChildNodes()) slot.appendChild(window.ExhibitTable(result.table));
    drawnWidth.set(fig, width);
  }

  function redrawAll() { if (study) figures.forEach(draw); }

  // Before printing, draw the charts in the light palette (the print stylesheet is light).
  var printTheme = null;
  window.addEventListener('beforeprint', function () {
    if (theme() === 'dark') { printTheme = root.getAttribute('data-theme'); root.setAttribute('data-theme', 'light'); redrawAll(); }
  });
  window.addEventListener('afterprint', function () {
    if (printTheme === null) return;
    if (printTheme) root.setAttribute('data-theme', printTheme); else root.removeAttribute('data-theme');
    printTheme = null;
    redrawAll();
  });

  function start() {
    if (!window.Plot || !window.d3 || !window.Exhibits) {
      figures.forEach(function (f) { message(f, 'Charts are unavailable: the chart library (cdn.jsdelivr.net) did not load. The numbers are in the text and in assets/study.json.'); });
      return;
    }
    fetch('assets/study.json', {credentials: 'same-origin'})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        study = data;
        redrawAll();
        // label room is measured in the web font: draw again once it has loaded, if it had not
        if (document.fonts && document.fonts.status !== 'loaded') document.fonts.ready.then(redrawAll);
        if ('ResizeObserver' in window) {
          var pending = new Set(), frame = null;
          var ro = new ResizeObserver(function (entries) {
            entries.forEach(function (e) {
              var fig = e.target.closest('figure');
              var w = Math.floor(e.contentRect.width);
              if (fig && drawnWidth.has(fig) && Math.abs(drawnWidth.get(fig) - w) >= 2) pending.add(fig);
            });
            if (pending.size && frame === null) {
              frame = requestAnimationFrame(function () { pending.forEach(draw); pending.clear(); frame = null; });
            }
          });
          figures.forEach(function (f) { var ch = f.querySelector('.ex-chart'); if (ch) ro.observe(ch); });
        }
      })
      .catch(function (err) {
        figures.forEach(function (f) { message(f, 'Charts are unavailable: assets/study.json could not be loaded (' + err.message + '). Open the page through a web server.'); });
      });
  }
  start();
})();
