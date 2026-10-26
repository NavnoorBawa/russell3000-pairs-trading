/* "Verify this number". Every published number on the page sits in a marker,
 * data-metric="KEY", that scripts/check_published_numbers.py checks in CI against the
 * value KEY names: keys starting "study." in assets/study.json, the others in
 * results/v33_dev/headline_metrics.json. This file repeats that check in the reader's
 * browser, by the checker's own rule, and shows where each number comes from.
 *
 *   Verify.open(el)    a card for one marked number: the value stored under its key, at full
 *                      precision; whether the number shown matches it at the precision shown;
 *                      the file and the path inside it; how the file was built; the Source
 *                      line of the enclosing exhibit or table; the key's places on the page.
 *   Verify.audit()     checks every marked number, marks each (data-audit="ok|fail|na") and
 *                      reports the count, and the headline file's SHA-256, in a status bar;
 *                      "All numbers" lists them in a table that downloads as CSV.
 *   Verify.exit(), Verify.toggle(), Verify.active()   leave, flip or query that mode.
 *   Verify.fromHash()  for a #n=KEY address: the audit, then that key's card.
 *   Verify.ready       a promise, settled once the page data and verify.css are in.
 *
 * assets/site.js loads this file on demand (a click on a number, the "Check the numbers"
 * button, a #n= address) once it has assets/study.json (window.Study, event study:ready);
 * nothing here runs at page load and the page is complete without it. It styles itself
 * with assets/verify.css. tests/test_verify_parity.py keeps the parsing and rounding rule
 * below identical to the Python checker's. */
(function (global) {
  'use strict';

  // ── the checker's rule (scripts/check_published_numbers.py) ───────────────
  var HEADLINE_FILE = 'results/v33_dev/headline_metrics.json';   // DEFAULT_JSON
  var SITE_FILE = 'assets/study.json';                            // DEFAULT_SITE_JSON
  var SITE_NAMESPACE = 'study';                                   // SITE_NAMESPACE
  var SUPPORTED_SCHEMA = 1;                                       // SUPPORTED_SCHEMA
  var CHECKER = 'scripts/check_published_numbers.py';
  // _NUMBER, matched against the whole text (fullmatch). JavaScript's \d is ASCII only, where
  // Python's also takes other scripts' digits; the parity test checks the page uses ASCII.
  var NUMBER = /^(?<sign>[+-]?)(?<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?<frac>\d+))?(?<pct>%?)$/;
  // re's \s on str: exactly the characters for which str.isspace() is true
  var SPACE = /[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/g;

  function KeyMissing(key) { this.key = key; }
  function hasOwn(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function isDict(x) { return x !== null && typeof x === 'object' && !Array.isArray(x); }
  function pyTruthy(x) {
    if (Array.isArray(x)) return x.length > 0;
    if (isDict(x)) return Object.keys(x).length > 0;
    return !!x;
  }

  var decoder = null;
  /* html.unescape: the checker unescapes the marker's text once more after the parser has. */
  function htmlUnescape(s) {
    if (s.indexOf('&') < 0) return s;
    if (typeof document !== 'undefined') {
      try {
        decoder = decoder || document.createElement('textarea');
        decoder.innerHTML = s;            // RCDATA: character references only, never markup
        return decoder.value;
      } catch (e) { /* a Trusted Types policy refuses it: the references below */ }
    }
    var named = {minus: '\u2212', nbsp: '\u00a0', thinsp: '\u2009', ensp: '\u2002', emsp: '\u2003', hairsp: '\u200a',
                 amp: '&', plus: '+', percnt: '%', comma: ',', period: '.', lt: '<', gt: '>', quot: '"'};
    return s.replace(/&(?:#[xX]([0-9a-fA-F]+)|#(\d+)|([A-Za-z]+));/g, function (all, hex, dec, name) {
      if (name) return hasOwn(named, name) ? named[name] : all;
      var cp = parseInt(hex || dec, hex ? 16 : 10);
      return cp > 0 && cp <= 0x10ffff && !(cp >= 0xd800 && cp <= 0xdfff) ? String.fromCodePoint(cp) : '\ufffd';
    });
  }

  /** Marker text -> {value, decimals}; throws if it is not a number (parse_marker_value). */
  function parseMarkerValue(text) {
    var s = htmlUnescape(String(text)).replace(SPACE, '').replace(/\u2212/g, '-');
    var m = NUMBER.exec(s);
    if (!m) throw new Error('not a number: ' + JSON.stringify(String(text).trim()));
    var g = m.groups, frac = g.frac || '';
    return {value: Number(g.sign + g.int.replace(/,/g, '') + (frac ? '.' + frac : '')), decimals: frac.length};
  }

  /* 10 ** -d as Python's float power gives it, correctly rounded; Math.pow(10, -4) is not. */
  function tenToMinus(d) { return Number('1e-' + d); }

  /** True if value, displayed with `decimals` places, can read as `shown` (matches). */
  function matches(value, shown, decimals) {
    var tol = 0.5 * tenToMinus(decimals) + 1e-9 * Math.max(1, Math.abs(value));
    return Math.abs(value - shown) <= tol;
  }

  /** The value at a dotted path (dict keys or list indices) and that path as a jq filter;
   *  throws KeyMissing when it is absent (resolve_key). */
  function resolvePath(root, parts) {
    var cur = root, jq = '';
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (isDict(cur) && hasOwn(cur, p)) {
        cur = cur[p];
        jq += /^[A-Za-z_][A-Za-z0-9_]*$/.test(p) ? '.' + p : '[' + JSON.stringify(p) + ']';
      } else if (Array.isArray(cur) && /^\d+$/.test(p) && Number(p) < cur.length) {
        cur = cur[Number(p)];
        jq += '[' + Number(p) + ']';
      } else {
        throw new KeyMissing(parts.join('.'));
      }
    }
    return {value: cur, jq: jq === '' ? '.' : (jq.charAt(0) === '[' ? '.' + jq : jq)};
  }

  /** One marker, as check_text treats it. src: {site, headline, siteProblem, headlineProblem}.
   *  status: 'ok', 'fail', or 'na' (not checked: the headline file is unavailable here). */
  function checkMarker(key, text, src) {
    var parts = key.split('.'), site = parts[0] === SITE_NAMESPACE, inner = site ? parts.slice(1) : parts;
    var r = {key: key, text: String(text).replace(/\s+/g, ' ').trim(), site: site, file: site ? SITE_FILE : HEADLINE_FILE,
             path: inner.join('.'), status: 'fail', reason: '', value: undefined, jq: null, shown: null, decimals: null};
    var problem = site ? src.siteProblem : src.headlineProblem;
    if (problem) {
      r.status = site ? 'fail' : 'na';
      r.reason = problem;
      return r;
    }
    var res;
    try {
      res = resolvePath(site ? src.site : src.headline, inner);
    } catch (e) {
      if (!(e instanceof KeyMissing)) throw e;
      r.reason = 'unknown key: not in ' + r.file;
      return r;
    }
    r.value = res.value;
    r.jq = res.jq;
    if (res.value === null) { r.reason = 'the stored value is null'; return r; }
    if (typeof res.value !== 'number' || !isFinite(res.value)) { r.reason = 'the stored value is not a number'; return r; }
    var p;
    try { p = parseMarkerValue(text); } catch (e) { r.reason = 'the text shown is not a number'; return r; }
    r.shown = p.value;
    r.decimals = p.decimals;
    if (matches(res.value, p.value, p.decimals)) r.status = 'ok';
    else r.reason = 'differs at the precision shown';
    return r;
  }

  var core = {
    HEADLINE_FILE: HEADLINE_FILE, SITE_FILE: SITE_FILE, NUMBER: NUMBER, SPACE: SPACE,
    parseMarkerValue: parseMarkerValue, matches: matches, tenToMinus: tenToMinus,
    resolvePath: resolvePath, checkMarker: checkMarker, KeyMissing: KeyMissing
  };
  if (typeof document === 'undefined') {             // Node (tests/test_verify_parity.py)
    if (typeof module === 'object' && module.exports) module.exports = core;
    return;
  }
  if (global.Verify && global.Verify.core) return;   // loaded twice: keep the first

  // ── page data ───────────────────────────────────────────────────────────────
  var doc = document, root = doc.documentElement;
  var here = (doc.currentScript && doc.currentScript.src) || doc.baseURI;

  function url(path) { return new URL(path, doc.baseURI).href; }
  function delay(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
  function fmtCount(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function short(sha) { return sha ? sha.slice(0, 8) + '\u2026' + sha.slice(-4) : '\u2014'; }

  var cssReady = new Promise(function (resolve) {
    // already merged into the page's stylesheet: nothing to load
    if (getComputedStyle(root).getPropertyValue('--vf-css').trim()) { resolve(); return; }
    var link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = new URL('verify.css', here).href;
    link.onload = link.onerror = function () { resolve(); };
    doc.head.appendChild(link);
    setTimeout(resolve, 4000);
  });

  var studyAnnounced = new Promise(function (resolve) {
    if (global.Study) { resolve(global.Study); return; }
    doc.addEventListener('study:ready', function (e) { resolve((e && e.detail) || global.Study); }, {once: true});
  });
  var studyFetched = null;
  function fetchStudy() {
    if (global.Study) return Promise.resolve(global.Study);
    if (!studyFetched) {
      studyFetched = fetch(url(SITE_FILE), {credentials: 'same-origin'})
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .catch(function () { return null; });
    }
    return studyFetched;
  }
  /* The page data as site.js announced it; if it has not by now, read it directly (cached). */
  var studyWait = null;
  function getStudy() {
    if (global.Study) return Promise.resolve(global.Study);
    if (!studyWait) {
      studyWait = Promise.race([studyAnnounced, delay(3000).then(fetchStudy)]).then(function (s) {
        if (!s) { studyWait = null; studyFetched = null; }      // try again next time
        return s;
      });
    }
    return studyWait;
  }

  var headlineLoad = null;
  /* The headline file, read once as bytes: parsed, and hashed where the browser allows it. */
  function getHeadline() {
    if (headlineLoad) return headlineLoad;
    var ctl = global.AbortController ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 10000) : null;
    headlineLoad = fetch(url(HEADLINE_FILE), {credentials: 'same-origin', signal: ctl ? ctl.signal : undefined})
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
      .then(function (buf) {
        var data = JSON.parse(new TextDecoder('utf-8').decode(buf));
        var subtle = global.isSecureContext && global.crypto && global.crypto.subtle;
        if (!subtle) return {data: data, sha256: null, error: null};
        return subtle.digest('SHA-256', buf).then(function (d) {
          var hex = Array.prototype.map.call(new Uint8Array(d), function (b) { return (b < 16 ? '0' : '') + b.toString(16); }).join('');
          return {data: data, sha256: hex, error: null};
        }, function () { return {data: data, sha256: null, error: null}; });
      })
      .catch(function (err) {
        headlineLoad = null;               // a later check may try again
        return {data: null, sha256: null, error: err && err.name === 'AbortError' ? 'timed out' : (err && err.message) || 'error'};
      })
      .then(function (res) { if (timer) clearTimeout(timer); return res; });
    return headlineLoad;
  }

  /* What check_published_numbers.py would check against, and why a file cannot be used. */
  function getSources() {
    return Promise.all([getStudy(), getHeadline()]).then(function (got) {
      var study = got[0], head = got[1], h = head.data;
      var meta = study && isDict(study.meta) ? study.meta : {};
      var src = {site: study || null, headline: h, sha256: head.sha256, want: meta.headline_sha256 || null, meta: meta,
                 hash: 'unavailable', siteProblem: null, headlineProblem: null, loadError: head.error};
      if (!study) src.siteProblem = SITE_FILE + ' could not be loaded';
      if (!h) src.headlineProblem = HEADLINE_FILE + ' could not be loaded (' + head.error + ')';
      else if (!isDict(h) || h.schema !== SUPPORTED_SCHEMA) src.headlineProblem = HEADLINE_FILE + ' has a schema the checker does not read';
      else if (pyTruthy(h.non_default_switches)) src.headlineProblem = HEADLINE_FILE + ' comes from a sensitivity run';
      else if (hasOwn(h, SITE_NAMESPACE)) src.headlineProblem = HEADLINE_FILE + ' has a top-level ' + SITE_NAMESPACE + ' key';
      if (h) {
        if (head.sha256 === null) src.hash = 'unchecked';
        else if (study && head.sha256 === src.want) src.hash = 'match';
        else {
          src.hash = 'mismatch';
          if (!src.siteProblem) src.siteProblem = SITE_FILE + ' was built from another headline file';
        }
      }
      return src;
    });
  }

  function whenReady() { return Promise.all([cssReady, getStudy()]); }

  // ── the page ────────────────────────────────────────────────────────────────
  function markers() { return Array.prototype.slice.call(doc.querySelectorAll('[data-metric]')); }

  var sectionCache = new Map();
  /* "2 Performance": the section's entry in the contents, else its heading. */
  function sectionOf(el) {
    var sec = el.closest('main > section[id]') || el.closest('section[id]');
    if (!sec) return {id: null, label: '\u2014'};
    if (sectionCache.has(sec)) return sectionCache.get(sec);
    var label = '', a = doc.querySelector('.toc a[href="#' + CSS.escape(sec.id) + '"]');
    if (a) {
      var c = a.cloneNode(true);
      var n = c.querySelector('.toc-n');
      var num = n ? n.textContent.trim() : '';
      c.querySelectorAll('.toc-n, .vh, .toc-flag').forEach(function (x) { x.remove(); });
      label = (num ? num + ' ' : '') + c.textContent.replace(/\s+/g, ' ').trim();
    } else {
      var h2 = sec.querySelector('h2');
      label = h2 ? h2.textContent.replace(/\s+/g, ' ').trim() : sec.id;
    }
    var out = {id: sec.id, label: label};
    sectionCache.set(sec, out);
    return out;
  }

  /* The verbatim Source line of the exhibit or table around a marker, if it has one. */
  function sourceOf(el) {
    function clean(p) { return p.textContent.replace(/\s+/g, ' ').trim().replace(/^Source:?\s*/, ''); }
    var own = el.closest('p.src');
    if (own) return {where: tableName(prevTable(own)), text: clean(own)};
    var wrap = el.closest('.tbl-wrap');
    if (wrap) {
      for (var s = wrap.nextElementSibling, i = 0; s && i < 3; s = s.nextElementSibling, i++) {
        if (s.matches('p.src')) return {where: tableName(wrap), text: clean(s)};
        if (s.matches('p, figure, h2, h3, h4, table, section, ul, ol, details, .tbl-wrap')) break;
      }
    }
    var fig = el.closest('figure');
    if (fig) {
      var ps = fig.querySelectorAll('.ex-foot p');
      for (var j = 0; j < ps.length; j++) {
        var k = ps[j].querySelector('.k');
        if (k && k.textContent.trim() === 'Source') {
          var label = fig.querySelector('.ex-label');
          return {where: label ? label.textContent.trim() : '', text: clean(ps[j])};
        }
      }
    }
    return null;
  }
  function prevTable(p) {
    for (var s = p.previousElementSibling, i = 0; s && i < 3; s = s.previousElementSibling, i++) if (s.matches('.tbl-wrap')) return s;
    return null;
  }
  function tableName(wrap) {
    var name = wrap && wrap.getAttribute('aria-label');
    return name ? 'Table: ' + name : '';
  }

  function isShown(el) { return el.getClientRects().length > 0 && !el.closest('.vh'); }   // drawn, and not screen-reader-only

  /* A number reached from an address: in the upper part of the window, so its card fits below. */
  function revealHigh(el) {
    reveal(el, true);
    var r = el.getBoundingClientRect(), top = barBottom();
    global.scrollBy({top: r.top - (top + (global.innerHeight - top) * 0.2), behavior: 'instant'});
  }

  /* Bring a marker into view: open any closed disclosure around it, centre it, mark it briefly. */
  function reveal(el, quiet) {
    for (var d = el.closest('details:not([open])'); d; d = d.parentElement ? d.parentElement.closest('details:not([open])') : null) d.open = true;
    try { el.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'}); } catch (e) { el.scrollIntoView(); }
    if (quiet) return;
    el.classList.remove('vf-flash');
    void el.offsetWidth;
    el.classList.add('vf-flash');
    setTimeout(function () { el.classList.remove('vf-flash'); }, 2200);
  }

  /* Focus a marker; one that is not focusable outside the audit is, until it loses focus. */
  function focusMarker(el) {
    if (!el.hasAttribute('tabindex')) {
      el.setAttribute('tabindex', '-1');
      el.addEventListener('blur', function () { if (el.getAttribute('tabindex') === '-1') el.removeAttribute('tabindex'); }, {once: true});
    }
    try { el.focus({preventScroll: true}); } catch (e) { el.focus(); }
  }

  var ICONS = {ok: 'M3 8.6l3.1 3L13 4.4', fail: 'M4 4l8 8M12 4l-8 8', na: 'M4 8h8'}, iconCache = {};
  /* A check mark, a cross or a dash (aria-hidden: the words next to it say the same). */
  function icon(kind, cls) {
    if (!iconCache[kind]) {
      var NS = 'http://www.w3.org/2000/svg', svg = doc.createElementNS(NS, 'svg'), path = doc.createElementNS(NS, 'path');
      svg.setAttribute('viewBox', '0 0 16 16');
      svg.setAttribute('aria-hidden', 'true');
      svg.setAttribute('focusable', 'false');
      path.setAttribute('d', ICONS[kind]);
      svg.appendChild(path);
      iconCache[kind] = svg;
    }
    var n = iconCache[kind].cloneNode(true);
    n.setAttribute('class', 'vf-ico vf-ico-' + kind + (cls ? ' ' + cls : ''));
    return n;
  }
  function crossIcon() { var n = icon('fail'); n.setAttribute('class', 'vf-ico'); return n; }
  function nowrap(text) { return make('span', 'vf-nw', text); }

  function make(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function button(label, cls) {
    var b = make('button', cls || 'vf-btn', label);
    b.type = 'button';
    return b;
  }
  /* A link to a marker: #n=KEY works on its own (a new tab opens that key's card); a click
     goes to this very place. */
  function jumpLink(el, label) {
    var a = make('a', 'vf-jump', label);
    a.href = '#n=' + encodeURIComponent(el.getAttribute('data-metric'));
    a._vfTarget = el;
    return a;
  }

  var hasPopover = typeof HTMLElement !== 'undefined' && hasOwn(HTMLElement.prototype, 'popover');

  // ── copying ─────────────────────────────────────────────────────────────────
  function copyText(text, within) {
    function select() {
      return new Promise(function (resolve, reject) {
        var back = doc.activeElement, ta = make('textarea', 'vf-copy');
        ta.value = text;
        ta.setAttribute('readonly', '');
        (within || doc.body).appendChild(ta);
        ta.select();
        var ok = false;
        try { ok = doc.execCommand('copy'); } catch (e) { ok = false; }
        ta.remove();
        if (back && back.focus) back.focus();
        if (ok) resolve(); else reject(new Error('copy'));
      });
    }
    if (navigator.clipboard && global.isSecureContext) return navigator.clipboard.writeText(text).catch(select);
    return select();
  }

  // ── the card ────────────────────────────────────────────────────────────────
  var card = null, cardParts = null, anchor = null, offset = {x: 0, y: 0}, closeReason = null, openToken = 0;
  var pressed = null;          // {el, at}: a press on the number whose card was open
  var lastPointer = null;      // {x, y, at}: where the last click was

  function buildCard() {
    if (card) return;
    card = make('div', 'vf-card');
    card.id = 'vf-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-labelledby', 'vf-card-title');
    card.setAttribute('aria-describedby', 'vf-card-check');
    if (hasPopover) card.setAttribute('popover', 'auto');
    else card.hidden = true;

    var head = make('div', 'vf-head');
    var title = make('p', 'vf-title');
    title.id = 'vf-card-title';
    title.tabIndex = -1;
    var eyebrow = make('span', 'vf-eyebrow', 'Marked number');
    var shown = make('span', 'vf-shown');
    title.append(eyebrow, ' ', shown);
    var x = button('', 'vf-x');
    x.setAttribute('aria-label', 'Close');
    x.appendChild(crossIcon());
    x.addEventListener('click', function () { closeCard('button'); });
    head.append(title, x);

    var check = make('p', 'vf-check');
    check.id = 'vf-card-check';
    var mark = make('span', 'vf-mark');
    var checkText = make('span', 'vf-check-text');
    check.append(mark, checkText);

    var dl = make('dl', 'vf-dl');
    var actions = make('div', 'vf-actions');
    var copies = [['Copy value', 'value'], ['Copy key', 'key'], ['Copy jq command', 'jq'], ['Copy link', 'link']].map(function (c) {
      var b = button(c[0]);
      b.dataset.copy = c[1];
      b.dataset.label = c[0];
      actions.appendChild(b);
      return b;
    });
    var live = make('p', 'vf-live vh');
    live.setAttribute('aria-live', 'polite');
    var foot = make('p', 'vf-foot');
    foot.append('Checked in CI by ', make('code', null, CHECKER), '; this repeats its rule in your browser.');
    card.append(head, check, dl, actions, live, foot);
    doc.body.appendChild(card);
    cardParts = {title: title, shown: shown, check: check, mark: mark, checkText: checkText, dl: dl, copies: copies, live: live};

    actions.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-copy]');
      if (!b || !card._vf) return;
      var what = card._vf[b.dataset.copy];
      copyText(what, card).then(function () {
        b.textContent = 'Copied';
        live.textContent = 'Copied: ' + what;
      }, function () {
        b.textContent = 'Could not copy';
        live.textContent = 'Could not copy to the clipboard';
      });
      setTimeout(function () { b.textContent = b.dataset.label; }, 1600);
    });
    card.addEventListener('click', function (e) {
      var a = e.target.closest('a.vf-jump');
      if (!a || !a._vfTarget || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      var el = a._vfTarget;
      reveal(el);
      open(el, {force: true});
    });
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeReason = 'key';
        if (!hasPopover) { e.preventDefault(); closeCard('key'); }
        return;
      }
      // the card sits at the end of the page: Tab past its last control (or Shift+Tab before
      // its first) closes it and goes back to the number, so the reader carries on from there
      if (e.key !== 'Tab' || e.altKey || e.ctrlKey || e.metaKey) return;
      var f = Array.prototype.filter.call(card.querySelectorAll('a[href], button:not([disabled])'), isShown);
      var at = doc.activeElement;
      if ((!e.shiftKey && at === f[f.length - 1]) || (e.shiftKey && (at === f[0] || at === cardParts.title))) {
        e.preventDefault();
        closeCard('key');
      }
    });
    card.addEventListener('focusout', function (e) {
      // focus moved to something else on the page: the card closes, focus stays there
      if (e.relatedTarget && !card.contains(e.relatedTarget) && isOpen()) closeCard(null);
    });
    if (hasPopover) {
      card.addEventListener('beforetoggle', function (e) { if (e.newState === 'closed') noteClosing(); });
      card.addEventListener('toggle', function (e) { if (e.newState === 'closed') afterClose(); });
    } else {
      doc.addEventListener('pointerdown', function (e) {
        if (isOpen() && !card.contains(e.target)) { if (!(anchor && anchor.contains(e.target))) closeCard(null); }
      }, true);
    }
  }

  function isOpen() {
    if (!card) return false;
    if (hasPopover) { try { return card.matches(':popover-open'); } catch (e) { return false; } }
    return !card.hidden;
  }

  function showCard() {
    if (hasPopover) card.showPopover();
    else card.hidden = false;
    startTracking();
  }
  function closeCard(reason) {
    if (!isOpen()) return;
    closeReason = reason;
    if (hasPopover) card.hidePopover();
    else { noteClosing(); card.hidden = true; afterClose(); }
  }
  function noteClosing() { stopTracking(); if (anchor) anchor.classList.remove('vf-current'); }
  function afterClose() {
    var reason = closeReason, el = anchor;
    closeReason = null;
    if (el && (reason === 'key' || reason === 'button')) focusMarker(el);
  }

  function row(dl, label, content) {
    var dt = make('dt', null, label), dd = make('dd');
    if (typeof content === 'string') dd.textContent = content; else dd.append.apply(dd, content);
    dl.append(dt, dd);
    return dd;
  }
  function code(text, title) { var c = make('code', null, text); if (title) c.title = title; return c; }
  /* A dotted key or path in code, with a break opportunity after each dot. */
  function codeKey(text) {
    var c = make('code', 'vf-key');
    String(text).split('.').forEach(function (part, i, all) {
      c.append(part + (i < all.length - 1 ? '.' : ''));
      if (i < all.length - 1) c.appendChild(doc.createElement('wbr'));
    });
    return c;
  }
  function shq(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }

  function fillCard(r, src) {
    var p = cardParts;
    p.shown.textContent = r.text || '(empty)';
    p.check.setAttribute('data-state', r.status);
    p.mark.replaceChildren(icon(r.status));
    p.checkText.textContent = r.status === 'ok' ? 'Matches the stored value at the precision shown'
      : r.status === 'fail' ? 'Does not match: ' + r.reason
      : 'Not checked: ' + r.reason;

    var dl = p.dl;
    dl.replaceChildren();
    row(dl, 'Key', [codeKey(r.key)]);
    row(dl, 'Stored', r.value === undefined ? '\u2014' : [code(typeof r.value === 'number' ? String(r.value) : JSON.stringify(r.value))]);
    var file = make('a', null, r.file);
    file.href = r.file;
    row(dl, 'File', [file]);
    row(dl, 'Path', [r.path ? codeKey(r.path) : '(the whole file)']);

    // how the file was built
    var built = [];
    if (r.site) {
      var m = src.meta || {};
      if (m.builder) built.push(code(m.builder));
      if (m.commit) built.push(built.length ? ', from the run of commit ' : 'From the run of commit ', code(String(m.commit).slice(0, 12), m.commit));
      if (m.generated_utc) built.push(' (meta.generated_utc ', nowrap(m.generated_utc), ')');
    } else if (src.headline && isDict(src.headline.run_config)) {
      var rc = src.headline.run_config;
      if (rc.git_commit) built.push('Written by the run of commit ', code(String(rc.git_commit).slice(0, 12), rc.git_commit));
      if (rc.run_timestamp_utc) built.push(built.length ? ' at ' : 'Written at ', nowrap(rc.run_timestamp_utc), ' (run_config.run_timestamp_utc)');
    }
    if (built.length) row(dl, 'Built', built);

    // the headline file's hash against the one the site data was built from
    var hashDd = row(dl, 'SHA-256', '');
    if (src.hash === 'match') {
      hashDd.append(icon('ok', 'vf-ico-s'), ' ', code(short(src.sha256), src.sha256), ', computed in your browser for ' + HEADLINE_FILE + ', is the one ' + SITE_FILE + ' was built from');
    } else if (src.hash === 'mismatch') {
      hashDd.append(icon('fail', 'vf-ico-s'), ' ', HEADLINE_FILE + ' hashes to ', code(short(src.sha256), src.sha256), ' in your browser, not to the ',
                    code(short(src.want), src.want || ''), ' that ' + SITE_FILE + ' was built from');
    } else if (src.hash === 'unchecked') {
      hashDd.append('Hash not checked: the browser computes SHA-256 only on a secure (https or local) page');
    } else {
      hashDd.append('Hash not checked: ' + HEADLINE_FILE + ' could not be loaded (' + src.loadError + ')');
    }

    var s = sourceOf(r.el);
    if (s) {
      var sd = row(dl, 'Source', '');
      if (s.where) sd.append(make('span', 'vf-where', s.where + ' \u00b7 '));
      sd.append(s.text);
    }

    // where else the key is on the page
    var same = markers().filter(function (x) { return x.getAttribute('data-metric') === r.key; });
    var occ = make('span', 'vf-occ');
    if (same.length === 1) {
      occ.append('Once, here');
    } else {
      occ.append(same.length + ' times: ');
      same.forEach(function (x, i) {
        if (i) occ.append(', ');
        var label = sectionOf(x).label;
        if (x === r.el) occ.append(make('strong', null, label + ' (this one)'));
        else if (!isShown(x)) occ.append(make('span', 'vf-muted', label + ' (not shown at this width)'));
        else { occ.append(jumpLink(x, label)); occ.append(make('span', 'vh', ', ' + (i + 1) + ' of ' + same.length)); }
      });
    }
    row(dl, 'On page', [occ]);

    var link = location.href.split('#')[0] + '#n=' + encodeURIComponent(r.key);
    card._vf = {
      value: r.value === undefined ? '' : (typeof r.value === 'number' ? String(r.value) : JSON.stringify(r.value)),
      key: r.key,
      jq: 'jq ' + shq(r.jq || ('.' + r.path)) + ' ' + r.file,
      link: link
    };
    p.copies.forEach(function (b) {
      b.textContent = b.dataset.label;
      b.disabled = b.dataset.copy === 'value' && r.value === undefined;
    });
    p.live.textContent = '';
  }

  /* The box of the marker to place the card against: the line that was clicked, if it wraps. */
  function anchorRect(el) {
    var rects = el.getClientRects();
    if (!rects.length) return el.getBoundingClientRect();
    if (lastPointer && Date.now() - lastPointer.at < 1500) {
      for (var i = 0; i < rects.length; i++) {
        var q = rects[i];
        if (lastPointer.x >= q.left - 2 && lastPointer.x <= q.right + 2 && lastPointer.y >= q.top - 2 && lastPointer.y <= q.bottom + 2) return q;
      }
    }
    return rects[0];
  }

  var SHEET_BELOW = 600;      // narrower than this, the card is a sheet along the bottom edge
  function clamp(x, lo, hi) { return Math.max(lo, Math.min(x, hi)); }
  /* Below the number, else above it, else beside it, so that it stays in sight; fresh: choose
     anew, else keep the card where it was relative to the number (scrolling, layout). */
  function place(fresh) {
    if (!anchor || !isOpen()) return;
    var vw = root.clientWidth, vh = global.innerHeight, edge = 8, gap = 8;
    var sheet = vw < SHEET_BELOW;
    card.classList.toggle('vf-sheet', sheet);
    if (sheet) {
      card.style.left = card.style.top = '';
      if (fresh) keepVisibleAbove(anchor);
      return;
    }
    var r = anchorRect(anchor), w = card.offsetWidth, h = card.offsetHeight;
    if (fresh) {
      var high = barBottom() + edge;          // below the sticky bars, which the card would hide
      var top, left = r.left + r.width / 2 - w / 2;
      if (r.bottom + gap + h <= vh - edge) top = r.bottom + gap;
      else if (r.top - gap - h >= high) top = r.top - gap - h;
      else {
        top = clamp(r.top + r.height / 2 - h / 2, Math.min(high, vh - h - edge), vh - h - edge);
        if (r.right + gap + w <= vw - edge) left = r.right + gap;
        else if (r.left - gap - w >= edge) left = r.left - gap - w;
        else top = clamp(r.bottom + gap, edge, vh - h - edge);     // no room anywhere: overlap
      }
      offset = {x: clamp(left, edge, vw - w - edge) - r.left, y: top - r.top};
    }
    card.style.left = Math.round(clamp(r.left + offset.x, edge, vw - w - edge)) + 'px';
    card.style.top = Math.round(r.top + offset.y) + 'px';
  }
  /* Scroll any frame the number sits in sideways (a wide table) until all of it shows. */
  function revealInline(el) {
    for (var q = el.parentElement; q && q !== doc.body; q = q.parentElement) {
      if (q.scrollWidth <= q.clientWidth + 1) continue;
      var ox = getComputedStyle(q).overflowX;
      if (ox !== 'auto' && ox !== 'scroll') continue;
      var qr = q.getBoundingClientRect(), r = el.getBoundingClientRect();
      if (r.right > qr.right - 4) q.scrollLeft += r.right - qr.right + 16;
      else if (r.left < qr.left + 4) q.scrollLeft -= qr.left - r.left + 16;
    }
  }
  /* A sheet covers the bottom of the window: scroll the number into the part above it. */
  function keepVisibleAbove(el) {
    revealInline(el);
    var r = anchorRect(el), sheetTop = global.innerHeight - card.offsetHeight, top = barBottom();
    if (r.top >= top + 8 && r.bottom <= sheetTop - 8) return;
    var target = top + Math.max(8, (sheetTop - top - r.height) / 2);
    global.scrollBy({top: r.top - target, behavior: 'instant'});
  }
  function barBottom() {
    var b = 0;
    [doc.querySelector('.topbar'), bar].forEach(function (x) {
      if (!x || !isShown(x)) return;
      var pos = getComputedStyle(x).position;
      if (pos === 'sticky' || pos === 'fixed') b = Math.max(b, x.getBoundingClientRect().bottom);
    });
    return Math.max(0, b);
  }

  var frame = null, bodyObserver = null;
  function schedule() {
    if (frame !== null) return;
    frame = requestAnimationFrame(function () { frame = null; place(false); });
  }
  function onResize() { if (isOpen()) place(true); }
  function startTracking() {
    doc.addEventListener('scroll', schedule, {capture: true, passive: true});
    global.addEventListener('resize', onResize);
    if ('ResizeObserver' in global && !bodyObserver) {
      bodyObserver = new ResizeObserver(schedule);     // charts drawing nearby move the number
      bodyObserver.observe(doc.body);
    }
  }
  function stopTracking() {
    doc.removeEventListener('scroll', schedule, {capture: true});
    global.removeEventListener('resize', onResize);
    if (bodyObserver) { bodyObserver.disconnect(); bodyObserver = null; }
  }

  /** Open the card of one marked number. Returns a promise of whether it opened. */
  function open(el, opts) {
    el = el && el.closest ? el.closest('[data-metric]') : null;
    if (!el) return Promise.resolve(false);
    // a second press on the number whose card was open closes it (the press dismissed it)
    if (pressed && pressed.el === el && Date.now() - pressed.at < 1000 && !(opts && opts.force)) {
      pressed = null;
      closeCard(null);
      return Promise.resolve(false);
    }
    var token = ++openToken;
    return whenReady().then(getSources).then(function (src) {
      if (token !== openToken || !el.isConnected) return false;
      buildCard();
      var r = checkMarker(el.getAttribute('data-metric'), el.textContent, src);
      r.el = el;
      fillCard(r, src);
      if (anchor && anchor !== el) anchor.classList.remove('vf-current');
      anchor = el;
      el.classList.add('vf-current');
      if (!isOpen()) showCard();
      place(true);
      try { cardParts.title.focus({preventScroll: true}); } catch (e) { cardParts.title.focus(); }
      return true;
    });
  }

  // ── audit mode ──────────────────────────────────────────────────────────────
  var auditOn = false, bar = null, barParts = null, results = [], lastSources = null, dialog = null, dialogParts = null;

  function syncToggle() {
    var t = doc.getElementById('verify-toggle');
    if (t) t.setAttribute('aria-pressed', auditOn ? 'true' : 'false');
  }

  function buildBar() {
    if (bar) return;
    bar = make('div', 'vf-bar');
    bar.id = 'vf-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Number check');
    var inner = make('div', 'vf-bar-in');
    var msg = make('p', 'vf-bar-msg');
    msg.setAttribute('role', 'status');
    // on a phone, once the reader scrolls, the bar keeps one line: the counts, which open it again
    var brief = button('', 'vf-bar-brief');
    brief.setAttribute('aria-expanded', 'false');
    brief.setAttribute('aria-controls', 'vf-bar-msg');
    msg.id = 'vf-bar-msg';
    brief.addEventListener('click', function () { compact(false); });
    var btns = make('span', 'vf-bar-btns');
    var all = button('All numbers');
    all.setAttribute('aria-haspopup', 'dialog');
    var ex = button('', 'vf-btn vf-exit');
    ex.append(crossIcon(), make('span', 'vf-exit-t', 'Exit'));
    ex.setAttribute('aria-label', 'Exit the number check');
    btns.append(all, ex);
    inner.append(msg, brief, btns);
    bar.appendChild(inner);
    all.addEventListener('click', openDialog);
    ex.addEventListener('click', function () {
      var t = doc.getElementById('verify-toggle');
      exit();
      if (t && isShown(t)) t.focus();
    });
    msg.addEventListener('click', function (e) {
      var a = e.target.closest('a.vf-jump');
      if (!a || !a._vfTarget || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      reveal(a._vfTarget);
      focusMarker(a._vfTarget);
    });
    barParts = {msg: msg, all: all, brief: brief};
  }

  var compactFrom = 0, compactFrame = null;
  function compact(on) {
    if (!bar) return;
    bar.classList.toggle('is-compact', on);
    barParts.brief.setAttribute('aria-expanded', on ? 'false' : 'true');
    compactFrom = global.scrollY;
    syncBarTop();
  }
  function onBarScroll() {
    if (compactFrame !== null) return;
    compactFrame = requestAnimationFrame(function () {
      compactFrame = null;
      if (!bar || !bar.isConnected) return;
      var y = global.scrollY, is = bar.classList.contains('is-compact');
      if (y < 8 && is) compact(false);
      else if (!is && y >= 8 && Math.abs(y - compactFrom) > 64) compact(true);
    });
  }

  function topbarOffset() {
    var tb = doc.querySelector('.topbar');
    if (!tb) return 0;
    var pos = getComputedStyle(tb).position;
    return pos === 'sticky' || pos === 'fixed' ? Math.round(tb.getBoundingClientRect().height) : 0;
  }
  function syncBarTop() {
    if (!bar) return;
    bar.style.setProperty('--vf-top', topbarOffset() + 'px');
    root.style.setProperty('--vf-pad', (topbarOffset() + bar.offsetHeight + 16) + 'px');
    syncSticky(bar.isConnected ? bar.offsetHeight : 0);
  }
  /* Other sticky columns under the top bar (the contents) move down while the bar shows. */
  var stuck = [];
  function syncSticky(h) {
    stuck.forEach(function (x) { x.el.style.top = x.top; x.el.style.maxHeight = x.max; });
    stuck = [];
    if (!h) return;
    doc.querySelectorAll('.toc').forEach(function (el) {
      var cs = getComputedStyle(el);
      if (cs.position !== 'sticky') return;
      var keep = {el: el, top: el.style.top, max: el.style.maxHeight};
      el.style.top = (parseFloat(cs.top) || 0) + h + 'px';
      if (cs.maxHeight !== 'none') el.style.maxHeight = Math.max(120, parseFloat(cs.maxHeight) - h) + 'px';
      stuck.push(keep);
    });
  }

  /* The bar sits in the flow under the top bar; where the browser does not keep the reading
     position when content is added above it, keep it here. */
  var anchoring = typeof CSS !== 'undefined' && CSS.supports && CSS.supports('overflow-anchor', 'auto');
  function withSteadyScroll(change) {
    var before = bar && bar.isConnected ? bar.offsetHeight : 0;
    change();
    var after = bar && bar.isConnected ? bar.offsetHeight : 0;
    if (!anchoring && global.scrollY > 0 && after !== before) global.scrollBy(0, after - before);
  }

  function showBar() {
    buildBar();
    if (bar.isConnected) return;
    var tb = doc.querySelector('.topbar');
    withSteadyScroll(function () {
      if (tb && tb.parentNode) tb.parentNode.insertBefore(bar, tb.nextSibling);
      else doc.body.insertBefore(bar, doc.body.firstChild);
      syncBarTop();
    });
    compactFrom = global.scrollY;
    global.addEventListener('resize', syncBarTop);
    global.addEventListener('scroll', onBarScroll, {passive: true});
  }
  function hideBar() {
    if (!bar || !bar.isConnected) return;
    withSteadyScroll(function () { bar.remove(); });
    root.style.removeProperty('--vf-pad');
    syncSticky(0);
    global.removeEventListener('resize', syncBarTop);
    global.removeEventListener('scroll', onBarScroll);
    bar.classList.remove('is-compact');
  }

  function summarize() {
    var s = {total: results.length, ok: 0, fail: 0, na: 0, hash: lastSources ? lastSources.hash : 'unavailable', failures: []};
    results.forEach(function (r) {
      s[r.status]++;
      if (r.status === 'fail') s.failures.push({key: r.key, text: r.text, reason: r.reason, section: sectionOf(r.el).label});
    });
    return s;
  }

  function hashSentence(src) {
    if (src.hash === 'match') return 'the headline file\u2019s SHA-256 matches the one ' + SITE_FILE + ' was built from';
    if (src.hash === 'mismatch') return 'the headline file\u2019s SHA-256 does not match the one ' + SITE_FILE + ' was built from, so its study.* numbers fail, as they would in CI';
    if (src.hash === 'unchecked') return 'hash not checked (the browser computes SHA-256 only on a secure page)';
    return 'hash not checked';
  }

  function statusText(s, src) {
    var t = 'Checked in your browser: ' + fmtCount(s.ok) + ' of ' + fmtCount(s.total) +
      ' marked numbers match their stored values at the precision shown';
    if (s.na) t += '; ' + fmtCount(s.na) + ' could not be checked, because ' + src.headlineProblem;
    return t + '; ' + hashSentence(src) + '.';
  }
  function briefText(s, src) {
    var t = fmtCount(s.ok) + ' of ' + fmtCount(s.total) + ' match';
    if (s.fail) t += ', ' + fmtCount(s.fail) + ' do not';
    if (s.na) t += ', ' + fmtCount(s.na) + ' not checked';
    return t + '; hash ' + (src.hash === 'match' ? 'matches' : src.hash === 'mismatch' ? 'does not match' : 'not checked');
  }

  function renderStatus(s, src) {
    var msg = barParts.msg;
    msg.replaceChildren();
    var good = s.fail === 0 && s.na === 0 && src.hash === 'match';
    var state = good ? 'ok' : (s.fail || src.hash === 'mismatch' ? 'fail' : 'na');
    bar.setAttribute('data-state', state);
    msg.setAttribute('data-state', state);
    var mark = make('span', 'vf-mark');
    mark.appendChild(icon(state));
    msg.append(mark, make('span', 'vf-bar-text', statusText(s, src)));
    barParts.brief.replaceChildren(icon(state), make('span', null, briefText(s, src)));
    barParts.brief.setAttribute('aria-label', briefText(s, src) + '. Show the full line');
    if (s.fail) {
      var list = make('span', 'vf-bar-fails');
      list.append(' Not matching: ');
      var shown = results.filter(function (r) { return r.status === 'fail'; });
      shown.slice(0, 6).forEach(function (r, i) {
        if (i) list.append(', ');
        list.append(jumpLink(r.el, r.key));
      });
      if (shown.length > 6) list.append(' and ' + fmtCount(shown.length - 6) + ' more (All numbers)');
      list.append('.');
      msg.appendChild(list);
    }
    syncBarTop();
  }

  function setFocusable(el, on) {
    if (on) {
      if (!el.hasAttribute('tabindex') || el.getAttribute('tabindex') === '-1') { el.setAttribute('tabindex', '0'); el.setAttribute('data-vf-tab', ''); }
      if (!/^(TD|TH)$/.test(el.tagName) && !el.hasAttribute('role')) {
        el.setAttribute('role', 'button');
        el.setAttribute('aria-haspopup', 'dialog');
        el.setAttribute('data-vf-role', '');
      }
    } else {
      if (el.hasAttribute('data-vf-tab')) { el.removeAttribute('tabindex'); el.removeAttribute('data-vf-tab'); }
      if (el.hasAttribute('data-vf-role')) { el.removeAttribute('role'); el.removeAttribute('aria-haspopup'); el.removeAttribute('data-vf-role'); }
    }
  }

  /** Check every marked number on the page, mark each, report in the status bar. */
  function audit() {
    return whenReady().then(function () {
      if (!auditOn) {
        auditOn = true;
        root.classList.add('audit');
        syncToggle();
        showBar();
        if (!results.length) {
          barParts.msg.replaceChildren(make('span', 'vf-bar-text', 'Checking the marked numbers in your browser\u2026'));
          barParts.msg.removeAttribute('data-state');
        }
      }
      return getSources();
    }).then(function (src) {
      if (!auditOn) return summarize();
      lastSources = src;
      results = markers().map(function (el) {
        var r = checkMarker(el.getAttribute('data-metric'), el.textContent, src);
        r.el = el;
        el.setAttribute('data-audit', r.status);
        setFocusable(el, isShown(el));
        return r;
      });
      var s = summarize();
      renderStatus(s, src);
      if (dialog) dialog._stale = true;
      return s;
    });
  }

  /** Leave audit mode: markers back as they were, the bar and the table closed. */
  function exit() {
    if (!auditOn) return;
    auditOn = false;
    closeCard(null);
    if (dialog && dialog.open) dialog.close();
    root.classList.remove('audit');
    markers().forEach(function (el) { el.removeAttribute('data-audit'); setFocusable(el, false); });
    hideBar();
    syncToggle();
  }

  function toggle() { if (auditOn) { exit(); return Promise.resolve(null); } return audit(); }

  // ── all numbers: a table and its CSV ────────────────────────────────────────
  function stored(r) { return r.value === undefined ? '' : typeof r.value === 'number' ? String(r.value) : JSON.stringify(r.value); }
  function verdict(r) { return r.status === 'ok' ? 'matches' : r.status === 'fail' ? r.reason : 'not checked'; }

  function buildDialog() {
    if (dialog) return;
    dialog = make('dialog', 'vf-all');
    dialog.setAttribute('aria-labelledby', 'vf-all-h');
    var head = make('div', 'vf-all-head');
    var h = make('h2', 'vf-all-h', 'All marked numbers');
    h.id = 'vf-all-h';
    var close = button('Close');
    var sum = make('p', 'vf-all-sum');
    var tools = make('div', 'vf-all-tools');
    var fl = make('label', 'vf-filter');
    var input = make('input');
    input.type = 'search';
    input.setAttribute('aria-controls', 'vf-all-body');
    fl.append(make('span', null, 'Filter'), input);
    var only = make('label', 'vf-only');
    var box = make('input');
    box.type = 'checkbox';
    box.setAttribute('aria-controls', 'vf-all-body');
    only.append(box, ' Only numbers that do not match');
    var csv = button('Download CSV');
    var count = make('span', 'vf-all-count');
    count.setAttribute('aria-live', 'polite');
    tools.append(fl, only, csv, count);
    var top = make('div', 'vf-all-top');
    top.append(h, close);
    head.append(top, sum, tools);

    var scroll = make('div', 'vf-all-scroll');
    scroll.tabIndex = 0;
    scroll.setAttribute('role', 'region');
    scroll.setAttribute('aria-label', 'All marked numbers, table');
    var table = make('table', 'vf-tbl');
    var cap = make('caption', 'vh', 'Every marked number on the page: its section, key, the text shown, the stored value, the check and a link to it.');
    var thead = make('thead'), tr = make('tr');
    [['Section', ''], ['Key', ''], ['Shown', 'r'], ['Stored', 'r'], ['Check', ''], ['Where', '']].forEach(function (c) {
      var th = make('th', c[1], c[0]);
      th.scope = 'col';
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    var tbody = make('tbody');
    tbody.id = 'vf-all-body';
    table.append(cap, thead, tbody);
    scroll.appendChild(table);
    dialog.append(head, scroll);
    doc.body.appendChild(dialog);
    dialogParts = {sum: sum, tbody: tbody, input: input, box: box, only: only, count: count};

    close.addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (e) { if (e.target === dialog) dialog.close(); });   // the backdrop
    dialog.addEventListener('close', function () {
      if (dialog._leaving) { dialog._leaving = false; return; }     // gone to a number: focus is there
      var b = barParts && barParts.all;
      if (b && b.isConnected) b.focus();
    });
    input.addEventListener('input', filterRows);
    box.addEventListener('change', filterRows);
    csv.addEventListener('click', downloadCsv);
    tbody.addEventListener('click', function (e) {
      var a = e.target.closest('a.vf-jump');
      if (!a || !a._vfTarget || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      e.preventDefault();
      var el = a._vfTarget;
      dialog._leaving = true;
      dialog.close();
      reveal(el);
      focusMarker(el);
    });
  }

  function fillDialog() {
    var P = dialogParts, s = summarize();
    P.sum.textContent = statusText(s, lastSources);
    P.only.hidden = s.fail === 0;
    if (!s.fail) P.box.checked = false;
    var frag = doc.createDocumentFragment();
    results.forEach(function (r) {
      var tr = make('tr');
      tr.setAttribute('data-state', r.status);
      var sec = sectionOf(r.el).label;
      tr._vfText = (sec + ' ' + r.key + ' ' + r.text).toLowerCase();
      var key = make('td');
      key.appendChild(codeKey(r.key));
      var st = make('td', 'r');
      if (r.value !== undefined) st.appendChild(code(stored(r)));
      var chk = make('td', 'vf-chk');
      chk.append(icon(r.status, 'vf-ico-s'), ' ' + verdict(r));
      var go = make('td');
      if (isShown(r.el)) {
        var a = jumpLink(r.el, 'Go');
        a.appendChild(make('span', 'vh', ' to ' + r.key + ' in ' + sec));
        go.appendChild(a);
      } else {
        go.appendChild(make('span', 'vf-muted', 'not shown at this width'));
      }
      tr.append(make('td', 'vf-sec', sec), key, make('td', 'r vf-num', r.text), st, chk, go);
      frag.appendChild(tr);
    });
    P.tbody.replaceChildren(frag);
    dialog._stale = false;
    filterRows();
  }

  function filterRows() {
    var P = dialogParts, q = P.input.value.trim().toLowerCase(), only = P.box.checked, n = 0;
    Array.prototype.forEach.call(P.tbody.rows, function (tr) {
      var show = (!q || tr._vfText.indexOf(q) >= 0) && (!only || tr.getAttribute('data-state') !== 'ok');
      tr.hidden = !show;
      if (show) n++;
    });
    P.count.textContent = (q || only) ? 'Showing ' + fmtCount(n) + ' of ' + fmtCount(results.length) + ' rows' : '';
  }

  function openDialog() {
    if (!results.length) return;
    buildDialog();
    if (dialog._stale !== false) fillDialog();
    closeCard(null);
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
    dialogParts.input.focus();
  }

  function csvField(v) {
    v = String(v);
    return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }
  function downloadCsv() {
    var lines = [['section', 'key', 'shown', 'stored', 'check', 'file'].join(',')];
    results.forEach(function (r) {
      lines.push([sectionOf(r.el).label, r.key, r.text, stored(r), r.status === 'ok' ? 'matches' : r.status === 'fail' ? 'fails: ' + r.reason : 'not checked', r.file].map(csvField).join(','));
    });
    var blob = new Blob(['\ufeff' + lines.join('\r\n') + '\r\n'], {type: 'text/csv;charset=utf-8'});
    var a = make('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'marked-numbers.csv';
    a.hidden = true;
    dialog.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  // ── #n=KEY ──────────────────────────────────────────────────────────────────
  /** For an address ending #n=KEY: the audit, then the card of KEY's first place on the page.
   *  Returns false when the address has no such part. */
  function fromHash() {
    var m = /^#n=(.+)$/.exec(location.hash || '');
    if (!m) return false;
    var key;
    try { key = decodeURIComponent(m[1]); } catch (e) { return false; }
    audit().then(function () {
      var all = markers().filter(function (x) { return x.getAttribute('data-metric') === key; });
      var el = all.filter(isShown)[0] || all[0];
      if (!el) {
        barParts.msg.appendChild(make('span', 'vf-bar-fails', ' No number on this page is marked ' + key + '.'));
        return;
      }
      revealHigh(el);
      open(el, {force: true}).then(function () { settle(el); });
    });
    return true;
  }
  /* Charts above the number draw as the page settles and push it down: follow it until the
     reader scrolls or a second has passed with nothing moving. */
  function settle(el) {
    if (!('ResizeObserver' in global)) return;
    var quiet = null, done = false;
    function stop() {
      if (done) return;
      done = true;
      ro.disconnect();
      ['wheel', 'touchstart', 'keydown', 'pointerdown'].forEach(function (t) { global.removeEventListener(t, stop, true); });
    }
    var ro = new ResizeObserver(function () {
      if (done) return;
      var r = el.getBoundingClientRect();
      if (r.top < barBottom() || r.bottom > global.innerHeight) { revealHigh(el); place(true); }
      clearTimeout(quiet);
      quiet = setTimeout(stop, 1200);
    });
    ro.observe(doc.body);
    ['wheel', 'touchstart', 'keydown', 'pointerdown'].forEach(function (t) { global.addEventListener(t, stop, true); });
    quiet = setTimeout(stop, 1200);
    setTimeout(stop, 8000);
  }

  // ── events ──────────────────────────────────────────────────────────────────
  function interactive(el) { return el.closest('a[href], button, summary, label, input, select, textarea, [contenteditable]'); }

  doc.addEventListener('pointerdown', function (e) {
    var el = e.target.closest && e.target.closest('[data-metric]');
    pressed = el && isOpen() && anchor === el ? {el: el, at: Date.now()} : null;
  }, true);
  doc.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var el = e.target.closest && e.target.closest('[data-metric]');
    if (!el || (card && card.contains(el)) || interactive(e.target)) return;
    var sel = global.getSelection && global.getSelection();
    if (sel && !sel.isCollapsed && sel.toString().trim()) return;     // selecting text, not asking
    lastPointer = {x: e.clientX, y: e.clientY, at: Date.now()};
    open(el);
  });
  doc.addEventListener('keydown', function (e) {
    if (!auditOn || (e.key !== 'Enter' && e.key !== ' ')) return;
    var el = e.target;
    if (!el.hasAttribute || !el.hasAttribute('data-metric') || e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    lastPointer = null;
    open(el, {force: true});
  });
  global.addEventListener('hashchange', function () { fromHash(); });

  var ready = whenReady().then(function () { return global.Verify; });

  global.Verify = {
    open: open,
    audit: audit,
    exit: exit,
    toggle: toggle,
    active: function () { return auditOn; },
    fromHash: fromHash,
    ready: ready,
    results: function () { return results.map(function (r) { return {key: r.key, text: r.text, status: r.status, reason: r.reason, value: r.value}; }); },
    core: core
  };
})(typeof window !== 'undefined' ? window : this);
