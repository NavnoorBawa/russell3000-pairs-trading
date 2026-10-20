/* Exhibits: one function per chart, each drawn with Observable Plot from assets/study.json.
 *
 * Contract (used by assets/site.js): Exhibits[name](study, ctx) returns null when its data
 * are absent (the page keeps the exhibit's static "pending" panel), or
 *   { nodes: [Element, ...],            chart panes, in order
 *     legend: [{label, color, kind}],    kind: line | band | box | dot | rule (+ band-inner, box-light); color is a CSS variable
 *     table: {caption, columns, numeric, rows},   the keyboard/screen-reader twin of the chart
 *     label: 'aria label',              for exhibits that start as pending
 *     mount(container) }                optional: runs after the nodes are in the page
 * ctx = {width, narrow, t (resolved colour tokens), figure}. Colours are never written here:
 * they come from the CSS custom properties, resolved for the current theme by site.js.
 */
(function (global) {
  'use strict';

  var MINUS = '−';
  var FONT = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  // ── formatting ────────────────────────────────────────────────────────────
  function num(x, dp, opts) {
    if (x === null || x === undefined || !isFinite(x)) return '–';
    var o = opts || {};
    var s = Math.abs(x).toLocaleString('en-US', {minimumFractionDigits: dp, maximumFractionDigits: dp});
    var zero = Number(Math.abs(x).toFixed(dp)) === 0;
    var sign = x < 0 && !zero ? MINUS : (o.plus && x > 0 && !zero ? '+' : '');
    return sign + s + (o.suffix || '');
  }
  function signed(x, dp, suffix) { return num(x, dp, {plus: true, suffix: suffix}); }
  function pct(x, dp) { return signed(x, dp === undefined ? 2 : dp, '%'); }
  function usdk(x) { return signed(x / 1e3, 1, 'k'); }
  // signed dollars for prose-like labels: −$9.80M, +$662.6k
  function money(x) {
    if (x === null || x === undefined || !isFinite(x)) return '–';
    var big = Math.abs(x) >= 1e6;
    var s = num(Math.abs(x) / (big ? 1e6 : 1e3), big ? 2 : 1, {suffix: big ? 'M' : 'k'});
    return (x < 0 && s !== num(0, big ? 2 : 1, {suffix: big ? 'M' : 'k'}) ? MINUS : x > 0 ? '+' : '') + '$' + s;
  }
  var parse = function (s) { return global.d3.utcParse('%Y-%m-%d')(s); };
  var fmtDate = function (d) { return global.d3.utcFormat('%-d %b %Y')(d); };
  var fmtISO = function (d) { return global.d3.utcFormat('%Y-%m-%d')(d); };

  // ── shared Plot pieces ────────────────────────────────────────────────────
  var X_LABEL_MARGIN = 44;     // room under the frame for tick labels plus a centred axis label
  function plot(c, o) {
    var opts = Object.assign({
      width: c.width,
      style: {background: 'transparent', color: c.t.ink2, fontFamily: FONT, fontSize: '12px', overflow: 'visible'}
    }, o);
    // a labelled x axis puts its label centred below the tick labels (see axisX), so the
    // bottom margin grows to hold it; the frame keeps the height the caller asked for
    var mb = o.marginBottom || 0;
    if (o.x && o.x.label && mb < X_LABEL_MARGIN) {
      opts.height = o.height + X_LABEL_MARGIN - mb;
      opts.marginBottom = X_LABEL_MARGIN;
    }
    return global.Plot.plot(opts);
  }
  function gridY(c, o) { return global.Plot.gridY(Object.assign({stroke: c.t.grid, strokeOpacity: 1}, o)); }
  function gridX(c, o) { return global.Plot.gridX(Object.assign({stroke: c.t.grid, strokeOpacity: 1}, o)); }
  function zeroY(c) { return global.Plot.ruleY([0], {stroke: c.t.axis, strokeWidth: 1}); }
  function zeroX(c) { return global.Plot.ruleX([0], {stroke: c.t.axis, strokeWidth: 1}); }
  function tip(c, data, o) {
    return global.Plot.tip(data, Object.assign({fill: c.t.surface, stroke: c.t.rule2, fontSize: 12, lineHeight: 1.35}, o));
  }
  function axisX(c, o) {
    var base = {stroke: c.t.axis, tickSize: 4, tickPadding: 4};
    if (o && o.label) Object.assign(base, {labelAnchor: 'center', labelOffset: 36});
    return global.Plot.axisX(Object.assign(base, o));
  }
  // a paper-coloured outline behind annotation text, so rules and grid lines it crosses stay legible
  function halo(c, o) { return Object.assign({stroke: c.t.paper, strokeWidth: 4, paintOrder: 'stroke'}, o); }
  function axisY(c, o) { return global.Plot.axisY(Object.assign({tickSize: 0, tickPadding: 6}, o)); }
  function signColor(c) { return function (v) { return v >= 0 ? c.t.pos : c.t.neg; }; }
  // WCAG contrast ratio of two CSS colours (for text set inside a coloured cell)
  function contrast(a, b) {
    var lum = function (col) {
      var rgb = global.d3.rgb(col);
      return [rgb.r, rgb.g, rgb.b].map(function (v) {
        v /= 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      }).reduce(function (s, v, i) { return s + v * [0.2126, 0.7152, 0.0722][i]; }, 0);
    };
    var la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }
  function table(caption, columns, numeric, rows) { return {caption: caption, columns: columns, numeric: numeric, rows: rows}; }
  // rendered width (px) of a label in the chart font, so label room can be computed, not guessed
  var measureCtx = null;
  function textWidth(text, size, weight) {
    measureCtx = measureCtx || document.createElement('canvas').getContext('2d');
    measureCtx.font = (weight || 400) + ' ' + size + 'px ' + FONT;
    return measureCtx.measureText(text).width;
  }
  // Widen an x domain until every bar-end label fits inside the frame: labels[i] = {x, px, side}
  // sits px pixels to the right (side 'right') or left ('left') of data value x. A few fixed-point
  // passes converge because each pass only widens the domain.
  function fitLabels(domain, labels, framePx) {
    var lo = domain[0], hi = domain[1];
    for (var pass = 0; pass < 10; pass++) {
      var perPx = (hi - lo) / framePx, nlo = domain[0], nhi = domain[1];
      labels.forEach(function (l) {
        if (l.side === 'right') nhi = Math.max(nhi, l.x + l.px * perPx);
        else nlo = Math.min(nlo, l.x - l.px * perPx);
      });
      lo = nlo; hi = nhi;
    }
    return [lo, hi];
  }
  function domainPad(values, pad, include) {
    var vals = values.filter(function (v) { return v !== null && v !== undefined && isFinite(v); }).concat(include || []);
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    var span = (hi - lo) || 1;
    return [lo - span * pad, hi + span * pad];
  }

  // one strategy of the evaluated 2026 holdout (scripts/evaluate_holdout.py), or null while sealed
  function holdoutArm(S, key) {
    var H = S.holdout;
    if (!H || H.status !== 'complete' || !H.arms) return null;
    return H.arms.filter(function (a) { return a.key === key && a.sharpe !== null && a.sharpe !== undefined; })[0] || null;
  }

  var X = {};

  // ── Exhibit 2: cumulative return, drawdown, exposure on one time axis ─────
  X.equity = function (S, c) {
    var D = S.dev && S.dev.daily;
    if (!D || !D.dates || !D.dates.length) return null;
    var G = S.dev.gatev, B = S.dev.random_band;
    var gatevByDate = {}, bandByDate = {};
    if (G) G.dates.forEach(function (d, i) { gatevByDate[d] = G.cum[i]; });
    // random-pair draws: per-day quantiles of their cumulative returns (exports from v33 on)
    var band = B ? B.dates.map(function (d, i) {
      var b = {date: parse(d), p05: B.p05[i], p25: B.p25[i], p50: B.p50[i], p75: B.p75[i], p95: B.p95[i]};
      bandByDate[d] = b;
      return b;
    }) : null;
    var rows = D.dates.map(function (d, i) {
      return {date: parse(d), iso: d, cum: D.cum[i], dd: D.dd[i], exp: D.exposure[i], pos: D.positions[i],
              gatev: gatevByDate[d] === undefined ? null : gatevByDate[d], rnd: bandByDate[d] || null};
    });
    var dom = [rows[0].date, rows[rows.length - 1].date];
    var mL = 46, mR = c.narrow ? 58 : 62;
    var last = rows[rows.length - 1];
    var common = {marginLeft: mL, marginRight: mR, x: {type: 'utc', domain: dom, axis: null}};
    var P = global.Plot;

    var cumVals = rows.map(function (r) { return r.cum; }).concat(rows.map(function (r) { return r.gatev; }));
    if (band) cumVals = cumVals.concat(band.map(function (b) { return b.p05; }), band.map(function (b) { return b.p95; }));
    var endLabels = [{y: last.cum, text: pct(last.cum), color: c.t.s1}];
    if (last.gatev !== null) endLabels.push({y: last.gatev, text: pct(last.gatev), color: c.t.s2});
    if (endLabels.length === 2 && Math.abs(endLabels[0].y - endLabels[1].y) < 0.3) {   // keep end labels apart
      var up = endLabels[0].y > endLabels[1].y ? 0 : 1;
      endLabels[up].dy = -7; endLabels[1 - up].dy = 7;
    }
    var pane1 = plot(c, Object.assign({}, common, {
      height: c.narrow ? 210 : 250, marginTop: 22, marginBottom: 4,
      y: {domain: domainPad(cumVals, 0.08, [0]), label: 'Cumulative net return, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }},
      marks: [
        gridY(c), axisY(c, {label: 'Cumulative net return, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        band ? P.areaY(band, {x: 'date', y1: 'p05', y2: 'p95', fill: c.t.neutral, fillOpacity: 0.14}) : null,
        band ? P.areaY(band, {x: 'date', y1: 'p25', y2: 'p75', fill: c.t.neutral, fillOpacity: 0.22}) : null,
        zeroY(c),
        G ? P.lineY(rows, {x: 'date', y: 'gatev', stroke: c.t.s2, strokeWidth: 2, curve: 'linear'}) : null,
        P.lineY(rows, {x: 'date', y: 'cum', stroke: c.t.s1, strokeWidth: 2}),
        P.dot(endLabels, {x: function () { return last.date; }, y: 'y', r: 4, fill: function (d) { return d.color; }, stroke: c.t.paper, strokeWidth: 2}),
        P.text(endLabels, {x: function () { return last.date; }, y: 'y', text: 'text', dx: 8, textAnchor: 'start', fill: c.t.ink, fontWeight: 600, fontSize: 12})
      ].filter(Boolean)
    }));
    // nudge colliding end labels (Plot's dy is a constant, so shift the text nodes)
    pane1.querySelectorAll('g[aria-label="text"] text').forEach(function (n, i) {
      if (endLabels[i] && endLabels[i].dy) n.setAttribute('dy', String(endLabels[i].dy));
    });
    var minDd = rows.reduce(function (a, r) { return r.dd < a.dd ? r : a; }, rows[0]);
    var pane2 = plot(c, Object.assign({}, common, {
      height: c.narrow ? 96 : 116, marginTop: 20, marginBottom: 4,
      y: {domain: [Math.min(minDd.dd * 1.15, -0.5), 0], label: 'Drawdown, %', labelArrow: 'none'},
      marks: [
        gridY(c, {ticks: 3}), axisY(c, {ticks: 3, label: 'Drawdown, %', labelArrow: 'none', tickFormat: function (v) { return num(v, 1); }}),
        P.areaY(rows, {x: 'date', y: 'dd', fill: c.t.s1, fillOpacity: 0.12}),
        P.lineY(rows, {x: 'date', y: 'dd', stroke: c.t.s1, strokeWidth: 1.5}),
        zeroY(c),
        P.dot([minDd], {x: 'date', y: 'dd', r: 4, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        P.text([minDd], {x: 'date', y: 'dd', text: function (d) { return 'max ' + pct(d.dd); }, dx: 8, textAnchor: 'start', fill: c.t.ink, fontSize: 11.5})
      ]
    }));
    var expMax = Math.max.apply(null, rows.map(function (r) { return r.exp; }));
    var pane3 = plot(c, Object.assign({}, common, {
      height: c.narrow ? 122 : 142, marginTop: 20, marginBottom: 26,
      x: {type: 'utc', domain: dom},
      y: {domain: [0, Math.max(32, expMax * 1.08)], label: 'Gross exposure, % of capital', labelArrow: 'none'},
      marks: [
        gridY(c, {ticks: 3}), axisY(c, {ticks: 3, label: 'Gross exposure, % of capital', labelArrow: 'none'}),
        axisX(c, {ticks: c.narrow ? 4 : 8}),
        P.areaY(rows, {x: 'date', y: 'exp', curve: 'step-after', fill: c.t.s1, fillOpacity: 0.12}),
        P.lineY(rows, {x: 'date', y: 'exp', curve: 'step-after', stroke: c.t.s1, strokeWidth: 1.5}),
        P.ruleY([30], {stroke: c.t.ink3, strokeWidth: 1}),
        P.text([30], {y: function (v) { return v; }, frameAnchor: 'right', text: function () { return '30% cap'; }, dy: -7, textAnchor: 'end', fill: c.t.ink2, fontSize: 11}),
        zeroY(c)
      ]
    }));
    [pane1, pane2, pane3].forEach(function (p) { p.classList.add('plot-pane'); });

    var legend = [{label: 'Strategy, net', color: '--series-1', kind: 'line'}];
    if (G) legend.push({label: 'Gatev distance method, net', color: '--series-2', kind: 'line'});
    if (band) {
      legend.push({label: 'Random pairs, 5–95% of ' + (B.n_draws || '') + ' draws', color: '--neutral-series', kind: 'band'});
      legend.push({label: '25–75%', color: '--neutral-series', kind: 'band band-inner'});
    }
    var columns = ['Date', 'Strategy cumulative', 'Gatev cumulative'];
    if (band) columns = columns.concat(['Random 5%', 'Random median', 'Random 95%']);
    columns = columns.concat(['Drawdown', 'Gross exposure', 'Open positions']);

    return {
      nodes: [pane1, pane2, pane3],
      legend: legend,
      table: table('Daily series, main backtest (% of capital).', columns,
        columns.map(function (_, i) { return i > 0; }),
        rows.map(function (r) {
          var cells = [r.iso, pct(r.cum, 3), r.gatev === null ? '–' : pct(r.gatev, 3)];
          if (band) cells = cells.concat(r.rnd ? [pct(r.rnd.p05, 3), pct(r.rnd.p50, 3), pct(r.rnd.p95, 3)] : ['–', '–', '–']);
          return cells.concat([num(r.dd, 3, {suffix: '%'}), num(r.exp, 2, {suffix: '%'}), String(r.pos)]);
        })),
      mount: function (container) { crosshair(container, [pane1, pane2, pane3], rows, c); }
    };
  };

  // One vertical rule across all panes and one tooltip listing every series at that date.
  function crosshair(container, panes, rows, c) {
    var xs = panes[0].scale('x');
    var dates = rows.map(function (r) { return +r.date; });
    var bisect = global.d3.bisector(function (d) { return d; }).center;
    var rules = panes.map(function (p) {
      var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('y1', 0);
      line.setAttribute('y2', p.getAttribute('height'));
      line.setAttribute('stroke', c.t.ink3);
      line.setAttribute('stroke-width', 1);
      line.style.display = 'none';
      line.setAttribute('aria-hidden', 'true');
      p.appendChild(line);
      return line;
    });
    var tipEl = document.createElement('div');
    tipEl.className = 'xtip';
    tipEl.style.display = 'none';
    tipEl.setAttribute('aria-hidden', 'true');
    container.appendChild(tipEl);

    function row(label, color, value) {
      var r = document.createElement('div');
      r.className = 'xt-row';
      if (color) {
        var k = document.createElement('span');
        k.className = 'xt-key';
        k.style.color = color;
        r.appendChild(k);
      }
      var l = document.createElement('span');
      l.textContent = label;
      var v = document.createElement('b');
      v.textContent = value;
      r.appendChild(l);
      r.appendChild(v);
      return r;
    }
    function show(evt) {
      var box = panes[0].getBoundingClientRect();
      var scale = box.width / Number(panes[0].getAttribute('width'));
      var px = (evt.clientX - box.left) / scale;
      var i = bisect(dates, +xs.invert(px));
      var r = rows[i];
      var x = xs.apply(r.date);
      rules.forEach(function (l) { l.setAttribute('x1', x); l.setAttribute('x2', x); l.style.display = ''; });
      tipEl.replaceChildren();
      var d = document.createElement('div');
      d.className = 'xt-date';
      d.textContent = fmtDate(r.date);
      tipEl.appendChild(d);
      tipEl.appendChild(row('Strategy', c.t.s1, pct(r.cum)));
      if (r.gatev !== null) tipEl.appendChild(row('Gatev', c.t.s2, pct(r.gatev)));
      if (r.rnd) tipEl.appendChild(row('Random, median', null, pct(r.rnd.p50) + ' [' + pct(r.rnd.p05, 1) + ', ' + pct(r.rnd.p95, 1) + ']'));
      tipEl.appendChild(row('Drawdown', null, num(r.dd, 2, {suffix: '%'})));
      tipEl.appendChild(row('Gross exposure', null, num(r.exp, 1, {suffix: '%'})));
      tipEl.appendChild(row('Open positions', null, String(r.pos)));
      tipEl.style.display = '';
      var cw = container.clientWidth, tw = tipEl.offsetWidth;
      var left = x * scale + 14;
      if (left + tw > cw) left = x * scale - tw - 14;
      tipEl.style.left = Math.max(0, left) + 'px';
      tipEl.style.top = '28px';
    }
    function hide() { rules.forEach(function (l) { l.style.display = 'none'; }); tipEl.style.display = 'none'; }
    // a redraw replaces the panes: drop the previous drawing's listeners first
    if (container.crosshair) {
      container.removeEventListener('pointermove', container.crosshair.show);
      container.removeEventListener('pointerleave', container.crosshair.hide);
    }
    container.crosshair = {show: show, hide: hide};
    container.addEventListener('pointermove', show);
    container.addEventListener('pointerleave', hide);
  }

  // ── Exhibit 3: walk-forward windows and the stitched path ─────────────────
  X.walkforward = function (S, c) {
    var WF = S.dev && S.dev.walk_forward;
    if (!WF || !WF.windows || !WF.windows.length) return null;
    var P = global.Plot;
    // windows are numbered 1..N here; the run's own index (it counts windows inside the
    // formation period too) stays in the data table
    var W = WF.windows.map(function (w, i) {
      var a = parse(w.test_start), b = parse(w.test_end);
      return {k: i + 1, n: w.n, a: a, b: b, mid: new Date((+a + +b) / 2), ret: w.ret_pct, trades: w.trades, sharpe: w.sharpe, auc: w.ranker_auc};
    });
    var path = [{date: W[0].a, cum: 0}].concat(WF.stitched.map(function (s) { return {date: parse(s.date), cum: s.cum_pct}; }));
    if (WF.daily) path = WF.daily.dates.map(function (d, i) { return {date: parse(d), cum: WF.daily.cum[i]}; });
    // the daily series can run past the last window's end (the simulation continues to the data end)
    var dom = [new Date(Math.min(+W[0].a, +path[0].date)), new Date(Math.max(+W[W.length - 1].b, +path[path.length - 1].date))];
    var ext = domainPad(W.map(function (w) { return w.ret; }), 0.25, [0]);
    var pos = W.filter(function (w) { return w.ret >= 0; }), neg = W.filter(function (w) { return w.ret < 0; });
    var label = function (w) { return w.trades ? String(w.trades) : 'none'; };
    var pane1 = plot(c, {
      height: c.narrow ? 200 : 230, marginLeft: 46, marginRight: 16, marginTop: 22, marginBottom: 6,
      x: {type: 'utc', domain: dom, axis: null},
      y: {domain: ext, label: 'Window net return, %', labelArrow: 'none'},
      marks: [
        gridY(c), axisY(c, {label: 'Window net return, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        P.rect(W, {x1: 'a', x2: 'b', y1: 0, y2: 'ret', fill: function (w) { return signColor(c)(w.ret); }, insetLeft: 2, insetRight: 2, rx1y2: 3, rx2y2: 3}),
        zeroY(c),
        P.text(pos, {x: 'mid', y: 'ret', text: label, dy: -8, fill: c.t.ink2, fontSize: 11}),
        P.text(neg, {x: 'mid', y: 'ret', text: label, dy: 9, fill: c.t.ink2, fontSize: 11}),
        tip(c, W, P.pointerX({x: 'mid', y: 'ret', title: function (w) {
          return 'Window ' + w.k + ' of ' + W.length + ' · ' + fmtDate(w.a) + ' – ' + fmtDate(w.b) + '\nNet return ' + pct(w.ret, 3) +
            '\nTrades entered ' + w.trades + '\nSharpe ' + num(w.sharpe, 2) + (w.auc !== null ? '\nRanker AUC ' + num(w.auc, 3) : '');
        }}))
      ]
    });
    var lastP = path[path.length - 1];
    var pane2 = plot(c, {
      height: c.narrow ? 140 : 150, marginLeft: 46, marginRight: c.narrow ? 46 : 60, marginTop: 20, marginBottom: 26,
      x: {type: 'utc', domain: dom},
      y: {domain: domainPad(path.map(function (p) { return p.cum; }), 0.15, [0]), label: 'Stitched path, %', labelArrow: 'none'},
      marks: [
        gridY(c, {ticks: 4}), axisY(c, {ticks: 4, label: 'Stitched path, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisX(c, {ticks: c.narrow ? 4 : 7}),
        zeroY(c),
        P.lineY(path, {x: 'date', y: 'cum', stroke: c.t.s1, strokeWidth: 2}),
        WF.daily ? null : P.dot(path, {x: 'date', y: 'cum', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        P.text([lastP], {x: 'date', y: 'cum', text: function (p) { return pct(p.cum); }, dx: 8, textAnchor: 'start', fill: c.t.ink, fontWeight: 600}),
        tip(c, path, P.pointerX({x: 'date', y: 'cum', title: function (p) { return fmtDate(p.date) + '\nStitched ' + pct(p.cum, 3); }}))
      ].filter(Boolean)
    });
    pane1.classList.add('plot-pane');
    pane2.classList.add('plot-pane');
    return {
      nodes: [pane1, pane2],
      legend: [{label: 'Window gain', color: '--pos', kind: 'box'}, {label: 'Window loss', color: '--neg', kind: 'box'},
               {label: 'Labels: trades entered in the window', color: '--ink-3', kind: 'none'}],
      table: table('Walk-forward test windows (net, % of capital).',
        ['Window', 'Test start', 'Test end', 'Net return', 'Sharpe', 'Trades', 'Ranker AUC', 'Stitched', "Run's window no."],
        [false, false, false, true, true, true, true, true, true],
        W.map(function (w, i) {
          return [String(w.k), fmtISO(w.a), fmtISO(w.b), pct(w.ret, 3), num(w.sharpe, 2), String(w.trades),
                  num(w.auc, 3), pct(WF.stitched[i] ? WF.stitched[i].cum_pct : null, 3), String(w.n)];
        }))
    };
  };

  // ── Exhibit 4: monthly returns heatmap ────────────────────────────────────
  X.monthly = function (S, c) {
    var M = S.dev && S.dev.monthly;
    if (!M || !M.length) return null;
    var P = global.Plot;
    var cells = M.map(function (m) { return {year: m.ym.slice(0, 4), col: MONTHS[+m.ym.slice(5, 7) - 1], v: m.ret_pct}; });
    (S.dev.annual || []).forEach(function (a) { cells.push({year: a.year, col: 'Year', v: a.ret_pct, months: a.months}); });
    var years = Array.from(new Set(cells.map(function (d) { return d.year; })));
    var cols = MONTHS.concat(['Year']);
    var m = Math.max.apply(null, cells.map(function (d) { return Math.abs(d.v); })) || 1;
    var fillOf = global.d3.scaleLinear().domain([-m, 0, m]).range([c.t.neg, c.t.mid, c.t.pos]).interpolate(global.d3.interpolateLab);
    var strong = function (d) { return contrast(fillOf(d.v), c.t.paper) > contrast(fillOf(d.v), c.t.ink); };
    var t = c.narrow;            // transpose on phones: months down, years across
    var xk = t ? 'year' : 'col', yk = t ? 'col' : 'year';
    var cellH = t ? 26 : 40;
    var node = plot(c, {
      height: (t ? cols.length : years.length) * cellH + 34, marginLeft: t ? 40 : 44, marginRight: 4, marginTop: 26, marginBottom: 4,
      x: {domain: t ? years : cols, axis: 'top', label: null, tickSize: 0, padding: 0.06},
      y: {domain: t ? cols : years, label: null, tickSize: 0, padding: 0.08},
      color: {type: 'linear', domain: [-m, 0, m], range: [c.t.neg, c.t.mid, c.t.pos], interpolate: 'lab'},
      marks: [
        P.cell(cells, {x: xk, y: yk, fill: 'v', rx: 2}),
        P.text(cells.filter(function (d) { return !strong(d); }), {x: xk, y: yk, text: function (d) { return signed(d.v, 2); }, fill: c.t.ink, fontSize: t ? 11 : 12}),
        P.text(cells.filter(strong), {x: xk, y: yk, text: function (d) { return signed(d.v, 2); }, fill: c.t.paper, fontSize: t ? 11 : 12, fontWeight: 600}),
        tip(c, cells, P.pointer({x: xk, y: yk, title: function (d) {
          return d.col === 'Year' ? d.year + ' (' + d.months + ' months): ' + pct(d.v) : d.col + ' ' + d.year + ': ' + pct(d.v);
        }}))
      ]
    });
    return {
      nodes: [node],
      table: table('Monthly net return, % of capital.', ['Month', 'Net return'], [false, true],
        M.map(function (m2) { return [m2.ym, pct(m2.ret_pct, 3)]; }).concat((S.dev.annual || []).map(function (a) {
          return [a.year + ' (' + a.months + ' months, compounded)', pct(a.ret_pct, 3)];
        })))
    };
  };

  // ── Exhibit 5: rolling Sharpe with a standard-error band ──────────────────
  X.rolling = function (S, c) {
    var R = S.dev && S.dev.rolling_sharpe;
    if (!R || !R.dates || !R.dates.length) return null;
    var P = global.Plot;
    var rows = R.dates.map(function (d, i) { return {date: parse(d), sr: R.sharpe[i], lo: R.lo[i], hi: R.hi[i]}; });
    var node = plot(c, {
      height: c.narrow ? 220 : 260, marginLeft: 40, marginRight: 16, marginTop: 20, marginBottom: 26,
      x: {type: 'utc'},
      y: {domain: domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.04), label: 'Sharpe ratio, annualised', labelArrow: 'none'},
      marks: [
        gridY(c), axisY(c, {label: 'Sharpe ratio, annualised', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
        axisX(c, {ticks: c.narrow ? 4 : 8}),
        P.areaY(rows, {x: 'date', y1: 'lo', y2: 'hi', fill: c.t.neutral, fillOpacity: 0.18}),
        zeroY(c),
        P.lineY(rows, {x: 'date', y: 'sr', stroke: c.t.s1, strokeWidth: 2}),
        tip(c, rows, P.pointerX({x: 'date', y: 'sr', title: function (r) {
          return r.sr === null ? fmtDate(r.date) + '\nflat throughout the window' :
            fmtDate(r.date) + '\nSharpe ' + signed(r.sr, 2) + '\n95% band ' + num(r.lo, 2) + ' to ' + signed(r.hi, 2);
        }}))
      ]
    });
    return {
      nodes: [node],
      legend: [{label: 'Rolling ' + R.window + '-day Sharpe', color: '--series-1', kind: 'line'},
               {label: '±1.96 standard errors', color: '--neutral-series', kind: 'band'}],
      table: table('Rolling ' + R.window + '-day Sharpe ratio (window ending on the date).', ['Window end', 'Sharpe', 'Lower', 'Upper'],
        [false, true, true, true],
        rows.map(function (r) { return [fmtISO(r.date), num(r.sr, 2), num(r.lo, 2), num(r.hi, 2)]; }))
    };
  };

  // ── Exhibit 6: Sharpe forest plot ─────────────────────────────────────────
  X.forest = function (S, c) {
    var F = S.dev && S.dev.forest;
    if (!F || !F.length) return null;
    var P = global.Plot, pw = S.dev.power || {};
    var color = {main: c.t.s1, gross: c.t.s1, oos: c.t.s1, gatev: c.t.s2, diff_main: c.t.ink2, diff_oos: c.t.ink2, random: c.t.neutral};
    var rows = F.map(function (r) { return Object.assign({}, r, {color: color[r.key] || c.t.ink2}); });
    // rows whose runs do not exist yet keep their place, marked pending or sealed
    var pending = [];
    if (!rows.some(function (r) { return r.key === 'gross'; })) pending.push({label: 'Main backtest, gross of costs', status: 'pending: v33 export'});
    if (S.residual && S.residual.sharpe !== null) {
      rows.push({key: 'residual', label: 'Avellaneda–Lee, net', kind: 'ci', sharpe: S.residual.sharpe, lo: S.residual.lo, hi: S.residual.hi, color: c.t.s3, method: 'block bootstrap'});
    } else pending.push({label: 'Avellaneda–Lee, net', status: 'pending: v33 run'});
    var held = holdoutArm(S, 'v33_pairs');
    if (held) {
      rows.push({key: 'holdout', label: 'Holdout 2026, v33 pairs, net', kind: 'ci', sharpe: held.sharpe, lo: held.lo, hi: held.hi, days: held.days, color: c.t.s3, method: 'block bootstrap'});
    } else pending.push({label: 'Holdout 2026, net', status: 'sealed'});
    var labels = rows.map(function (r) { return r.label; }).concat(pending.map(function (p) { return p.label; }));
    var devRows = rows.filter(function (r) { return r.key !== 'residual' && r.key !== 'holdout'; });
    var xdom = domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.06, [pw.mde || 0, 0]);
    var main = rows.filter(function (r) { return r.key === 'main'; });
    var refs = [];
    if (pw.mde) refs.push({x: pw.mde, text: 'detectable at 80% power: ' + num(pw.mde, 2)});
    var node = plot(c, {
      height: labels.length * (c.narrow ? 40 : 34) + 50, marginLeft: c.narrow ? 132 : 212, marginRight: 16, marginTop: 30, marginBottom: 30,
      x: {domain: xdom, label: 'Annualised Sharpe ratio', labelArrow: 'none'},
      y: {domain: labels, label: null, padding: 0.4},
      marks: [
        gridX(c, {ticks: c.narrow ? 4 : 8}), axisX(c, {ticks: c.narrow ? 4 : 8, label: 'Annualised Sharpe ratio', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisY(c, {lineWidth: c.narrow ? 10 : 20, lineHeight: 1.15, fill: c.t.ink, fontSize: c.narrow ? 11 : 12}),
        zeroX(c),
        // the development period's reference lines span its rows, not the other arms' or pending rows
        P.ruleX(refs, {x: 'x', y1: function () { return devRows[0].label; }, y2: function () { return devRows[devRows.length - 1].label; }, stroke: c.t.ink3, strokeWidth: 1}),
        P.text(refs, {x: 'x', frameAnchor: 'top', text: 'text', dy: -16, textAnchor: 'end', dx: -4, fill: c.t.ink2, fontSize: 11}),
        P.ruleY(rows, {y: 'label', x1: 'lo', x2: 'hi', stroke: 'color', strokeWidth: 2}),
        P.dot(rows, {x: 'sharpe', y: 'label', r: 4.5, fill: 'color', stroke: c.t.paper, strokeWidth: 2}),
        main.length && pw.ucb ? P.tickX(main, {x: function () { return pw.ucb; }, y: 'label', stroke: c.t.ink, strokeWidth: 1.5}) : null,
        main.length && pw.ucb ? P.text(main, halo(c, {x: function () { return pw.ucb; }, y: 'label', text: function () { return (c.narrow ? '95% bound ' : 'one-sided 95% bound ') + num(pw.ucb, 2); }, dy: -13, textAnchor: 'end', dx: 3, fill: c.t.ink2, fontSize: 11})) : null,
        // pending rows say so at the frame's left edge, which stays on screen at any width
        P.text(pending, halo(c, {y: 'label', frameAnchor: 'left', text: 'status', textAnchor: 'start', dx: 2, fill: c.t.ink3, fontSize: 11.5, fontStyle: 'italic'})),
        tip(c, rows, P.pointer({x: 'sharpe', y: 'label', title: function (r) {
          return r.label + '\nSharpe ' + signed(r.sharpe, 2) + '\n' + (r.kind === 'spread' ? '5th–95th pct ' : '95% interval ') + num(r.lo, 2) + ' to ' + signed(r.hi, 2) +
            (r.p !== undefined && r.p !== null ? '\np = ' + num(r.p, 3) : '') + '\n' + r.method;
        }}))
      ].filter(Boolean)
    });
    return {
      nodes: [node],
      legend: [{label: 'Strategy', color: '--series-1', kind: 'dot'}, {label: 'Gatev baseline', color: '--series-2', kind: 'dot'},
               {label: 'Difference', color: '--ink-2', kind: 'dot'}, {label: 'Random pairs', color: '--neutral-series', kind: 'dot'}],
      table: table('Sharpe ratios and intervals. Power: ' + (pw.method || '') + '.', ['Series', 'Sharpe', 'Lower', 'Upper', 'Days', 'Interval'],
        [false, true, true, true, true, false],
        rows.map(function (r) { return [r.label, signed(r.sharpe, 2), num(r.lo, 2), signed(r.hi, 2), r.days ? String(r.days) : '–', r.method]; })
          .concat(pending.map(function (p) { return [p.label, p.status, '', '', '', '']; }))
          .concat(pw.mde ? [['Minimum detectable Sharpe (80% power)', num(pw.mde, 2), '', '', String(pw.n || ''), 'one-sided 5% test'],
                            ['One-sided 95% upper bound, main', num(pw.ucb, 2), '', '', String(pw.n || ''), 'Wald']] : []))
    };
  };

  // ── Exhibit 7: random-pair null distribution ──────────────────────────────
  X.randomnull = function (S, c) {
    var R = S.dev && S.dev.random_sharpes;
    if (!R || !R.length) return null;
    var P = global.Plot, s = S.dev.strategy_sharpe, g = S.dev.gatev_sharpe;
    var lo = Math.floor(Math.min.apply(null, R.concat([s, g])) * 5) / 5 - 0.2;
    var hi = Math.ceil(Math.max.apply(null, R.concat([s, g])) * 5) / 5 + 0.2;
    var thresholds = global.d3.range(lo, hi + 1e-9, 0.2);
    var marks = [{x: s, text: 'Strategy ' + signed(s, 2), color: c.t.s1, anchor: 'end', dx: -6},
                 {x: g, text: 'Gatev ' + signed(g, 2), color: c.t.s2, anchor: 'start', dx: 6}];
    if (s > g) { marks[0].anchor = 'start'; marks[0].dx = 6; marks[1].anchor = 'end'; marks[1].dx = -6; }
    var node = plot(c, {
      height: c.narrow ? 220 : 250, marginLeft: 40, marginRight: 16, marginTop: 30, marginBottom: 30,
      x: {domain: [lo, hi], label: 'Annualised Sharpe ratio of a random-pair draw', labelArrow: 'none'},
      y: {label: 'Draws', labelArrow: 'none'},
      marks: [
        gridY(c), axisY(c, {label: 'Draws', labelArrow: 'none'}),
        axisX(c, {label: 'Annualised Sharpe ratio of a random-pair draw', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        P.rectY(R, P.binX({y: 'count'}, {x: function (v) { return v; }, thresholds: thresholds, fill: c.t.neutral, fillOpacity: 0.55, insetLeft: 1, insetRight: 1, ry2: 2})),
        zeroY(c),
        P.ruleX(marks, {x: 'x', stroke: function (d) { return d.color; }, strokeWidth: 2}),
        P.text(marks.filter(function (m) { return m.anchor === 'end'; }), {x: 'x', text: 'text', frameAnchor: 'top', dy: -14, dx: -6, textAnchor: 'end', fill: c.t.ink, fontWeight: 600}),
        P.text(marks.filter(function (m) { return m.anchor === 'start'; }), {x: 'x', text: 'text', frameAnchor: 'top', dy: -14, dx: 6, textAnchor: 'start', fill: c.t.ink, fontWeight: 600}),
        tip(c, R, P.pointerX(P.binX({y: 'count', title: function (b) { return b.length + ' draws'; }}, {x: function (v) { return v; }, thresholds: thresholds})))
      ]
    });
    var sorted = R.slice().sort(function (a, b) { return a - b; });
    return {
      nodes: [node],
      legend: [{label: 'Random-pair draws', color: '--neutral-series', kind: 'box'}, {label: 'Strategy', color: '--series-1', kind: 'rule'},
               {label: 'Gatev baseline', color: '--series-2', kind: 'rule'}],
      table: table('Sharpe ratios of the random-pair draws, sorted (strategy ' + signed(s, 2) + ', Gatev ' + signed(g, 2) + ', strategy percentile ' + S.dev.random_percentile + ').',
        ['Rank', 'Sharpe'], [true, true], sorted.map(function (v, i) { return [String(i + 1), signed(v, 2)]; }))
    };
  };

  // ── Exhibit 8: deflated Sharpe against the number of trials (+ snooping) ──
  X.dsr = function (S, c) {
    var C = S.dev && S.dev.dsr_curve;
    if (!C || !C.length) return null;
    var P = global.Plot;
    var rows = C.map(function (r) { return {n: r.n, dsr: 100 * r.dsr, star: r.sr_star}; });
    var at = rows.filter(function (r) { return r.n === (S.dev.facts && S.dev.facts.dsr_trials); });
    var node = plot(c, {
      height: c.narrow ? 200 : 220, marginLeft: 40, marginRight: 24, marginTop: 20, marginBottom: 30,
      x: {type: 'log', domain: [rows[0].n, rows[rows.length - 1].n], label: 'Number of independent trials N', labelArrow: 'none'},
      y: {domain: [0, Math.max(50, rows[0].dsr * 1.1)], label: 'Deflated Sharpe, %', labelArrow: 'none'},
      marks: [
        gridY(c, {ticks: 4}), axisY(c, {ticks: 4, label: 'Deflated Sharpe, %', labelArrow: 'none'}),
        axisX(c, {label: 'Number of independent trials N', labelArrow: 'none', tickFormat: function (v) { return global.d3.format(',')(v); }}),
        zeroY(c),
        P.lineY(rows, {x: 'n', y: 'dsr', stroke: c.t.s1, strokeWidth: 2}),
        P.dot(rows, {x: 'n', y: 'dsr', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        P.dot(at, {x: 'n', y: 'dsr', r: 5.5, fill: c.t.paper, stroke: c.t.s1, strokeWidth: 2}),
        P.text(at, {x: 'n', y: 'dsr', text: function (r) { return 'N = ' + r.n + ' (reported): ' + num(r.dsr, 1) + '%'; }, dx: 10, dy: -10, textAnchor: 'start', fill: c.t.ink, fontWeight: 600}),
        tip(c, rows, P.pointerX({x: 'n', y: 'dsr', title: function (r) { return 'N = ' + r.n + '\nDSR ' + num(r.dsr, 1) + '%\nExpected best null Sharpe ' + num(r.star, 2); }}))
      ]
    });
    var sn = S.dev.snooping;
    var slot = c.figure && c.figure.querySelector('[data-snoop]');
    if (slot && sn && sn.results) {
      var r = sn.results;
      var tbl = buildTable(table('Data-snooping tests over the declared variant family.', ['Test', 'Result'], [false, true], [
        ['Hansen SPA p (consistent)', num(r.spa_p, 3)], ['White Reality Check p', num(r.reality_check_p, 3)],
        ['Romano–Wolf: variants rejected at 5%', String((r.romano_wolf_rejected || []).length)],
        ['Model confidence set (90%): variants kept', String((r.mcs_included || []).length)],
        ['Effective number of trials', num(r.effective_trials, 1)], ['PBO', r.pbo === null || r.pbo === undefined ? '–' : num(100 * r.pbo, 1, {suffix: '%'})]]));
      slot.replaceChildren(tbl);
    }
    return {
      nodes: [node],
      table: table('Deflated Sharpe ratio of the main backtest by number of trials.', ['Trials N', 'DSR', 'Expected best null Sharpe'],
        [true, true, true], rows.map(function (r) { return [String(r.n), num(r.dsr, 2, {suffix: '%'}), num(r.star, 2)]; }))
    };
  };

  // ── Exhibit 9: implementation-shortfall waterfall ─────────────────────────
  X.waterfall = function (S, c) {
    var steps = (S.dev && (S.dev.shortfall || S.dev.waterfall)) || [];
    if (!steps.length) return null;
    var P = global.Plot;
    var cap = (S.dev.run && S.dev.run.capital) || 1e8;
    var rows = steps.map(function (s) {
      var total = s.key === 'gross' || s.key === 'net' || s.key === 'paper';
      return {step: s.step, a: s.start / 1e3, b: s.end / 1e3, usd: s.usd, total: total, bp: s.usd / cap * 1e4};
    });
    var fill = function (r) { return r.total ? c.t.ink2 : signColor(c)(r.usd); };
    var right = rows.filter(function (r) { return r.b >= r.a; });      // bar grows rightwards: label at its end
    var left = rows.filter(function (r) { return r.b < r.a; });
    var mL = c.narrow ? 98 : 120, mR = 16;
    // room for each value label beyond its bar's end, so none runs into the step names or off the page
    var xs = fitLabels(domainPad(rows.map(function (r) { return r.a; }).concat(rows.map(function (r) { return r.b; })), 0.04, [0]),
      rows.map(function (r) {
        var grows = r.b >= r.a;
        return {x: grows ? r.b : Math.min(r.a, r.b), px: textWidth(usdk(r.usd), 11.5) + 12, side: grows ? 'right' : 'left'};
      }), c.width - mL - mR);
    var node = plot(c, {
      height: rows.length * 38 + 50, marginLeft: mL, marginRight: mR, marginTop: 10, marginBottom: 30,
      x: {domain: xs, label: '$ thousands', labelArrow: 'none'},
      y: {domain: rows.map(function (r) { return r.step; }), label: null, padding: 0.3},
      marks: [
        gridX(c), axisX(c, {label: '$ thousands', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
        axisY(c, {fill: c.t.ink, fontSize: 12}),
        zeroX(c),
        P.barX(rows, {y: 'step', x1: 'a', x2: 'b', fill: fill, rx: 2}),
        P.text(right, halo(c, {y: 'step', x: 'b', text: function (r) { return usdk(r.usd); }, dx: 6, textAnchor: 'start', fill: c.t.ink, fontSize: 11.5})),
        P.text(left, halo(c, {y: 'step', x: function (r) { return Math.min(r.a, r.b); }, text: function (r) { return usdk(r.usd); }, dx: -6, textAnchor: 'end', fill: c.t.ink, fontSize: 11.5})),
        tip(c, rows, P.pointerY({y: 'step', x: 'b', title: function (r) {
          return r.step + '\n' + money(r.usd) + '\n' + signed(r.bp, 1) + ' bp of starting capital';
        }}))
      ]
    });
    return {
      nodes: [node],
      table: table('Implementation shortfall, main backtest.', ['Step', '$', 'bp of capital', 'Running total, $'],
        [false, true, true, true], rows.map(function (r) { return [r.step, signed(r.usd, 2), signed(r.bp, 1), signed(r.b * 1e3, 2)]; }))
    };
  };

  // ── Exhibit 10: trade anatomy small multiples ─────────────────────────────
  X.anatomy = function (S, c) {
    var T = S.dev && S.dev.trades;
    if (!T || !T.by_exit) return null;
    var P = global.Plot;
    var panels = [['By exit', T.by_exit], ['By side of the spread', T.by_side], ['By |z| at entry', T.by_z]];
    var groups = [].concat(T.by_exit, T.by_side, T.by_z);
    var wrap = document.createElement('div');
    wrap.className = 'multi multi-3';
    var cols = c.narrow ? 1 : 3;
    var cw = Math.floor((c.width - (cols - 1) * 24) / cols);
    wrap.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    var mL = 86, mR = 8;
    // one x scale for the three panels, wide enough for every "n = ..." label beyond its bar
    var xs = fitLabels(domainPad(groups.map(function (g) { return g.net_usd / 1e6; }), 0.04, [0]), groups.map(function (g) {
      return {x: g.net_usd / 1e6, px: textWidth('n = ' + g.n, 11) + 10, side: g.net_usd >= 0 ? 'right' : 'left'};
    }), cw - mL - mR);
    // side by side, the panels share one height and baseline: a panel with fewer rows keeps
    // the same row step and centres its rows in the frame
    var ROW = 36, MT = 6, MB = 28;
    var maxRows = Math.max.apply(null, panels.map(function (pp) { return pp[1].length; }));
    panels.forEach(function (pp) {
      var rows = pp[1].map(function (g) { return Object.assign({}, g, {k: g.net_usd / 1e6}); });
      var cell = document.createElement('div');
      cell.className = 'multi-cell';
      var h = document.createElement('p');
      h.className = 'mc-title';
      h.textContent = pp[0];
      cell.appendChild(h);
      var pos = rows.filter(function (r) { return r.k >= 0; }), neg = rows.filter(function (r) { return r.k < 0; });
      var slots = cols > 1 ? maxRows : rows.length;
      var top = MT + (slots - rows.length) * ROW / 2;
      cell.appendChild(plot(Object.assign({}, c, {width: cw}), {
        height: slots * ROW + MT + MB + 2, marginLeft: mL, marginRight: mR, marginTop: MT, marginBottom: MB,
        x: {domain: xs, label: '$ millions', labelArrow: 'none'},
        y: {domain: rows.map(function (r) { return r.label; }), label: null, padding: 0.3, range: [top, top + rows.length * ROW + 2]},
        marks: [
          gridX(c, {ticks: 4}), axisX(c, {ticks: 4, label: '$ millions', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
          axisY(c, {fill: c.t.ink}),
          zeroX(c),
          P.barX(rows, {y: 'label', x: 'k', fill: function (r) { return signColor(c)(r.k); }, rx2: 3}),
          P.text(pos, {y: 'label', x: 'k', text: function (r) { return 'n = ' + r.n; }, dx: 5, textAnchor: 'start', fill: c.t.ink2, fontSize: 11}),
          P.text(neg, {y: 'label', x: 'k', text: function (r) { return 'n = ' + r.n; }, dx: -5, textAnchor: 'end', fill: c.t.ink2, fontSize: 11}),
          tip(c, rows, P.pointerY({y: 'label', x: 'k', title: function (r) {
            return r.label + ' · ' + r.n + ' trades, ' + r.wins + ' winners\nNet ' + money(r.net_usd) + '\nGross ' + money(r.gross_usd) + ', costs ' + money(-r.cost_usd) +
              '\nMean net ' + signed(r.mean_net_bp, 1) + ' bp of notional';
          }}))
        ]
      }));
      wrap.appendChild(cell);
    });
    var rowsT = [];
    panels.forEach(function (pp) {
      pp[1].forEach(function (g) {
        rowsT.push([pp[0], g.label, String(g.n), String(g.wins), usdk(g.gross_usd), usdk(-g.cost_usd), usdk(g.net_usd), signed(g.mean_net_bp, 1)]);
      });
    });
    return {
      nodes: [wrap],
      table: table('Trades by group ($ thousands; mean net in bp of gross notional).', ['Group', 'Bucket', 'Trades', 'Winners', 'Gross', 'Costs', 'Net', 'Mean net, bp'],
        [false, false, true, true, true, true, true, true], rowsT)
    };
  };

  // ── Exhibit 15: cost-schedule replay small multiples ──────────────────────
  X.schedules = function (S, c) {
    var C = S.dev && S.dev.cost_schedules;
    if (!C || !C.length) return null;
    var P = global.Plot;
    var dates = S.dev.daily.dates;
    var all = [];
    C.forEach(function (s) { all = all.concat(s.cum); });
    var ys = domainPad(all, 0.08, [0]);
    var wrap = document.createElement('div');
    wrap.className = 'multi';
    var cols = c.narrow ? 2 : (c.width < 820 ? 3 : 5);
    var cw = Math.floor((c.width - (cols - 1) * 14) / cols);
    wrap.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    C.forEach(function (s) {
      var ds = s.dates || dates;
      var rows = s.cum.map(function (v, i) { return {date: parse(ds[i]), v: v}; });
      var last = rows[rows.length - 1];
      var cell = document.createElement('div');
      cell.className = 'multi-cell';
      var h = document.createElement('p');
      h.className = 'mc-title';
      h.textContent = 'Schedule ' + s.id + ': ' + pct(s.ret_pct);
      var p = document.createElement('p');
      p.textContent = num(s.commission_bps, 1) + ' bp commission · ' + num(s.half_spread_bps, 1) + ' bp half-spread · impact cap ' +
        num(s.impact_cap_bps, 0) + ' bp · borrow ' + num(s.borrow_pct, 2) + '% · financing ' + num(s.financing_pct, 2) + '% · positions ' +
        num(s.position_pct[0], 0) + '–' + num(s.position_pct[1], 0) + '%';
      cell.appendChild(h);
      cell.appendChild(p);
      cell.appendChild(plot(Object.assign({}, c, {width: cw}), {
        height: 130, marginLeft: 34, marginRight: 6, marginTop: 8, marginBottom: 22,
        x: {type: 'utc', ticks: 2, tickFormat: global.d3.utcFormat('%Y')},
        y: {domain: ys, ticks: 4, label: null, tickFormat: function (v) { return signed(v, 0); }},
        marks: [
          gridY(c, {ticks: 4}), axisY(c, {ticks: 4, tickFormat: function (v) { return signed(v, 0); }}),
          axisX(c, {ticks: 2, tickFormat: global.d3.utcFormat('%Y')}),
          zeroY(c),
          P.lineY(rows, {x: 'date', y: 'v', stroke: c.t.s1, strokeWidth: 1.75}),
          P.dot([last], {x: 'date', y: 'v', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
          tip(c, rows, P.pointerX({x: 'date', y: 'v', title: function (r) { return 'Schedule ' + s.id + '\n' + fmtDate(r.date) + '\n' + pct(r.v); }}))
        ]
      }));
      wrap.appendChild(cell);
    });
    return {
      nodes: [wrap],
      table: table('Cost schedules A–E: parameters and results of the replay.',
        ['Schedule', 'Commission, bp', 'Half-spread, bp', 'Impact cap, bp', 'Borrow, %/yr', 'Financing, %/yr', 'Position, % equity',
         'Net return', 'Sharpe', 'Max drawdown', 'Costs, % capital', 'Peak gross, ×'],
        [false, true, true, true, true, true, false, true, true, true, true, true],
        C.map(function (s) {
          return [s.id, num(s.commission_bps, 1), num(s.half_spread_bps, 1), num(s.impact_cap_bps, 0), num(s.borrow_pct, 2), num(s.financing_pct, 2),
                  num(s.position_pct[0], 0) + '–' + num(s.position_pct[1], 0), pct(s.ret_pct), num(s.sharpe, 2), num(s.max_dd_pct, 2, {suffix: '%'}),
                  num(s.cost_pct, 2), num(s.peak_gross_x, 2)];
        }))
    };
  };

  // ── Exhibit 17: factor loadings ───────────────────────────────────────────
  X.factors = function (S, c) {
    var F = S.dev && S.dev.factors;
    if (!F || !F.rows || !F.rows.length) return null;
    var P = global.Plot;
    // one row per loading; with the multi-factor attribution (v33 exports) one row per factor,
    // the main backtest (filled dots) and the walk-forward (open dots) offset within it
    var multi = !!F.multi_factor;
    var rows = F.rows.filter(function (r) { return r.beta !== null; })
      .map(function (r) { return Object.assign({}, r, {label: multi ? r.name : r.series, oos: r.series !== 'Main backtest'}); });
    var labels = Array.from(new Set(rows.map(function (r) { return r.label; })));
    var step = multi ? 30 : 40;
    var lane = function (oos) { return multi ? (oos ? 5 : -5) : 0; };
    var series = [false, true].map(function (oos) {
      var rs = rows.filter(function (r) { return r.oos === oos; });
      return [
        P.ruleY(rs, {y: 'label', x1: 'lo', x2: 'hi', stroke: c.t.s1, strokeWidth: 2, dy: lane(oos)}),
        P.dot(rs, {x: 'beta', y: 'label', r: 4.5, fill: oos && multi ? c.t.paper : c.t.s1, stroke: oos && multi ? c.t.s1 : c.t.paper, strokeWidth: 2, dy: lane(oos)})
      ];
    });
    var mL = c.narrow ? 112 : 130, mR = 20;
    var xdom = domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.15, [0]);
    if (!multi) {        // room for the t labels beyond each interval
      xdom = fitLabels(xdom, rows.map(function (r) { return {x: r.hi, px: textWidth('t = ' + num(r.t, 2), 11) + 12, side: 'right'}; }), c.width - mL - mR);
    }
    var node = plot(c, {
      height: labels.length * step + 56, marginLeft: mL, marginRight: mR, marginTop: 14, marginBottom: 34,
      x: {domain: xdom, label: 'Beta (95% interval)', labelArrow: 'none'},
      y: {domain: labels, label: null, padding: multi ? 0.2 : 0.4},
      marks: [
        gridX(c, {ticks: c.narrow ? 3 : 5}), axisX(c, {ticks: c.narrow ? 3 : 5, label: 'Beta (95% interval)', labelArrow: 'none', tickFormat: function (v) { return signed(v, multi ? 2 : 3); }}),
        axisY(c, {fill: c.t.ink, lineWidth: 12}),
        zeroX(c)
      ].concat(series[0], series[1], [
        multi ? null : P.text(rows, {x: 'hi', y: 'label', text: function (r) { return 't = ' + num(r.t, 2); }, dx: 8, textAnchor: 'start', fill: c.t.ink2, fontSize: 11}),
        tip(c, rows, P.pointer({x: 'beta', y: 'label', title: function (r) { return r.series + (multi ? ': ' + r.name : '') + '\nbeta ' + signed(r.beta, 4) + ' (t = ' + num(r.t, 2) + ')\n95% ' + num(r.lo, 4) + ' to ' + signed(r.hi, 4); }}))
      ]).filter(Boolean)
    });
    return {
      nodes: [node],
      legend: multi ? [{label: 'Main backtest', color: '--series-1', kind: 'dot'}, {label: 'Walk-forward OOS', color: '--series-1', kind: 'dot ring'}] : null,
      table: table('Factor loadings (Newey–West) and annualised alpha; ' + (multi ? 'factors: ' : 'proxy: ') + (F.proxy || 'n/a') + '.',
        ['Series', 'Factor', 'Beta', 't', 'Lower', 'Upper'], [false, false, true, true, true, true],
        rows.map(function (r) { return [r.series, r.name, signed(r.beta, 4), num(r.t, 2), num(r.lo, 4), signed(r.hi, 4)]; })
          .concat((F.alpha || []).map(function (a) { return [a.series, 'Alpha, % a year', pct(a.alpha_ann_pct), num(a.t, 2), '', 'R² ' + num(a.r2, 3)]; })))
    };
  };

  // ── Exhibit 18: daily return distribution ─────────────────────────────────
  X.distribution = function (S, c) {
    var D = S.dev && S.dev.daily;
    if (!D || !D.net) return null;
    var P = global.Plot;
    var bp = D.net.map(function (v) { return v * 100; });
    var lo = Math.floor(Math.min.apply(null, bp) / 5) * 5, hi = Math.ceil(Math.max.apply(null, bp) / 5) * 5;
    var thresholds = global.d3.range(lo - 1.25, hi + 2.5, 2.5);
    var node = plot(c, {
      height: c.narrow ? 220 : 250, marginLeft: 40, marginRight: 16, marginTop: 20, marginBottom: 30,
      x: {label: 'Daily net return, bp of capital', labelArrow: 'none'},
      y: {label: 'Days', labelArrow: 'none'},
      marks: [
        gridY(c), axisY(c, {label: 'Days', labelArrow: 'none'}),
        axisX(c, {label: 'Daily net return, bp of capital', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
        P.rectY(bp, P.binX({y: 'count'}, {x: function (v) { return v; }, thresholds: thresholds, fill: c.t.s1, fillOpacity: 0.8, insetLeft: 0.5, insetRight: 0.5})),
        zeroY(c),
        tip(c, bp, P.pointerX(P.binX({y: 'count', title: function (b) { return b.length + ' days'; }}, {x: function (v) { return v; }, thresholds: thresholds})))
      ]
    });
    var sorted = bp.slice().sort(function (a, b) { return a - b; });
    var q = function (p) { return global.d3.quantileSorted(sorted, p); };
    return {
      nodes: [node],
      table: table('Daily net return, bp of capital: summary.', ['Statistic', 'Value'], [false, true], [
        ['Days', String(bp.length)], ['Zero-return days', String(bp.filter(function (v) { return v === 0; }).length)],
        ['Worst day', signed(sorted[0], 1)], ['5th percentile', signed(q(0.05), 1)], ['Median', signed(q(0.5), 1)],
        ['95th percentile', signed(q(0.95), 1)], ['Best day', signed(sorted[sorted.length - 1], 1)],
        ['Skew', num(S.dev.power && S.dev.power.skew, 2)], ['Kurtosis (non-excess)', num(S.dev.power && S.dev.power.kurtosis, 2)]])
    };
  };

  // ── Exhibit 19: selection funnel ──────────────────────────────────────────
  X.funnel = function (S, c) {
    var F = S.dev && S.dev.funnel;
    if (!F || !F.pairs || !F.pairs.length) return null;
    var P = global.Plot;
    var ramp = [c.t.ord1, c.t.ord2, c.t.ord3, c.t.ord4, c.t.ord4];
    var rows = F.pairs.map(function (s, i) { return Object.assign({}, s, {color: ramp[Math.min(i, ramp.length - 1)], share: i ? s.n / F.pairs[i - 1].n : null}); });
    var exp = rows.filter(function (r) { return r.expected; });
    var maxN = Math.max.apply(null, rows.map(function (r) { return r.n; }));
    var node = plot(c, {
      height: rows.length * 44 + 50, marginLeft: c.narrow ? 118 : 196, marginRight: 70, marginTop: 10, marginBottom: 30,
      x: {domain: [0, maxN * 1.02], label: 'Pairs', labelArrow: 'none'},
      y: {domain: rows.map(function (r) { return r.stage; }), label: null, padding: 0.32},
      marks: [
        gridX(c, {ticks: 4}), axisX(c, {ticks: 4, label: 'Pairs', labelArrow: 'none', tickFormat: global.d3.format(',')}),
        axisY(c, {fill: c.t.ink, lineWidth: c.narrow ? 10 : 22}),
        P.barX(rows, {y: 'stage', x: 'n', fill: 'color', rx2: 3}),
        zeroX(c),
        P.text(rows, {y: 'stage', x: 'n', text: function (r) { return global.d3.format(',')(r.n); }, dx: 6, textAnchor: 'start', fill: c.t.ink, fontWeight: 600, fontSize: 12}),
        // the count chance alone would produce: a tick on the bar, its value beside the bar's own
        P.tickX(exp, {y: 'stage', x: 'expected', stroke: c.t.ink, strokeWidth: 2}),
        P.text(exp, {y: 'stage', x: 'n', text: function (r) { return '(' + global.d3.format(',.0f')(r.expected) + ' by chance)'; }, dx: 6, dy: 15, textAnchor: 'start', fill: c.t.ink2, fontSize: 11}),
        tip(c, rows, P.pointerY({y: 'stage', x: 'n', title: function (r) {
          return r.stage + '\n' + global.d3.format(',')(r.n) + ' pairs' + (r.share !== null ? '\n' + num(100 * r.share, 1) + '% of the previous stage' : '') +
            (r.expected ? '\nexpected by chance ' + global.d3.format(',.0f')(r.expected) : '');
        }}))
      ]
    });
    var names = (F.names || []).map(function (s) { return [s.stage, global.d3.format(',')(s.n), '']; });
    return {
      nodes: [node],
      table: table('Selection funnel (formation data). Benjamini–Hochberg survivors at q = 0.05: ' + F.bh_q05 + '.',
        ['Stage', 'Count', 'Share of previous'], [false, true, true],
        names.concat(rows.map(function (r) { return [r.stage, global.d3.format(',')(r.n), r.share === null ? '' : num(100 * r.share, 1, {suffix: '%'})]; })))
    };
  };

  // ── Exhibits that fill in when later runs land (pending until then) ───────

  // Exhibit 24: point-in-time universe at each formation date (exports from v33 on)
  X.universe = function (S, c) {
    var U = S.dev && S.dev.universe_by_formation;
    if (!U || !U.length) return null;
    var P = global.Plot, fmtN = global.d3.format(',');
    var rows = U.map(function (u) {
      return Object.assign({}, u, {label: fmtDate(parse(u.formation_date)), cover: 100 * u.with_prices / u.members,
                                   gap: (u.missing_weight_pct || 0) + (u.unmapped_weight_pct || 0)});
    });
    var labels = rows.map(function (r) { return r.label; });
    var counts = [], weights = [];
    rows.forEach(function (r) {
      counts.push({label: r.label, part: 'With price history', v: r.with_prices, fill: c.t.s1, r: r});
      counts.push({label: r.label, part: 'Without price history', v: r.missing, fill: c.t.neutral, r: r});
      weights.push({label: r.label, part: 'Members without price history', v: r.missing_weight_pct || 0, op: 1, r: r});
      weights.push({label: r.label, part: 'Holdings without a usable ticker', v: r.unmapped_weight_pct || 0, op: 0.45, r: r});
    });
    var cols = c.width >= 680 ? 2 : 1;
    var cw = Math.floor((c.width - (cols - 1) * 28) / cols);
    var wrap = document.createElement('div');
    wrap.className = 'multi multi-3';
    wrap.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    function panel(title, node) {
      var cell = document.createElement('div');
      cell.className = 'multi-cell';
      var h = document.createElement('p');
      h.className = 'mc-title';
      h.textContent = title;
      cell.appendChild(h);
      cell.appendChild(node);
      wrap.appendChild(cell);
    }
    var height = rows.length * 30 + 44, mL = 92;
    var maxM = Math.max.apply(null, rows.map(function (r) { return r.members; }));
    panel('Index members, labelled with the share that has price history', plot(Object.assign({}, c, {width: cw}), {
      height: height, marginLeft: mL, marginRight: 64, marginTop: 6, marginBottom: 30,
      x: {domain: [0, maxM * 1.02], label: 'Members', labelArrow: 'none'},
      y: {domain: labels, label: null, padding: 0.28},
      marks: [
        gridX(c, {ticks: 4}), axisX(c, {ticks: 4, label: 'Members', labelArrow: 'none', tickFormat: fmtN}),
        axisY(c, {fill: c.t.ink}),
        P.barX(counts, {y: 'label', x: 'v', fill: 'fill'}),
        zeroX(c),
        P.text(rows, {y: 'label', x: 'members', text: function (r) { return num(r.cover, 1, {suffix: '%'}); }, dx: 6, textAnchor: 'start', fill: c.t.ink2, fontSize: 11}),
        tip(c, rows, P.pointerY({y: 'label', x: 'members', title: function (r) {
          return 'Formation ' + r.formation_date + ' (snapshot ' + r.snapshot + ')\n' + fmtN(r.members) + ' members, ' + fmtN(r.with_prices) +
            ' with price history (' + num(r.cover, 1) + '%)\n' + fmtN(r.missing) + ' without';
        }}))
      ]
    }));
    var maxW = Math.max.apply(null, rows.map(function (r) { return r.gap; }));
    panel('Index weight not covered, %', plot(Object.assign({}, c, {width: cw}), {
      height: height, marginLeft: mL, marginRight: 48, marginTop: 6, marginBottom: 30,
      x: {domain: [0, Math.max(1, maxW * 1.08)], label: '% of index weight', labelArrow: 'none'},
      y: {domain: labels, label: null, padding: 0.28},
      marks: [
        gridX(c, {ticks: 4}), axisX(c, {ticks: 4, label: '% of index weight', labelArrow: 'none', tickFormat: function (v) { return num(v, 1); }}),
        axisY(c, {fill: c.t.ink}),
        P.barX(weights, {y: 'label', x: 'v', fill: c.t.neutral, fillOpacity: 'op'}),
        zeroX(c),
        P.text(rows, {y: 'label', x: 'gap', text: function (r) { return num(r.gap, 2, {suffix: '%'}); }, dx: 6, textAnchor: 'start', fill: c.t.ink2, fontSize: 11}),
        tip(c, rows, P.pointerY({y: 'label', x: 'gap', title: function (r) {
          return 'Formation ' + r.formation_date + '\nMembers without price history ' + num(r.missing_weight_pct, 2) + '%' +
            '\nHoldings without a usable ticker ' + num(r.unmapped_weight_pct, 2) + '%\nTotal ' + num(r.gap, 2) + '% of index weight';
        }}))
      ]
    }));
    return {
      nodes: [wrap],
      label: 'Two panels by formation date: index members split into those with and without price history, and the index weight not covered.',
      legend: [{label: 'With price history', color: '--series-1', kind: 'box'}, {label: 'Without price history', color: '--neutral-series', kind: 'box'},
               {label: 'No usable ticker (weight only)', color: '--neutral-series', kind: 'box box-light'}],
      table: table('Point-in-time universe at each formation date.',
        ['Formation date', 'Snapshot', 'Members', 'With prices', 'Without prices', 'Coverage', 'Weight without prices', 'Weight without ticker'],
        [false, false, true, true, true, true, true, true],
        rows.map(function (r) {
          return [r.formation_date, r.snapshot, fmtN(r.members), fmtN(r.with_prices), fmtN(r.missing), num(r.cover, 1, {suffix: '%'}),
                  num(r.missing_weight_pct, 2, {suffix: '%'}), num(r.unmapped_weight_pct, 2, {suffix: '%'})];
        }))
    };
  };

  // Exhibit 11: Sharpe against a cost multiplier (needs the daily gross/cost split)
  X.costcurve = function (S, c) {
    var C = S.dev && S.dev.cost_curve;
    if (!C || !C.length) return null;
    var P = global.Plot;
    var be = null;                          // linear interpolation of the zero crossing
    for (var i = 1; i < C.length; i++) {
      if ((C[i - 1].sharpe >= 0) !== (C[i].sharpe >= 0)) be = C[i - 1].k + (C[i].k - C[i - 1].k) * C[i - 1].sharpe / (C[i - 1].sharpe - C[i].sharpe);
    }
    // without a crossing, say why: net Sharpe is negative (or positive) at every multiple shown
    var note = be !== null ? null : (C[0].sharpe < 0 ? 'below zero even at zero cost: no break-even' : 'above zero at every multiple shown');
    var node = plot(c, {
      height: 200, marginLeft: 40, marginRight: 16, marginTop: 26, marginBottom: 30,
      x: {label: 'Multiple of modelled costs', labelArrow: 'none'},
      y: {domain: domainPad(C.map(function (r) { return r.sharpe; }), 0.1, [0]), label: 'Net Sharpe', labelArrow: 'none'},
      marks: [gridY(c), axisY(c, {label: 'Net Sharpe', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisX(c, {label: 'Multiple of modelled costs', labelArrow: 'none', tickFormat: function (v) { return num(v, 1) + '×'; }}),
        zeroY(c), P.ruleX([1], {stroke: c.t.ink3}),
        P.text([1], halo(c, {x: function (v) { return v; }, frameAnchor: 'top', text: function () { return 'modelled'; }, dy: 8, dx: 4, textAnchor: 'start', fill: c.t.ink2, fontSize: 11})),
        P.lineY(C, {x: 'k', y: 'sharpe', stroke: c.t.s1, strokeWidth: 2}), P.dot(C, {x: 'k', y: 'sharpe', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        be === null ? null : P.text([be], halo(c, {x: function (v) { return v; }, y: function () { return 0; }, text: function (v) { return 'break-even ' + num(v, 2) + '×'; }, dy: -10, fill: c.t.ink, fontSize: 11})),
        note === null ? null : P.text([note], halo(c, {frameAnchor: 'bottom-left', text: function (v) { return v; }, dx: 6, dy: -6, textAnchor: 'start', fill: c.t.ink2, fontSize: 11})),
        tip(c, C, P.pointerX({x: 'k', y: 'sharpe', title: function (r) { return num(r.k, 2) + '× costs\nSharpe ' + signed(r.sharpe, 2) + '\nReturn ' + pct(r.ret_pct); }}))].filter(Boolean)
    });
    return {nodes: [node], label: 'Line of net Sharpe ratio against the multiple of modelled costs.',
      table: table('Net Sharpe and return by cost multiple.', ['Cost multiple', 'Sharpe', 'Return'], [true, true, true],
        C.map(function (r) { return [num(r.k, 2) + '×', signed(r.sharpe, 2), pct(r.ret_pct)]; }))};
  };

  // Exhibit 12: exit race. anatomy.json exit_race: {targets, stops, expected_targets, z}
  X.exitrace = function (S, c) {
    var E = S.dev && S.dev.exit_race;
    if (!E) return null;
    var P = global.Plot;
    var rows = [{k: 'Targets hit first', v: E.targets, e: E.expected_targets}, {k: 'Stops hit first', v: E.stops, e: (E.targets + E.stops) - E.expected_targets}];
    var node = plot(c, {
      height: 140, marginLeft: 120, marginRight: 40, marginTop: 10, marginBottom: 28,
      x: {label: 'Trades', labelArrow: 'none'}, y: {domain: rows.map(function (r) { return r.k; }), label: null, padding: 0.3},
      marks: [gridX(c), axisX(c, {label: 'Trades', labelArrow: 'none'}), axisY(c, {fill: c.t.ink}),
        P.barX(rows, {y: 'k', x: 'v', fill: c.t.s1, rx2: 3}), P.tickX(rows, {y: 'k', x: 'e', stroke: c.t.ink, strokeWidth: 2}), zeroX(c),
        tip(c, rows, P.pointerY({y: 'k', x: 'v', title: function (r) { return r.k + ': ' + r.v + '\nexpected with no mean reversion: ' + num(r.e, 1); }}))]
    });
    return {nodes: [node], label: 'Bars of target and stop exits with ticks at the counts expected without mean reversion.',
      legend: [{label: 'Observed', color: '--series-1', kind: 'box'}, {label: 'Expected under the null', color: '--ink', kind: 'rule'}],
      table: table('Exit race (z = ' + num(E.z, 2) + ').', ['Exit', 'Observed', 'Expected'], [false, true, true],
        rows.map(function (r) { return [r.k, String(r.v), num(r.e, 1)]; }))};
  };

  // Exhibit 13: decay. anatomy.json decay: [{period, bp, lo, hi, n}]
  X.decay = function (S, c) {
    var D = S.dev && S.dev.decay;
    if (!D || !D.length) return null;
    var P = global.Plot;
    var node = plot(c, {
      height: D.length * 40 + 50, marginLeft: 150, marginRight: 20, marginTop: 10, marginBottom: 30,
      x: {domain: domainPad(D.map(function (r) { return r.lo; }).concat(D.map(function (r) { return r.hi; })), 0.1, [0]), label: 'Gross bp per trade', labelArrow: 'none'},
      y: {domain: D.map(function (r) { return r.period; }), label: null, padding: 0.4},
      marks: [gridX(c), axisX(c, {label: 'Gross bp per trade', labelArrow: 'none'}), axisY(c, {fill: c.t.ink, lineWidth: 14}), zeroX(c),
        P.ruleY(D, {y: 'period', x1: 'lo', x2: 'hi', stroke: c.t.s1, strokeWidth: 2}),
        P.dot(D, {x: 'bp', y: 'period', r: 4.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        tip(c, D, P.pointer({x: 'bp', y: 'period', title: function (r) { return r.period + '\n' + signed(r.bp, 1) + ' bp (n = ' + r.n + ')'; }}))]
    });
    return {nodes: [node], label: 'Dot plot of gross basis points per trade by period with 95% intervals.',
      table: table('Gross bp per trade by period.', ['Period', 'bp', 'Lower', 'Upper', 'Trades'], [false, true, true, true, true],
        D.map(function (r) { return [r.period, signed(r.bp, 1), num(r.lo, 1), signed(r.hi, 1), String(r.n)]; }))};
  };

  // Exhibit 14: persistence. anatomy.json persistence: {chance_pct, windows: [{window, pct}]}
  X.persistence = function (S, c) {
    var Pd = S.dev && S.dev.persistence;
    if (!Pd || !Pd.windows || !Pd.windows.length) return null;
    var P = global.Plot;
    var node = plot(c, {
      height: 200, marginLeft: 40, marginRight: 16, marginTop: 16, marginBottom: 30,
      x: {domain: Pd.windows.map(function (w) { return w.window; }), label: null}, y: {label: 'Still cointegrated, %', labelArrow: 'none'},
      marks: [gridY(c), axisY(c, {label: 'Still cointegrated, %', labelArrow: 'none'}), axisX(c, {}),
        P.barY(Pd.windows, {x: 'window', y: 'pct', fill: c.t.s1, ry2: 3}), zeroY(c),
        P.ruleY([Pd.chance_pct], {stroke: c.t.ink, strokeWidth: 1.5}),
        tip(c, Pd.windows, P.pointerX({x: 'window', y: 'pct', title: function (w) { return w.window + ': ' + num(w.pct, 1) + '%'; }}))]
    });
    return {nodes: [node], label: 'Bars of the share of pairs still cointegrated by window against the chance rate.',
      legend: [{label: 'Selected pairs still cointegrated', color: '--series-1', kind: 'box'}, {label: 'Chance rate', color: '--ink', kind: 'line'}],
      table: table('Cointegration persistence (chance ' + num(Pd.chance_pct, 1) + '%).', ['Window', 'Still cointegrated'], [false, true],
        Pd.windows.map(function (w) { return [w.window, num(w.pct, 1, {suffix: '%'})]; }))};
  };

  // Exhibit 16: capacity. anatomy.json capacity: [{aum_musd, net_bp}]
  X.capacity = function (S, c) {
    var C = S.dev && S.dev.capacity;
    if (!C || !C.length) return null;
    var P = global.Plot;
    var node = plot(c, {
      height: 200, marginLeft: 40, marginRight: 16, marginTop: 16, marginBottom: 30,
      x: {type: 'log', label: 'Book size, $M', labelArrow: 'none'}, y: {label: 'Net bp per trade', labelArrow: 'none'},
      marks: [gridY(c), axisY(c, {label: 'Net bp per trade', labelArrow: 'none'}), axisX(c, {label: 'Book size, $M', labelArrow: 'none'}), zeroY(c),
        P.lineY(C, {x: 'aum_musd', y: 'net_bp', stroke: c.t.s1, strokeWidth: 2}),
        tip(c, C, P.pointerX({x: 'aum_musd', y: 'net_bp', title: function (r) { return '$' + r.aum_musd + 'M: ' + signed(r.net_bp, 1) + ' bp'; }}))]
    });
    return {nodes: [node], label: 'Line of net basis points per trade against book size.',
      table: table('Capacity curve.', ['Book size, $M', 'Net bp per trade'], [true, true], C.map(function (r) { return [String(r.aum_musd), signed(r.net_bp, 1)]; }))};
  };

  // Exhibit 20: p-value histogram. {edges: [21 values], counts: [20]}
  X.pvalues = function (S, c) {
    var H = (S.dev && S.dev.funnel && S.dev.funnel.pvalue_hist) || (S.dev && S.dev.pvalue_hist);
    if (!H || !H.counts) return null;
    var P = global.Plot;
    var rows = H.counts.map(function (n, i) { return {a: H.edges[i], b: H.edges[i + 1], n: n}; });
    var total = rows.reduce(function (s, r) { return s + r.n; }, 0);
    var uniform = total / rows.length;
    var node = plot(c, {
      height: 200, marginLeft: 48, marginRight: 16, marginTop: 16, marginBottom: 30,
      x: {domain: [0, 1], label: 'Engle–Granger p-value', labelArrow: 'none'}, y: {label: 'Pairs', labelArrow: 'none'},
      marks: [gridY(c), axisY(c, {label: 'Pairs', labelArrow: 'none', tickFormat: global.d3.format(',')}), axisX(c, {label: 'Engle–Granger p-value', labelArrow: 'none'}),
        P.rectY(rows, {x1: 'a', x2: 'b', y: 'n', fill: c.t.s1, insetLeft: 1, insetRight: 1}), zeroY(c),
        P.ruleY([uniform], {stroke: c.t.ink, strokeWidth: 1.5}),
        tip(c, rows, P.pointerX({x: function (r) { return (r.a + r.b) / 2; }, y: 'n', title: function (r) { return 'p ' + num(r.a, 2) + '–' + num(r.b, 2) + ': ' + global.d3.format(',')(r.n); }}))]
    });
    return {nodes: [node], label: 'Histogram of Engle–Granger p-values against the uniform height expected by chance.',
      legend: [{label: 'Pairs tested', color: '--series-1', kind: 'box'}, {label: 'Uniform null', color: '--ink', kind: 'line'}],
      table: table('Engle–Granger p-values (uniform null ' + num(uniform, 0) + ' per bin).', ['Bin', 'Pairs'], [false, true],
        rows.map(function (r) { return [num(r.a, 2) + '–' + num(r.b, 2), global.d3.format(',')(r.n)]; }))};
  };

  // Exhibits 21 and 1: summaries of the other arms against the pairs strategy
  function armSummary(c, arms, caption) {
    var P = global.Plot;
    var widest = Math.max.apply(null, arms.map(function (a) { return textWidth(a.label, 12); }));
    var mL = Math.min(Math.ceil(widest) + 18, Math.floor(c.width * 0.45));
    var node = plot(c, {
      height: arms.length * 40 + 56, marginLeft: mL, marginRight: 20, marginTop: 10, marginBottom: 34,
      x: {domain: domainPad(arms.map(function (a) { return a.lo; }).concat(arms.map(function (a) { return a.hi; })), 0.1, [0]), label: 'Annualised Sharpe ratio', labelArrow: 'none'},
      y: {domain: arms.map(function (a) { return a.label; }), label: null, padding: 0.4},
      marks: [gridX(c), axisX(c, {label: 'Annualised Sharpe ratio', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisY(c, {fill: c.t.ink, fontSize: 12, lineWidth: (mL - 12) / 12}), zeroX(c),     // wrap only past the margin
        P.ruleY(arms, {y: 'label', x1: 'lo', x2: 'hi', stroke: 'color', strokeWidth: 2}),
        P.dot(arms, {x: 'sharpe', y: 'label', r: 4.5, fill: 'color', stroke: c.t.paper, strokeWidth: 2}),
        tip(c, arms, P.pointer({x: 'sharpe', y: 'label', title: function (a) { return a.label + '\nSharpe ' + signed(a.sharpe, 2) + ' [' + num(a.lo, 2) + ', ' + signed(a.hi, 2) + ']'; }}))]
    });
    return {nodes: [node], label: 'Sharpe ratios with 95% intervals by strategy arm.',
      table: table(caption, ['Arm', 'Sharpe', 'Lower', 'Upper', 'Trades'], [false, true, true, true, true],
        arms.map(function (a) { return [a.label, signed(a.sharpe, 2), num(a.lo, 2), signed(a.hi, 2), a.trades === undefined || a.trades === null ? '–' : String(a.trades)]; }))};
  }
  X.residual = function (S, c) {
    var R = S.residual;
    if (!R || R.sharpe === null || R.sharpe === undefined) return null;
    var main = (S.dev.forest || []).filter(function (r) { return r.key === 'main'; })[0];
    var arms = [{label: 'Avellaneda–Lee, net', sharpe: R.sharpe, lo: R.lo, hi: R.hi, trades: R.trades, color: c.t.s3}];
    if (main) arms.push({label: 'Pairs, main backtest, net', sharpe: main.sharpe, lo: main.lo, hi: main.hi, trades: S.dev.facts.trades, color: c.t.s1});
    return armSummary(c, arms, 'Second strategy family against the pairs strategy, development period.');
  };
  // Exhibit 1: the evaluated holdout, one row per pre-registered strategy; also fills the
  // hypotheses table above it (Sharpe, Holm-adjusted p, decision at the registered alpha)
  X.holdout = function (S, c) {
    var H = S.holdout;
    if (!H || H.status !== 'complete' || !H.arms || !H.arms.length) return null;
    var colour = {v33_pairs: c.t.s1, avellaneda_lee: c.t.s3, v32_pairs: c.t.neutral};
    var short = {v33_pairs: 'v33 pairs', avellaneda_lee: 'Avellaneda–Lee', v32_pairs: 'v32 frozen'};
    var arms = H.arms.filter(function (a) { return a.sharpe !== null && a.sharpe !== undefined; }).map(function (a) {
      return Object.assign({}, a, {label: (a.hypothesis ? a.hypothesis + ' · ' : '') + (short[a.key] || a.label), color: colour[a.key] || c.t.ink2});
    });
    var alpha = H.alpha === null || H.alpha === undefined ? 0.05 : H.alpha;
    H.arms.forEach(function (a) {
      var decision = a.p_holm === null || a.p_holm === undefined ? '–' :
        (a.p_holm < alpha ? 'Rejects zero at ' + num(100 * alpha, 0) + '%' : 'Does not reject zero');
      var cells = {sharpe: signed(a.sharpe, 2), p_holm: num(a.p_holm, 3), decision: decision};
      Object.keys(cells).forEach(function (k) {
        var td = document.querySelector('[data-holdout="' + a.key + ':' + k + '"]');
        if (td) { td.textContent = cells[k]; td.classList.remove('muted'); }
      });
    });
    var out = armSummary(c, arms, 'Pre-registered 2026 holdout: ' + (H.test || '') + ', alpha ' + num(alpha, 2) + '.');
    out.table.columns = out.table.columns.concat(['t', 'p (one-sided)', 'p (Holm)', 'Days']);
    out.table.numeric = out.table.numeric.concat([true, true, true, true]);
    out.table.rows = out.table.rows.map(function (row, i) {
      var a = arms[i];
      return row.concat([num(a.t, 2), num(a.p_one_sided, 3), num(a.p_holm, 3), a.days ? String(a.days) : '–']);
    });
    return out;
  };

  // Exhibit 25: known-answer checks; also fills the validation table's result cells
  X.validation = function (S, c) {
    var V = S.validation;
    if (!V) return null;
    var P = global.Plot;
    var cells = {
      edge: V.edge.trades + ' trades, ' + signed(V.edge.mean_bp, 1) + ' bp gross per trade (t = ' + num(V.edge.t, 1) + '), median net Sharpe ' + num(V.edge.median_net_sharpe, 1),
      forced_null: V.forced_null.trades + ' trades, ' + signed(V.forced_null.mean_bp, 1) + ' bp (t = ' + num(V.forced_null.t, 2) + ')',
      hedge_ratio: 'median absolute error ' + num(V.hedge_ratio.median_abs_error, 3) + ' (90th percentile ' + num(V.hedge_ratio.p90_abs_error, 3) + ')',
      selection: num(100 * V.selection.recall, 0) + '% of planted pairs found; worst market admitted ' + num(100 * V.selection.worst_fp_rate, 1) + '% of unrelated pairs'
    };
    document.querySelectorAll('[data-validation]').forEach(function (td) {
      var k = td.getAttribute('data-validation');
      if (cells[k]) { td.textContent = cells[k]; td.classList.remove('muted'); }
    });
    var rows = [{k: 'Planted edge', m: V.edge.mean_bp, se: V.edge.se_bp, color: c.t.s1}, {k: 'Forced null', m: V.forced_null.mean_bp, se: V.forced_null.se_bp, color: c.t.neutral}]
      .filter(function (r) { return r.m !== null && r.se !== null; })
      .map(function (r) { return Object.assign(r, {lo: r.m - 1.96 * r.se, hi: r.m + 1.96 * r.se}); });
    var node = plot(c, {
      height: rows.length * 44 + 56, marginLeft: 110, marginRight: 20, marginTop: 10, marginBottom: 34,
      x: {domain: domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.1, [0]), label: 'Gross bp per trade', labelArrow: 'none'},
      y: {domain: rows.map(function (r) { return r.k; }), label: null, padding: 0.4},
      marks: [gridX(c), axisX(c, {label: 'Gross bp per trade', labelArrow: 'none'}), axisY(c, {fill: c.t.ink}), zeroX(c),
        P.ruleY(rows, {y: 'k', x1: 'lo', x2: 'hi', stroke: 'color', strokeWidth: 2}),
        P.dot(rows, {x: 'm', y: 'k', r: 4.5, fill: 'color', stroke: c.t.paper, strokeWidth: 2})]
    });
    return {nodes: [node], label: 'Dot plot of gross basis points per trade on synthetic markets with 95% intervals.',
      table: table('Known-answer checks (' + V.seeds + ' markets per scenario; all pass: ' + (V.all_pass ? 'yes' : 'no') + ').', ['Check', 'Result'], [false, false],
        Object.keys(cells).map(function (k) { return [k.replace('_', ' '), cells[k]]; }))};
  };

  // ── data tables (shared by site.js) ───────────────────────────────────────
  function buildTable(spec) {
    var wrap = document.createElement('div');
    wrap.className = 'tbl-wrap';
    wrap.setAttribute('role', 'region');
    wrap.setAttribute('aria-label', spec.caption);
    wrap.tabIndex = 0;
    var t = document.createElement('table');
    t.className = 'tbl';
    var cap = document.createElement('caption');
    cap.textContent = spec.caption;
    t.appendChild(cap);
    var thead = document.createElement('thead'), hr = document.createElement('tr');
    spec.columns.forEach(function (h, i) {
      var th = document.createElement('th');
      th.scope = 'col';
      th.textContent = h;
      if (spec.numeric[i]) th.className = 'r';
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    t.appendChild(thead);
    var tb = document.createElement('tbody');
    spec.rows.forEach(function (row) {
      var tr = document.createElement('tr');
      row.forEach(function (v, i) {
        var cell = document.createElement(i === 0 ? 'th' : 'td');
        if (i === 0) cell.scope = 'row';
        cell.textContent = v;
        if (spec.numeric[i]) cell.className = 'r';
        tr.appendChild(cell);
      });
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    return wrap;
  }

  global.Exhibits = X;
  global.ExhibitTable = buildTable;
})(window);
