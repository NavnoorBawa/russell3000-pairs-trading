/* Page behaviour: theme, contents and wayfinding, exhibits drawn as they come near the
 * window, deep links that land where they point, and the hooks for the reader's tools
 * (checking any number against its data, copying tables and exhibits).
 * Charts are drawn from assets/study.json by assets/exhibits.js. Everything here is
 * progressive: without JavaScript the page keeps its text, numbers and tables, the
 * contents list, and each chart's no-script note. */
(function () {
  'use strict';

  var root = document.documentElement;
  var darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function css(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function theme() { return root.getAttribute('data-theme') || (darkQuery && darkQuery.matches ? 'dark' : 'light'); }

  // ── a short status message (copying a link, a table) ──────────────────────
  var toast = document.createElement('div');
  toast.className = 'toast';
  toast.setAttribute('role', 'status');
  document.body.appendChild(toast);
  function say(text) {
    toast.textContent = text;
    toast.classList.add('on');
    clearTimeout(say.timer);
    say.timer = setTimeout(function () { toast.classList.remove('on'); }, 2600);
  }
  window.SiteToast = say;

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
      // let the button's new state paint first, then redraw the charts near the window
      requestAnimationFrame(function () { redraw(); });
    });
  }
  if (darkQuery && darkQuery.addEventListener) {
    darkQuery.addEventListener('change', function () {
      if (!root.hasAttribute('data-theme')) { syncTheme(); redraw(); }
    });
  }
  syncTheme();

  // ── contents: the section being read, in the sidebar and in the top bar ───
  var tocDetails = document.querySelector('.toc-d');
  var wide = window.matchMedia('(min-width: 1081px)');
  // On narrow screens the top bar's button opens the contents as a sheet, so the in-flow
  // list is hidden there (CSS); 'is-ready' marks that the page has decided, so nothing
  // collapses under the reader after the first paint.
  function syncToc() { if (tocDetails) { tocDetails.open = wide.matches; tocDetails.classList.add('is-ready'); } }
  syncToc();
  if (wide.addEventListener) wide.addEventListener('change', syncToc);

  var sections = Array.prototype.slice.call(document.querySelectorAll('main > section[id]'));
  var tocLinks = {};
  document.querySelectorAll('.toc a[href^="#"]').forEach(function (a) {
    tocLinks[a.getAttribute('href').slice(1)] = a;
    a.addEventListener('click', function () { if (!wide.matches && tocDetails) tocDetails.open = false; });
  });
  function entry(a) {
    var n = a.querySelector('.toc-n');
    var t = a.cloneNode(true);
    t.querySelectorAll('.toc-n, .toc-flag').forEach(function (x) { x.remove(); });
    return {n: n ? n.textContent.trim() : '', t: t.textContent.replace(/\s+/g, ' ').trim()};
  }

  var where = document.getElementById('where');
  var sheet = null;
  if (where) {
    var list = document.querySelector('.toc ol');
    if (list && 'showPopover' in HTMLElement.prototype) {
      sheet = document.createElement('nav');
      sheet.id = 'toc-sheet';
      sheet.className = 'toc-sheet';
      sheet.setAttribute('popover', '');
      sheet.setAttribute('aria-label', 'Contents');
      var head = document.createElement('p');
      head.className = 'toc-sheet-h';
      head.textContent = 'Contents';
      sheet.appendChild(head);
      // the contents' groups and lists, with the group ids renamed so they stay unique
      document.querySelectorAll('.toc .toc-g, .toc ol').forEach(function (el) {
        var c = el.cloneNode(true);
        if (c.id) c.id = 'sheet-' + c.id;
        var by = c.getAttribute('aria-labelledby');
        if (by) c.setAttribute('aria-labelledby', 'sheet-' + by);
        sheet.appendChild(c);
      });
      document.body.appendChild(sheet);
      where.popoverTargetElement = sheet;
      sheet.addEventListener('click', function (e) { if (e.target.closest('a')) sheet.hidePopover(); });
    } else if (tocDetails) {
      // no Popover API: the button opens the in-flow contents
      where.addEventListener('click', function () {
        tocDetails.classList.add('is-shown');
        tocDetails.open = true;
        tocDetails.scrollIntoView({block: 'start'});
      });
    }
    where.hidden = false;
  }

  var currentId = null, spyFrame = null;
  function keepVisible(a) {
    var box = document.querySelector('.toc');
    if (!a || !box || box.scrollHeight <= box.clientHeight + 1) return;
    var b = box.getBoundingClientRect(), r = a.getBoundingClientRect();
    if (r.top < b.top || r.bottom > b.bottom) box.scrollTop += r.top - b.top - b.height / 3;
  }
  // The section being read is the last one whose top has passed a reading line a third of
  // the way down the window (at most 280 px); at the very end of the page, the last one
  // whose top is on screen.
  function spy() {
    spyFrame = null;
    if (!sections.length) return;
    var line = Math.min(window.innerHeight / 3, 280);
    var atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
    var id = sections[0].id;
    for (var i = 0; i < sections.length; i++) {
      var top = sections[i].getBoundingClientRect().top;
      if (top <= line || (atEnd && top < window.innerHeight * 0.85)) id = sections[i].id;
      else break;
    }
    if (id === currentId) return;
    currentId = id;
    document.querySelectorAll('.toc a[aria-current], .toc-sheet a[aria-current]').forEach(function (a) { a.removeAttribute('aria-current'); });
    document.querySelectorAll('.toc a[href="#' + id + '"], .toc-sheet a[href="#' + id + '"]').forEach(function (a) { a.setAttribute('aria-current', 'location'); });
    keepVisible(tocLinks[id]);
    if (where && tocLinks[id]) {
      var e = entry(tocLinks[id]);
      where.querySelector('.where-n').textContent = e.n;
      where.querySelector('.where-t').textContent = e.t;
      where.setAttribute('aria-label', 'Contents, now reading ' + (e.n ? e.n + ' ' : '') + e.t);
    }
  }
  window.addEventListener('scroll', function () { if (spyFrame === null) spyFrame = requestAnimationFrame(spy); }, {passive: true});
  window.addEventListener('resize', function () { if (spyFrame === null) spyFrame = requestAnimationFrame(spy); });
  spy();

  // ── permalinks: a section, exhibit or table link copies its address ──────
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a.anchor, a.ex-label, a.secno');
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || !navigator.clipboard) return;   // the link still navigates
    var url = location.origin + location.pathname + a.hash;
    navigator.clipboard.writeText(url).then(function () { say('Link copied: ' + url); }, function () { /* not allowed: the address bar has it */ });
  });

  // ── checking a number against its data: assets/verify.js, loaded on first use ──
  var verifyLoading = null;
  function verify() {
    if (window.Verify) return Promise.resolve(window.Verify);
    if (!verifyLoading) {
      verifyLoading = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = 'assets/verify.js';
        s.onload = function () { if (window.Verify) resolve(window.Verify); else reject(new Error('assets/verify.js did not load')); };
        s.onerror = function () { verifyLoading = null; reject(new Error('assets/verify.js could not be loaded')); };
        document.head.appendChild(s);
      });
    }
    return verifyLoading;
  }
  var verifyToggle = document.getElementById('verify-toggle');
  if (verifyToggle) {
    verifyToggle.hidden = false;
    verifyToggle.addEventListener('click', function () {
      verify().then(function (V) { V.audit(); }, function (err) { say(err.message); });
    });
  }
  document.addEventListener('click', function (e) {
    var el = e.target.closest && e.target.closest('[data-metric]');
    if (!el || !study || e.defaultPrevented || e.target.closest('a, button, summary, input, label, .mv')) return;
    var sel = window.getSelection && window.getSelection();
    if (sel && !sel.isCollapsed) return;                 // selecting text, not asking
    verify().then(function (V) { V.open(el); }, function (err) { say(err.message); });
  });

  // ── exhibits ──────────────────────────────────────────────────────────────
  var study = null;
  var figures = Array.prototype.slice.call(document.querySelectorAll('figure[data-exhibit]'));
  var drawn = new WeakMap();        // figure -> {width, theme, epoch} of its last drawing
  var specs = new WeakMap();        // figure -> its data table's spec, built when the table is opened
  var near = new Set();             // figures within a screen or so of the window
  var epoch = 0;                    // bumped when the web fonts arrive: label room is measured in them

  function tokens() {
    return {
      ink: css('--ink'), ink2: css('--ink-2'), ink3: css('--ink-3'), paper: css('--paper'), surface: css('--surface'),
      rule2: css('--rule-2'), grid: css('--grid'), axis: css('--axis'),
      s1: css('--series-1'), s2: css('--series-2'), s3: css('--series-3'), neutral: css('--neutral-series'),
      ref: css('--ref-series') || css('--neutral-series'),
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
        if (!/\b(line|rule|ring|hollow)\b/.test(it.kind)) key.style.background = 'var(' + it.color + ')';
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

  function chartWidth(fig) { var c = fig.querySelector('.ex-chart'); return c ? Math.floor(c.clientWidth) : 0; }

  function buildTable(fig) {
    var slot = fig.querySelector('[data-table]'), spec = specs.get(fig);
    if (!slot || !spec || slot.hasChildNodes() || !window.ExhibitTable) return;
    slot.appendChild(window.ExhibitTable(spec));
    if (window.TableTools && window.TableTools.attach) {
      try { window.TableTools.attach(slot, {name: fig.id}); } catch (err) { console.error(err); }
    }
    syncScrollable();
  }

  function draw(fig) {
    var name = fig.getAttribute('data-exhibit');
    var fn = window.Exhibits && window.Exhibits[name];
    var chart = fig.querySelector('.ex-chart');
    if (!fn || !chart || !study) return;
    var width = chartWidth(fig);
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
    if (result.table) {
      specs.set(fig, result.table);
      var d = fig.querySelector('details.ex-data');
      if (d && d.open) buildTable(fig);
    }
    drawn.set(fig, {width: width, theme: theme(), epoch: epoch});
    fig.classList.add('is-drawn');
    if (window.ExhibitTools && window.ExhibitTools.attach) {
      try { window.ExhibitTools.attach(fig); } catch (err) { console.error(err); }
    }
  }

  // A figure needs drawing when it never was, or was drawn in another theme, at another
  // width or before the web fonts arrived.
  function stale(fig) {
    var d = drawn.get(fig);
    return !d || d.theme !== theme() || d.epoch !== epoch || Math.abs(d.width - chartWidth(fig)) >= 2;
  }
  function drawIfStale(fig) { if (stale(fig)) draw(fig); }
  // Redraw what is near the window now; the rest is redrawn as it comes near.
  function redraw() {
    if (!study) return;
    near.forEach(drawIfStale);
    syncScrollable();
  }
  function drawAll() { if (study) figures.forEach(drawIfStale); syncScrollable(); }

  // A table region takes keyboard focus (so it can be scrolled from the keyboard) only while
  // its table is wider or taller than its frame; it then shows an edge shadow (site.css).
  function syncScrollable() {
    document.querySelectorAll('.tbl-wrap').forEach(function (w) {
      var scrolls = w.clientWidth > 0 && (w.scrollWidth > w.clientWidth + 1 || w.scrollHeight > w.clientHeight + 1);
      w.classList.toggle('is-scrollable', scrolls);
      if (scrolls) w.tabIndex = 0;
      else if (!w.hasAttribute('data-keep-tab')) w.removeAttribute('tabindex');
    });
  }
  syncScrollable();
  var scrollFrame = null;
  window.addEventListener('resize', function () {
    if (scrollFrame === null) scrollFrame = requestAnimationFrame(function () { scrollFrame = null; syncScrollable(); });
  });
  // each data-table disclosure names its exhibit, and builds its table when first opened
  document.querySelectorAll('details.ex-data').forEach(function (d) {
    var fig = d.closest('figure');
    var label = fig && fig.querySelector('.ex-label');
    var summary = d.querySelector('summary');
    if (summary && label) summary.setAttribute('aria-label', 'Data table, ' + label.textContent.trim());
    d.addEventListener('toggle', function () {
      if (d.open && fig) { if (!drawn.has(fig)) draw(fig); buildTable(fig); }
      syncScrollable();
    });
  });

  // Printing: draw every chart in the light palette (the print stylesheet is light), and
  // open the closed disclosures so that their text prints (the contents and the exhibits'
  // data tables stay closed: print hides them).
  var printTheme = null, reopened = [];
  window.addEventListener('beforeprint', function () {
    if (theme() === 'dark') { printTheme = root.getAttribute('data-theme'); root.setAttribute('data-theme', 'light'); }
    drawAll();
    document.querySelectorAll('details:not([open])').forEach(function (d) {
      if (d.matches('.toc-d, .ex-data')) return;
      d.open = true;
      reopened.push(d);
    });
  });
  window.addEventListener('afterprint', function () {
    reopened.forEach(function (d) { d.open = false; });
    reopened = [];
    if (printTheme === null) return;
    if (printTheme) root.setAttribute('data-theme', printTheme); else root.removeAttribute('data-theme');
    printTheme = null;
    syncTheme();
    redraw();
  });

  // ── deep links and in-page jumps land on their target ─────────────────────
  // Charts are drawn as they come near, so the page can grow above a target while the
  // browser jumps to it. Jumps are therefore instant (no smooth scrolling), and for a
  // moment after each one the target is held at the top of the window while the charts
  // around it draw, unless the reader starts to move.
  var lastInput = 0;
  ['wheel', 'touchstart', 'keydown'].forEach(function (t) {
    window.addEventListener(t, function () { lastInput = Date.now(); }, {passive: true, capture: true});
  });
  function hashTarget() {
    var h = location.hash;
    if (!h || h.length < 2 || h.indexOf('#n=') === 0) return null;
    try { return document.getElementById(decodeURIComponent(h.slice(1))); } catch (e) { return null; }
  }
  var holding = null;
  function hold(el, ms) {
    if (!el) return;
    // a target in (or that is) a closed disclosure opens it, so the link shows what it names
    for (var d = el; d; d = d.parentElement && d.parentElement.closest('details')) {
      if (d.tagName === 'DETAILS' && !d.open) d.open = true;
      if (!d.parentElement) break;
    }
    if (holding) cancelAnimationFrame(holding.frame);
    var since = Date.now(), until = since + (ms || 1600);
    var pad = parseFloat(getComputedStyle(root).scrollPaddingTop) || 0;
    holding = {frame: 0};
    (function step() {
      if (lastInput > since || Date.now() > until) { holding = null; return; }
      var top = el.getBoundingClientRect().top;
      var atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
      if (Math.abs(top - pad) > 2 && !(atEnd && top > pad)) el.scrollIntoView({block: 'start'});
      holding.frame = requestAnimationFrame(step);
    })();
  }
  window.addEventListener('hashchange', function () { hold(hashTarget()); });
  // a click on a link to the fragment already in the address bar fires no hashchange
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a || e.defaultPrevented || a.getAttribute('href') !== location.hash) return;
    setTimeout(function () { hold(hashTarget()); }, 0);
  });
  function settle() { hold(hashTarget(), 2500); }

  function start() {
    if (!window.Plot || !window.d3 || !window.Exhibits) {
      figures.forEach(function (f) { message(f, 'Charts are unavailable: the chart library (assets/vendor/) did not load. The numbers are in the text and in assets/study.json.'); });
      settle();
      return;
    }
    fetch('assets/study.json', {credentials: 'same-origin'})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        study = data;
        window.Study = data;
        // once the holdout is evaluated, its text (status, key figure, hypotheses table, result
        // and run record) replaces the sealed text; while it is sealed this changes nothing
        if (window.ExhibitPage) {
          try { window.ExhibitPage.holdout(study); } catch (err) { console.error('The holdout text could not be filled: ' + err.message); }
        }
        document.dispatchEvent(new CustomEvent('study:ready', {detail: study}));

        // Draw each exhibit as it comes within about a screen of the window.
        if ('IntersectionObserver' in window) {
          var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (e) {
              if (e.isIntersecting) { near.add(e.target); drawIfStale(e.target); } else near.delete(e.target);
            });
            syncScrollable();
          }, {rootMargin: '1000px 0px'});
          figures.forEach(function (f) { io.observe(f); });
        } else {
          figures.forEach(function (f) { near.add(f); });
          drawAll();
        }
        // label room is measured in the web font: redraw near charts once it has loaded
        if (document.fonts && document.fonts.status !== 'loaded') {
          document.fonts.ready.then(function () { epoch++; redraw(); });
        }
        if ('ResizeObserver' in window) {
          var pending = new Set(), frame = null;
          var ro = new ResizeObserver(function (entries) {
            entries.forEach(function (e) {
              var fig = e.target.closest('figure');
              if (fig && drawn.has(fig) && near.has(fig) && stale(fig)) pending.add(fig);
            });
            if (pending.size && frame === null) {
              frame = requestAnimationFrame(function () { pending.forEach(draw); pending.clear(); frame = null; });
            }
          });
          figures.forEach(function (f) { var ch = f.querySelector('.ex-chart'); if (ch) ro.observe(ch); });
        }
        requestAnimationFrame(function () {
          settle();
          // a link to one number (#n=KEY) opens the check for it
          if (location.hash.indexOf('#n=') === 0) verify().then(function (V) { if (V.fromHash) V.fromHash(); }, function () {});
        });
      })
      .catch(function (err) {
        figures.forEach(function (f) { message(f, 'Charts are unavailable: assets/study.json could not be loaded (' + err.message + '). Open the page through a web server.'); });
        settle();
      });
  }
  start();
})();
