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
  // zero is the comparison in almost every exhibit: its rule is heavier than the grid and the axis
  function zeroY(c) { return global.Plot.ruleY([0], {stroke: c.t.ink2, strokeWidth: 1.5}); }
  function zeroX(c) { return global.Plot.ruleX([0], {stroke: c.t.ink2, strokeWidth: 1.5}); }
  function tip(c, data, o) {
    return global.Plot.tip(data, Object.assign({fill: c.t.surface, stroke: c.t.rule2, fontSize: 12, lineHeight: 1.35}, o));
  }
  // annotation text inside a chart: 12 px on a narrow screen, 11 px otherwise
  function annot(c) { return c.narrow ? 12 : 11; }
  // the colour for reference marks (S3, the random-pair median, differences): --ref-series, a
  // lighter neutral than --neutral-series (which stays the fill of bands and histogram bars)
  function refColor(c) {
    if (c.t.ref) return c.t.ref;
    var v = global.getComputedStyle(document.documentElement).getPropertyValue('--ref-series').trim();
    return v || c.t.neutral;
  }
  // One Sharpe axis for every interval chart of Sharpe ratios (Exhibits 1, 6 and 22), so that
  // interval widths compare from one exhibit to the next; widened only if a value falls outside.
  var SHARPE = [-2.5, 2.5];
  function sharpeDomain(values) {
    var v = values.filter(function (x) { return x !== null && x !== undefined && isFinite(x); });
    var lo = Math.min.apply(null, v.concat([SHARPE[0]])), hi = Math.max.apply(null, v.concat([SHARPE[1]]));
    if (lo >= SHARPE[0] && hi <= SHARPE[1]) return SHARPE.slice();
    var pad = (hi - lo) * 0.04;
    return [lo < SHARPE[0] ? lo - pad : SHARPE[0], hi > SHARPE[1] ? hi + pad : SHARPE[1]];
  }
  // Shape is the second identity channel, after colour: circle for the v33 pairs strategy, square
  // for Avellaneda–Lee, diamond for the Gatev baseline; a hollow mark is gross of costs or descriptive.
  var SHAPE = {v33: 'circle', al: 'square', gatev: 'diamond2', ref: 'circle'};
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

  // ── interval rows: an estimate and its 95% interval per row (Exhibits 1, 6, 12, 22, 26) ──
  // rows: [{label, est, lo, hi, color, symbol, hollow, dash, spread, group, ucb, status}]: a row
  //   without an estimate keeps its place with the reason (status); a spread (across draws, not
  //   an interval) is drawn as a pale band; ucb draws a one-sided 95% upper bound as a tick.
  // o: {domain, label (x axis), ticks, tickFormat, dp, value(r), groups: [{key, label}], values,
  //     valueHead, refs: [{row (index into rows), x, text, side: 'left' | 'right', dash}], title(r)}
  // Wide: labels at the left, values ('+0.05 [−1.81, +1.83]') in a column at the right where they
  // fit. Narrow: each label above its row with the value on the same line, so the scale keeps the
  // whole width; annotations then go under their row.
  function intervalPlot(c, rows, o) {
    var P = global.Plot, narrow = c.narrow, fs = 12, af = annot(c), dp = o.dp === undefined ? 2 : o.dp;
    var value = o.value || function (r) { return signed(r.est, dp) + ' [' + signed(r.lo, dp) + ', ' + signed(r.hi, dp) + ']'; };
    var widestLabel = Math.max.apply(null, rows.map(function (r) { return textWidth(r.label, fs); }));
    var widestValue = Math.max.apply(null, rows.filter(function (r) { return has(r.est); }).map(function (r) { return textWidth(value(r), fs); }).concat([0]));
    var values = !!o.values && widestValue > 0, mL, mR, step, labelEm;
    if (narrow) {
      mL = 8; mR = 8; step = 46;
      var room = c.width - mL - mR;
      if (values && room - widestValue - 14 < Math.min(widestLabel, 110)) values = false;   // no room for both on one line
      labelEm = (values ? room - widestValue - 14 : room) / fs;
    } else {
      mL = Math.min(Math.ceil(widestLabel) + 18, Math.floor(c.width * 0.36));
      mR = values ? Math.ceil(Math.max(widestValue, o.valueHead ? textWidth(o.valueHead, af) : 0)) + 16 : 16;
      if (values && c.width - mL - mR < 220) { values = false; mR = 16; }
      step = 34;
      // Plot wraps by its own estimate of text width: no wrapping unless the label is past the margin
      labelEm = widestLabel + 18 <= mL ? Infinity : (mL - 14) / fs;
    }
    // rows in group order, each at its own pixel row (the y scale is the identity)
    var headH = 26, heads = [], placed = [];
    var mT = o.valueHead && values && !o.groups ? 22 : 8, y = mT;
    (o.groups || [{key: undefined}]).forEach(function (g) {
      var rs = rows.filter(function (r) { return !o.groups || r.group === g.key; });
      if (!rs.length) return;
      if (o.groups) { heads.push({label: g.label.toUpperCase(), py: y + (narrow ? headH - 5 : headH / 2 + 2)}); y += headH; }
      rs.forEach(function (r) {
        placed[rows.indexOf(r)] = Object.assign({}, r, {py: y + (narrow ? 30 : step / 2)});
        y += step;
      });
    });
    var A = placed.filter(Boolean);
    var D = A.filter(function (r) { return has(r.est); }), B = A.filter(function (r) { return !has(r.est); });
    // an annotation sits beside its tick (left or right), moved back inside the frame if it would leave it
    var xs = global.d3.scaleLinear().domain(o.domain).range([mL, c.width - mR]);
    var refs = (o.refs || []).filter(function (f) { return placed[f.row] && has(f.x); }).map(function (f) {
      var w = textWidth(f.text, af), px = f.side === 'left' ? xs(f.x) - 5 - w : xs(f.x) + 5;
      px = Math.max(mL, Math.min(px, c.width - mR - w));
      return Object.assign({}, f, {py: placed[f.row].py, lx: xs.invert(px)});
    });
    var mB = 44;
    var tick = function (d) { return {y1: function (r) { return r.py - d; }, y2: function (r) { return r.py + d; }}; };
    var labelMark = narrow ?
      P.text(A, halo(c, {frameAnchor: 'left', y: 'py', text: 'label', textAnchor: 'start', lineAnchor: 'bottom', dy: -9, fill: c.t.ink, fontSize: fs, lineWidth: labelEm})) :
      P.text(A, {frameAnchor: 'left', y: 'py', text: 'label', textAnchor: 'end', dx: -10, fill: c.t.ink, fontSize: fs, lineWidth: labelEm, lineHeight: 1.15});
    var valueOpts = {frameAnchor: 'right', y: 'py', text: value, textAnchor: 'end', dx: mR - 2, fill: c.t.ink2, fontSize: fs};
    if (narrow) valueOpts = halo(c, Object.assign(valueOpts, {lineAnchor: 'bottom', dy: -9}));
    var refText = refs.length ? P.text(refs, halo(c, {x: 'lx', y: 'py', text: 'text', textAnchor: 'start', dy: narrow ? 15 : -13, fill: c.t.ink2, fontSize: af})) : null;
    var ticks = o.ticks || (narrow ? 5 : 10);
    var node = plot(c, {
      height: y + mB, marginLeft: mL, marginRight: mR, marginTop: mT, marginBottom: mB,
      x: {domain: o.domain, label: o.label, labelArrow: 'none'},
      y: {type: 'identity', axis: null},
      marks: [
        gridX(c, {ticks: ticks}), axisX(c, {ticks: ticks, label: o.label, labelArrow: 'none', tickFormat: o.tickFormat || function (v) { return signed(v, 1); }}),
        zeroX(c),
        P.ruleY(D.filter(function (r) { return r.spread; }), {y: 'py', x1: 'lo', x2: 'hi', stroke: 'color', strokeWidth: 8, strokeOpacity: 0.55}),
        P.ruleY(D.filter(function (r) { return !r.spread && !r.dash; }), {y: 'py', x1: 'lo', x2: 'hi', stroke: 'color', strokeWidth: 2}),
        P.ruleY(D.filter(function (r) { return !r.spread && r.dash; }), {y: 'py', x1: 'lo', x2: 'hi', stroke: 'color', strokeWidth: 2, strokeDasharray: '5,3'}),
        P.ruleX(D.filter(function (r) { return has(r.ucb); }), Object.assign({x: 'ucb', stroke: c.t.ink, strokeWidth: 2}, tick(7))),
        P.ruleX(refs.filter(function (f) { return !f.dash; }), Object.assign({x: 'x', stroke: c.t.ink, strokeWidth: 2}, tick(7))),
        P.ruleX(refs.filter(function (f) { return f.dash; }), Object.assign({x: 'x', stroke: c.t.ink2, strokeWidth: 1.5, strokeDasharray: '2,2'}, tick(9))),
        refText,
        P.dot(D, {x: 'est', y: 'py', r: 5, symbol: function (r) { return r.symbol || 'circle'; },
          fill: function (r) { return r.hollow ? c.t.paper : r.color; }, stroke: function (r) { return r.hollow ? r.color : c.t.paper; }, strokeWidth: 2}),
        labelMark,
        values ? P.text(D, valueOpts) : null,
        values && o.valueHead ? P.text([o.valueHead], {frameAnchor: 'right', y: function () { return heads.length ? heads[0].py : mT - 12; }, text: function (d) { return d; },
          textAnchor: 'end', dx: mR - 2, lineAnchor: narrow && heads.length ? 'bottom' : 'middle', fill: c.t.ink3, fontSize: af}) : null,
        heads.length ? P.text(heads, {frameAnchor: 'left', y: 'py', text: 'label', textAnchor: 'start', dx: narrow ? 0 : 2 - mL,
          lineAnchor: narrow ? 'bottom' : 'middle', fill: c.t.ink2, fontSize: af, fontWeight: 600}) : null,
        B.length ? P.text(B, halo(c, {frameAnchor: 'left', y: 'py', text: 'status', textAnchor: 'start', dx: 2, fill: c.t.ink3, fontSize: narrow ? 12 : 11.5, fontStyle: 'italic'})) : null,
        tip(c, D, P.pointer({x: 'est', y: 'py', title: o.title || function (r) { return r.label + '\n' + value(r); }}))
      ].filter(Boolean)
    });
    // group headings spaced as the page's small capitals (.ex-label)
    var H = {};
    heads.forEach(function (h) { H[h.label] = true; });
    node.querySelectorAll('text').forEach(function (t) { if (H[t.textContent]) t.setAttribute('letter-spacing', '0.06em'); });
    return node;
  }

  // ── the evaluated 2026 holdout (study.holdout, from scripts/evaluate_holdout.py) ──
  // Every decision shown is the evaluation's own (holdout.decision and each arm's edge): nothing
  // here recomputes it. A statistic the evaluation has no value for is null and prints as '–';
  // an arm whose daily returns never vary (flat: no position opened) has no Sharpe ratio.
  function has(x) { return x !== null && x !== undefined && isFinite(x); }
  function holdoutDone(S) {
    var H = S && S.holdout;
    return H && H.status === 'complete' && H.arms && H.arms.length ? H : null;
  }
  // one arm of the evaluated holdout, or null while it is sealed
  function holdoutArm(S, key) {
    var H = holdoutDone(S);
    return H ? H.arms.filter(function (a) { return a.key === key; })[0] || null : null;
  }
  // each arm's colour role and shape: S1 the v33 pairs strategy (--series-1, circle), S2
  // Avellaneda–Lee (--series-3, square), S3 descriptive (--ref-series, hollow circle, dashed);
  // key is its legend key (site.css .lg-key classes)
  var ARM = {
    v33_pairs: {tag: 'S1', name: 'v33 pairs', color: 's1', css: '--series-1', symbol: 'circle', key: 'line mk'},
    avellaneda_lee: {tag: 'S2', name: 'Avellaneda–Lee', color: 's3', css: '--series-3', symbol: 'square', key: 'line mk mk-sq'},
    v32_pairs: {tag: 'S3', name: 'v32 frozen', color: 'ref', css: '--ref-series', dash: true, symbol: 'circle', open: true, key: 'line dash mk mk-ring'}
  };
  function armInfo(a) { return ARM[a.key] || {tag: a.key, name: a.label || a.key, color: 'ink2', css: '--ink-2', symbol: 'circle', key: 'line mk'}; }
  function armColor(c, info) { return info.color === 'ref' ? refColor(c) : c.t[info.color]; }
  function armTag(a) { return armInfo(a).tag; }
  function armLabel(a) { return (a.hypothesis ? a.hypothesis + ' · ' : '') + armTag(a) + ' ' + armInfo(a).name; }
  function holdoutAlpha(H) { return has(H.alpha) ? H.alpha : (H.decision && has(H.decision.alpha) ? H.decision.alpha : 0.05); }
  // A p-value at three decimals, as the paper prints it: one that rounds to zero prints as '<0.001'
  function pText(p) {
    var s = num(p, 3);
    return has(p) && Number(s) === 0 ? '<' + num(0.001, 3) : s;
  }
  // A Holm p-value below alpha that rounds to alpha prints as '<0.050', never as 0.050 beside a rejection
  function holmP(p, below, alpha) {
    if (!has(p)) return '–';
    var s = pText(p);
    return below === true && Number(s) >= alpha ? '<' + num(alpha, 3) : s;
  }
  // the registered decision for an arm: {tested, edge (true | false | null), p, below, text}
  function holdoutDecision(H, a) {
    if (a.role === 'descriptive' || !a.hypothesis) return {tested: false, edge: null, text: 'Not tested (descriptive)'};
    var d = H.decision && H.decision.arms ? H.decision.arms[a.key] : null;
    var p = d && has(d.p_holm) ? d.p_holm : a.p_holm;
    var below = d && typeof d.p_holm_below_alpha === 'boolean' ? d.p_holm_below_alpha : a.p_holm_below_alpha;
    var ok = d && typeof d.edge === 'boolean' && (typeof a.edge !== 'boolean' || a.edge === d.edge);
    return {tested: true, edge: ok ? d.edge : null, p: p, below: below, text: !ok ? '–' : d.edge ? 'Null rejected' : 'Null not rejected'};
  }
  function interval(lo, hi) { return has(lo) && has(hi) ? signed(lo, 2) + ' to ' + signed(hi, 2) : '–'; }
  function sharpeText(a) { return has(a.sharpe) ? signed(a.sharpe, 2) : a.flat ? 'not defined' : '–'; }
  function flatWhy(a) { return a.trades === 0 ? 'no position opened' : 'daily returns without variation'; }
  var fmtLong = function (d) { return global.d3.utcFormat('%-d %B %Y')(d); };
  function dayOf(iso) {
    var d = iso ? parse(String(iso).slice(0, 10)) : null;
    return d ? fmtLong(d) : '–';
  }
  function hex12(h) { return h ? String(h).slice(0, 12) : '–'; }
  function listJoin(xs) { return xs.length < 2 ? xs.join('') : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1]; }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

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
    var mL = 46, mR = c.narrow ? 66 : 62;
    var last = rows[rows.length - 1];
    var common = {marginLeft: mL, marginRight: mR, x: {type: 'utc', domain: dom, axis: null}};
    var P = global.Plot;

    var cumVals = rows.map(function (r) { return r.cum; }).concat(rows.map(function (r) { return r.gatev; }));
    // The draws' middle half is drawn. Their tails can lie far outside the strategy's range (the
    // draws' returns are on committed capital, and an unhedged random pair can lose most of it),
    // so the 5th-95th percentile path is in the data table and the notes, not on the scale.
    if (band) cumVals = cumVals.concat(band.map(function (b) { return b.p25; }), band.map(function (b) { return b.p75; }));
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
        P.areaY(rows, {x: 'date', y: 'dd', fill: c.t.neg, fillOpacity: 0.14}),
        P.lineY(rows, {x: 'date', y: 'dd', stroke: c.t.neg, strokeWidth: 1.5}),
        zeroY(c),
        P.dot([minDd], {x: 'date', y: 'dd', r: 4, fill: c.t.neg, stroke: c.t.paper, strokeWidth: 2}),
        P.text([minDd], {x: 'date', y: 'dd', text: function (d) { return 'max ' + pct(d.dd); }, dx: 8, textAnchor: 'start', fill: c.t.ink, fontSize: c.narrow ? 12 : 11.5})
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
        P.text([30], {y: function (v) { return v; }, frameAnchor: 'right', text: function () { return '30% cap'; }, dy: -7, textAnchor: 'end', fill: c.t.ink2, fontSize: annot(c)}),
        zeroY(c)
      ]
    }));
    [pane1, pane2, pane3].forEach(function (p) { p.classList.add('plot-pane'); });

    var legend = [{label: 'Strategy, net', color: '--series-1', kind: 'line'}];
    if (G) legend.push({label: 'Gatev distance method, net', color: '--series-2', kind: 'line'});
    if (band) legend.push({label: 'Random pairs, middle half of ' + (B.n_draws || '') + ' draws', color: '--neutral-series', kind: 'band band-inner'});
    var columns = ['Date', 'Strategy cumulative', 'Gatev cumulative'];
    if (band) columns = columns.concat(['Random 5%', 'Random 25%', 'Random median', 'Random 75%', 'Random 95%']);
    columns = columns.concat(['Drawdown', 'Gross exposure', 'Open positions']);

    return {
      nodes: [pane1, pane2, pane3],
      legend: legend,
      table: table('Daily series, main backtest (% of capital).', columns,
        columns.map(function (_, i) { return i > 0; }),
        rows.map(function (r) {
          var cells = [r.iso, pct(r.cum, 3), r.gatev === null ? '–' : pct(r.gatev, 3)];
          if (band) cells = cells.concat(r.rnd ? [pct(r.rnd.p05, 3), pct(r.rnd.p25, 3), pct(r.rnd.p50, 3), pct(r.rnd.p75, 3), pct(r.rnd.p95, 3)] : ['–', '–', '–', '–', '–']);
          return cells.concat([num(r.dd, 3, {suffix: '%'}), num(r.exp, 2, {suffix: '%'}), String(r.pos)]);
        })),
      mount: function (container) {
        crosshair(container, {
          panes: [pane1, pane2, pane3], rows: rows, stacked: true,
          dots: [{pane: 0, y: function (r) { return r.cum; }, color: c.t.s1}, {pane: 0, y: function (r) { return r.gatev; }, color: c.t.s2},
                 {pane: 1, y: function (r) { return r.dd; }, color: c.t.neg}, {pane: 2, y: function (r) { return r.exp; }, color: c.t.s1}],
          items: function (r) {
            var out = [{label: 'Strategy', color: c.t.s1, value: pct(r.cum)}];
            if (G) out.push({label: 'Gatev', color: c.t.s2, value: r.gatev === null ? '–' : pct(r.gatev)});
            if (band) {
              out.push({label: 'Random, median', color: c.t.neutral, key: 'band', value: r.rnd ? pct(r.rnd.p50) : '–', wide: true});
              out.push({label: 'Random, middle half', value: r.rnd ? pct(r.rnd.p25, 1) + ' to ' + pct(r.rnd.p75, 1) : '–', wide: true});
            }
            return out.concat([{label: 'Drawdown', color: c.t.neg, value: num(r.dd, 2, {suffix: '%'})},
                               {label: 'Gross exposure', value: num(r.exp, 1, {suffix: '%'})},
                               {label: 'Open positions', value: String(r.pos)}]);
          }
        }, c);
      }
    };
  };

  // The crosshair of the time-series exhibits (2, 1 and 22's cumulative panes, 3, 5 and 18): one
  // vertical rule across every pane at the date under the pointer, a dot on each line, and one
  // read-out of every series at that date. Mouse: the read-out follows the pointer. Touch: a tap
  // pins it, a sideways drag scrubs (the panes take touch-action: pan-y pinch-zoom, so a vertical
  // swipe still scrolls the page), and a tap outside the chart hides it. On a narrow screen the
  // read-out is docked above the first pane with its height reserved, so it never covers the
  // lines and never moves the page; while nothing is pinned it shows the last date.
  // spec: {panes: [svg], rows: [{date, ...}], items(r) -> [{label, color, value, key}],
  //        dots: [{pane, y(r), color}], stacked (panes share one column), dock (element to dock before)}
  var SVGNS = 'http://www.w3.org/2000/svg';
  function crosshair(container, spec, c) {
    var panes = spec.panes, rows = spec.rows;
    var dates = rows.map(function (r) { return +r.date; });
    var bisect = global.d3.bisector(function (d) { return d; }).center;
    var scales = panes.map(function (p) { return {x: p.scale('x'), y: p.scale('y')}; });
    var rules = panes.map(function (p) {
      var line = document.createElementNS(SVGNS, 'line');
      line.setAttribute('y1', 0);
      line.setAttribute('y2', p.getAttribute('height'));
      line.setAttribute('stroke', c.t.ink3);
      line.setAttribute('stroke-width', 1);
      line.setAttribute('aria-hidden', 'true');
      line.setAttribute('class', 'xh');
      line.style.display = 'none';
      p.appendChild(line);
      p.style.touchAction = 'pan-y pinch-zoom';
      return line;
    });
    var dots = (spec.dots || []).map(function (d) {
      var el = document.createElementNS(SVGNS, 'circle');
      el.setAttribute('r', 3.5);
      el.setAttribute('fill', d.color);
      el.setAttribute('stroke', c.t.paper);
      el.setAttribute('stroke-width', 1.5);
      el.setAttribute('aria-hidden', 'true');
      el.setAttribute('class', 'xh');
      el.style.display = 'none';
      panes[d.pane].appendChild(el);
      return {el: el, d: d};
    });
    var docked = !!c.narrow;
    var tipEl = document.createElement('div');
    tipEl.className = 'xtip' + (docked ? ' is-docked' : '');
    tipEl.setAttribute('aria-hidden', 'true');
    if (docked) {
      var at = spec.dock || panes[0];
      at.parentNode.insertBefore(tipEl, at);
    } else {
      tipEl.style.display = 'none';
      container.appendChild(tipEl);
    }

    function line(it) {
      var r = document.createElement('div');
      r.className = 'xt-row' + (it.wide ? ' is-wide' : '');
      var k = document.createElement('span');
      k.className = 'xt-key' + (it.key ? ' ' + it.key : '') + (it.color ? '' : ' is-none');
      if (it.color) k.style.color = it.color;
      r.appendChild(k);
      var l = document.createElement('span');
      l.className = 'xt-l';
      l.textContent = it.label;
      var v = document.createElement('b');
      v.textContent = it.value;
      r.appendChild(l);
      r.appendChild(v);
      return r;
    }
    function fill(r, active) {
      tipEl.replaceChildren();
      var d = document.createElement('div');
      d.className = 'xt-date';
      d.textContent = fmtDate(r.date);
      tipEl.appendChild(d);
      spec.items(r).forEach(function (it) { tipEl.appendChild(line(it)); });
      tipEl.classList.toggle('is-idle', !active);
    }
    function mark(j, active) {
      var r = rows[j];
      rules.forEach(function (l, i) {
        var x = scales[i].x.apply(r.date);
        l.setAttribute('x1', x);
        l.setAttribute('x2', x);
        l.style.display = active ? '' : 'none';
      });
      dots.forEach(function (o) {
        var v = o.d.y(r);
        if (!active || !has(v)) { o.el.style.display = 'none'; return; }
        o.el.setAttribute('cx', scales[o.d.pane].x.apply(r.date));
        o.el.setAttribute('cy', scales[o.d.pane].y.apply(v));
        o.el.style.display = '';
      });
    }
    // the pane under a pointer (stacked panes: the gaps between them count as the first pane)
    function paneAt(x, y) {
      for (var i = 0; i < panes.length; i++) {
        var b = panes[i].getBoundingClientRect();
        if (x >= b.left && x <= b.right && y >= b.top - 3 && y <= b.bottom + 3) return i;
      }
      if (spec.stacked) {
        var a = panes[0].getBoundingClientRect(), z = panes[panes.length - 1].getBoundingClientRect();
        if (x >= a.left && x <= a.right && y >= a.top && y <= z.bottom) return 0;
      }
      return -1;
    }
    function show(evt) {
      var i = paneAt(evt.clientX, evt.clientY);
      if (i < 0) { if (evt.pointerType === 'mouse') hide(); return; }
      var box = panes[i].getBoundingClientRect();
      var k = box.width / Number(panes[i].getAttribute('width'));
      var j = bisect(dates, +scales[i].x.invert((evt.clientX - box.left) / k));
      j = Math.max(0, Math.min(rows.length - 1, j));
      mark(j, true);
      fill(rows[j], true);
      if (docked) {
        if (tipEl.offsetHeight > parseFloat(tipEl.style.minHeight || 0)) tipEl.style.minHeight = tipEl.offsetHeight + 'px';
        return;
      }
      tipEl.style.display = '';
      var cb = container.getBoundingClientRect();
      var top = (spec.stacked ? panes[0] : panes[i]).getBoundingClientRect().top - cb.top;
      var x = box.left - cb.left + scales[i].x.apply(rows[j].date) * k;
      var cw = container.clientWidth, tw = tipEl.offsetWidth;
      var left = x + 14;
      if (left + tw > cw) left = x - tw - 14;
      tipEl.style.left = Math.max(0, Math.min(left, cw - tw)) + 'px';
      tipEl.style.top = (top + 8) + 'px';
    }
    function hide() {
      mark(rows.length - 1, false);
      if (docked) fill(rows[rows.length - 1], false);
      else tipEl.style.display = 'none';
    }
    function down(evt) { if (paneAt(evt.clientX, evt.clientY) >= 0) show(evt); }
    function leave(evt) { if (evt.pointerType === 'mouse') hide(); }
    function outside(evt) { if (!container.contains(evt.target)) hide(); }
    // a redraw replaces the panes: drop the previous drawing's listeners first
    var old = container.crosshair;
    if (old) {
      container.removeEventListener('pointermove', old.show);
      container.removeEventListener('pointerdown', old.down);
      container.removeEventListener('pointerleave', old.leave);
      document.removeEventListener('pointerdown', old.outside);
    }
    container.crosshair = {show: show, down: down, leave: leave, outside: outside};
    container.addEventListener('pointermove', show);
    container.addEventListener('pointerdown', down);
    container.addEventListener('pointerleave', leave);
    document.addEventListener('pointerdown', outside);
    if (docked) {
      hide();
      tipEl.style.minHeight = tipEl.offsetHeight + 'px';
    }
  }

  // ── Exhibit 3: walk-forward windows and the stitched path ─────────────────
  X.walkforward = function (S, c) {
    var WF = S.dev && S.dev.walk_forward;
    if (!WF || !WF.windows || !WF.windows.length) return null;
    var P = global.Plot;
    // windows are numbered 1..N here; the run's own index (it counts windows inside the
    // formation period too) stays in the data table
    // a window ends on its last day in the daily series (the last one runs past its 63-day slot)
    var W = WF.windows.map(function (w, i) {
      var a = parse(w.test_start), b = parse(w.end || w.test_end);
      return {k: i + 1, n: w.n, a: a, b: b, mid: new Date((+a + +b) / 2), ret: w.ret_pct, trades: w.trades, sharpe: w.sharpe,
              auc: w.ranker_auc, days: w.n_days};
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
        P.text(pos, {x: 'mid', y: 'ret', text: label, dy: -8, fill: c.t.ink2, fontSize: annot(c)}),
        P.text(neg, {x: 'mid', y: 'ret', text: label, dy: 9, fill: c.t.ink2, fontSize: annot(c)})
      ]
    });
    var lastP = path[path.length - 1];
    var pane2 = plot(c, {
      height: c.narrow ? 140 : 150, marginLeft: 46, marginRight: c.narrow ? 56 : 60, marginTop: 20, marginBottom: 26,
      x: {type: 'utc', domain: dom},
      y: {domain: domainPad(path.map(function (p) { return p.cum; }), 0.15, [0]), label: 'Stitched path, %', labelArrow: 'none'},
      marks: [
        gridY(c, {ticks: 4}), axisY(c, {ticks: 4, label: 'Stitched path, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisX(c, {ticks: c.narrow ? 4 : 7}),
        zeroY(c),
        P.lineY(path, {x: 'date', y: 'cum', stroke: c.t.s1, strokeWidth: 2}),
        WF.daily ? null : P.dot(path, {x: 'date', y: 'cum', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        P.text([lastP], {x: 'date', y: 'cum', text: function (p) { return pct(p.cum); }, dx: 8, textAnchor: 'start', fill: c.t.ink, fontWeight: 600})
      ].filter(Boolean)
    });
    pane1.classList.add('plot-pane');
    pane2.classList.add('plot-pane');
    // the read-out: the window a date falls in (its return, trades and Sharpe) and the stitched path
    var windowOf = function (d) {
      for (var i = 0; i < W.length; i++) if (+d >= +W[i].a && +d <= +W[i].b) return W[i];
      return null;
    };
    return {
      mount: function (container) {
        crosshair(container, {
          panes: [pane1, pane2], rows: path, stacked: true,
          dots: [{pane: 1, y: function (p) { return p.cum; }, color: c.t.s1}],
          items: function (p) {
            var w = windowOf(p.date);
            return [{label: w ? 'Window ' + w.k + ' of ' + W.length : 'Window', color: w ? signColor(c)(w.ret) : null, key: 'box', wide: true,
                     value: w ? pct(w.ret) + ', ' + plural(w.trades, 'trade', 'trades') + ', Sharpe ' + num(w.sharpe, 2) : '–'},
                    {label: 'Stitched path', color: c.t.s1, value: pct(p.cum), wide: true}];
          }
        }, c);
      },
      nodes: [pane1, pane2],
      legend: [{label: 'Window gain', color: '--pos', kind: 'box'}, {label: 'Window loss', color: '--neg', kind: 'box'},
               {label: 'Labels: trades entered in the window', color: '--ink-3', kind: 'none'}],
      table: table('Walk-forward test windows (net, % of capital).',
        ['Window', 'Test start', 'Test end', 'Days', 'Net return', 'Sharpe', 'Trades', 'Ranker AUC', 'Stitched', "Run's window no."],
        [false, false, false, true, true, true, true, true, true, true],
        W.map(function (w, i) {
          return [String(w.k), fmtISO(w.a), fmtISO(w.b), w.days ? String(w.days) : '–', pct(w.ret, 3), num(w.sharpe, 2), String(w.trades),
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
    // an empty column (a row on phones) keeps the compounded year apart from the months
    var cols = MONTHS.concat([' ', 'Year']);
    var m = Math.max.apply(null, cells.map(function (d) { return Math.abs(d.v); })) || 1;
    var fillOf = global.d3.scaleLinear().domain([-m, 0, m]).range([c.t.neg, c.t.mid, c.t.pos]).interpolate(global.d3.interpolateLab);
    // each label in black or white, whichever contrasts more with its cell (at least 4.6:1 on any fill)
    var strong = function (d) { return contrast(fillOf(d.v), '#ffffff') > contrast(fillOf(d.v), '#000000'); };
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
        P.text(cells.filter(function (d) { return !strong(d); }), {x: xk, y: yk, text: function (d) { return signed(d.v, 2); }, fill: '#000000', fontSize: t ? 11 : 12}),
        P.text(cells.filter(strong), {x: xk, y: yk, text: function (d) { return signed(d.v, 2); }, fill: '#ffffff', fontSize: t ? 11 : 12, fontWeight: 600}),
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
        P.lineY(rows, {x: 'date', y: 'sr', stroke: c.t.s1, strokeWidth: 2})
      ]
    });
    node.classList.add('plot-pane');
    return {
      mount: function (container) {
        crosshair(container, {
          panes: [node], rows: rows,
          dots: [{pane: 0, y: function (r) { return r.sr; }, color: c.t.s1}],
          items: function (r) {
            return r.sr === null ? [{label: 'Sharpe', color: c.t.s1, value: 'flat throughout the window'}] :
              [{label: 'Sharpe', color: c.t.s1, value: signed(r.sr, 2)},
               {label: '±1.96 standard errors', color: c.t.neutral, key: 'band', value: num(r.lo, 2) + ' to ' + signed(r.hi, 2), wide: true}];
          }
        }, c);
      },
      nodes: [node],
      legend: [{label: 'Rolling ' + R.window + '-day Sharpe', color: '--series-1', kind: 'line'},
               {label: '±1.96 standard errors', color: '--neutral-series', kind: 'band'}],
      table: table('Rolling ' + R.window + '-day Sharpe ratio (window ending on the date).', ['Window end', 'Sharpe', 'Lower', 'Upper'],
        [false, true, true, true],
        rows.map(function (r) { return [fmtISO(r.date), num(r.sr, 2), num(r.lo, 2), num(r.hi, 2)]; }))
    };
  };

  // ── Exhibit 6: Sharpe forest plot ─────────────────────────────────────────
  // Grouped rows on the shared Sharpe axis, values printed beside them: the development series,
  // the differences against the Gatev baseline, the baselines, and the holdout. The main
  // backtest's one-sided 95% bound and 80%-power mark, and the walk-forward's bound, sit on their
  // own rows, labelled next to their ticks.
  X.forest = function (S, c) {
    var F = S.dev && S.dev.forest;
    if (!F || !F.length) return null;
    var pw = S.dev.power || {}, ref = refColor(c), facts = S.dev.facts || {};
    var LOOK = {main: {color: c.t.s1, symbol: SHAPE.v33, group: 'dev'}, gross: {color: c.t.s1, symbol: SHAPE.v33, hollow: true, group: 'dev'},
                oos: {color: c.t.s1, symbol: SHAPE.v33, group: 'dev'}, gatev: {color: c.t.s2, symbol: SHAPE.gatev, group: 'base'},
                diff_main: {color: ref, symbol: SHAPE.ref, group: 'diff'}, diff_oos: {color: ref, symbol: SHAPE.ref, group: 'diff'},
                random: {color: ref, symbol: SHAPE.ref, spread: true, group: 'base'}};
    var rows = F.map(function (r) {
      return Object.assign({}, r, {est: r.sharpe, color: c.t.ink2, symbol: 'circle', group: r.kind === 'diff' ? 'diff' : 'dev'}, LOOK[r.key] || {});
    });
    // rows whose runs do not exist yet keep their place, marked pending or sealed
    if (!rows.some(function (r) { return r.key === 'gross'; })) rows.push({key: 'gross', label: 'Main backtest, gross of costs', status: 'pending: v33 export', group: 'dev'});
    if (S.residual && S.residual.sharpe !== null) {
      rows.push({key: 'residual', label: 'Avellaneda–Lee, net', kind: 'ci', est: S.residual.sharpe, sharpe: S.residual.sharpe, lo: S.residual.lo, hi: S.residual.hi,
                 color: c.t.s3, symbol: SHAPE.al, group: 'dev', method: 'block bootstrap'});
    } else rows.push({key: 'residual', label: 'Avellaneda–Lee, net', status: 'pending: v33 run', group: 'dev'});
    // the holdout's S1, the pairs strategy's own design (in its colour); a flat S1 keeps its row
    var held = holdoutArm(S, 'v33_pairs');
    var heldLabel = held ? 'Holdout ' + String(S.holdout.calendar_start || '2026').slice(0, 4) + ', S1 v33 pairs, net' : 'Holdout 2026, net';
    if (held && has(held.sharpe)) {
      rows.push({key: 'holdout', label: heldLabel, kind: 'ci', est: held.sharpe, sharpe: held.sharpe, lo: held.lo, hi: held.hi, days: held.days,
                 color: c.t.s1, symbol: SHAPE.v33, group: 'hold', method: 'block bootstrap'});
    } else rows.push({key: 'holdout', label: heldLabel, status: held ? flatWhy(held) + ': Sharpe not defined' : 'sealed', group: 'hold'});
    // the title and subtitle speak of the development period: once the holdout row is filled, say so
    if (held && c.figure) {
      var lead = 'Every bootstrap interval spans zero', t0 = c.figure.querySelector('.ex-title');
      var sub = c.figure.querySelector('.ex-sub'), subText = 'Annualised Sharpe ratio with its 95% interval; development period, net of costs unless stated';
      if (t0 && t0.firstChild && t0.firstChild.nodeType === 3 && t0.firstChild.nodeValue.indexOf(lead) === 0) {
        t0.firstChild.nodeValue = 'Every development-period bootstrap interval spans zero' + t0.firstChild.nodeValue.slice(lead.length);
      }
      if (sub && sub.textContent === subText) sub.textContent = subText + '; the holdout row is S1 on the holdout, outside the development period';
    }
    var idx = function (k) { for (var i = 0; i < rows.length; i++) if (rows[i].key === k && has(rows[i].est)) return i; return -1; };
    var refs = [];
    if (idx('main') >= 0) {
      if (has(pw.ucb)) refs.push({row: idx('main'), x: pw.ucb, text: 'bound ' + num(pw.ucb, 2), side: 'left'});
      if (has(pw.mde)) refs.push({row: idx('main'), x: pw.mde, text: '80% power ' + num(pw.mde, 2), side: 'right', dash: true});
    }
    if (idx('oos') >= 0 && has(facts.oos_ucb)) refs.push({row: idx('oos'), x: facts.oos_ucb, text: 'bound ' + signed(facts.oos_ucb, 2), side: 'left'});
    var node = intervalPlot(c, rows, {
      domain: sharpeDomain([].concat.apply([], rows.map(function (r) { return [r.lo, r.hi]; })).concat(refs.map(function (f) { return f.x; }))),
      label: 'Annualised Sharpe ratio', values: true, valueHead: 'Sharpe [95% interval]',
      groups: [{key: 'dev', label: 'Development series'}, {key: 'diff', label: 'Differences vs Gatev'},
               {key: 'base', label: 'Baselines'}, {key: 'hold', label: 'Holdout ' + String((S.holdout && S.holdout.calendar_start) || '2026').slice(0, 4)}],
      refs: refs,
      title: function (r) {
        return r.label + '\nSharpe ' + signed(r.sharpe, 2) + '\n' + (r.kind === 'spread' ? '5th–95th pct ' : '95% interval ') + signed(r.lo, 2) + ' to ' + signed(r.hi, 2) +
          (r.p !== undefined && r.p !== null ? '\np = ' + num(r.p, 3) : '') + '\n' + r.method;
      }
    });
    var drawn = rows.filter(function (r) { return has(r.est); }), pending = rows.filter(function (r) { return !has(r.est); });
    var legend = [{label: 'Pairs strategy (v33)', color: '--series-1', kind: 'dot'}, {label: 'Gross of costs', color: '--ink-2', kind: 'dot ring'},
                  {label: 'Gatev baseline', color: '--series-2', kind: 'dot dia'}];
    if (rows.some(function (r) { return r.key === 'residual' && has(r.est); })) legend.push({label: 'Avellaneda–Lee', color: '--series-3', kind: 'dot sq'});
    legend.push({label: 'Difference', color: '--ref-series', kind: 'dot'}, {label: 'Random pairs, 5th–95th percentile spread', color: '--ref-series', kind: 'band'});
    if (refs.length) legend.push({label: 'One-sided 95% upper bound', color: '--ink', kind: 'rule'});
    if (has(pw.mde) && idx('main') >= 0) legend.push({label: 'Detectable with 80% power', color: '--ink-2', kind: 'rule dash'});
    return {
      nodes: [node],
      legend: legend,
      table: table('Sharpe ratios and intervals. Power: ' + (pw.method || '') + '.', ['Series', 'Sharpe', 'Lower', 'Upper', 'Days', 'Interval'],
        [false, true, true, true, true, false],
        drawn.map(function (r) { return [r.label, signed(r.sharpe, 2), signed(r.lo, 2), signed(r.hi, 2), r.days ? String(r.days) : '–', r.method]; })
          .concat(pending.map(function (p) { return [p.label, p.status, '', '', '', '']; }))
          .concat(pw.mde ? [['Minimum detectable Sharpe (80% power)', num(pw.mde, 2), '', '', String(pw.n || ''), 'one-sided 5% test'],
                            ['One-sided 95% upper bound, main', num(pw.ucb, 2), '', '', String(pw.n || ''), 'Wald']] : [])
          .concat(has(facts.oos_ucb) ? [['One-sided 95% upper bound, walk-forward', signed(facts.oos_ucb, 2), '', '', has(facts.oos_days) ? String(facts.oos_days) : '–', 'Wald']] : []))
    };
  };

  // ── Exhibit 7: random-pair null distribution ──────────────────────────────
  // The draws at or below the strategy are the darker part of each bar, so the strategy's
  // percentile (the title's) is the darker share; the median draw (the notes') is marked.
  // Bars are binned here, so a bar's read-out names its range.
  function bins(values, thresholds) {
    return global.d3.bin().domain([thresholds[0], thresholds[thresholds.length - 1]]).thresholds(thresholds)(values)
      .map(function (b) { return {x1: b.x0, x2: b.x1, n: b.length, values: b}; });
  }
  X.randomnull = function (S, c) {
    var R = S.dev && S.dev.random_sharpes;
    if (!R || !R.length) return null;
    var P = global.Plot, s = S.dev.strategy_sharpe, g = S.dev.gatev_sharpe, af = annot(c);
    var lo = Math.floor(Math.min.apply(null, R.concat([s, g])) * 5) / 5 - 0.2;
    var hi = Math.ceil(Math.max.apply(null, R.concat([s, g])) * 5) / 5 + 0.2;
    var thresholds = global.d3.range(lo, hi + 1e-9, 0.2);
    var B = bins(R, thresholds).map(function (b) {
      var below = b.values.filter(function (v) { return v <= s; }).length;
      return Object.assign(b, {below: below});
    });
    var randomRow = (S.dev.forest || []).filter(function (r) { return r.key === 'random'; })[0];
    var median = randomRow && has(randomRow.sharpe) ? randomRow.sharpe : global.d3.median(R);
    var pctile = S.dev.random_percentile;
    var strat = 'Strategy ' + signed(s, 2) + (has(pctile) ? ', ' + ordinalRank(Math.round(pctile)) + ' percentile' : '');
    // three lines of labels above the frame, each next to the top of its own rule
    var marks = [{x: g, text: 'Gatev ' + signed(g, 2), color: c.t.s2, line: 2, w: 2},
                 {x: s, text: strat, color: c.t.s1, line: 0, w: 2},
                 {x: median, text: 'median draw ' + signed(median, 2), color: c.t.ink2, line: 1, w: 1.5, dash: true}];
    var xs = global.d3.scaleLinear().domain([lo, hi]).range([40, c.width - 16]);
    marks.forEach(function (m) {
      // a label runs right of its rule unless it would leave the frame
      m.anchor = xs(m.x) + 6 + textWidth(m.text, af, m.line === 0 ? 600 : 400) > c.width - 4 ? 'end' : 'start';
      m.dy = -12 - 14 * m.line;
    });
    // each label on its own line above the frame, its rule rising to it
    var labels = marks.map(function (m) {
      return P.text([m], halo(c, {x: 'x', text: 'text', frameAnchor: 'top', dy: m.dy, textAnchor: m.anchor, dx: m.anchor === 'start' ? 5 : -5,
        fill: c.t.ink, fontSize: af, fontWeight: m.line === 0 ? 600 : 400}));
    });
    var rules = marks.map(function (m) {
      return P.ruleX([m], {x: 'x', stroke: m.dash ? c.t.ink2 : m.color, strokeWidth: m.w, strokeDasharray: m.dash ? '3,2' : null, insetTop: m.dy + 6});
    });
    var node = plot(c, {
      height: c.narrow ? 236 : 266, marginLeft: 40, marginRight: 16, marginTop: 50, marginBottom: 30,
      x: {domain: [lo, hi], label: 'Annualised Sharpe ratio of a random-pair draw', labelArrow: 'none'},
      y: {label: 'Draws', labelArrow: 'none'},
      marks: [
        gridY(c), axisY(c, {label: 'Draws', labelArrow: 'none'}),
        axisX(c, {label: 'Annualised Sharpe ratio of a random-pair draw', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        P.rectY(B, {x1: 'x1', x2: 'x2', y1: 0, y2: 'below', fill: c.t.neutral, fillOpacity: 0.8, insetLeft: 1, insetRight: 1}),
        P.rectY(B, {x1: 'x1', x2: 'x2', y1: 'below', y2: 'n', fill: c.t.neutral, fillOpacity: 0.35, insetLeft: 1, insetRight: 1}),
        zeroY(c)
      ].concat(rules, labels, [
        tip(c, B, P.pointerX({x: function (b) { return (b.x1 + b.x2) / 2; }, y: 'n', title: function (b) {
          return 'Sharpe ' + signed(b.x1, 1) + ' to ' + signed(b.x2, 1) + ': ' + plural(b.n, 'draw', 'draws') + ' (' + num(100 * b.n / R.length, 1) + '%)' +
            (b.below && b.below < b.n ? '\n' + b.below + ' at or below the strategy' : '');
        }}))
      ])
    });
    var sorted = R.slice().sort(function (a, b) { return a - b; });
    return {
      nodes: [node],
      legend: [{label: 'Random-pair draws at or below the strategy', color: '--neutral-series', kind: 'box'},
               {label: 'Draws above the strategy', color: '--neutral-series', kind: 'box box-light'},
               {label: 'Strategy', color: '--series-1', kind: 'rule'}, {label: 'Gatev baseline', color: '--series-2', kind: 'rule'},
               {label: 'Median draw', color: '--ink-2', kind: 'rule dash'}],
      table: table('Sharpe ratios of the random-pair draws, sorted (strategy ' + signed(s, 2) + ', Gatev ' + signed(g, 2) + ', strategy percentile ' + S.dev.random_percentile + ').',
        ['Rank', 'Sharpe'], [true, true], sorted.map(function (v, i) { return [String(i + 1), signed(v, 2)]; }))
    };
  };

  // ── Exhibit 8: the declared variant family, and the deflated Sharpe against N ──
  // Left: each declared variant's net Sharpe ratio (a dodged dot strip), the v33 design and
  // the Gatev baseline marked. Right: the main backtest's deflated Sharpe ratio against the
  // number of trials N, with the null trial variance (the run's own) and with the variants'
  // Sharpe dispersion (the declared deflation, its N the family's effective rank, rounded up).
  X.dsr = function (S, c) {
    var C = S.dev && S.dev.dsr_curve;
    if (!C || !C.length) return null;
    var P = global.Plot;
    var R = S.dev.snooping && S.dev.snooping.results;
    var reported = S.dev.facts && S.dev.facts.dsr_trials;
    var nullRows = C.map(function (r) { return {n: r.n, dsr: 100 * r.dsr, star: r.sr_star, curve: 'null'}; });
    var famRows = [], famAt = [];
    if (R && R.dsr && R.dsr.dsr_pct !== null && R.dsr.dsr_pct !== undefined) {
      famRows = R.dsr.curve.map(function (r) { return {n: r.n, dsr: 100 * r.dsr, star: r.sr_star, curve: 'family'}; });
      famAt = [{n: R.dsr.n_trials, dsr: R.dsr.dsr_pct, star: R.dsr.sr_star, curve: 'family'}];
      famRows = famRows.concat(famAt).sort(function (a, b) { return a.n - b.n; });
    }
    var nullAt = nullRows.filter(function (r) { return r.n === reported; });
    var two = !!(R && R.variants && R.variants.length);
    var cols = two && c.width >= 900 ? 2 : 1;
    var cw = Math.floor((c.width - (cols - 1) * 28) / cols);
    var cc = Object.assign({}, c, {width: cw, narrow: cw < 560});
    var all = nullRows.concat(famRows);
    var dsrNode = plot(cc, {
      height: cc.narrow ? 210 : 230, marginLeft: 40, marginRight: 24, marginTop: 24, marginBottom: 30,
      x: {type: 'log', domain: [nullRows[0].n, nullRows[nullRows.length - 1].n], label: 'Number of independent trials N', labelArrow: 'none'},
      y: {domain: [0, Math.max(50, Math.max.apply(null, all.map(function (r) { return r.dsr; })) * 1.1)], label: 'Deflated Sharpe, %', labelArrow: 'none'},
      marks: [
        gridY(c, {ticks: 4}), axisY(c, {ticks: 4, label: 'Deflated Sharpe, %', labelArrow: 'none'}),
        axisX(c, {label: 'Number of independent trials N', labelArrow: 'none', tickFormat: function (v) { return global.d3.format(',')(v); }}),
        zeroY(c),
        P.lineY(nullRows, {x: 'n', y: 'dsr', stroke: c.t.ink2, strokeWidth: 1.5, strokeDasharray: '4,3'}),
        P.lineY(famRows, {x: 'n', y: 'dsr', stroke: c.t.s1, strokeWidth: 2}),
        P.dot(nullAt, {x: 'n', y: 'dsr', r: 5, fill: c.t.paper, stroke: c.t.ink2, strokeWidth: 2}),
        P.dot(famAt, {x: 'n', y: 'dsr', r: 5.5, fill: c.t.paper, stroke: c.t.s1, strokeWidth: 2}),
        // the two marked values, as a key in the top-right corner (the curves meet near zero)
        P.text(famAt, {frameAnchor: 'top-right', text: function (r) { return 'N = ' + r.n + ', the family\u2019s effective trials: ' + num(r.dsr, 1) + '%'; }, dy: 2, textAnchor: 'end', fill: c.t.s1, fontWeight: 600, fontSize: annot(cc)}),
        P.text(nullAt, {frameAnchor: 'top-right', text: function (r) { return 'N = ' + r.n + ', the trials reported: ' + num(r.dsr, 1) + '%'; }, dy: 19, textAnchor: 'end', fill: c.t.ink2, fontSize: annot(cc)}),
        tip(c, all, P.pointer({x: 'n', y: 'dsr', title: function (r) {
          return 'N = ' + r.n + (r.curve === 'family' ? ', the variants’ dispersion' : ', null trial variance') + '\nDSR ' + num(r.dsr, 1) + '%\nExpected best null Sharpe ' + num(r.star, 2);
        }}))
      ]
    });
    var dsrTable = table('Deflated Sharpe ratio of the main backtest by number of trials: with the null trial variance, and with the declared variants’ Sharpe dispersion.',
      ['Trials N', 'Trial variance', 'DSR', 'Expected best null Sharpe'], [true, false, true, true],
      nullRows.map(function (r) { return [String(r.n), 'null', num(r.dsr, 2, {suffix: '%'}), num(r.star, 2)]; })
        .concat(famRows.map(function (r) { return [String(r.n), 'the variants’', num(r.dsr, 2, {suffix: '%'}), num(r.star, 2)]; })));
    if (!two) return {nodes: [dsrNode], table: dsrTable};

    // the variants in the neutral colour, a circle for a grid point and a triangle for a toggle;
    // the v33 design (one of the grid points) in the pairs strategy's colour
    var V = R.variants.map(function (v) {
      return Object.assign({}, v, {color: v.base ? c.t.s1 : c.t.neutral, symbol: v.kind === 'grid' || v.base ? 'circle' : 'triangle'});
    });
    var g = S.dev.gatev_sharpe;
    var base = V.filter(function (v) { return v.base; });
    var xs = domainPad(V.map(function (v) { return v.sharpe; }).concat(g !== null && g !== undefined ? [g] : []), 0.08, [0]);
    var refs = [];
    if (base.length) refs.push({key: 'base', x: base[0].sharpe, text: 'v33 design ' + signed(base[0].sharpe, 2) + ', ' + ordinalRank(base[0].rank) + ' of ' + V.length});
    if (g !== null && g !== undefined) refs.push({key: 'gatev', x: g, text: 'Gatev ' + signed(g, 2)});
    var af = annot(cc);
    var famNode = plot(cc, {
      height: cc.narrow ? 180 : 140, marginLeft: 16, marginRight: 16, marginTop: 44, marginBottom: 30,
      x: {domain: xs, label: 'Annualised net Sharpe ratio, development period', labelArrow: 'none'},
      y: {axis: null},
      marks: [
        gridX(c, {ticks: cc.narrow ? 4 : 6}),
        axisX(c, {ticks: cc.narrow ? 4 : 6, label: 'Annualised net Sharpe ratio, development period', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        zeroX(c),
        // zero is cash: the comparison of the title
        P.text(['cash'], halo(c, {x: function () { return 0; }, frameAnchor: 'top', text: function (d) { return d; }, dy: -10, dx: 4, textAnchor: 'start', fill: c.t.ink2, fontSize: af})),
        g !== null && g !== undefined ? P.ruleX([g], {stroke: c.t.s2, strokeWidth: 1.5, strokeDasharray: '4,3'}) : null,
        P.ruleX(base, {x: 'sharpe', stroke: c.t.s1, strokeWidth: 1, strokeOpacity: 0.6}),
        P.dot(V, P.dodgeY({anchor: 'bottom', x: 'sharpe', r: 6, fill: 'color', symbol: 'symbol', stroke: c.t.paper, strokeWidth: 1.5, padding: 1,
          title: function (v) {
            return v.label + (v.base ? ' (the v33 design)' : '') + '\nSharpe ' + signed(v.sharpe, 2) + ', rank ' + v.rank + ' of ' + V.length +
              '\nReturn ' + pct(v.ret_pct) + ', ' + v.trades + ' trades\nRomano\u2013Wolf adjusted p ' + num(v.rw_p, 3) + '; MCS p ' + num(v.mcs_p, 3);
          }, tip: {fill: c.t.surface, stroke: c.t.rule2, fontSize: 12, lineHeight: 1.35}})),
        P.text(refs.filter(function (r) { return r.key === 'base'; }), {x: 'x', text: 'text', frameAnchor: 'top', dy: -26, textAnchor: 'end', dx: 4, fill: c.t.ink, fontWeight: 600, fontSize: af}),
        P.text(refs.filter(function (r) { return r.key === 'gatev'; }), {x: 'x', text: 'text', frameAnchor: 'top', dy: -10, textAnchor: 'end', dx: 4, fill: c.t.ink2, fontSize: af}),
      ].filter(Boolean)
    });
    var wrap = document.createElement('div');
    wrap.className = 'multi';
    wrap.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    // the panel's title counts the variants above zero (the prose before the exhibit gives the count)
    var positive = has(R.positive) ? R.positive : V.filter(function (v) { return v.sharpe > 0; }).length;
    [['The ' + V.length + ' declared variants: ' + positive + ' with a positive Sharpe ratio', famNode],
     ['Deflated Sharpe ratio of the main backtest', dsrNode]].forEach(function (pp) {
      var cell = document.createElement('div');
      cell.className = 'multi-cell';
      var h = document.createElement('p');
      h.className = 'mc-title';
      h.textContent = pp[0];
      cell.appendChild(h);
      cell.appendChild(pp[1]);
      wrap.appendChild(cell);
    });
    var sorted = V.slice().sort(function (a, b) { return a.rank - b.rank; });
    return {
      nodes: [wrap],
      legend: [{label: 'Threshold grid', color: '--neutral-series', kind: 'dot'}, {label: 'Design toggle', color: '--neutral-series', kind: 'dot tri'},
               {label: 'v33 design', color: '--series-1', kind: 'dot'}, {label: 'Gatev baseline', color: '--series-2', kind: 'rule dash'},
               {label: 'DSR, the variants’ dispersion', color: '--series-1', kind: 'line'}, {label: 'DSR, null trial variance', color: '--ink-2', kind: 'line dash'}],
      table: [table('The declared variants by net Sharpe ratio (development period, ' + R.days + ' days), with each one’s Romano–Wolf adjusted p-value against cash and its model-confidence-set p-value.',
        ['Rank', 'Variant', 'Sharpe', 'Return', 'Trades', 'Romano–Wolf p', 'MCS p'], [true, false, true, true, true, true, true],
        sorted.map(function (v) { return [String(v.rank), v.label + (v.base ? ' (v33 design)' : ''), signed(v.sharpe, 2), pct(v.ret_pct), String(v.trades), num(v.rw_p, 3), num(v.mcs_p, 3)]; })),
        dsrTable]
    };
  };
  function ordinalRank(n) {
    var s = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }

  // ── Exhibit 9: implementation-shortfall waterfall ─────────────────────────
  X.waterfall = function (S, c) {
    var steps = (S.dev && (S.dev.shortfall || S.dev.waterfall)) || [];
    if (!steps.length) return null;
    var P = global.Plot;
    var cap = (S.dev.run && S.dev.run.capital) || 1e8;
    var SHORT = {paper: 'Paper P&L', entry_delay: 'Entry delay', exit_delay: 'Exit delay', gross: 'Gross P&L', bid_ask: 'Half-spread',
                 market_impact: 'Market impact', commission: 'Commission', borrow: 'Borrow', financing: 'Financing', net: 'Net P&L'};
    var rows = steps.filter(function (s) { return s.usd !== 0 || s.key === 'gross' || s.key === 'net'; }).map(function (s) {
      var total = s.key === 'gross' || s.key === 'net' || s.key === 'paper';
      return {step: SHORT[s.key] || s.step, name: s.step, a: s.start / 1e3, b: s.end / 1e3, usd: s.usd, total: total, bp: s.usd / cap * 1e4};
    });
    var fill = function (r) { return r.total ? c.t.ink2 : signColor(c)(r.usd); };
    var right = rows.filter(function (r) { return r.b >= r.a; });      // bar grows rightwards: label at its end
    var left = rows.filter(function (r) { return r.b < r.a; });
    var mL = c.narrow ? 98 : 120, mR = 16;
    // room for each value label beyond its bar's end, so none runs into the step names or off the page
    var xs = fitLabels(domainPad(rows.map(function (r) { return r.a; }).concat(rows.map(function (r) { return r.b; })), 0.04, [0]),
      rows.map(function (r) {
        var grows = r.b >= r.a;
        return {x: grows ? r.b : Math.min(r.a, r.b), px: textWidth(usdk(r.usd), c.narrow ? 12 : 11.5) + 12, side: grows ? 'right' : 'left'};
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
        P.text(right, halo(c, {y: 'step', x: 'b', text: function (r) { return usdk(r.usd); }, dx: 6, textAnchor: 'start', fill: c.t.ink, fontSize: c.narrow ? 12 : 11.5})),
        P.text(left, halo(c, {y: 'step', x: function (r) { return Math.min(r.a, r.b); }, text: function (r) { return usdk(r.usd); }, dx: -6, textAnchor: 'end', fill: c.t.ink, fontSize: c.narrow ? 12 : 11.5})),
        tip(c, rows, P.pointerY({y: 'step', x: 'b', title: function (r) {
          return r.name + '\n' + money(r.usd) + '\n' + signed(r.bp, 1) + ' bp of starting capital';
        }}))
      ]
    });
    return {
      nodes: [node],
      table: table('Implementation shortfall, main backtest.', ['Step', '$', 'bp of capital', 'Running total, $'],
        [false, true, true, true], rows.map(function (r) { return [r.name, signed(r.usd, 2), signed(r.bp, 1), signed(r.b * 1e3, 2)]; }))
    };
  };

  // ── Exhibit 10: trade anatomy small multiples ─────────────────────────────
  X.anatomy = function (S, c) {
    var T = S.dev && S.dev.trades;
    if (!T || !T.by_exit) return null;
    var P = global.Plot;
    var panels = [['By exit', T.by_exit], ['By side of the spread', T.by_side], ['By |z| at entry', T.by_z]];
    var wrap = document.createElement('div');
    wrap.className = 'multi multi-3';
    // one panel per row unless each of three columns can hold its bar labels
    var cols = c.width >= 1100 ? 3 : 1;
    var cw = Math.floor((c.width - (cols - 1) * 24) / cols);
    wrap.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    // each bar labelled with its net P&L and its trade count; on a narrow panel the count
    // moves into the row label, so the value labels leave room for the bars
    var compact = cw < 560;
    var mL = compact ? 116 : 86, mR = 12;
    var barLabel = function (g) { return compact ? money(g.net_usd) : money(g.net_usd) + ' (n = ' + g.n + ')'; };
    var rowLabel = function (g) { return compact ? g.label + ' (' + g.n + ')' : g.label; };
    // side by side, the panels share one height and baseline: a panel with fewer rows keeps
    // the same row step and centres its rows in the frame
    var ROW = 36, MT = 6, MB = 28;
    var maxRows = Math.max.apply(null, panels.map(function (pp) { return pp[1].length; }));
    panels.forEach(function (pp) {
      var rows = pp[1].map(function (g) { return Object.assign({}, g, {k: g.net_usd / 1e6, y: rowLabel(g)}); });
      // each panel on its own scale, wide enough for every label beyond its bar: the exit
      // panel's $15M bars would otherwise leave the side and |z| panels as slivers
      var xs = fitLabels(domainPad(rows.map(function (r) { return r.k; }), 0.04, [0]), rows.map(function (r) {
        return {x: r.k, px: textWidth(barLabel(r), annot(c)) + 10, side: r.k >= 0 ? 'right' : 'left'};
      }), cw - mL - mR);
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
        y: {domain: rows.map(function (r) { return r.y; }), label: null, padding: 0.3, range: [top, top + rows.length * ROW + 2]},
        marks: [
          gridX(c, {ticks: 3}), axisX(c, {ticks: 3, label: '$ millions', labelArrow: 'none', tickFormat: function (v) { return signed(v, Math.abs(xs[1] - xs[0]) < 6 ? 1 : 0); }}),
          axisY(c, {fill: c.t.ink}),
          zeroX(c),
          P.barX(rows, {y: 'y', x: 'k', fill: function (r) { return signColor(c)(r.k); }, rx2: 3}),
          P.text(pos, {y: 'y', x: 'k', text: barLabel, dx: 5, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)}),
          P.text(neg, {y: 'y', x: 'k', text: barLabel, dx: -5, textAnchor: 'end', fill: c.t.ink2, fontSize: annot(c)}),
          tip(c, rows, P.pointerY({y: 'y', x: 'k', title: function (r) {
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
    var gross = function (s) { return s.gross_pct === null || s.gross_pct === undefined ? '' : ' · gross ' + pct(s.gross_pct); };
    var all = [];
    C.forEach(function (s) { all = all.concat(s.cum); });
    var ys = domainPad(all, 0.08, [0]);
    var wrap = document.createElement('div');
    wrap.className = 'multi';
    var cols = c.narrow ? 2 : (c.width < 820 ? 3 : 5);
    var cw = Math.floor((c.width - (cols - 1) * 14) / cols);
    wrap.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    var panes = [], byDate = C.map(function () { return {}; });
    C.forEach(function (s, k) {
      var ds = s.dates || dates;
      var rows = s.cum.map(function (v, i) { byDate[k][ds[i]] = v; return {date: parse(ds[i]), v: v}; });
      var last = rows[rows.length - 1];
      var cell = document.createElement('div');
      cell.className = 'multi-cell';
      var h = document.createElement('p');
      h.className = 'mc-title';
      h.textContent = 'Schedule ' + s.id + ': ' + pct(s.ret_pct) + gross(s);
      var p = document.createElement('p');
      p.textContent = num(s.commission_bps, 1) + ' bp commission · ' + num(s.half_spread_bps, 1) + ' bp half-spread · impact cap ' +
        num(s.impact_cap_bps, 0) + ' bp · borrow ' + num(s.borrow_pct, 2) + '% · financing ' + num(s.financing_pct, 2) + '% · positions ' +
        num(s.position_pct[0], 0) + '–' + num(s.position_pct[1], 0) + '% · ' + s.trades + ' trades replayed';
      cell.appendChild(h);
      cell.appendChild(p);
      var pane = plot(Object.assign({}, c, {width: cw}), {
        height: 130, marginLeft: 34, marginRight: 6, marginTop: 8, marginBottom: 22,
        x: {type: 'utc', ticks: 2, tickFormat: global.d3.utcFormat('%Y')},
        y: {domain: ys, ticks: 4, label: null, tickFormat: function (v) { return signed(v, 0); }},
        marks: [
          gridY(c, {ticks: 4}), axisY(c, {ticks: 4, tickFormat: function (v) { return signed(v, 0); }}),
          axisX(c, {ticks: 2, tickFormat: global.d3.utcFormat('%Y')}),
          zeroY(c),
          P.lineY(rows, {x: 'date', y: 'v', stroke: c.t.s1, strokeWidth: 1.75}),
          P.dot([last], {x: 'date', y: 'v', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2})
        ]
      });
      panes.push(pane);
      cell.appendChild(pane);
      wrap.appendChild(cell);
    });
    // one date across the five schedules: the dates of the main backtest, each schedule's value on it
    var days = Array.from(new Set([].concat.apply([], C.map(function (s) { return s.dates || dates; })))).sort();
    var rowsX = days.map(function (d) { return {date: parse(d), v: C.map(function (s, k) { return byDate[k][d]; })}; });
    return {
      mount: function (container) {
        crosshair(container, {
          panes: panes, rows: rowsX, dock: wrap,
          dots: C.map(function (s, k) { return {pane: k, y: function (r) { return r.v[k]; }, color: c.t.s1}; }),
          items: function (r) { return C.map(function (s, k) { return {label: 'Schedule ' + s.id, color: c.t.s1, value: has(r.v[k]) ? pct(r.v[k]) : '–'}; }); }
        }, c);
      },
      nodes: [wrap],
      table: table('Cost schedules A–E: parameters and results of the replay.',
        ['Schedule', 'Commission, bp', 'Half-spread, bp', 'Impact cap, bp', 'Borrow, %/yr', 'Financing, %/yr', 'Position, % equity',
         'Trades replayed', 'Gross, % capital', 'Costs, % capital', 'Net return', 'Sharpe', 'Max drawdown', 'Peak gross, ×'],
        [false, true, true, true, true, true, false, true, true, true, true, true, true, true],
        C.map(function (s) {
          return [s.id, num(s.commission_bps, 1), num(s.half_spread_bps, 1), num(s.impact_cap_bps, 0), num(s.borrow_pct, 2), num(s.financing_pct, 2),
                  num(s.position_pct[0], 0) + '–' + num(s.position_pct[1], 0), String(s.trades), signed(s.gross_pct, 2), num(s.cost_pct, 2),
                  pct(s.ret_pct), num(s.sharpe, 2), num(s.max_dd_pct, 2, {suffix: '%'}), num(s.peak_gross_x, 2)];
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
    var mL = c.narrow ? 112 : 130, mR = 20, af = annot(c);
    // each beta printed at the right, on its own lane, where the scale keeps 200 px
    var betaText = function (r) { return signed(r.beta, 3); };
    var valueW = Math.ceil(Math.max.apply(null, rows.map(function (r) { return textWidth(betaText(r), af); }).concat([textWidth('Beta', af)]))) + 14;
    var values = multi && c.width - mL - valueW >= 200;
    if (values) mR = valueW;
    var step = multi ? (values ? 34 : 30) : 40;
    var lane = function (oos) { return multi ? (oos ? 1 : -1) * (values ? 6 : 5) : 0; };
    var series = [false, true].map(function (oos) {
      var rs = rows.filter(function (r) { return r.oos === oos; });
      return [
        P.ruleY(rs, {y: 'label', x1: 'lo', x2: 'hi', stroke: c.t.s1, strokeWidth: 2, dy: lane(oos)}),
        P.dot(rs, {x: 'beta', y: 'label', r: 4.5, fill: oos && multi ? c.t.paper : c.t.s1, stroke: oos && multi ? c.t.s1 : c.t.paper, strokeWidth: 2, dy: lane(oos)})
      ];
    });
    var xdom = domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.15, [0]);
    if (!multi) {        // room for the t labels beyond each interval
      xdom = fitLabels(xdom, rows.map(function (r) { return {x: r.hi, px: textWidth('t = ' + num(r.t, 2), af) + 12, side: 'right'}; }), c.width - mL - mR);
    }
    var node = plot(c, {
      height: labels.length * step + 56 + (values ? 12 : 0), marginLeft: mL, marginRight: mR, marginTop: values ? 26 : 14, marginBottom: 34,
      x: {domain: xdom, label: 'Beta (95% interval)', labelArrow: 'none'},
      y: {domain: labels, label: null, padding: multi ? 0.2 : 0.4},
      marks: [
        gridX(c, {ticks: c.narrow ? 3 : 5}), axisX(c, {ticks: c.narrow ? 3 : 5, label: 'Beta (95% interval)', labelArrow: 'none', tickFormat: function (v) { return signed(v, multi ? 2 : 3); }}),
        axisY(c, {fill: c.t.ink, lineWidth: 12}),
        zeroX(c)
      ].concat(series[0], series[1], [
        multi ? null : P.text(rows, {x: 'hi', y: 'label', text: function (r) { return 't = ' + num(r.t, 2); }, dx: 8, textAnchor: 'start', fill: c.t.ink2, fontSize: af}),
        values ? P.text(rows.filter(function (r) { return !r.oos; }), {frameAnchor: 'right', y: 'label', dy: lane(false), text: betaText, textAnchor: 'end', dx: mR - 2, fill: c.t.ink2, fontSize: af}) : null,
        values ? P.text(rows.filter(function (r) { return r.oos; }), {frameAnchor: 'right', y: 'label', dy: lane(true), text: betaText, textAnchor: 'end', dx: mR - 2, fill: c.t.ink2, fontSize: af}) : null,
        values ? P.text(['Beta'], {frameAnchor: 'top-right', text: function (d) { return d; }, dy: -14, textAnchor: 'end', dx: mR - 2, fill: c.t.ink3, fontSize: af}) : null,
        tip(c, rows, P.pointer({x: 'beta', y: 'label', title: function (r) { return r.series + (multi ? ': ' + r.name : '') + '\nbeta ' + signed(r.beta, 4) + ' (t = ' + num(r.t, 2) + ')\n95% ' + num(r.lo, 4) + ' to ' + signed(r.hi, 4); }}))
      ]).filter(Boolean)
    });
    return {
      nodes: [node],
      legend: multi ? [{label: 'Main backtest', color: '--series-1', kind: 'dot'}, {label: 'Walk-forward', color: '--series-1', kind: 'dot ring'}] : null,
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
    var B = bins(bp, thresholds);
    var node = plot(c, {
      height: c.narrow ? 220 : 250, marginLeft: 40, marginRight: 16, marginTop: 20, marginBottom: 30,
      x: {label: 'Daily net return, bp of capital', labelArrow: 'none'},
      y: {label: 'Days', labelArrow: 'none'},
      marks: [
        gridY(c), axisY(c, {label: 'Days', labelArrow: 'none'}),
        axisX(c, {label: 'Daily net return, bp of capital', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
        P.rectY(B, {x1: 'x1', x2: 'x2', y: 'n', fill: c.t.s1, fillOpacity: 0.8, insetLeft: 0.5, insetRight: 0.5}),
        zeroY(c),
        tip(c, B, P.pointerX({x: function (b) { return (b.x1 + b.x2) / 2; }, y: 'n', title: function (b) {
          return signed(b.x1, 2) + ' to ' + signed(b.x2, 2) + ' bp: ' + plural(b.n, 'day', 'days') + ' (' + num(100 * b.n / bp.length, 1) + '%)';
        }}))
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
    // a 'separate' stage (the pairs traded across every formation) is not a share of the stage
    // above it, which is the first formation's alone: it gets no share and a neutral bar
    var rows = F.pairs.map(function (s, i) {
      return Object.assign({}, s, {color: s.separate ? c.t.neutral : ramp[Math.min(i, ramp.length - 1)],
                                   share: i && !s.separate ? s.n / F.pairs[i - 1].n : null});
    });
    var exp = rows.filter(function (r) { return r.expected; });
    var maxN = Math.max.apply(null, rows.map(function (r) { return r.n; }));
    var node = plot(c, {
      height: rows.length * 44 + 50, marginLeft: c.narrow ? 118 : 196, marginRight: 70, marginTop: 10, marginBottom: 30,
      x: {domain: [0, maxN * 1.02], label: 'Pairs', labelArrow: 'none'},
      y: {domain: rows.map(function (r) { return r.stage; }), label: null, padding: 0.32},
      marks: [
        gridX(c, {ticks: c.narrow ? 3 : 4}), axisX(c, {ticks: c.narrow ? 3 : 4, label: 'Pairs', labelArrow: 'none', tickFormat: global.d3.format(c.narrow ? '~s' : ',')}),
        axisY(c, {fill: c.t.ink, lineWidth: c.narrow ? 10 : 22}),
        P.barX(rows, {y: 'stage', x: 'n', fill: 'color', rx2: 3}),
        zeroX(c),
        P.text(rows, {y: 'stage', x: 'n', text: function (r) { return global.d3.format(',')(r.n); }, dx: 6, textAnchor: 'start', fill: c.t.ink, fontWeight: 600, fontSize: 12}),
        // the count chance alone would produce: a tick on the bar, its value beside the bar's own
        P.tickX(exp, {y: 'stage', x: 'expected', stroke: c.t.ink, strokeWidth: 2}),
        P.text(exp, {y: 'stage', x: 'n', text: function (r) { return '(' + global.d3.format(',.0f')(r.expected) + ' by chance)'; }, dx: 6, dy: 15, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)}),
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
    // the gap split by fetch outcome (null when the run's price manifest is not published)
    var split = S.dev.survivorship, splitBy = {};
    ((split && split.formations) || []).forEach(function (f) { splitBy[f.formation_date] = f; });
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
        gridX(c, {ticks: c.narrow ? [0, 1000, 2000] : 4}),
        axisX(c, {ticks: c.narrow ? [0, 1000, 2000] : 4, label: 'Members', labelArrow: 'none', tickFormat: c.narrow ? function (v) { return v ? num(v / 1000, 0) + 'k' : '0'; } : fmtN}),
        axisY(c, {fill: c.t.ink}),
        P.barX(counts, {y: 'label', x: 'v', fill: 'fill'}),
        zeroX(c),
        P.text(rows, {y: 'label', x: 'members', text: function (r) { return num(r.cover, 1, {suffix: '%'}); }, dx: 6, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)}),
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
        P.text(rows, {y: 'label', x: 'gap', text: function (r) { return num(r.gap, 2, {suffix: '%'}); }, dx: 6, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)}),
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
      table: table('Point-in-time universe at each formation date (weights in % of the snapshot\'s equity value). Members without prices are split by '
        + 'the outcome of their fetch: no longer served by the vendor (HTTP 404), fetch failed (an HTTP error or an empty answer), failed the data checks; '
        + 'the last columns count those among the snapshot\'s ' + (split ? split.heaviest_members : 500) + ' heaviest members.',
        ['Formation date', 'Snapshot', 'Filed', 'Members', 'With prices', 'Without prices', 'Coverage', 'Weight without prices',
         'of which 404', 'fetch failed', 'data checks', 'Weight without ticker', 'Heaviest members without prices', 'their weight', 'Heaviest without prices'],
        [false, false, false, true, true, true, true, true, true, true, true, true, true, true, false],
        rows.map(function (r) {
          var s = splitBy[r.formation_date], by = {};
          ((s && s.by_outcome) || []).forEach(function (o) { by[o.key] = o; });
          var w = function (k) { return by[k] ? num(by[k].weight_pct, 2, {suffix: '%'}) : '–'; };
          return [r.formation_date, r.snapshot, r.snapshot_filed || '–', fmtN(r.members), fmtN(r.with_prices), fmtN(r.missing), num(r.cover, 1, {suffix: '%'}),
                  num(r.missing_weight_pct, 2, {suffix: '%'}), w('not_found'), w('fetch_failed'), w('data_checks'), num(r.unmapped_weight_pct, 2, {suffix: '%'}),
                  s ? String(s.heaviest_missing) : '–', s ? num(s.heaviest_missing_weight_pct, 2, {suffix: '%'}) : '–',
                  s ? s.heaviest_missing_names.map(function (h) { return h[0] + ' ' + num(h[2], 2) + '% (' + ({not_found: '404', fetch_failed: 'fetch failed', data_checks: 'data checks'}[h[3]] || h[3]) + ')'; }).join(', ')
                    : (r.missing_heaviest || []).map(function (h) { return h[0] + ' ' + num(h[1], 2) + '%'; }).join(', ') || '–'];
        }))
    };
  };

  // Exhibit 16: Sharpe against a cost multiplier, the trades held fixed (needs the daily gross/cost split)
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
        P.text([1], halo(c, {x: function (v) { return v; }, frameAnchor: 'top', text: function () { return 'modelled'; }, dy: 8, dx: 4, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)})),
        P.lineY(C, {x: 'k', y: 'sharpe', stroke: c.t.s1, strokeWidth: 2}), P.dot(C, {x: 'k', y: 'sharpe', r: 3.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 2}),
        be === null ? null : P.dot([be], {x: function (v) { return v; }, y: function () { return 0; }, r: 4, fill: c.t.paper, stroke: c.t.ink, strokeWidth: 1.5}),
        be === null ? null : P.text([be], halo(c, {x: function (v) { return v; }, y: function () { return 0; }, text: function (v) { return 'zero at ' + num(v, 2) + '×'; }, dy: 14, dx: -6, textAnchor: 'end', fill: c.t.ink, fontSize: annot(c)})),
        note === null ? null : P.text([note], halo(c, {frameAnchor: 'bottom-left', text: function (v) { return v; }, dx: 6, dy: -6, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)})),
        tip(c, C, P.pointerX({x: 'k', y: 'sharpe', title: function (r) { return num(r.k, 2) + '× costs\nSharpe ' + signed(r.sharpe, 2) + '\nReturn ' + pct(r.ret_pct); }}))].filter(Boolean)
    });
    return {nodes: [node], label: 'Line of net Sharpe ratio against the multiple of modelled costs.',
      table: table('Net Sharpe and return by cost multiple, the headline trades held fixed.', ['Cost multiple', 'Sharpe', 'Return'], [true, true, true],
        C.map(function (r) { return [num(r.k, 2) + '×', signed(r.sharpe, 2), pct(r.ret_pct)]; }))};
  };

  // Exhibit 11: exit race. anatomy.json exit_race: targets and stops among the barrier exits,
  // and the targets each null expects (nulls.random_walk: no mean reversion; nulls.ou: an OU
  // spread at the pair's formation half-life, the reversion the selection promised)
  X.exitrace = function (S, c) {
    var E = S.dev && S.dev.exit_race;
    if (!E || !E.barrier_exits) return null;
    var P = global.Plot, N = E.nulls || {};
    var n = E.targets + E.stops;
    var rw = N.random_walk || {expected_targets: E.expected_targets, z: E.z};
    var rows = [{k: 'Observed', share: 100 * E.targets / n, count: E.targets, fill: c.t.s1, z: null},
                {k: 'Random-walk spread', share: 100 * rw.expected_targets / n, count: rw.expected_targets, fill: c.t.neutral, z: rw.z}];
    if (N.ou) rows.push({k: 'Reverting as selected', share: 100 * N.ou.expected_targets / n, count: N.ou.expected_targets, fill: c.t.neutral, z: N.ou.z});
    var mL = c.narrow ? 112 : 124;
    var node = plot(c, {
      height: rows.length * 44 + 40, marginLeft: mL, marginRight: 46, marginTop: 8, marginBottom: 30,
      x: {domain: [0, 100], label: 'Targets hit first, % of ' + n + ' barrier exits', labelArrow: 'none'},
      y: {domain: rows.map(function (r) { return r.k; }), label: null, padding: 0.3},
      marks: [gridX(c, {ticks: 5}), axisX(c, {ticks: 5, label: 'Targets hit first, % of ' + n + ' barrier exits', labelArrow: 'none', tickFormat: function (v) { return num(v, 0); }}),
        axisY(c, {fill: c.t.ink, lineWidth: (mL - 12) / 12, lineHeight: 1.1}),
        P.barX(rows, {y: 'k', x: 'share', fill: function (r) { return r.fill; }, rx2: 3}), zeroX(c),
        P.text(rows, halo(c, {y: 'k', x: 'share', text: function (r) { return num(r.share, 1, {suffix: '%'}); }, dx: 5, textAnchor: 'start', fill: c.t.ink, fontSize: annot(c)})),
        tip(c, rows, P.pointerY({y: 'k', x: 'share', title: function (r) {
          return r.k + '\n' + (r.z === null ? r.count + ' targets of ' + n : num(r.count, 1) + ' targets expected of ' + n + '\nobserved against it: z = ' + signed(r.z, 2));
        }}))]
    });
    return {nodes: [node], label: 'Bars of the share of barrier exits that hit the profit target: observed, and expected for a random-walk spread and for a spread reverting at its formation half-life.',
      table: table('Exit race: target exits among the ' + n + ' target and stop exits (' + E.other_exits + ' trades left at the time stop or the end of data).',
        ['Spread', 'Targets', 'Share', 'z (observed vs expected)'], [false, true, true, true],
        rows.map(function (r) { return [r.k, r.z === null ? String(r.count) : num(r.count, 1), num(r.share, 1, {suffix: '%'}), r.z === null ? '' : signed(r.z, 2)]; }))};
  };

  // Exhibit 12: decay. anatomy.json decay: [{period, bp, lo, hi, n, t}]
  X.decay = function (S, c) {
    var D = S.dev && S.dev.decay;
    if (!D || !D.length) return null;
    var P = global.Plot;
    // the anatomy's labels say "out of sample" for data after formation; this note keeps that
    // term for the 2026 holdout, so the periods are relabelled here
    var short = {'Formation (in sample), same rule': 'Formation window', 'Out of sample, same rule': 'After formation', 'Engine trades': 'The book'};
    var long = {'Formation (in sample), same rule': 'Formation window (in sample), same rule', 'Out of sample, same rule': 'After formation, same rule',
                'Engine trades': 'The book\'s own trades'};
    var rows = D.map(function (r) {
      return Object.assign({}, r, {k: short[r.period] || r.period, name: long[r.period] || r.period, label: short[r.period] || r.period, est: r.bp,
                                   color: c.t.s1, symbol: SHAPE.v33});
    });
    var node = intervalPlot(c, rows, {
      domain: domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.08, [0]),
      label: 'Gross bp per trade (95% interval)', ticks: 5, tickFormat: function (v) { return signed(v, 0); }, dp: 1, values: true, valueHead: 'bp [95% interval]',
      title: function (r) { return r.name + '\n' + signed(r.bp, 1) + ' bp (t = ' + num(r.t, 2) + ', n = ' + r.n + ')\n95% ' + num(r.lo, 1) + ' to ' + signed(r.hi, 1); }
    });
    return {nodes: [node], label: 'Dot plot of gross basis points per trade, in sample, after formation and in the book, with 95% intervals.',
      table: table('Gross bp per trade of the same rule on the same pairs (t clustered by signal month in the last column).',
        ['Period', 'Trades', 'bp', 'Lower', 'Upper', 't', 't, month-clustered'], [false, true, true, true, true, true, true],
        rows.map(function (r) { return [r.name, String(r.n), signed(r.bp, 1), num(r.lo, 1), signed(r.hi, 1), num(r.t, 2), num(r.t_month_clustered, 2)]; }))};
  };

  // Exhibit 13: persistence. anatomy.json persistence: {chance_pct, windows: [{window, pct, base_pct, pairs}]}
  X.persistence = function (S, c) {
    var Pd = S.dev && S.dev.persistence;
    if (!Pd || !Pd.windows || !Pd.windows.length) return null;
    var P = global.Plot;
    var tick = function (w) {
      var m = /^(\d{4})\D+(\d{4})$/.exec(w.window);
      return m ? '’' + m[1].slice(2) + '→’' + m[2].slice(2) : (c.narrow ? 'Traded' : 'Traded, after');
    };
    // the anatomy calls the traded pairs' later window "out of sample"; this note keeps that term
    // for the 2026 test (as in Exhibit 12)
    var name = function (w) { return /^(\d{4})\D+(\d{4})$/.test(w.window) ? w.window : 'Traded pairs, after formation'; };
    var W = Pd.windows.map(function (w) { return Object.assign({}, w, {k: tick(w), name: name(w)}); });
    var withBase = W.filter(function (w) { return w.base_pct !== null && w.base_pct !== undefined; });
    var ymax = Math.max.apply(null, W.map(function (w) { return Math.max(w.pct, w.base_pct || 0); }).concat([Pd.chance_pct])) * 1.18;
    var node = plot(c, {
      height: 200, marginLeft: 36, marginRight: 8, marginTop: 14, marginBottom: 30,
      x: {domain: W.map(function (w) { return w.k; }), label: null, padding: 0.25},
      y: {domain: [0, ymax], label: 'Still cointegrated, %', labelArrow: 'none'},
      marks: [gridY(c, {ticks: 4}), axisY(c, {ticks: 4, label: 'Still cointegrated, %', labelArrow: 'none'}), axisX(c, {fontSize: 11}),
        P.barY(W, {x: 'k', y: 'pct', fill: c.t.s1, ry2: 2}), zeroY(c),
        P.ruleY([Pd.chance_pct], {stroke: c.t.ink2, strokeWidth: 1.5, strokeDasharray: '4,3'}),
        P.text([Pd.chance_pct], halo(c, {y: function (v) { return v; }, frameAnchor: 'right', text: function (v) { return 'chance ' + num(v, 0) + '%'; },
          dy: -8, textAnchor: 'end', fill: c.t.ink2, fontSize: annot(c)})),
        P.tickY(withBase, {x: 'k', y: 'base_pct', stroke: c.t.ink, strokeWidth: 2}),
        tip(c, W, P.pointerX({x: 'k', y: 'pct', title: function (w) {
          return w.name + '\n' + num(w.pct, 1) + '% of ' + w.pairs + ' pairs still cointegrated' + (w.base_pct ? '\nbase rate of the next year ' + num(w.base_pct, 1) + '%' : '');
        }}))]
    });
    return {nodes: [node], label: 'Bars of the share of cointegrated pairs still cointegrated a year later, with ticks at the next year\'s base rate and a line at the 5% chance rate.',
      legend: [{label: 'Still cointegrated', color: '--series-1', kind: 'box'}, {label: 'Base rate of the next year', color: '--ink', kind: 'line'}],
      table: table('Cointegration persistence: pairs cointegrated in one year that are cointegrated the next (chance ' + num(Pd.chance_pct, 1) + '%).',
        ['Window', 'Pairs', 'Still cointegrated', 'Next year’s base rate'], [false, true, true, true],
        W.map(function (w) { return [w.name, String(w.pairs), num(w.pct, 1, {suffix: '%'}), w.base_pct ? num(w.base_pct, 1, {suffix: '%'}) : '–']; }))};
  };

  // Exhibit 14: the traded pairs' half-lives, on the formation window and after formation
  // (anatomy.persistence_detail.traded_pairs, passed through as dev.half_lives)
  X.halflife = function (S, c) {
    var H = S.dev && S.dev.half_lives;
    if (!H || !H.pairs || !H.pairs.length) return null;
    var P = global.Plot, CAP = 400, LO = 2, max = H.max_half_life || 25;
    var rows = H.pairs.filter(function (r) { return r.f !== null; }).map(function (r) {
      var clipped = r.o === null || r.o > CAP;
      return {pair: r.pair, f: r.f, o: clipped ? CAP : Math.max(r.o, LO), raw: r.o, clipped: clipped, trades: r.trades, p_f: r.p_f, p_o: r.p_o};
    });
    // y = x drawn on a log y axis: sampled densely, or the straight segment between two points is a chord
    var diag = global.d3.range(4, max + 1.01, 0.25).map(function (v) { return [v, v]; });
    var above = rows.filter(function (r) { return r.raw === null || r.raw > max; }).length;
    var facts = S.dev.facts || {};
    var abovePct = has(facts.hl_oos_above_max_pct) ? facts.hl_oos_above_max_pct : 100 * above / rows.length;
    var node = plot(c, {
      height: 240, marginLeft: 44, marginRight: 14, marginTop: 26, marginBottom: 30,
      x: {domain: [0, max + 1], label: 'Half-life at formation, days', labelArrow: 'none'},
      y: {type: 'log', domain: [LO, CAP * 1.35], label: 'Half-life after formation, days', labelArrow: 'none'},
      marks: [gridY(c, {ticks: [2, 5, 10, 25, 50, 100, 400]}), axisY(c, {ticks: [2, 5, 10, 25, 50, 100, 400], tickFormat: function (v) { return String(v); }, label: 'Half-life after formation, days', labelArrow: 'none'}),
        axisX(c, {ticks: 5, label: 'Half-life at formation, days', labelArrow: 'none'}),
        P.rect([max], {x1: 0, x2: max + 1, y1: function (v) { return v; }, y2: CAP * 1.35, fill: c.t.neutral, fillOpacity: 0.12}),
        P.ruleY([max], {stroke: c.t.ink2, strokeWidth: 1.5, strokeDasharray: '4,3'}),
        P.text([max], halo(c, {y: function (v) { return v; }, frameAnchor: 'left', text: function () { return 'rule’s maximum, ' + max + ' days'; }, dy: -8, dx: 4, textAnchor: 'start', fill: c.t.ink2, fontSize: annot(c)})),
        P.text([abovePct], halo(c, {y: function () { return max; }, frameAnchor: 'left', text: function (v) { return num(v, 1) + '% of the traded pairs above it'; },
          dy: -23, dx: 4, textAnchor: 'start', fill: c.t.ink, fontWeight: 600, fontSize: annot(c)})),
        P.line(diag, {stroke: c.t.ink3, strokeWidth: 1}),
        P.dot(rows.filter(function (r) { return !r.clipped; }), {x: 'f', y: 'o', r: 3, fill: c.t.s1, fillOpacity: 0.75}),
        P.dot(rows.filter(function (r) { return r.clipped; }), {x: 'f', y: 'o', r: 4, symbol: 'triangle', fill: c.t.s1}),
        tip(c, rows, P.pointer({x: 'f', y: 'o', title: function (r) {
          return r.pair + ' (' + r.trades + ' trade' + (r.trades === 1 ? '' : 's') + ')\nformation ' + num(r.f, 1) + ' days, p = ' + num(r.p_f, 3) +
            '\nafter formation ' + (r.raw === null ? 'no mean reversion' : num(r.raw, 1) + ' days') + ', p = ' + num(r.p_o, 3);
        }}))]
    });
    return {nodes: [node], label: 'Scatter of each traded pair\'s spread half-life on its formation window against its half-life after formation, with the rule\'s 25-day maximum marked.',
      legend: [{label: 'Traded pair', color: '--series-1', kind: 'dot'}, {label: 'Equal half-lives', color: '--ink-3', kind: 'line'}],
      table: table('Half-lives of the ' + rows.length + ' traded pairs (' + above + ' above ' + max + ' days after formation); Engle–Granger p in each window.',
        ['Pair', 'Trades', 'Formation, days', 'Formation p', 'After formation, days', 'After-formation p'], [false, true, true, true, true, true],
        rows.map(function (r) { return [r.pair, String(r.trades), num(r.f, 1), num(r.p_f, 3), r.raw === null ? 'none' : num(r.raw, 1), num(r.p_o, 3)]; }))};
  };

  // Exhibit 15: the declared cost and capacity scenarios two ways: the whole backtest re-run
  // (scripts/cost_sensitivity.py; the trades change) and the headline run's trades re-priced
  // (anatomy.json; the trades are fixed)
  X.scenarios = function (S, c) {
    var C = S.dev && S.dev.cost_sensitivity;
    if (!C || !C.available) return null;
    var P = global.Plot;
    var names = {headline: 'Headline (Y = 0.3, borrow 0.38%, $100M)', impact_0_6: 'Impact Y = 0.6', impact_1_0: 'Impact Y = 1.0',
                 borrow_1: 'Borrow 1% a year', borrow_3: 'Borrow 3% a year', capital_10m: 'Book of $10M', capital_1b: 'Book of $1B', capital_5b: 'Book of $5B'};
    if (c.narrow) names.headline = 'Headline';
    var rows = C.order.map(function (k) { var r = C.scenarios[k]; return {k: k, label: names[k] || r.label, full: r.full, fixed: r.fixed}; })
      .filter(function (r) { return r.full.sharpe !== null; });
    var full = rows.map(function (r) { return {label: r.label, x: r.full.sharpe, trades: r.full.trades, r: r}; });
    var fixed = rows.filter(function (r) { return r.fixed.sharpe !== null; }).map(function (r) { return {label: r.label, x: r.fixed.sharpe, r: r}; });
    var links = fixed.map(function (f) { return {label: f.label, a: f.x, b: f.r.full.sharpe}; });
    var xs = domainPad(full.map(function (d) { return d.x; }).concat(fixed.map(function (d) { return d.x; })), 0.1, [0]);
    var mL = c.narrow ? 112 : 176, mR = c.narrow ? 46 : 70;
    var node = plot(c, {
      height: rows.length * 38 + 50, marginLeft: mL, marginRight: mR, marginTop: 22, marginBottom: 30,
      x: {domain: xs, label: 'Net Sharpe ratio, annualised', labelArrow: 'none'},
      y: {domain: rows.map(function (r) { return r.label; }), label: null, padding: 0.4},
      marks: [gridX(c, {ticks: c.narrow ? 4 : 6}), axisX(c, {ticks: c.narrow ? 4 : 6, label: 'Net Sharpe ratio, annualised', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisY(c, {fill: c.t.ink, lineWidth: (mL - 12) / 12, lineHeight: 1.1}), zeroX(c),
        P.link(links, {y1: 'label', y2: 'label', x1: 'a', x2: 'b', stroke: c.t.rule2, strokeWidth: 2}),
        P.dot(fixed, {x: 'x', y: 'label', r: 4.5, fill: c.t.paper, stroke: c.t.s1, strokeWidth: 2}),
        P.dot(full, {x: 'x', y: 'label', r: 4.5, fill: c.t.s1, stroke: c.t.paper, strokeWidth: 1.5}),
        P.text(full, {y: 'label', frameAnchor: 'right', text: function (d) { return String(d.trades); }, dx: mR - 4, textAnchor: 'end', fill: c.t.ink2, fontSize: annot(c)}),
        P.text(['Trades'], {frameAnchor: 'top-right', text: function () { return 'trades, re-run'; }, dx: mR - 4, dy: -16, textAnchor: 'end', fill: c.t.ink3, fontSize: annot(c)}),
        tip(c, full, P.pointer({x: 'x', y: 'label', title: function (d) {
          var r = d.r;
          return d.label + '\nfull re-run: Sharpe ' + signed(r.full.sharpe, 2) + ', ' + pct(r.full.ret_pct) + ', ' + r.full.trades + ' trades, costs ' + num(r.full.cost_bp, 1) + ' bp of notional' +
            (r.fixed.sharpe === null ? '' : '\nsame trades re-priced: Sharpe ' + signed(r.fixed.sharpe, 2) + ', ' + pct(r.fixed.ret_pct));
        }}))]
    });
    return {nodes: [node], label: 'Dot plot of the net Sharpe ratio under each declared cost or capacity scenario: the full re-run (filled) and the headline trades re-priced (open), joined by a line.',
      legend: [{label: 'Full re-run (trades change)', color: '--series-1', kind: 'dot'}, {label: 'Headline trades re-priced', color: '--series-1', kind: 'dot ring'}],
      table: table('Cost and capacity scenarios: the full re-run and the headline run\'s ' + ((S.dev.facts && S.dev.facts.trades) || '') + ' trades re-priced.',
        ['Scenario', 'Trades', 'Net return', 'Sharpe', 'Max drawdown', 'Costs, % capital', 'Cost, bp of notional', 'Larger leg, % ADV', 'Same trades: return', 'Same trades: Sharpe'],
        [false, true, true, true, true, true, true, true, true, true],
        rows.map(function (r) {
          return [r.label, String(r.full.trades), pct(r.full.ret_pct), signed(r.full.sharpe, 2), num(r.full.max_dd_pct, 2, {suffix: '%'}), num(r.full.cost_pct, 2),
                  num(r.full.cost_bp, 1), num(r.full.adv_pct, 2), r.fixed.ret_pct === null ? '–' : pct(r.fixed.ret_pct), r.fixed.sharpe === null ? '–' : signed(r.fixed.sharpe, 2)];
        }))};
  };

  // Exhibit 17: capacity. anatomy.json capacity: [{aum_musd, net_bp, impact_bp}] (the same trades, re-priced)
  X.capacity = function (S, c) {
    var C = S.dev && S.dev.capacity;
    if (!C || !C.length) return null;
    var P = global.Plot;
    // net in the strategy's colour; market impact, a cost plotted below zero, dashed in the loss
    // colour; each line labelled at its end rather than in a legend
    var pts = [];
    C.forEach(function (r) {
      pts.push({aum: r.aum_musd, v: r.net_bp, s: 'Net, bp per trade', k: 'net', color: c.t.s1});
      if (r.impact_bp !== undefined && r.impact_bp !== null) pts.push({aum: r.aum_musd, v: -r.impact_bp, s: 'Market impact, bp per trade', k: 'impact', color: c.t.neg});
    });
    var lastAum = C[C.length - 1].aum_musd, af = annot(c);
    var ends = pts.filter(function (d) { return d.aum === lastAum; }).map(function (d) {
      return Object.assign({}, d, {text: d.k === 'net' ? 'Net' : 'Market impact\n(negative)'});
    }).sort(function (a, b) { return b.v - a.v; });
    var mR = Math.ceil(Math.max.apply(null, ends.map(function (e) { return Math.max.apply(null, e.text.split('\n').map(function (t) { return textWidth(t, af); })); }))) + 14;
    var endText = function (e, i) {
      return P.text([e], {x: 'aum', y: 'v', text: 'text', dx: 8, textAnchor: 'start', lineAnchor: i ? 'top' : 'bottom', dy: i ? -4 : 4,
        fill: c.t.ink, fontSize: af, lineHeight: 1.1});
    };
    var node = plot(c, {
      height: 200, marginLeft: 40, marginRight: mR, marginTop: 14, marginBottom: 30,
      x: {type: 'log', domain: [C[0].aum_musd * 0.8, C[C.length - 1].aum_musd * 1.25], label: 'Book size, $M (log scale)', labelArrow: 'none'},
      y: {domain: domainPad(pts.map(function (d) { return d.v; }), 0.1, [0]), label: 'bp per trade', labelArrow: 'none'},
      marks: [gridY(c, {ticks: 4}), axisY(c, {ticks: 4, label: 'bp per trade', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
        axisX(c, {ticks: 4, label: 'Book size, $M (log scale)', labelArrow: 'none', tickFormat: global.d3.format(',')}), zeroY(c),
        P.lineY(pts.filter(function (d) { return d.k === 'net'; }), {x: 'aum', y: 'v', stroke: c.t.s1, strokeWidth: 2}),
        P.lineY(pts.filter(function (d) { return d.k === 'impact'; }), {x: 'aum', y: 'v', stroke: c.t.neg, strokeWidth: 2, strokeDasharray: '5,3'}),
        P.dot(pts, {x: 'aum', y: 'v', fill: 'color', r: 3.5, stroke: c.t.paper, strokeWidth: 1.5}),
        tip(c, pts, P.pointer({x: 'aum', y: 'v', title: function (d) { return '$' + global.d3.format(',')(d.aum) + 'M\n' + d.s + ': ' + signed(d.v, 1); }}))]
        .concat(ends.slice(0, 2).map(endText))
    });
    return {nodes: [node], label: 'Lines of net basis points per trade and of market impact per trade against book size, for the same trades re-priced.',
      table: table('Capacity: the headline trades re-priced at other book sizes (impact re-priced per execution).', ['Book size, $M', 'Net bp per trade', 'Impact bp per trade', 'Sharpe', 'Net return'],
        [true, true, true, true, true], C.map(function (r) { return [global.d3.format(',')(r.aum_musd), signed(r.net_bp, 1), num(r.impact_bp, 1), signed(r.sharpe, 2), pct(r.total_return_pct)]; }))};
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

  // Exhibits 22 and 1: Sharpe ratios of strategy arms on the shared Sharpe axis, with their
  // values printed beside each row. An arm without a Sharpe ratio (status: why) keeps its row with
  // the reason; a dashed arm (dash) has a dashed interval; opts.ucb draws each arm's one-sided 95%
  // upper bound as a tick.
  function armSummary(c, arms, caption, opts) {
    var o = opts || {};
    var rows = arms.map(function (a) {
      return {label: a.label, est: a.sharpe, lo: a.lo, hi: a.hi, color: a.color, symbol: a.symbol, hollow: !!a.open, dash: !!a.dash,
              ucb: o.ucb ? a.ucb : null, status: a.status, arm: a};
    });
    var node = intervalPlot(c, rows, {
      domain: sharpeDomain([].concat.apply([], rows.map(function (r) { return [r.lo, r.hi, r.ucb]; }))),
      label: 'Annualised Sharpe ratio', values: true, valueHead: 'Sharpe [95% interval]',
      title: function (r) { return o.title ? o.title(r.arm) : r.label + '\nSharpe ' + signed(r.est, 2) + ' [' + signed(r.lo, 2) + ', ' + signed(r.hi, 2) + ']'; }
    });
    return {nodes: [node], label: 'Sharpe ratios with 95% intervals by strategy arm.',
      table: table(caption, ['Arm', 'Sharpe', 'Lower', 'Upper', 'Trades'], [false, true, true, true, true],
        arms.map(function (a) { return [a.label, signed(a.sharpe, 2), num(a.lo, 2), signed(a.hi, 2), a.trades === undefined || a.trades === null ? '–' : String(a.trades)]; }))};
  }
  X.residual = function (S, c) {
    var R = S.residual;
    if (!R || R.sharpe === null || R.sharpe === undefined) return null;
    var P = global.Plot, F = {};
    (S.dev.forest || []).forEach(function (r) { F[r.key] = r; });
    var arms = [{label: 'Avellaneda–Lee, net', sharpe: R.sharpe, lo: R.lo, hi: R.hi, trades: R.trades, color: c.t.s3, symbol: SHAPE.al}];
    if (R.gross_sharpe !== null && R.gross_sharpe !== undefined) arms.push({label: 'Avellaneda–Lee, gross', sharpe: R.gross_sharpe, lo: R.gross_lo, hi: R.gross_hi, trades: R.trades, color: c.t.s3, symbol: SHAPE.al, open: true});
    if (F.main) arms.push({label: 'Pairs, net', sharpe: F.main.sharpe, lo: F.main.lo, hi: F.main.hi, trades: S.dev.facts.trades, color: c.t.s1, symbol: SHAPE.v33});
    if (F.gross) arms.push({label: 'Pairs, gross', sharpe: F.gross.sharpe, lo: F.gross.lo, hi: F.gross.hi, trades: S.dev.facts.trades, color: c.t.s1, symbol: SHAPE.v33, open: true});
    var out = armSummary(c, arms, 'Second strategy family against the pairs strategy, development period, net and gross of costs.');
    out.legend = [{label: 'Avellaneda–Lee', color: '--series-3', kind: 'line mk mk-sq'}, {label: 'Pairs (v33)', color: '--series-1', kind: 'line mk'},
                  {label: 'Gross of costs', color: '--ink-2', kind: 'dot ring'}];
    if (R.paths && S.dev.daily) {
      var dates = R.paths.dates || S.dev.daily.dates, pairsBy = {};
      S.dev.daily.dates.forEach(function (d, i) { pairsBy[d] = S.dev.daily.cum[i]; });
      var rows = dates.map(function (d, i) { return {date: parse(d), al: R.paths.net[i], pr: pairsBy[d] === undefined ? null : pairsBy[d]}; });
      var last = rows[rows.length - 1];
      // each line named at its end, so the two stay apart without colour
      var ends = [{y: last.al, text: 'A–L ' + pct(last.al), color: c.t.s3}];
      if (last.pr !== null) ends.push({y: last.pr, text: 'Pairs ' + pct(last.pr), color: c.t.s1});
      var mR = Math.ceil(Math.max.apply(null, ends.map(function (e) { return textWidth(e.text, 12, 600); }))) + 14;
      var pane = plot(c, {
        height: c.narrow ? 180 : 210, marginLeft: 46, marginRight: mR, marginTop: 18, marginBottom: 26,
        x: {type: 'utc', domain: [rows[0].date, last.date]},
        y: {domain: domainPad(rows.map(function (r) { return r.al; }).concat(rows.map(function (r) { return r.pr; })), 0.08, [0]), label: 'Cumulative net return, %', labelArrow: 'none'},
        marks: [gridY(c), axisY(c, {label: 'Cumulative net return, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 0); }}),
          axisX(c, {ticks: c.narrow ? 4 : 8}), zeroY(c),
          P.lineY(rows, {x: 'date', y: 'pr', stroke: c.t.s1, strokeWidth: 2}),
          P.lineY(rows, {x: 'date', y: 'al', stroke: c.t.s3, strokeWidth: 2}),
          P.dot(ends, {x: function () { return last.date; }, y: 'y', r: 4, fill: function (d) { return d.color; }, stroke: c.t.paper, strokeWidth: 2}),
          P.text(ends, {x: function () { return last.date; }, y: 'y', text: 'text', dx: 8, textAnchor: 'start', fill: c.t.ink, fontWeight: 600, fontSize: 12})]
      });
      out.nodes[0].classList.add('plot-pane');
      pane.classList.add('plot-pane');
      out.nodes.push(pane);
      out.mount = function (container) {
        crosshair(container, {
          panes: [pane], rows: rows,
          dots: [{pane: 0, y: function (r) { return r.al; }, color: c.t.s3}, {pane: 0, y: function (r) { return r.pr; }, color: c.t.s1}],
          items: function (r) {
            return [{label: 'Avellaneda–Lee', color: c.t.s3, value: pct(r.al), wide: true}, {label: 'Pairs', color: c.t.s1, value: r.pr === null ? '–' : pct(r.pr), wide: true}];
          }
        }, c);
      };
    }
    return out;
  };
  // ── Exhibit 1: the evaluated holdout ──────────────────────────────────────
  // Top pane: each pre-registered arm's net Sharpe ratio with its 95% block-bootstrap interval and
  // its one-sided 95% upper bound, on the Sharpe axis Exhibits 6 and 22 share, with the values
  // printed; S3, descriptive, is hollow and dashed, and an arm without a Sharpe ratio keeps its row
  // with the reason. Bottom pane: each arm's cumulative net return by day, read with the
  // crosshair. The hypotheses table, the key figure and the run record are text, filled once by
  // ExhibitPage.holdout (below).
  X.holdout = function (S, c) {
    var H = holdoutDone(S);
    if (!H) return null;
    var P = global.Plot, alpha = holdoutAlpha(H);
    var arms = H.arms.map(function (a) {
      var info = armInfo(a);
      return Object.assign({}, a, {label: armLabel(a), color: armColor(c, info), dash: !!info.dash, symbol: info.symbol, open: !!info.open,
        status: has(a.sharpe) ? null : a.flat ? flatWhy(a) + ': Sharpe not defined' : 'Sharpe not reported'});
    });
    var out = armSummary(c, arms, '', {ucb: true, title: function (a) {
      var d = holdoutDecision(H, a);
      return a.label + '\nSharpe ' + signed(a.sharpe, 2) + ', 95% interval ' + interval(a.lo, a.hi) +
        (has(a.ucb) ? '\nOne-sided 95% upper bound ' + signed(a.ucb, 2) : '') +
        '\nNet return ' + pct(a.ret_pct) + (has(a.days) ? ' over ' + a.days + ' days' : '') +
        '\nOne-sided p ' + pText(a.p_one_sided) + (d.tested ? ', Holm p ' + holmP(d.p, d.below, alpha) : '') + '\n' + d.text;
    }});
    out.legend = arms.map(function (a) {
      var info = armInfo(a);
      return {label: a.label + (a.role === 'descriptive' ? ', descriptive' : ''), color: info.css, kind: info.key};
    }).concat(arms.some(function (a) { return has(a.sharpe) && has(a.ucb); }) ? [{label: 'One-sided 95% upper bound', color: '--ink', kind: 'rule'}] : []);
    out.table = [holdoutTable(H, alpha)];
    // the sealed page has no legend slot here: one is added above the chart (site.js fills it)
    var addLegend = function (chart) {
      var fig = chart.closest('figure');
      if (fig && !fig.querySelector('[data-legend]')) {
        var slot = document.createElement('div');
        slot.className = 'ex-legend';
        slot.setAttribute('data-legend', '');
        chart.before(slot);
      }
    };
    out.mount = addLegend;

    var D = H.daily;
    var series = D && D.dates && D.dates.length && D.cum ? arms.filter(function (a) {
      var v = D.cum[a.key];
      return v && v.length === D.dates.length;
    }) : [];
    out.label = 'Dot plot of the net Sharpe ratio of each pre-registered arm on the holdout, with 95% intervals and one-sided 95% upper bounds' +
      (series.length ? ', and lines of each arm’s cumulative net return by day.' : '. No daily series is published, so the cumulative net return is not drawn.');
    if (!series.length) {
      var note = document.createElement('p');
      note.className = 'ex-note';
      note.textContent = 'No daily series is published with this evaluation, so the cumulative net return of each arm is not drawn; each arm’s total is in the table above.';
      out.nodes.push(note);
      return out;
    }
    var rows = D.dates.map(function (d, i) {
      var r = {date: parse(d), iso: d};
      series.forEach(function (a) { r[a.key] = D.cum[a.key][i]; });
      return r;
    });
    var last = rows[rows.length - 1];
    var ends = series.map(function (a) { return {y: last[a.key], text: armTag(a) + ' ' + pct(last[a.key]), color: a.color}; });
    var h = c.narrow ? 200 : 240, mT = 18, mB = 26, mL = 46;
    var mR = Math.ceil(Math.max.apply(null, ends.map(function (e) { return textWidth(e.text, 12, 600); }))) + 14;
    var ydom = domainPad([].concat.apply([], series.map(function (a) { return D.cum[a.key]; })), 0.08, [0]);
    if (ydom[1] - ydom[0] < 1) ydom = [(ydom[0] + ydom[1]) / 2 - 0.5, (ydom[0] + ydom[1]) / 2 + 0.5];   // flat paths: ticks stay distinct at 1 dp
    // end labels at least 15px apart: placed in pixels on the pane's own scale, then mapped back
    var span = h - mT - mB;
    var px = function (v) { return mT + (ydom[1] - v) / (ydom[1] - ydom[0]) * span; };
    var order = ends.slice().sort(function (a, b) { return px(a.y) - px(b.y); });
    order.forEach(function (e, i) { e.py = Math.max(px(e.y), i ? order[i - 1].py + 15 : -Infinity); });
    var over = order[order.length - 1].py - (h - mB);
    order.forEach(function (e) { if (over > 0) e.py -= over; e.ty = ydom[1] - (e.py - mT) / span * (ydom[1] - ydom[0]); });
    var lines = series.slice().reverse().map(function (a) {          // S1 drawn last, on top
      var o = {x: 'date', y: a.key, stroke: a.color, strokeWidth: 2};
      if (a.dash) o.strokeDasharray = '5,3';
      return P.lineY(rows, o);
    });
    var pane = plot(c, {
      height: h, marginLeft: mL, marginRight: mR, marginTop: mT, marginBottom: mB,
      x: {type: 'utc', domain: [rows[0].date, last.date]},
      y: {domain: ydom, label: 'Cumulative net return, %', labelArrow: 'none'},
      marks: [gridY(c), axisY(c, {label: 'Cumulative net return, %', labelArrow: 'none', tickFormat: function (v) { return signed(v, 1); }}),
        axisX(c, {ticks: c.narrow ? 4 : 8}), zeroY(c)].concat(lines, [
        P.dot(ends, {x: function () { return last.date; }, y: 'y', r: 4, fill: function (d) { return d.color; }, stroke: c.t.paper, strokeWidth: 2}),
        P.text(ends, {x: function () { return last.date; }, y: 'ty', text: 'text', dx: 8, textAnchor: 'start', fill: c.t.ink, fontWeight: 600, fontSize: 12})])
    });
    out.nodes.forEach(function (n) { n.classList.add('plot-pane'); });
    pane.classList.add('plot-pane');
    out.nodes.push(pane);
    out.mount = function (chart) {
      addLegend(chart);
      crosshair(chart, {
        panes: [pane], rows: rows,
        dots: series.map(function (a) { return {pane: 0, y: function (r) { return r[a.key]; }, color: a.color}; }),
        items: function (r) {
          return series.map(function (a) { return {label: armTag(a) + ' ' + armInfo(a).name, color: a.color, key: a.dash ? 'dash' : '', value: pct(r[a.key]), wide: true}; });
        }
      }, c);
    };
    out.table.push(table('Cumulative net return by day, % of capital.', ['Date'].concat(series.map(function (a) { return a.label; })),
      [false].concat(series.map(function () { return true; })),
      rows.map(function (r) { return [r.iso].concat(series.map(function (a) { return pct(r[a.key], 3); })); })));
    return out;
  };

  // every statistic the evaluation reports for each arm, one column per arm
  function holdoutTable(H, alpha) {
    var A = H.arms, ma = A[0] && has(A[0].mde_alpha) ? A[0].mde_alpha : 0.025;
    var g = function (a) { return a.vs_gatev || {}; }, rp = function (a) { return a.random_pair || {}; };
    // the evaluator's only cross-arm source is its BASELINE_ARM, S1 (its run directory's name, e.g.
    // 'holdout2026_v33 run'); the paper words it the same way
    var src = function (s) { return s === 'own run' ? 'its own run' : s ? 'S1’s run' : '–'; };
    // the gap as the development period measures it: weight without price history or a usable ticker
    var gap = function (a) {
      var U = (a.universe || []).map(function (u) { return (u.missing_weight_pct || 0) + (u.unmapped_weight_pct || 0); });
      if (!U.length) return '–';
      var f = num(U[0], 2) + '%';
      return U.length === 1 ? f : f + ' to ' + num(U[U.length - 1], 2) + '% (' + U.length + ' entries)';
    };
    var R = [
      ['Hypothesis', function (a) { return (a.hypothesis || 'none') + ' (' + (a.role || '–') + ')'; }],
      ['First and last day', function (a) { return a.period && a.period.length === 2 ? a.period[0] + ' to ' + a.period[1] : '–'; }],
      ['Days', function (a) { return has(a.days) ? String(a.days) : '–'; }],
      ['Trades', function (a) { return has(a.trades) ? global.d3.format(',')(a.trades) : '–'; }],
      ['Net return, compounded', function (a) { return pct(a.ret_pct); }],
      ['Gross return (before costs), compounded', function (a) { return pct(a.gross_ret_pct); }],
      ['Sharpe ratio, net', sharpeText],
      ['95% interval (block bootstrap)', function (a) { return interval(a.lo, a.hi); }],
      ['Sharpe ratio, gross', function (a) { return signed(a.gross_sharpe, 2); }],
      ['Sharpe ratio, Lo (2002)', function (a) { return signed(a.sharpe_lo2002, 2); }],
      ['Standard error of the Sharpe ratio', function (a) { return num(a.sharpe_se, 2); }],
      ['One-sided 95% upper bound', function (a) { return signed(a.ucb, 2); }],
      ['Probabilistic Sharpe ratio', function (a) { return has(a.psr_pct) ? num(a.psr_pct, 1) + '%' : '–'; }],
      ['Newey–West t (lags)', function (a) { return num(a.t, 2) + (has(a.lags) ? ' (' + a.lags + ')' : ''); }],
      ['p, one-sided', function (a) { return pText(a.p_one_sided); }],
      ['p, Holm-adjusted', function (a, d) { return d.tested ? holmP(d.p, d.below, alpha) : 'not tested'; }],
      ['Decision', function (a, d) { return d.text; }],
      ['Minimum detectable Sharpe from the arm’s own returns, one-sided ' + num(100 * ma, 1) + '%', function (a) { return num(a.mde, 2); }],
      ['Minimum detectable Sharpe from the arm’s own returns, one test at 5%', function (a) { return num(a.mde_single, 2); }],
      ['Gross exposure, mean and maximum, % of equity', function (a) {
        var e = a.exposure || {};
        return has(e.avg_pct) && has(e.max_pct) ? num(e.avg_pct, 1) + ' and ' + num(e.max_pct, 1) : '–';
      }],
      ['Days with open positions', function (a) { return a.exposure && has(a.exposure.days_open) ? String(a.exposure.days_open) : '–'; }],
      ['Sharpe difference from the Gatev distance method (95% interval)', function (a) {
        return has(g(a).diff) ? signed(g(a).diff, 2) + ' (' + interval(g(a).lo, g(a).hi) + ')' : '–';
      }],
      ['Difference: two-sided p; common days', function (a) { return has(g(a).p) ? pText(g(a).p) + '; ' + (has(g(a).days) ? g(a).days : '–') : '–'; }],
      ['Gatev distance method’s Sharpe; from', function (a) { return signed(g(a).distance_sharpe, 2) + '; ' + src(g(a).source); }],
      ['Random pairs: percentile of the arm’s Sharpe', function (a) { return has(rp(a).percentile) ? num(rp(a).percentile, 1) : '–'; }],
      ['Random pairs: median Sharpe (draws); from', function (a) {
        var r = rp(a);
        return signed(r.median_sharpe, 2) + (has(r.n_draws) ? ' (' + r.n_draws + ')' : '') + '; ' + src(r.source) + (r.note ? ' (' + r.note + ')' : '');
      }],
      ['Survivorship gap: index weight without prices or a usable ticker, first and last entry', gap],
      ['Commit', function (a) { return hex12(a.commit); }]
    ];
    var dec = A.map(function (a) { return holdoutDecision(H, a); });
    return table('Every statistic the evaluation reports for each arm. Test: one-sided Newey–West t of the mean daily net return, Holm-adjusted across H1 and H2 at a familywise ' +
      num(100 * alpha, 0) + '%; S3 is descriptive, with no hypothesis, adjusted p-value or decision.',
      ['Statistic'].concat(A.map(armLabel)), [false].concat(A.map(function () { return true; })),
      R.map(function (r) { return [r[0]].concat(A.map(function (a, i) { return r[1](a, dec[i]); })); }));
  }

  // ── the completed holdout's text: status, key figure, hypotheses table, result, run record ──
  // Filled once, from study.holdout alone, in place of the sealed text (site.js calls it when
  // assets/study.json has loaded). While the holdout is sealed it changes nothing.
  var STEP = {universe: 'universe', data: 'data', v33: 'v33 (S1)', v32: 'v32 (S3)', residual: 'residual (S2)', evaluate: 'evaluation'};
  function stepName(s) { return STEP[s] || s; }
  function stepList(xs) { return listJoin((xs || []).map(stepName)); }
  // a paragraph from text, {code} and {href, text} parts
  function para(cls, lead, parts) {
    var p = document.createElement('p');
    p.className = cls;
    if (lead) {
      var b = document.createElement('strong');
      b.textContent = lead;
      p.appendChild(b);
      p.appendChild(document.createTextNode(' '));
    }
    parts.forEach(function (x) {
      if (x === null || x === undefined || x === '') return;
      if (typeof x === 'string') { p.appendChild(document.createTextNode(x)); return; }
      var n = document.createElement(x.href ? 'a' : 'code');
      if (x.href) n.href = x.href;
      n.textContent = x.href ? x.text : x.code;
      p.appendChild(n);
    });
    return p;
  }
  function familyOf(H) {
    return (H.family || []).map(function (k) { return H.arms.filter(function (a) { return a.key === k; })[0]; }).filter(Boolean)
      .map(function (a) { return {a: a, d: holdoutDecision(H, a)}; });
  }
  function holmOf(x, alpha) { return holmP(x.d.p, x.d.below, alpha); }
  // 'Holm p = 0.008' or 'Holm p < 0.050'; in a list, '0.008' or 'below 0.050'
  function holmIs(x, alpha) { var s = holmOf(x, alpha); return s.charAt(0) === '<' ? '< ' + s.slice(1) : '= ' + s; }
  function holmWord(x, alpha) { var s = holmOf(x, alpha); return s.charAt(0) === '<' ? 'below ' + s.slice(1) : s; }
  function stepsDone(xs) { return 'the ' + stepList(xs) + (xs.length === 1 ? ' step' : ' steps'); }

  // the key figure: S1's net Sharpe ratio, and the decision on both hypotheses in one line
  function holdoutKpi(S, H, alpha) {
    var tile = document.querySelector('.kpis .kpi.is-pending');
    if (!tile) return;
    var a = holdoutArm(S, 'v33_pairs') || H.arms[0];
    var year = String(H.calendar_start || '2026').slice(0, 4);
    var label = document.createElement('p');
    label.className = 'kpi-label';
    label.textContent = 'Holdout ' + year + ' · ' + armTag(a) + ' net Sharpe';
    var value = document.createElement('p');
    value.className = 'kpi-value' + (has(a.sharpe) ? '' : ' is-text');
    value.textContent = has(a.sharpe) ? signed(a.sharpe, 2) : a.trades === 0 ? 'No position' : 'Not defined';
    var facts = [];
    if (has(a.sharpe)) {
      if (has(a.lo) && has(a.hi)) facts.push('95% CI ' + interval(a.lo, a.hi));
      if (has(a.ucb)) facts.push('one-sided 95% bound ' + signed(a.ucb, 2));
    } else facts.push(armInfo(a).name + ': ' + flatWhy(a) + ' (t = ' + num(a.t, 2) + ', one-sided p = ' + pText(a.p_one_sided) + ')');
    facts.push('net return ' + pct(a.ret_pct));
    if (has(a.days)) facts.push(a.days + ' days');
    var fam = familyOf(H), lvl = num(100 * alpha, 0) + '%';
    var ps = ' (Holm p: ' + fam.map(function (x) { return x.a.hypothesis + ' ' + holmOf(x, alpha); }).join(', ') + ')';
    var rej = fam.filter(function (x) { return x.d.edge === true; });
    var known = fam.every(function (x) { return x.d.edge === true || x.d.edge === false; });
    var parts;
    if (!known) parts = ['Decision not available' + ps + '.'];
    else if (!rej.length) parts = ['Neither null rejected at ' + lvl + ps + '; given the power stated in advance, not evidence of a zero edge (', {href: '#holdout', text: 'Section 1'}, ').'];
    else {
      var keep = fam.filter(function (x) { return x.d.edge === false; });
      parts = [(rej.length === fam.length ? (fam.length === 2 ? 'Both nulls' : 'Every null') : listJoin(rej.map(function (x) { return x.a.hypothesis + '’s null'; }))) +
        ' rejected at ' + lvl + (keep.length ? ', ' + listJoin(keep.map(function (x) { return x.a.hypothesis + '’s'; })) + ' not' : '') + ps +
        (keep.length ? '; ' + listJoin(keep.map(function (x) { return x.a.hypothesis + '’s'; })) + ' non-rejection is not evidence of a zero edge' : '') +
        '. A sealed test, not prospective: caveats in ', {href: '#holdout', text: 'Section 1'}, '.'];
    }
    tile.classList.remove('is-pending');
    tile.replaceChildren(label, value, para('kpi-sub', null, [facts.join(' · ')]), para('kpi-sub', null, parts));
  }

  // the hypotheses table: net return, upper bound and one-sided p added after the Sharpe ratio
  function holdoutHypotheses(H, alpha) {
    var first = document.querySelector('[data-holdout$=":sharpe"]');
    var tbl = first && first.closest('table');
    if (!tbl || tbl.hasAttribute('data-holdout-filled')) return tbl;
    tbl.setAttribute('data-holdout-filled', '');
    tbl.classList.add('tbl-holdout');
    var ADD = [['ret_pct', 'Net return'], ['ucb', 'Upper bound'], ['p_one_sided', 'p (one-sided)']];
    var col = Array.prototype.indexOf.call(first.parentNode.children, first);
    var head = tbl.querySelector('thead tr');
    var hth = head ? head.children[col] : null;
    ADD.slice().reverse().forEach(function (k) {
      if (hth) {
        var th = document.createElement('th');
        th.scope = 'col';
        th.className = 'r';
        th.textContent = k[1];
        hth.after(th);
      }
      tbl.querySelectorAll('tbody [data-holdout$=":sharpe"]').forEach(function (sc) {
        var td = document.createElement('td');
        td.className = 'r';
        td.setAttribute('data-holdout', sc.getAttribute('data-holdout').split(':')[0] + ':' + k[0]);
        td.textContent = '–';
        sc.after(td);
      });
    });
    H.arms.forEach(function (a) {
      var d = holdoutDecision(H, a);
      var cells = {sharpe: sharpeText(a), ret_pct: pct(a.ret_pct), ucb: signed(a.ucb, 2), p_one_sided: pText(a.p_one_sided),
                   p_holm: d.tested ? holmP(d.p, d.below, alpha) : '–', decision: d.text};
      Object.keys(cells).forEach(function (k) {
        var td = tbl.querySelector('[data-holdout="' + a.key + ':' + k + '"]');
        if (!td) return;
        td.textContent = cells[k];
        td.classList.toggle('muted', cells[k] === '–' || cells[k] === 'not defined' || (k === 'decision' && !d.tested));
      });
    });
    var cap = tbl.querySelector('caption');
    if (cap) cap.appendChild(document.createTextNode(' Net return: compounded over the holdout’s days. Upper bound: the one-sided 95% upper confidence bound on the Sharpe ratio. Each decision is the evaluation’s own.'));
    return tbl;
  }

  // the result in words: the decision, and the caveats that go with a rejection or its absence
  function holdoutResult(S, H, alpha) {
    var fam = familyOf(H), lvl = 'the familywise ' + num(100 * alpha, 0) + '% level';
    var rej = fam.filter(function (x) { return x.d.edge === true; }), keep = fam.filter(function (x) { return x.d.edge === false; });
    var name = function (x) { return x.a.hypothesis + ' (' + armTag(x.a) + ', ' + armInfo(x.a).name + ')'; };
    var pFor = function (xs) { return listJoin(xs.map(function (x) { return holmWord(x, alpha) + ' for ' + name(x); })); };
    var pOf = function (xs) { return xs.length === 1 ? 'Holm p ' + holmIs(xs[0], alpha) : 'Holm p ' + listJoin(xs.map(function (x) { return holmWord(x, alpha); })); };
    var days = fam.length && has(fam[0].a.days) ? fam[0].a.days : null;
    var out = [];
    if (rej.length + keep.length < fam.length || !fam.length) {
      out.push('The decision is not available in assets/study.json.');
    } else if (!rej.length) {
      out.push((fam.length === 2 ? 'Neither null is' : 'No null is') + ' rejected at ' + lvl + ': Holm p is ' + pFor(fam) + '.');
    } else if (!keep.length) {
      out.push((fam.length === 2 ? 'Both nulls are' : 'Every null is') + ' rejected at ' + lvl + ': Holm p is ' + pFor(fam) + '.');
    } else {
      out.push('The null of ' + listJoin(rej.map(name)) + ' is rejected at ' + lvl + ' (' + pOf(rej) + '); that of ' + listJoin(keep.map(name)) + ' is not (' + pOf(keep) + ').');
    }
    var f = S.dev && S.dev.facts ? S.dev.facts : {};
    if (rej.length) {
      // the caveats the paper and the pre-registration attach to a rejection, power among them
      // (stated here in full unless the non-rejection below states it)
      out.push('A rejection is evidence, at that level, that the arm’s mean daily net return over ' + (days ? 'these ' + days + ' days' : 'the holdout') +
        ' was above zero under the engine’s fills and modelled costs; it does not show how large the edge is, that it lasted beyond the period, that it survives higher costs or a larger book, or that it holds in another period' +
        (keep.length ? ', and it says nothing about the other arm' : '') + '. The test is sealed, not prospective: the period had ended before the protocol was filed and the project was developed during it, and the inputs dated 2026 may flatter it (Section 11). ' +
        (rej.length === 1 && fam.length === 2 ? 'It is one test of two' : 'They are ' + (fam.length === 2 ? 'two' : fam.length) + ' tests') +
        ' over a single period of about ten months, at a simulated size a little above the nominal level, with the power stated in advance' +
        (!keep.length && has(f.ho_mde_025) ? ' (below: 80% only against a Sharpe ratio of about ' + num(f.ho_mde_025, 2) + ')' : '') + '.');
    }
    if (keep.length) {
      var ub = keep.filter(function (x) { return has(x.a.ucb); }), noUb = keep.filter(function (x) { return !has(x.a.ucb); });
      var mdes = keep.filter(function (x) { return has(x.a.mde); });
      out.push('Not rejecting a null is not evidence that the edge is zero: with the power stated in advance from S1’s development returns (below)' +
        (has(f.ho_mde_025) ? ', the test detects with 80% probability only a Sharpe ratio of about ' + num(f.ho_mde_025, 2) +
          (has(f.ho_power_1) ? ' (its power against a Sharpe ratio of 1 is ' + num(f.ho_power_1, 0) + '%)' : '') +
          (mdes.length ? ', and, from each arm’s own ' + String(H.calendar_start || '2026').slice(0, 4) + ' returns, about ' +
            listJoin(mdes.map(function (x) { return num(x.a.mde, 2) + ' for ' + armTag(x.a); })) : '') : '') + '.' +
        (ub.length ? ' The one-sided 95% upper bound on the Sharpe ratio is ' + listJoin(ub.map(function (x) { return signed(x.a.ucb, 2) + ' for ' + armTag(x.a); })) +
          (noUb.length ? '; ' + listJoin(noUb.map(function (x) { return armTag(x.a); })) + (noUb.length > 1 ? ' have' : ' has') + ' none' : '') + '.' : ''));
    }
    H.arms.filter(function (a) { return a.flat; }).forEach(function (a) {
      out.push(armTag(a) + ' ' + (a.trades === 0 ? 'opened no position' : 'has daily returns without variation') + ': its net return is ' + pct(a.ret_pct) +
        ' and its Sharpe ratio is not defined' + (a.hypothesis ? '; the registered test gives it t = ' + num(a.t, 2) + ' and p = ' + pText(a.p_one_sided) : '') + '.');
    });
    var desc = H.arms.filter(function (a) { return a.role === 'descriptive' || !a.hypothesis; });
    if (desc.length) out.push(listJoin(desc.map(armTag)) + (desc.length > 1 ? ' are reported without a test and enter' : ' is reported without a test and enters') + ' no decision.');
    return para('note ho-note ho-result', 'Result.', [out.join(' ')]);
  }

  // the run record: commits, tree, dates, attempts and failures, crash fix, logs, registry
  function holdoutRun(H) {
    var P = H.provenance;
    if (!P) return para('note ho-note', 'Run record.', ['No run record is published with this evaluation.']);
    var out = [], keys = H.arms.map(function (a) { return a.key; });
    var rc = P.run_commits || {}, ru = P.run_utc || {};
    var commits = keys.map(function (k) { return rc[k]; });
    var same = commits.every(function (h) { return h && h === commits[0]; });
    var reg = P.registered_commit || (P.registry && P.registry.prereg_commit);
    if (same) {
      out.push(listJoin(H.arms.map(armTag)) + ' ran from commit ', {code: hex12(commits[0])});
      if (P.at_registered_commit === true) out.push(', the registered commit,');
      else if (reg && P.crash_fix) out.push(', not the registered commit ', {code: hex12(reg)}, ' but a crash-fix commit,');
      else if (reg) out.push(', a commit later than the registered ', {code: hex12(reg)}, ',');
    } else {
      out.push('The arms ran from different commits: ');
      H.arms.forEach(function (a, i) { out.push((i ? (i === H.arms.length - 1 ? ' and ' : ', ') : '') + armTag(a) + ' from ', {code: hex12(rc[a.key])}); });
      if (reg) out.push(' (the registered commit is ', {code: hex12(reg)}, ')');
      out.push('. They ran');
    }
    out.push(P.clean === true ? ' with a clean tree' : P.clean === false ? ' with uncommitted changes' : '');
    var dates = keys.map(function (k) { return ru[k] ? String(ru[k]).slice(0, 10) : null; }).filter(Boolean).sort();
    if (dates.length) out.push(dates[0] === dates[dates.length - 1] ? ', on ' + dayOf(dates[0]) : ', between ' + dayOf(dates[0]) + ' and ' + dayOf(dates[dates.length - 1]));
    out.push('. ');
    // a later commit without a crash fix: the runbook allows it only when the frozen code is unchanged
    if (same && P.at_registered_commit !== true && reg && !P.crash_fix) {
      out.push('The runbook starts at a later commit without a crash fix only if nothing under the frozen paths differs from the registered commit (commitment 2 of the pre-registration). ');
    }
    if (H.period_matches_calendar === false && H.arms[0].period) {
      out.push('Their days run from ' + H.arms[0].period[0] + ' to ' + H.arms[0].period[1] + ', not over the whole calendar (' + (H.calendar_start || '–') + ' to ' + (H.calendar_end || '–') + '). ');
    }
    // every attempt, as the attempt record has it: an earlier one failed (its failure line) or
    // stopped without recording a failure; the last registered the trial, and its completion
    // line follows unless the runbook stopped in between
    var A = P.attempts || [];
    var n = has(P.n_attempts) ? P.n_attempts : A.length;
    var nf = has(P.n_failed) ? P.n_failed : A.filter(function (t) { return t.failed; }).length;
    var nu = has(P.n_unfinished) ? P.n_unfinished : A.slice(0, -1).filter(function (t) { return !t.failed; }).length;
    var sa = P.step_attempts || {};
    var R = P.registry || {};
    var ending = function (t) {
      return t.completed_utc ? ' and completed on ' + dayOf(t.completed_utc) :
        ' and registered the trial' + (R.registered_utc ? ' on ' + dayOf(R.registered_utc) : '') + ' (no completion line follows in results/trial_attempts.jsonl)';
    };
    if (A.length === 1 && !nf) {
      out.push('It took one attempt, which ran ' + stepsDone(A[0].steps_done || []) + ending(A[0]) + '. ');
    } else if (A.length) {
      var ends = (nf ? [(nf === 1 ? 'one' : nf) + ' failed'] : []).concat(nu ? [(nu === 1 ? 'one' : nu) + ' stopped without finishing or recording a failure'] : [])
        .concat([A[A.length - 1].completed_utc ? 'the last completed' : 'the last registered the trial']);
      out.push('It took ' + word(n) + ' attempts (' + listJoin(ends) + '): ');
      A.forEach(function (t, i) {
        var done = t.steps_done || [], last = i === A.length - 1;
        out.push((i ? '; ' : '') + 'attempt ' + t.attempt + ' at ', {code: hex12(t.head)},
          t.at_registered_commit ? ' (the registered commit)' : t.crash_fix ? ' (a crash-fix commit)' : ' (a later commit; no crash-fix note)',
          ', started ' + dayOf(t.started_utc));
        if (t.failed) {
          out.push(', failed at the ' + stepName(t.failed.step) + ' step' + (t.failed.note ? ' (' + t.failed.note + ')' : '') +
            (done.length ? ' after completing ' + stepsDone(done) : ' before completing a step'));
        } else if (last) {
          // the steps an earlier attempt at the same commit finished, by that attempt
          var by = {};
          Object.keys(STEP).concat(Object.keys(sa).filter(function (s) { return !STEP[s]; }))
            .filter(function (s) { return has(sa[s]) && sa[s] !== t.attempt; })
            .forEach(function (s) { (by[sa[s]] = by[sa[s]] || []).push(s); });
          var reused = Object.keys(by).sort(function (x, y) { return x - y; });
          out.push(', ran ' + (done.length ? stepsDone(done) : 'no step') +
            (reused.length ? ', reusing ' + listJoin(reused.map(function (k) { return stepsDone(by[k]) + ' of attempt ' + k; })) + ',' : '') + ending(t));
        } else out.push(', stopped without finishing or recording a failure' + (done.length ? ' after completing ' + stepsDone(done) : ''));
      });
      out.push('. ');
    }
    var diffs = P.crash_fix_diffs || [];
    if (P.crash_fix) {
      var cf = P.crash_fix, dd = diffs.filter(function (d) { return d.sha256 === cf.sha256; })[0];
      out.push('Crash fix: “' + (cf.fix || '') + '”. Its diff of the frozen paths since the registered commit is ', {code: 'logs/' + cf.diff},
        ' (sha256 ', {code: String(cf.sha256 || '–')}, ')');
      if (dd && dd.files && dd.files.length) {
        out.push('; it changes ');
        dd.files.forEach(function (f, i) { out.push(i ? (i === dd.files.length - 1 ? ' and ' : ', ') : '', {code: f}); });
        if (has(dd.insertions) && has(dd.deletions)) out.push(' (' + plural(dd.insertions, 'line', 'lines') + ' added, ' + dd.deletions + ' removed)');
      }
      out.push('. ');
    } else if (!A.some(function (t) { return t.crash_fix; })) out.push('No attempt carries a crash fix. ');
    diffs.filter(function (d) { return !d.attempts || !d.attempts.length; }).forEach(function (d) {
      out.push('The diff ', {code: d.file}, ' is published but named by no attempt (the runbook writes it before its other start checks, so a refused start can leave one). ');
    });
    var L = P.logs;
    if (L && has(L.count)) {
      var kinds = [];
      if (L.step_logs > 0) kinds.push(plural(L.step_logs, 'step log', 'step logs'));
      if (L.environment > 0) kinds.push(plural(L.environment, 'environment listing', 'environment listings'));
      if (L.diffs > 0) kinds.push(plural(L.diffs, 'diff', 'diffs'));
      out.push('Every attempt’s logs are published: ' + plural(L.count, 'file', 'files') + ' in ', {code: 'results/' + (H.trial || 'holdout2026') + '/logs/'},
        kinds.length ? ' (' + listJoin(kinds) + '). ' : '. ');
    }
    if (P.registry) {
      out.push('The trial is registered as ', {code: R.name || H.trial || 'holdout2026'}, ' in ', {code: 'results/trial_registry.jsonl'},
        ' on ' + dayOf(R.registered_utc) + ', with pre-registration commit ', {code: hex12(R.prereg_commit)});
      // the registry line copies the attempt lines written before registration; the runbook then
      // appends the completion line, so the attempt file holds one more line for the trial
      if (has(R.attempt_lines)) {
        var lines = P.attempt_record_lines;
        out.push('; its line copies the ' + R.attempt_lines + ' attempt lines written before registration' +
          (has(lines) && lines === R.attempt_lines + 1 ? ', and ' : has(lines) && lines === R.attempt_lines ? '; ' : '. '), {code: 'results/trial_attempts.jsonl'},
          has(lines) && lines === R.attempt_lines + 1 ? ' holds them and the completion line, ' + lines + ' lines for the trial' :
          has(lines) && lines === R.attempt_lines ? ' holds the same ' + lines + ' lines and no completion line' : ' holds the trial’s lines');
      }
      out.push('.');
    }
    return para('note ho-note', 'Run record.', out);
  }

  // ── the sealed-tense text of index.html, and its wording once the holdout is evaluated ──
  // On a page published while the test is sealed, each sentence that is true only while it is
  // sealed is replaced here, worded as main.typ's `done` branches word it; a page published after
  // the test (data-holdout="complete") carries the `done` wording itself and is left alone.
  // Strict JSON between the markers (tests/test_build_site_data.py reads it): `sealed` occurs
  // `count` times (default once) in index.html, each time inside an element `in` selects; `attr`
  // names an attribute instead of the text; `cut` drops everything after the sealed text to the
  // element's end; `done` is text, or parts (text, {href, text}); '{name}' is filled from
  // holdoutWords().
  /* holdout-text-begin */
  var HOLDOUT_TEXT = [
    {"in": "meta[name=\"description\"]", "attr": "content", "sealed": "A pre-registered test on 2026 data is sealed.",
     "done": "A pre-registered test on 2026 data (sealed, not prospective) has been run: {short}."},
    {"in": "meta[property=\"og:description\"]", "attr": "content", "sealed": "A pre-registered 2026 test is sealed.",
     "done": "A pre-registered 2026 test (sealed, not prospective) has been run: {short}."},
    {"in": "script[type=\"application/ld+json\"]", "sealed": "a pre-registered test on 2026 data is sealed.",
     "done": "a pre-registered test on 2026 data (sealed, not prospective) has been run: {short}."},
    {"in": "p.dek", "sealed": " and runs once.",
     "done": [" and has since been run and evaluated (", {"href": "#holdout", "text": "Section 1"}, ")."]},
    {"in": ".bottom-line p", "sealed": "The pre-registered falsification test on 2026 data, which has ", "cut": true,
     "done": ["{outcome} (", {"href": "#holdout", "text": "Section 1"}, ")."]},
    {"in": "#holdout .lede", "sealed": "The pre-registered confirmatory test runs on daily prices that no part of the code or its caches has held: those of the ",
     "done": "The pre-registered confirmatory test ran on daily prices that no part of the code or its caches had held before it: those of the "},
    {"in": "#holdout .lede", "sealed": "That period has already ended, and the project",
     "done": "That period had ended before the filing, and the project"},
    {"in": "#holdout .lede", "sealed": "was fetched into the project's code, caches or files (network",
     "done": "was fetched into the project's code, caches or files before the filing (network"},
    {"in": "#holdout .lede", "sealed": "and the fetch code refuses such a request until the registered commit unseals it;",
     "done": "and from commit a1c76db of 20 October 2026, five hours after the 2026 calendar was added to the code, the fetch code refused such a request until the registered commit unsealed it;"},
    {"in": "#holdout .lede", "sealed": "The protocol was filed first, on 26 October 2026; each arm then runs once, and its result is published whatever it is.",
     "done": "The protocol was filed first, on 26 October 2026; the runbook then ran the three arms and the evaluation, every attempt is on record (run record, below), and the result is published in full, as the protocol requires."},
    {"in": "#holdout p.note", "sealed": "The power is stated in advance, from no return dated after 31 December 2025.",
     "done": "The power was stated in advance, from no return dated after 31 December 2025."},
    {"in": "#holdout p.note", "sealed": "and not rejecting the null will not show that the edge is zero",
     "done": "and not rejecting the null does not show that the edge is zero"},
    {"in": "#holdout p.note", "sealed": "so the three arms are frozen together and each runs once.",
     "done": "so the three arms were frozen together and ran under one runbook (run record, above)."},
    {"in": "caption", "sealed": "The holdout will be added as one trial.",
     "done": "The holdout is the trial holdout2026, one row for each of its {runs} runs."},
    {"in": ".ex-title", "sealed": "main backtest and the sealed holdout", "done": "main backtest and the holdout"},
    {"in": "svg desc", "sealed": "the sealed holdout from January to October 2026.", "count": 2,
     "done": "the holdout from January to October 2026, pre-registered, then run and evaluated."},
    {"in": "svg text", "sealed": "pre-registered, sealed", "count": 2, "done": "pre-registered, then run and evaluated"},
    {"in": "td", "sealed": "The code and caches hold no daily 2026 prices of the traded securities",
     "done": "Before the filing the code and caches held no daily 2026 prices of the traded securities"},
    {"in": "td", "sealed": "designs, test and decision rule frozen before any 2026 daily price is fetched; one run per arm, every attempt on record",
     "done": ["designs, test and decision rule frozen before any 2026 daily price history was fetched into the project; every attempt on record (", {"href": "#holdout", "text": "Section 1"}, ")"]},
    {"in": "td", "sealed": "the trial registry and the sealed 2026 holdout.",
     "done": ["the trial registry and the 2026 holdout, pre-registered and evaluated (", {"href": "#holdout", "text": "Section 1"}, ")."]}
  ];
  /* holdout-text-end */

  var WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
  function word(n) { return n >= 0 && n < WORDS.length ? WORDS[n] : String(n); }

  // the decision in words, from the evaluation's own decision only, as the paper words it: its
  // summary pill (verdict), its summary's last sentence (outcome) and a short form (short)
  function holdoutOutcome(H) {
    var fam = familyOf(H);
    var edge = function (k) { return fam.filter(function (x) { return x.a.key === k; }).map(function (x) { return x.d.edge; })[0]; };
    var e1 = edge('v33_pairs'), e2 = edge('avellaneda_lee');
    var lead = 'In the 2026 test (pre-registered, sealed, not prospective; power stated in advance) ';
    if (typeof e1 !== 'boolean' || typeof e2 !== 'boolean') {
      return {verdict: null, outcome: 'The decision of the 2026 test is not available in assets/study.json', short: 'its decision is not available'};
    }
    if (e1 && e2) {
      return {verdict: '2026 test: edge in S1 and S2', short: 'both tested arms show an edge out of sample, on inputs that may flatter it',
        outcome: lead + 'both tested arms show an edge out of sample, over a short period and on inputs that may flatter it'};
    }
    if (e1 || e2) {
      var yes = e1 ? 'the v33 design' : 'Avellaneda–Lee', no = e1 ? 'Avellaneda–Lee' : 'the v33 design';
      return {verdict: '2026 test: edge in ' + (e1 ? 'S1, not S2' : 'S2, not S1'),
        short: yes + ' shows an edge out of sample and ' + no + ' does not, which is not evidence that its edge is zero',
        outcome: lead + yes + ' shows an edge out of sample and ' + no + ' does not, which is not evidence that its edge is zero: one test of two, on inputs that may flatter it'};
    }
    return {verdict: 'No detectable edge', short: 'neither tested arm shows an edge out of sample, which is not evidence that the edge is zero',
      outcome: 'In the 2026 test (pre-registered, sealed, not prospective) neither tested arm shows an edge, which, given the power stated in advance, is not evidence that the edge is zero'};
  }
  function holdoutWords(S, H) {
    var o = holdoutOutcome(H);
    var runs = (S.trials || []).filter(function (t) { return t.name === (H.trial || 'holdout2026'); }).length;
    return {outcome: o.outcome, short: o.short, verdict: o.verdict, runs: word(runs)};
  }
  function partNodes(parts) {
    return parts.filter(function (x) { return x !== null && x !== undefined && x !== ''; }).map(function (x) {
      if (typeof x === 'string') return document.createTextNode(x);
      var n = document.createElement(x.href ? 'a' : 'code');
      if (x.href) n.href = x.href;
      n.textContent = x.href ? x.text : x.code;
      return n;
    });
  }
  // replaces every sealed text of HOLDOUT_TEXT; returns the sealed texts not found as often as listed
  function holdoutText(words) {
    var missing = [];
    var fill = function (t) { return t.replace(/\{(\w+)\}/g, function (m, k) { return words[k] !== undefined && words[k] !== null ? words[k] : m; }); };
    HOLDOUT_TEXT.forEach(function (e) {
      var parts = (Array.isArray(e.done) ? e.done : [e.done]).map(function (x) { return typeof x === 'string' ? fill(x) : x; });
      var hit = 0;
      document.querySelectorAll(e['in']).forEach(function (el) {
        if (e.attr) {
          var v = el.getAttribute(e.attr);
          if (v && v.indexOf(e.sealed) >= 0) {
            el.setAttribute(e.attr, v.replace(e.sealed, parts.map(function (x) { return typeof x === 'string' ? x : x.text || x.code; }).join('')));
            hit++;
          }
          return;
        }
        var walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), node;
        while ((node = walk.nextNode())) {
          var at = node.nodeValue.indexOf(e.sealed);
          if (at < 0) continue;
          var rest = e.cut ? '' : node.nodeValue.slice(at + e.sealed.length);
          if (e.cut) {
            for (var up = node; up && up !== el; up = up.parentNode) {
              while (up.nextSibling) up.parentNode.removeChild(up.nextSibling);
            }
          }
          var after = node.splitText(at);
          after.nodeValue = rest;
          partNodes(parts).forEach(function (x) { after.parentNode.insertBefore(x, after); });
          if (!rest) after.parentNode.removeChild(after);
          hit++;
          break;
        }
      });
      if (hit !== (e.count || 1)) missing.push(e.sealed);
    });
    missing.forEach(function (t) { console.error('The holdout text was not replaced: ' + t); });
    return missing;
  }

  // the trial registry table: one row per run record of the holdout's trial, as the paper's
  // trials table prints them; its counts are study.json's (the registry gains the trial)
  function holdoutTrials(S, H) {
    var cell = document.querySelector('[data-metric="study.registry.trials"]');
    var tbody = cell && cell.closest('table') ? cell.closest('table').querySelector('tbody') : null;
    var name = H.trial || 'holdout2026';
    if (tbody) {
      var what = {v33: 'v33', v32: 'v32', avellaneda_lee: 'Avellaneda–Lee'};
      var role = {v33: 'the pre-registered 2026 test, S1', v32: 'the same, v32 design (S3, descriptive)', avellaneda_lee: 'the same, Avellaneda–Lee (S2)'};
      (S.trials || []).filter(function (t) { return t.name === name; }).forEach(function (t) {
        var tr = document.createElement('tr');
        var th = document.createElement('th');
        th.scope = 'row';
        var muted = document.createElement('span');
        muted.className = 'muted';
        muted.textContent = role[t.profile] || 'the pre-registered 2026 test';
        th.append(document.createTextNode(t.name), document.createElement('br'), muted);
        var cal = String(t.calendar || '').replace('rehearsal2025', '2025').replace('holdout2026', '2026');
        var commit = document.createElement('code');
        commit.textContent = t.commit || '—';
        var tds = [[(what[t.profile] || t.profile || '—') + ' · ' + cal, ''], [commit, ''], [has(t.sharpe) ? signed(t.sharpe, 2) : '—', 'r'],
          [has(t.ret_pct) ? pct(t.ret_pct) : '—', 'r'], [has(t.trades) ? global.d3.format(',')(t.trades) : '—', 'r'], ['—', 'r muted']];
        tr.appendChild(th);
        tds.forEach(function (c) {
          var td = document.createElement('td');
          if (c[1]) td.className = c[1];
          if (typeof c[0] === 'string') td.textContent = c[0]; else td.appendChild(c[0]);
          if (t.dirty && c[0] === commit) td.appendChild(document.createTextNode('*'));
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }
    var R = S.registry || {};
    document.querySelectorAll('[data-metric^="study.registry."]').forEach(function (el) {
      var v = R[el.getAttribute('data-metric').slice('study.registry.'.length)];
      if (has(v)) el.textContent = global.d3.format(',')(v);
    });
  }

  // the threats table gains the row the paper adds once the test has run
  function holdoutThreat(S, H) {
    var th = Array.prototype.filter.call(document.querySelectorAll('tr > th[scope="row"]'), function (x) {
      return x.textContent === 'The 2026 test is sealed, not prospective';
    })[0];
    if (!th) return;
    var f = S.dev && S.dev.facts ? S.dev.facts : {}, days = H.arms[0] && has(H.arms[0].days) ? H.arms[0].days : null;
    var tr = document.createElement('tr');
    var head = document.createElement('th');
    head.scope = 'row';
    head.textContent = 'The 2026 test is short, and tests two arms';
    var dir = document.createElement('span');
    dir.className = 'dir dir-flat';
    dir.textContent = 'either way';
    var cells = [[dir], [(days ? days + ' trading days: with' : 'With') + ' returns shaped like S1’s development returns, 80% power only against an annual Sharpe ratio of about ' +
      num(f.ho_mde_025, 2) + ' at Holm\'s first step, stated in advance; the Newey–West test is asymptotic, and its size at this length is a little above 5% (simulated in the pre-registration); an edge in one arm says nothing about the other'],
      ['Power and size stated in advance, from no return dated after 31 December 2025; each arm\'s one-sided upper bound and minimum detectable Sharpe ratio reported (', {href: '#holdout', text: 'Section 1'}, '); Holm\'s correction across the two tested arms']];
    tr.appendChild(head);
    cells.forEach(function (parts) {
      var td = document.createElement('td');
      parts.forEach(function (x) { td.appendChild(x.nodeType ? x : partNodes([x])[0]); });
      tr.appendChild(td);
    });
    th.parentNode.after(tr);
  }

  function holdoutPage(S) {
    var H = holdoutDone(S);
    // a page published after the test carries its wording, key figure, table, result, run record,
    // trial rows and threat itself (data-holdout="complete"): only the drawn parts are added here
    var written = document.documentElement.getAttribute('data-holdout') === 'complete';
    if (!H || (!written && document.querySelector('.ho-note'))) return false;
    var alpha = holdoutAlpha(H);
    var words = holdoutWords(S, H);
    if (!written) holdoutText(words);
    var verdict = document.querySelector('.findings-head .verdict');
    if (verdict && words.verdict) {
      verdict.textContent = words.verdict;
      verdict.parentElement.classList.add('is-result');
    }
    var pill = document.querySelector('#h-holdout .status-pill');
    if (pill) pill.replaceChildren(document.createTextNode('Complete'));
    var flag = document.querySelector('.toc a[href="#holdout"] .toc-flag');
    if (flag) {
      var vh = document.createElement('span');
      vh.className = 'vh';
      vh.textContent = '(complete)';
      flag.replaceChildren(vh);
    }
    holdoutKpi(S, H, alpha);
    var tbl = holdoutHypotheses(H, alpha);
    var wrap = tbl && tbl.closest('.tbl-wrap');
    if (wrap && !written) wrap.after(holdoutResult(S, H, alpha), holdoutRun(H));
    var sub = document.querySelector('figure[data-exhibit="holdout"] .ex-sub');
    var a0 = H.arms[0];
    if (sub && a0.period && a0.period.length === 2) {
      sub.textContent = 'Annualised, with 95% block-bootstrap intervals and one-sided 95% upper bounds' + (H.daily ? ', and the cumulative net return by day' : '') + ': ' +
        (has(a0.days) ? a0.days + ' ' : '') + 'daily net returns from ' + dayOf(a0.period[0]) + ' to ' + dayOf(a0.period[1]) +
        ', the same trading-cost model for every arm (S3 keeps v32’s borrow fee and prime-broker spread); S3, descriptive, hollow and dashed';
    }
    if (!written) {
      holdoutTrials(S, H);
      holdoutThreat(S, H);
    }
    document.querySelectorAll('rect.tl-hold').forEach(function (r) { r.classList.add('is-done'); });
    return true;
  }

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
    var node = intervalPlot(c, rows.map(function (r) { return Object.assign({}, r, {label: r.k, est: r.m}); }), {
      domain: domainPad(rows.map(function (r) { return r.lo; }).concat(rows.map(function (r) { return r.hi; })), 0.1, [0]),
      label: 'Gross bp per trade', ticks: c.narrow ? 5 : 10, tickFormat: function (v) { return signed(v, 0); }, dp: 1, values: true, valueHead: 'bp [95% interval]',
      title: function (r) { return r.label + '\n' + signed(r.m, 1) + ' bp, 95% interval ' + signed(r.lo, 1) + ' to ' + signed(r.hi, 1) + ' (±1.96 standard errors)'; }
    });
    return {nodes: [node], label: 'Dot plot of gross basis points per trade on synthetic markets with 95% intervals.',
      table: table('Known-answer checks (' + V.seeds + ' markets per scenario; all pass: ' + (V.all_pass ? 'yes' : 'no') + ').', ['Check', 'Result'], [false, false],
        Object.keys(cells).map(function (k) { return [k.replace('_', ' '), cells[k]]; }))};
  };

  // ── data tables (shared by site.js) ───────────────────────────────────────
  function buildTable(spec) {
    if (Array.isArray(spec)) {                // several tables under one disclosure
      var box = document.createElement('div');
      box.className = 'ex-tables';
      spec.forEach(function (one) { box.appendChild(buildTable(one)); });
      return box;
    }
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

  // ── tooltips stay inside the chart ────────────────────────────────────────
  // Plot keeps a tip inside its own frame, but near an edge of a narrow chart a tip can still run
  // past it. After every pointer event each tip shown is shifted back inside the chart's width.
  function clampTips(chart) {
    var cb = chart.getBoundingClientRect();
    chart.querySelectorAll('svg g[aria-label="tip"] > g').forEach(function (t) {
      var m = /translate\(([-\d.e]+),\s*([-\d.e]+)\)/.exec(t.getAttribute('transform') || '');
      var b = t.getBoundingClientRect();
      if (!m || !b.width) return;
      var svg = t.ownerSVGElement;
      var k = svg.getBoundingClientRect().width / (Number(svg.getAttribute('width')) || 1) || 1;
      var dx = b.left < cb.left + 2 ? cb.left + 2 - b.left : b.right > cb.right - 2 ? cb.right - 2 - b.right : 0;
      if (dx) t.setAttribute('transform', 'translate(' + (Number(m[1]) + dx / k) + ',' + m[2] + ')');
    });
  }
  function watchTips(chart) {
    if (chart.tipClamp) return;
    var frame = null;
    chart.tipClamp = function () {
      if (frame === null) frame = requestAnimationFrame(function () { frame = null; clampTips(chart); });
    };
    ['pointermove', 'pointerdown', 'pointerup'].forEach(function (e) { chart.addEventListener(e, chart.tipClamp, {passive: true}); });
  }

  // ── exhibit tools: a link to the exhibit, and the chart as SVG or PNG ─────
  // A row in the exhibit's foot, added once the chart is drawn (window.ExhibitTools.attach(fig);
  // without JavaScript and in print it does not exist or is hidden). The SVG is the chart drawn
  // again in the light palette, with the exhibit's label, title and subtitle above it and its
  // Source line, 'Hypothetical backtest' and the exhibit's address below; the PNG is that SVG
  // at twice the size. IBM Plex Sans is embedded, read from this site's own font files.
  var lastStudy = null;
  document.addEventListener('study:ready', function (e) { if (e.detail) lastStudy = e.detail; });
  var FONT_FILES = {400: 'IBMPlexSans-Regular', 600: 'IBMPlexSans-SemiBold'};
  var fontCache = {};
  function fontData(w) {
    if (!fontCache[w]) {
      fontCache[w] = fetch('assets/fonts/' + FONT_FILES[w] + '.woff2', {credentials: 'same-origin'})
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
        .then(function (buf) {
          var b = new Uint8Array(buf), s = '';
          for (var i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
          return 'data:font/woff2;base64,' + global.btoa(s);
        })
        .catch(function () { return null; });     // the export then names the font without embedding it
    }
    return fontCache[w];
  }
  function readTokens() {
    var cs = global.getComputedStyle(document.documentElement);
    var v = function (n) { return cs.getPropertyValue(n).trim(); };
    return {ink: v('--ink'), ink2: v('--ink-2'), ink3: v('--ink-3'), paper: v('--paper'), surface: v('--surface'), rule2: v('--rule-2'),
      grid: v('--grid'), axis: v('--axis'), s1: v('--series-1'), s2: v('--series-2'), s3: v('--series-3'), neutral: v('--neutral-series'),
      ref: v('--ref-series') || v('--neutral-series'), pos: v('--pos'), neg: v('--neg'), mid: v('--div-mid'),
      ord1: v('--ord-1'), ord2: v('--ord-2'), ord3: v('--ord-3'), ord4: v('--ord-4'), accent: v('--accent')};
  }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  // words of a text broken into lines no wider than width (px) in the chart font
  function wrap(text, width, size, weight) {
    var words = String(text).replace(/\s+/g, ' ').trim().split(' '), lines = [], cur = '';
    words.forEach(function (w) {
      var next = cur ? cur + ' ' + w : w;
      if (cur && textWidth(next, size, weight) > width) { lines.push(cur); cur = w; } else cur = next;
    });
    if (cur) lines.push(cur);
    return lines;
  }
  function textBlock(lines, x, y, size, weight, fill, lineHeight, extra) {
    return lines.map(function (l, i) {
      return '<text x="' + x + '" y="' + (y + size * 0.8 + i * size * lineHeight).toFixed(1) + '" font-size="' + size + '" font-weight="' + weight +
        '" fill="' + fill + '"' + (extra || '') + '>' + esc(l) + '</text>';
    }).join('');
  }
  // the legend as site.js builds it (assets/site.js legend())
  function legendNode(items) {
    var el = document.createElement('div');
    el.className = 'ex-legend';
    (items || []).forEach(function (it) {
      var span = document.createElement('span');
      span.className = 'lg';
      if (it.kind !== 'none') {
        var key = document.createElement('span');
        key.className = 'lg-key ' + it.kind;
        key.style.color = 'var(' + it.color + ')';
        if (it.kind !== 'line' && it.kind !== 'rule') key.style.background = 'var(' + it.color + ')';
        span.appendChild(key);
      }
      span.appendChild(document.createTextNode(it.label));
      el.appendChild(span);
    });
    return el;
  }
  // a legend key drawn in SVG from its classes (the .lg-key rules of the stylesheet)
  function keySVG(el, x, y, w, h, color, paper) {
    var cl = el.classList, cx = x + w / 2, cy = y + h / 2, dash = cl.contains('dash') ? ' stroke-dasharray="4,3"' : '';
    var marker = function (r) {
      if (cl.contains('mk-sq')) return '<rect x="' + (cx - r) + '" y="' + (cy - r) + '" width="' + 2 * r + '" height="' + 2 * r + '" rx="1" fill="' + color + '"/>';
      if (cl.contains('mk-ring')) return '<circle cx="' + cx + '" cy="' + cy + '" r="' + (r - 1) + '" fill="' + paper + '" stroke="' + color + '" stroke-width="2"/>';
      return '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + color + '"/>';
    };
    if (cl.contains('mk')) return '<line x1="' + x + '" x2="' + (x + w) + '" y1="' + cy + '" y2="' + cy + '" stroke="' + color + '" stroke-width="2"' + dash + '/>' + marker(4);
    if (cl.contains('rule')) return '<line x1="' + cx + '" x2="' + cx + '" y1="' + (cy - 6) + '" y2="' + (cy + 6) + '" stroke="' + color + '" stroke-width="2"' + dash + '/>';
    if (cl.contains('line')) return '<line x1="' + x + '" x2="' + (x + 16) + '" y1="' + cy + '" y2="' + cy + '" stroke="' + color + '" stroke-width="2"' + dash + '/>';
    var op = global.getComputedStyle(el).opacity;
    if (cl.contains('band')) return '<rect x="' + x + '" y="' + (cy - 5) + '" width="16" height="10" fill="' + color + '" opacity="' + op + '"/>';
    if (cl.contains('box')) return '<rect x="' + (cx - 5) + '" y="' + (cy - 5) + '" width="10" height="10" rx="2" fill="' + color + '" opacity="' + op + '"/>';
    var ring = cl.contains('ring');
    var paint = ring ? 'fill="' + paper + '" stroke="' + color + '" stroke-width="2"' : 'fill="' + color + '"';
    if (cl.contains('sq')) return '<rect x="' + (cx - 4.5) + '" y="' + (cy - 4.5) + '" width="9" height="9" rx="1" ' + paint + '/>';
    if (cl.contains('dia')) return '<rect x="' + (cx - 3.6) + '" y="' + (cy - 3.6) + '" width="7.2" height="7.2" transform="rotate(45 ' + cx + ' ' + cy + ')" ' + paint + '/>';
    if (cl.contains('tri')) return '<path d="M' + cx + ',' + (cy - 4.5) + 'L' + (cx + 5) + ',' + (cy + 4) + 'L' + (cx - 5) + ',' + (cy + 4) + 'Z" ' + paint + '/>';
    return '<circle cx="' + cx + '" cy="' + cy + '" r="' + (ring ? 3.5 : 4.5) + '" ' + paint + '/>';
  }
  function exhibitURL(fig) {
    var canon = document.querySelector('link[rel="canonical"]');
    var base = canon && canon.href ? canon.href.split('#')[0] : global.location.href.split('#')[0];
    return base + '#' + fig.id;
  }
  function footText(fig, key) {
    var ps = fig.querySelectorAll('.ex-foot p');
    for (var i = 0; i < ps.length; i++) {
      var k = ps[i].querySelector('.k');
      if (k && k.textContent.trim() === key) return ps[i].textContent.replace(k.textContent, '').replace(/\s+/g, ' ').trim();
    }
    return '';
  }
  // a static diagram's styles (site.css classes) written onto each element of its copy
  var INLINE = ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-opacity', 'opacity', 'font-size', 'font-weight', 'font-style'];
  function inlineStyles(src, dst) {
    var a = src.querySelectorAll('*'), b = dst.querySelectorAll('*');
    for (var i = 0; i < a.length; i++) {
      var cs = global.getComputedStyle(a[i]);
      b[i].setAttribute('style', INLINE.map(function (p) { return p + ':' + cs.getPropertyValue(p); }).join(';'));
      b[i].removeAttribute('class');
    }
  }
  // the exhibit as one self-contained SVG document: {svg, width, height}
  function composeSVG(fig) {
    var name = fig.getAttribute('data-exhibit'), build = name && X[name];
    var study = global.Study || lastStudy, chart = fig.querySelector('.ex-chart');
    // a static diagram (Exhibits 23 and 24): the version on screen, wide or compact
    var dg = build ? null : Array.prototype.filter.call(fig.querySelectorAll('svg.dg'), function (s) { return s.getBoundingClientRect().width > 0; })[0];
    if (!dg && (!build || !study || !chart)) return Promise.reject(new Error('the chart is not drawn'));
    var W = dg ? Math.round(dg.getBoundingClientRect().width) : Math.max(640, Math.min(960, Math.floor(chart.clientWidth))), pad = 24;
    var root = document.documentElement, prev = root.getAttribute('data-theme'), stage = null, body = '', bodyH = 0, t;
    root.setAttribute('data-theme', 'light');           // drawn and measured in the light palette, then restored
    try {
      t = readTokens();
      if (dg) {
        var db = dg.getBoundingClientRect(), copy = dg.cloneNode(true);
        inlineStyles(dg, copy);
        copy.removeAttribute('class');
        copy.setAttribute('width', db.width.toFixed(1));
        copy.setAttribute('height', db.height.toFixed(1));
        copy.setAttribute('x', 0);
        copy.setAttribute('y', 0);
        copy.setAttribute('font-family', FONT);
        body = new XMLSerializer().serializeToString(copy);
        bodyH = Math.ceil(db.height);
      } else {
        drawStage();
      }
    } finally {
      if (stage) stage.remove();
      if (prev === null) root.removeAttribute('data-theme'); else root.setAttribute('data-theme', prev);
    }
    function drawStage() {
      var out = build(study, {width: W, narrow: false, t: t, figure: null});
      if (!out) throw new Error('no data');
      stage = document.createElement('div');
      stage.setAttribute('aria-hidden', 'true');
      stage.style.cssText = 'position:absolute;left:-20000px;top:0;width:' + W + 'px;visibility:hidden;';
      var inner = document.createElement('div');
      inner.className = 'ex-chart';
      out.nodes.forEach(function (n) { inner.appendChild(n); });
      stage.appendChild(legendNode(out.legend));
      stage.appendChild(inner);
      fig.appendChild(stage);
      var sb = stage.getBoundingClientRect();
      bodyH = Math.ceil(sb.height);
      stage.querySelectorAll('svg, .lg, .mc-title, .multi-cell > p, .ex-note').forEach(function (el) {
        if (el.tagName.toLowerCase() === 'svg' && el.parentNode.closest && el.parentNode.closest('svg')) return;
        var b = el.getBoundingClientRect(), x = b.left - sb.left, y = b.top - sb.top;
        if (!b.width) return;
        if (el.tagName.toLowerCase() === 'svg') {
          var clone = el.cloneNode(true);
          clone.setAttribute('x', x.toFixed(1));
          clone.setAttribute('y', y.toFixed(1));
          body += new XMLSerializer().serializeToString(clone);
          return;
        }
        var cs = global.getComputedStyle(el), size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10) >= 550 ? 600 : 400;
        var color = global.d3.color(cs.color) ? global.d3.color(cs.color).formatHex() : t.ink2;
        if (el.classList.contains('lg')) {
          var key = el.querySelector('.lg-key'), tx = x;
          if (key) {
            var kb = key.getBoundingClientRect(), kc = global.getComputedStyle(key).color;
            body += keySVG(key, kb.left - sb.left, kb.top - sb.top, kb.width, kb.height, global.d3.color(kc) ? global.d3.color(kc).formatHex() : t.ink2, t.paper);
            tx = kb.right - sb.left + 7;
          }
          body += textBlock([el.textContent], tx.toFixed(1), y + (b.height - size * 1.2) / 2, size, weight, color, 1.2);
          return;
        }
        var lh = parseFloat(cs.lineHeight) / size || 1.4;
        body += textBlock(wrap(el.textContent, b.width + 1, size, weight), x.toFixed(1), y + (lh - 1) * size / 2, size, weight, color, lh);
      });
    }
    // header: label, title, subtitle; footer: source, the caveat and the address
    var text = function (sel) { var el = fig.querySelector(sel); return el ? el.textContent.replace(/\s+/g, ' ').trim() : ''; };
    var head = '', y = pad;
    var label = text('.ex-label').toUpperCase();
    head += textBlock([label], pad, y, 11.5, 600, t.accent || t.ink2, 1.2, ' letter-spacing="1.15"');
    y += 20;
    var title = wrap(text('.ex-title'), W, 18, 600);
    head += textBlock(title, pad, y, 18, 600, t.ink, 1.35);
    y += title.length * 18 * 1.35 + 4;
    var subLines = wrap(text('.ex-sub'), W, 14, 400);
    head += textBlock(subLines, pad, y, 14, 400, t.ink2, 1.45);
    y += subLines.length * 14 * 1.45 + 14;
    var top = y;
    y += bodyH + 14;
    var foot = '', src = footText(fig, 'Source');
    if (src) {
      var srcLines = wrap('Source: ' + src, W, 12, 400);
      foot += textBlock(srcLines, pad, y, 12, 400, t.ink2, 1.45);
      y += srcLines.length * 12 * 1.45 + 2;
    }
    var mark = wrap('Hypothetical backtest · ' + exhibitURL(fig), W, 12, 400);
    foot += textBlock(mark, pad, y, 12, 400, t.ink3, 1.45);
    y += mark.length * 12 * 1.45 + pad;
    var width = W + 2 * pad, height = Math.ceil(y);
    return Promise.all([fontData(400), fontData(600)]).then(function (f) {
      var faces = [[400, f[0]], [600, f[1]]].filter(function (x) { return x[1]; }).map(function (x) {
        return '@font-face{font-family:"IBM Plex Sans";font-weight:' + x[0] + ';src:url(' + x[1] + ') format("woff2")}';
      }).join('');
      var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" ' +
        'font-family="' + esc(FONT) + '"><title>' + esc(text('.ex-label') + ': ' + text('.ex-title')) + '</title>' +
        '<style>' + faces + 'text{font-variant-numeric:tabular-nums}</style>' +
        '<rect width="100%" height="100%" fill="' + t.paper + '"/>' + head +
        '<g transform="translate(' + pad + ',' + top.toFixed(1) + ')">' + body + '</g>' + foot + '</svg>';
      return {svg: svg, width: width, height: height};
    });
  }
  function toPNG(doc) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var k = 2, cv = document.createElement('canvas');
        cv.width = doc.width * k;
        cv.height = doc.height * k;
        var g = cv.getContext('2d');
        g.scale(k, k);
        g.drawImage(img, 0, 0, doc.width, doc.height);
        cv.toBlob(function (b) { if (b) resolve(b); else reject(new Error('the image could not be encoded')); }, 'image/png');
      };
      img.onerror = function () { reject(new Error('the image could not be drawn')); };
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(doc.svg);
    });
  }
  function save(blob, name) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.hidden = true;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 10000);
  }
  function attach(fig) {
    if (!fig || !fig.id || fig.querySelector('.ex-tools')) return;
    var chart = fig.querySelector('.ex-chart'), diagram = fig.querySelector('svg.dg');
    if (!diagram && (!chart || !chart.querySelector('svg'))) return;
    var name = fig.getAttribute('data-exhibit'), label = (fig.querySelector('.ex-label') || {}).textContent || fig.id;
    var file = fig.id.replace(/^ex-/, 'exhibit-');
    var row = document.createElement('div');
    row.className = 'ex-tools';
    var msg = document.createElement('span');
    msg.className = 'ex-tools-msg';
    msg.setAttribute('role', 'status');
    var timer = null;
    var say = function (s, keep) {
      msg.textContent = s;
      clearTimeout(timer);
      if (!keep) timer = setTimeout(function () { msg.textContent = ''; }, 4000);
    };
    var button = function (text, aria, run) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = text;
      b.setAttribute('aria-label', aria);
      b.addEventListener('click', function () {
        b.disabled = true;
        Promise.resolve().then(run).catch(function (err) { say('Not available: ' + err.message); })
          .then(function () { b.disabled = false; });
      });
      return b;
    };
    row.appendChild(button('Copy link', 'Copy link to ' + label, function () {
      var url = exhibitURL(fig);
      if (!global.navigator.clipboard) { say(url, true); return; }
      return global.navigator.clipboard.writeText(url).then(function () { say('Link copied'); }, function () { say(url, true); });
    }));
    if ((name && X[name]) || diagram) {
      row.appendChild(button('SVG', 'Download ' + label + ' as SVG', function () {
        return composeSVG(fig).then(function (doc) { save(new Blob([doc.svg], {type: 'image/svg+xml'}), file + '.svg'); say('SVG saved'); });
      }));
      row.appendChild(button('PNG', 'Download ' + label + ' as PNG', function () {
        return composeSVG(fig).then(toPNG).then(function (blob) { save(blob, file + '.png'); say('PNG saved'); });
      }));
    }
    row.appendChild(msg);
    var foot = fig.querySelector('.ex-foot');
    if (foot) foot.appendChild(row); else (chart || diagram.closest('.dg-wrap') || diagram).after(row);
  }
  // the static diagrams are never drawn: their tools are added once, at load
  document.querySelectorAll('figure.exhibit').forEach(function (f) { if (f.querySelector('svg.dg')) attach(f); });

  // every builder: remember the study (for the exports), and once its chart is in the page,
  // keep its tips inside it and add the exhibit's tools
  Object.keys(X).forEach(function (name) {
    var build = X[name];
    X[name] = function (S, c) {
      if (S) lastStudy = S;
      var out = build(S, c);
      if (out && c && c.figure) {
        var mount = out.mount, fig = c.figure;
        out.mount = function (chart) {
          if (mount) mount.call(this, chart);
          watchTips(chart);
          attach(fig);
        };
      }
      return out;
    };
  });

  global.Exhibits = X;
  global.ExhibitTable = buildTable;
  global.ExhibitPage = {holdout: holdoutPage};
  global.ExhibitTools = {attach: attach, svg: composeSVG};
})(window);
