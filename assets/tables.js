/* Tables: phone layouts, copy and CSV export, and scroll-aware edges.
 *
 * Progressive: without JavaScript every table is a plain HTML table that scrolls inside its
 * frame, and none of the controls below exist; print keeps the real tables (tables.css).
 *  - On phones (tables.css, screen and max-width 600px) the tables marked data-phone="cards"
 *    become one labelled card per row, and those marked "matrix" put the row label above its
 *    values. Here each <td> of a card table gets data-label from its column header, and both
 *    kinds get explicit ARIA roles, so their table semantics survive the display change.
 *    In a matrix the ' [lo, hi]' interval after an estimate is wrapped in <span class="ci">,
 *    moving the existing nodes, so every data-metric element stays as it is.
 *  - Every table gets Copy (tab-separated text) and CSV (a download): the cells as displayed,
 *    column-aligned across colspan and rowspan, with only U+2212 MINUS SIGN written as an
 *    ASCII hyphen-minus so that spreadsheets read the numbers.
 *  - A frame that scrolls sideways shades the edge that has more beyond it.
 * Exhibit data tables are built later by site.js, which then calls
 * window.TableTools.attach(wrapEl, {name: figureId}). */
(function () {
  'use strict';

  var doc = document;
  var slice = Array.prototype.slice;
  var done = new WeakSet();              // frames already given tools and edges
  var ISO_DATE = /^\d{4}-\d{2}(-\d{2})?$/;

  function $$(sel, el) { return slice.call((el || doc).querySelectorAll(sel)); }

  // ── text of a table, as displayed ─────────────────────────────────────────
  function cellText(node) {
    var out = '';
    (function walk(n) {
      for (var c = n.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === 3) out += c.data;
        else if (c.nodeType === 1) {
          if (c.tagName === 'BR') out += ' ';
          else if (c.tagName !== 'SCRIPT' && c.tagName !== 'STYLE' && !c.hidden) walk(c);
        }
      }
    })(node);
    return out.replace(/\s+/g, ' ').trim().replace(/−/g, '-');
  }

  // rows of cell texts, one column per grid column: a cell spanning k columns is followed by
  // k-1 empty fields, and a cell spanning rows leaves an empty field in the rows below
  function grid(table) {
    var rows = [], carry = [];
    slice.call(table.rows).forEach(function (tr) {
      var out = [], col = 0;
      function skip() { while (carry[col] > 0) { out[col] = ''; carry[col] -= 1; col += 1; } }
      slice.call(tr.cells).forEach(function (c) {
        skip();
        var s = cellText(c), span = Math.max(1, c.colSpan || 1), down = Math.max(1, c.rowSpan || 1) - 1;
        for (var k = 0; k < span; k++) {
          out[col] = k ? '' : s;
          if (down) carry[col] = down;
          col += 1;
        }
      });
      for (; col < carry.length; col++) { if (carry[col] > 0) carry[col] -= 1; out[col] = ''; }
      rows.push(out);
    });
    var width = rows.reduce(function (m, r) { return Math.max(m, r.length); }, 0);
    return rows.map(function (r) { while (r.length < width) r.push(''); return r; });
  }

  function toTSV(rows) {
    return rows.map(function (r) { return r.map(function (s) { return s.replace(/\t/g, ' '); }).join('\t'); }).join('\n');
  }
  function toCSV(rows) {
    return rows.map(function (r) {
      return r.map(function (s) { return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }).join(',');
    }).join('\r\n') + '\r\n';
  }

  // ── status message ────────────────────────────────────────────────────────
  var toast = null, toastTimer = null;
  function ensureToast() {
    if (toast || !doc.body) return toast;
    toast = doc.createElement('div');
    toast.className = 'tt-toast';
    toast.setAttribute('role', 'status');
    doc.body.appendChild(toast);
    return toast;
  }
  function say(text) {
    if (window.SiteToast) { window.SiteToast(text); return; }   // one toast for the page (site.js)
    if (!ensureToast()) return;
    clearTimeout(toastTimer);
    toast.textContent = '';
    requestAnimationFrame(function () {           // a fresh change, so a repeat is announced too
      toast.textContent = text;
      toast.classList.add('is-on');
      toastTimer = setTimeout(function () { toast.classList.remove('is-on'); toast.textContent = ''; }, 2200);
    });
  }

  // ── clipboard and download ────────────────────────────────────────────────
  function legacyCopy(text) {
    var active = doc.activeElement, ta = doc.createElement('textarea'), ok = false;
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.setAttribute('aria-hidden', 'true');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.opacity = '0';
    doc.body.appendChild(ta);
    ta.select();
    try { ok = doc.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    if (active && active.focus) active.focus();
    return ok;
  }
  function copy(text, message) {
    function fallback() { say(legacyCopy(text) ? message : 'Copy is blocked in this browser; use CSV'); }
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { say(message); }, fallback);
    } else fallback();
  }
  function download(text, filename) {
    var url = URL.createObjectURL(new Blob(['﻿' + text], {type: 'text/csv;charset=utf-8'}));
    var a = doc.createElement('a');
    a.href = url;
    a.download = filename;
    a.hidden = true;
    doc.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  // ── tools row ─────────────────────────────────────────────────────────────
  function button(text, name, title, onClick) {
    var b = doc.createElement('button');
    b.type = 'button';
    b.textContent = text;
    b.setAttribute('aria-label', name);
    b.title = title;
    b.addEventListener('click', onClick);
    return b;
  }
  function tableTools(table, label, filename) {
    var row = doc.createElement('div');
    row.className = 'tbl-tools';
    row.appendChild(button('Copy', 'Copy table: ' + label,
      'Copy the cells as shown, tab-separated (minus signs as ASCII hyphens)',
      function () { copy(toTSV(grid(table)), 'Table copied'); }));
    row.appendChild(button('CSV', 'CSV download: ' + label,
      'Download the cells as shown, as ' + filename + ' (minus signs as ASCII hyphens)',
      function () { download(toCSV(grid(table)), filename); say('Downloading ' + filename); }));
    return row;
  }

  // ── scroll-aware edges ────────────────────────────────────────────────────
  var edgeFrames = new Set();
  var ro = 'ResizeObserver' in window ? new ResizeObserver(function (entries) {
    entries.forEach(function (e) {
      var el = e.target.closest('.tt-edges');
      if (el) { measure(el); queue(el); }
    });
  }) : null;
  function measure(el) {
    if (!el.classList.contains('tbl-wrap')) return;
    var t = el.querySelector('table');
    var cap = t && t.caption;
    el.style.setProperty('--tt-cap', (cap ? cap.offsetHeight : 0) + 'px');
    if (el.classList.contains('tt-stick')) {
      var first = t && t.tBodies[0] && t.tBodies[0].rows[0] && t.tBodies[0].rows[0].cells[0];
      el.style.setProperty('--tt-stick', (first ? first.offsetWidth : 0) + 'px');
    }
  }
  function sync(el) {
    el.ttFrame = null;
    var max = el.scrollWidth - el.clientWidth, x = Math.abs(el.scrollLeft);
    el.classList.toggle('tt-l', max > 1 && x > 1);
    el.classList.toggle('tt-r', max > 1 && x < max - 1);
  }
  function queue(el) {
    if (el.ttFrame == null) el.ttFrame = requestAnimationFrame(function () { sync(el); });
  }
  function edges(el) {
    if (edgeFrames.has(el)) return;
    edgeFrames.add(el);
    el.classList.add('tt-edges');
    el.addEventListener('scroll', function () { queue(el); }, {passive: true});
    if (ro) { ro.observe(el); if (el.firstElementChild) ro.observe(el.firstElementChild); }
    measure(el);
    sync(el);
  }
  function resyncAll() { edgeFrames.forEach(function (el) { measure(el); queue(el); }); }

  // ── phone layouts: labels, roles, intervals ───────────────────────────────
  function headerTexts(table) {
    var head = table.tHead, out = [];
    var tr = head && head.rows[head.rows.length - 1];
    if (!tr) return out;
    var col = 0;
    slice.call(tr.cells).forEach(function (c) {
      for (var k = 0; k < (c.colSpan || 1); k++) out[col + k] = c.textContent.replace(/\s+/g, ' ').trim();
      col += c.colSpan || 1;
    });
    return out;
  }
  function labelCells(table) {
    var heads = headerTexts(table);
    slice.call(table.tBodies).forEach(function (tb) {
      slice.call(tb.rows).forEach(function (tr) {
        var col = 0;
        slice.call(tr.cells).forEach(function (c) {
          if (c.tagName === 'TD' && heads[col]) c.setAttribute('data-label', heads[col]);
          col += c.colSpan || 1;
        });
      });
    });
  }
  function addRoles(table) {
    table.setAttribute('role', 'table');
    [table.tHead].concat(slice.call(table.tBodies), [table.tFoot]).forEach(function (g) { if (g) g.setAttribute('role', 'rowgroup'); });
    slice.call(table.rows).forEach(function (tr) {
      tr.setAttribute('role', 'row');
      var inHead = tr.parentNode === table.tHead;
      slice.call(tr.cells).forEach(function (c) {
        var scope = c.getAttribute('scope');
        var role = c.tagName === 'TD' ? 'cell'
          : scope === 'col' || scope === 'colgroup' || (!scope && inHead) ? 'columnheader' : 'rowheader';
        c.setAttribute('role', role);
      });
    });
  }
  // '<estimate> [lo, hi]' -> '<estimate> <span class="ci">[lo, hi]</span>', moving the nodes
  function wrapIntervals(table) {
    $$('tbody td', table).forEach(function (td) {
      if (td.hasAttribute('data-metric') || td.querySelector('.ci')) return;
      var nodes = slice.call(td.childNodes), start = -1, offset = -1;
      for (var i = 0; i < nodes.length && start < 0; i++) {
        var n = nodes[i];
        if (n.nodeType !== 3) continue;
        var p = n.data.indexOf('[');
        if (p < 0) continue;
        var before = nodes.slice(0, i).some(function (m) { return m.textContent.trim() !== ''; }) || n.data.slice(0, p).trim() !== '';
        if (before) { start = i; offset = p; }
      }
      if (start < 0) return;
      var first = nodes[start].splitText(offset);
      var span = doc.createElement('span');
      span.className = 'ci';
      td.insertBefore(span, first);
      var node = first;
      while (node) {
        var next = node.nextSibling;
        if (node.nodeType === 3 && node.data.indexOf(']') >= 0) {
          var q = node.data.indexOf(']');
          if (q < node.data.length - 1) node.splitText(q + 1);
          span.appendChild(node);
          break;
        }
        span.appendChild(node);
        node = next;
      }
    });
  }
  // a long identifier in a row label (rehearsal2025_unscripted) may break after each '_'
  // (a <wbr>, no text added), so a sticky label column can stay narrow on a phone
  function breakIds(table) {
    $$('tbody > tr > th:first-child', table).forEach(function (th) {
      slice.call(th.childNodes).forEach(function (n) {
        if (n.nodeType !== 3 || !/\w_\w/.test(n.data)) return;
        var parts = n.data.replace(/_/g, '_\u0000').split('\u0000');
        parts.forEach(function (part, i) {
          th.insertBefore(doc.createTextNode(part), n);
          if (i < parts.length - 1) th.insertBefore(doc.createElement('wbr'), n);
        });
        n.remove();
      });
    });
  }
  function dataColumns(table) {
    var head = table.tHead, tr = head && head.rows[head.rows.length - 1];
    if (!tr) return 0;
    return slice.call(tr.cells).reduce(function (n, c) { return n + (c.colSpan || 1); }, 0) - 1;
  }
  function layout(wrap) {
    var table = wrap.querySelector('table');
    var mode = wrap.getAttribute('data-phone');
    if (!table) return;
    if (mode === 'cards') {
      labelCells(table);
      addRoles(table);
      wrap.classList.add('tt-cards');
    } else if (mode === 'matrix') {
      addRoles(table);
      wrapIntervals(table);
      table.style.setProperty('--n', String(Math.max(1, dataColumns(table))));
      wrap.classList.add('tt-matrix');
    } else if (mode === 'scroll') {
      wrap.classList.add('tt-stick');
      breakIds(table);
    }
  }

  // ── the page's own tables, and the scroll edges of the code blocks ─────────
  function pageTables() {
    $$('.tbl-wrap[role="region"]').forEach(function (wrap) {
      if (wrap.closest('.ex-table')) return;
      layout(wrap);                                  // idempotent: run again on study:ready
      if (done.has(wrap)) return;
      done.add(wrap);
      var table = wrap.querySelector('table');
      if (!table) return;
      edges(wrap);
      var label = wrap.getAttribute('aria-label') || 'table';
      wrap.after(tableTools(table, label, (wrap.id || 'table') + '.csv'));
    });
  }
  function commands() {
    $$('pre').forEach(function (pre) {
      if (done.has(pre) || pre.closest('.ex-table')) return;
      done.add(pre);
      edges(pre);                                    // its Copy button is site.js's, on every code block
    });
  }

  // ── exhibit data tables (called by site.js after it builds one) ───────────
  function attach(el, opts) {
    if (!el || !el.nodeType) return;
    opts = opts || {};
    var fig = el.closest('figure');
    var box = el.closest('.ex-table') || el;
    var wraps = el.classList.contains('tbl-wrap') ? [el] : $$('.tbl-wrap', el);
    var all = $$('.tbl-wrap', box);
    var name = opts.name || (fig && fig.id) || '';
    var exLabel = fig && fig.querySelector('.ex-label') ? fig.querySelector('.ex-label').textContent.trim() : '';
    wraps.forEach(function (wrap) {
      if (done.has(wrap)) return;
      done.add(wrap);
      var table = wrap.querySelector('table');
      if (!table) return;
      var i = all.indexOf(wrap), many = all.length > 1;
      $$('tbody > tr > th:first-child', table).forEach(function (th) {
        if (ISO_DATE.test(th.textContent.trim())) th.classList.add('tt-date');
      });
      wrap.classList.add('tt-stick');
      edges(wrap);
      var label = (exLabel || wrap.getAttribute('aria-label') || 'table') + (many ? ', table ' + (i + 1) : '');
      var file = (name ? name + '-data' : (wrap.id || 'table')) + (many ? '-' + (i + 1) : '') + '.csv';
      wrap.before(tableTools(table, label, file));
    });
    var det = el.closest('details.ex-data');
    var summary = det && det.querySelector('summary');
    if (summary) {
      var n = $$('table > tbody > tr', det).length;
      var count = summary.querySelector('.tt-count');
      if (!count) {
        count = doc.createElement('span');
        count.className = 'tt-count';
        summary.appendChild(count);
      }
      count.textContent = ' · ' + n.toLocaleString('en-US') + (n === 1 ? ' row' : ' rows');
      if (summary.hasAttribute('aria-label') || exLabel) {
        var visible = summary.textContent.replace(/\s+/g, ' ').trim();
        summary.setAttribute('aria-label', visible + (exLabel ? ', ' + exLabel : ''));
      }
    }
  }

  function init() {
    ensureToast();
    pageTables();
    commands();
    // data tables built before this script ran (site.js could not call attach yet)
    $$('.ex-table').forEach(function (box) { if (box.querySelector('.tbl-wrap')) attach(box); });
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(resyncAll);
    window.addEventListener('load', resyncAll);
    window.addEventListener('beforeprint', resyncAll);
  }

  window.TableTools = {attach: attach, copy: copy, say: say, text: function (t) { return grid(t); }};
  doc.addEventListener('study:ready', function () { pageTables(); resyncAll(); });
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', init);
  else init();
})();
