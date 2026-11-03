#!/usr/bin/env python3
"""Measure the room each part of index.html takes before it is laid out or drawn, for assets/site.css.

The page's sections below the summary are content-visibility: auto, so the browser skips laying
them out until they come near the window, and holds for each the room its contain-intrinsic-size
names; each chart is drawn by assets/exhibits.js only as it comes near, and until then its
.ex-chart holds the room its min-height names. When those guesses are wrong the page moves under
the reader (on a deep link such as index.html#ex-3, by hundreds of pixels). This script renders
the page in Chromium at 1440x900 and at 390x844, with every section laid out and every chart
drawn, and measures:

  - each section's height (main > section, all but #summary): its content box, as
    contain-intrinsic-size takes it;
  - each chart's room: what drawing adds above the chart (its legend), held under the caption
    so that the chart does not move down when the legend appears; and its .ex-chart before
    drawing plus all else that drawing adds to its figure (the chart, its tools below), so that
    the figure keeps its height. "Before drawing" is the moment assets/study.json has arrived
    and the holdout text is filled in, just before the first chart is drawn.

It writes them between the markers of assets/site.css: section-sizes (1440 px, the layout above
760 px), section-sizes-phone (390 px, inside the phone media block) and chart-sizes (both
layouts, keyed by figure id and applied only until the chart is drawn).

Usage:  python scripts/build_section_sizes.py           measure and rewrite the blocks
        python scripts/build_section_sizes.py --check   exit 1 if a measured height differs from
                                                        the CSS value by more than 5% (and say which)
Re-run it after the page's content changes. It needs Playwright for Python and its Chromium
(PLAYWRIGHT_BROWSERS_PATH is honoured), serves the repository itself on a free local port, and
takes about ten seconds. It is not run by the test suite (CI has no browsers).

Exit codes: 0 written or current; 1 out of date (--check); 2 cannot measure (no Playwright, no
markers in site.css, a page error, or charts that never settle).
"""

import argparse
import functools
import http.server
import math
import pathlib
import re
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]
CSS = ROOT / 'assets' / 'site.css'

LAYOUTS = (('desktop', 1440, 900), ('phone', 390, 844))
TOLERANCE = 0.05
BLOCKS = {
    'desktop': ('/* section-sizes:begin (scripts/build_section_sizes.py, measured at 1440 px) */',
                '/* section-sizes:end */'),
    'phone': ('  /* section-sizes-phone:begin (scripts/build_section_sizes.py, measured at 390 px) */',
              '  /* section-sizes-phone:end */'),
    'charts': ('/* chart-sizes:begin (scripts/build_section_sizes.py) */',
               '/* chart-sizes:end */'),
}
SECTION_RULE = re.compile(r'#([\w-]+) \{ contain-intrinsic-size: auto (\d+)px; \}')
CHART_RULE = re.compile(r'#([\w-]+):not\(\.is-drawn, \.no-chart\) \.ex-chart \{ min-height: (\d+)px; \}')
LEGEND_RULE = re.compile(r'#([\w-]+):not\(\.is-drawn, \.no-chart\) > \.ex-head \{ padding-bottom: (\d+)px; \}')
CHART_MEDIA = {'desktop': '@media screen and (min-width: 761px) {', 'phone': '@media screen and (max-width: 760px) {'}

# In the measured page every section is laid out, as in print and the number check.
FORCE_STYLE = 'main > section { content-visibility: visible !important; }'

# A figure's height is taken from its content (from its top to the bottom of its last shown
# child), not from its box: in a two-column grid a figure is stretched to the height of its row.
NATURAL_JS = """const natural = (f) => {
    const top = f.getBoundingClientRect().top;
    let bottom = top;
    for (const c of f.children) if (c.getClientRects().length) bottom = Math.max(bottom, c.getBoundingClientRect().bottom);
    return bottom - top;
  };"""

# Each figure as it stands when the page data have arrived, before any chart is drawn: site.js
# fires study:ready after filling in the holdout text and before it starts drawing.
ARM_JS = """() => {
  """ + NATURAL_JS + """
  document.addEventListener('study:ready', () => {
    window.__undrawn = [...document.querySelectorAll('main figure[data-exhibit]')].map((f) => {
      const c = f.querySelector('.ex-chart');
      return {id: f.id, drawn: f.classList.contains('is-drawn'), fig: natural(f), chart: c ? c.getBoundingClientRect().height : 0,
              top: c ? c.getBoundingClientRect().top - f.getBoundingClientRect().top : 0, head: !!f.querySelector(':scope > .ex-head')};
    });
  }, {once: true});
}"""

UNDRAWN_JS = """() => window.__undrawn ||
  new Promise((r) => document.addEventListener('study:ready', () => setTimeout(() => r(window.__undrawn)), {once: true}))"""

# Scroll through the page, two frames at each step, so that every chart comes near the window
# and site.js draws it; then wait until no further chart is drawn for a while.
DRAW_ALL_JS = """async () => {
  const frames = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const step = Math.max(600, innerHeight + 1200);
  for (let y = 0; y < document.documentElement.scrollHeight; y += step) { scrollTo(0, y); await frames(); }
  scrollTo(0, document.documentElement.scrollHeight);
  await frames();
  const count = () => document.querySelectorAll('main figure.is-drawn').length;
  let last = -1, quiet = 0;
  for (let i = 0; i < 200 && quiet < 6; i++) {
    await new Promise((r) => setTimeout(r, 100));
    const n = count();
    quiet = n === last ? quiet + 1 : 0;
    last = n;
  }
  await document.fonts.ready;
  scrollTo(0, 0);
  await frames();
  return quiet >= 6;
}"""

DRAWN_JS = """() => {
  """ + NATURAL_JS + """
  const inner = (el) => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return r.height - parseFloat(s.paddingTop) - parseFloat(s.paddingBottom) - parseFloat(s.borderTopWidth) - parseFloat(s.borderBottomWidth);
  };
  return {
    sections: [...document.querySelectorAll('main > section[id]')].filter((s) => s.id !== 'summary').map((s) => ({id: s.id, h: inner(s)})),
    figures: [...document.querySelectorAll('main figure[data-exhibit]')].map((f) => {
      const c = f.querySelector('.ex-chart');
      return {id: f.id, drawn: f.classList.contains('is-drawn'), fig: natural(f),
              top: c ? c.getBoundingClientRect().top - f.getBoundingClientRect().top : 0};
    }),
  };
}"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _serve():
    handler = functools.partial(_Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _fail(message):
    print('build_section_sizes: ' + message, file=sys.stderr)
    raise SystemExit(2)


def _block(css, name):
    """The span between a block's markers."""
    begin, end = BLOCKS[name]
    i, j = css.find(begin), css.find(end)
    if i < 0 or j < i:
        _fail(f'the {name} markers are missing from {CSS.relative_to(ROOT)}')
    return i + len(begin), j


def _measured_css(css):
    """The site.css the page is measured with: no room held for charts, and every font used."""
    i, j = _block(css, 'charts')
    css = css[:i] + '\n' + css[j:]
    return re.sub(r'font-display: \w+', 'font-display: block', css)


def measure(css):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _fail('Playwright for Python is not installed (pip install playwright)')
    served_css = _measured_css(css)
    server = _serve()
    url = f'http://127.0.0.1:{server.server_address[1]}/index.html'
    out = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, width, height in LAYOUTS:
                ctx = browser.new_context(viewport={'width': width, 'height': height}, color_scheme='light')
                page = ctx.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.route('**/assets/site.css', lambda r: r.fulfill(status=200, content_type='text/css', body=served_css))
                held = []                                  # the page data, held back until the page is ready
                page.route('**/assets/study.json', lambda r: held.append(r))
                page.goto(url, wait_until='load')
                page.add_style_tag(content=FORCE_STYLE)
                page.evaluate('document.fonts.ready.then(() => document.body.offsetHeight)')
                page.evaluate('document.fonts.ready')
                if len(held) != 1:
                    _fail(f'assets/study.json was requested {len(held)} times at {width} px')
                page.evaluate(ARM_JS)
                held[0].continue_()
                before = {f['id']: f for f in page.evaluate(UNDRAWN_JS)}
                if any(f['drawn'] for f in before.values()):
                    _fail('a chart was drawn before study:ready')
                if not page.evaluate(DRAW_ALL_JS):
                    _fail(f'the charts did not settle at {width} px')
                after = page.evaluate(DRAWN_JS)
                if errors:
                    _fail(f'page errors at {width} px: {errors[:3]}')
                charts, legends = {}, {}
                for f in after['figures']:
                    b = before.get(f['id'])
                    if not (f['drawn'] and b):
                        continue
                    # what drawing adds above the chart is held under the caption, so the chart
                    # stays put; the chart's room is what remains of the figure's growth
                    moved = f['top'] - b['top'] if b['head'] and f['top'] - b['top'] >= 1 else 0
                    if moved:
                        legends[f['id']] = round(moved)
                        moved = legends[f['id']]
                    charts[f['id']] = math.ceil(b['chart'] + f['fig'] - b['fig'] - moved - 0.01)
                out[name] = {'sections': {s['id']: round(s['h']) for s in after['sections']}, 'charts': charts, 'legends': legends}
                undrawn = [f['id'] for f in after['figures'] if not f['drawn']]
                if undrawn:
                    print(f'{name}: not drawn, so no room held: {", ".join(undrawn)}')
                ctx.close()
            browser.close()
    finally:
        server.shutdown()
    return out


def render(m):
    """The text of each block, between its markers."""
    blocks = {}
    for name in ('desktop', 'phone'):
        pad = '  ' if name == 'phone' else ''
        blocks[name] = ''.join(f'\n{pad}#{k} {{ contain-intrinsic-size: auto {v}px; }}' for k, v in m[name]['sections'].items()) + '\n'
    lines = ['', "/* each chart's room until it is drawn, measured at 1440 px (above 760 px) and 390 px:"
                 ' its legend (held under the caption), and the chart with its tools */']
    for name in ('desktop', 'phone'):
        lines.append(CHART_MEDIA[name])
        for k, v in m[name]['charts'].items():
            if k in m[name]['legends']:
                lines.append(f'  html.js #{k}:not(.is-drawn, .no-chart) > .ex-head {{ padding-bottom: {m[name]["legends"][k]}px; }}')
            lines.append(f'  html.js #{k}:not(.is-drawn, .no-chart) .ex-chart {{ min-height: {v}px; }}')
        lines.append('}')
    blocks['charts'] = '\n'.join(lines) + '\n'
    return blocks


def current(css):
    """The heights site.css holds now: {layout: {'sections'|'charts'|'legends': {id: px}}}."""
    out = {}
    for name in ('desktop', 'phone'):
        i, j = _block(css, name)
        out[name] = {'sections': {k: int(v) for k, v in SECTION_RULE.findall(css[i:j])}, 'charts': {}, 'legends': {}}
    i, j = _block(css, 'charts')
    text = css[i:j]
    for name in ('desktop', 'phone'):
        k = text.find(CHART_MEDIA[name])
        if k >= 0:
            body = text[k:text.find('\n}', k)]
            out[name]['charts'] = {a: int(b) for a, b in CHART_RULE.findall(body)}
            out[name]['legends'] = {a: int(b) for a, b in LEGEND_RULE.findall(body)}
    return out


def compare(measured, held):
    problems = []
    for name in ('desktop', 'phone'):
        for kind in ('sections', 'charts', 'legends'):
            m, h = measured[name][kind], held[name][kind]
            for k in sorted(set(m) | set(h)):
                if k not in h:
                    problems.append(f'{name} {kind}: #{k} measured {m[k]} px, not in site.css')
                elif k not in m:
                    problems.append(f'{name} {kind}: #{k} in site.css ({h[k]} px), not measured')
                elif abs(m[k] - h[k]) > TOLERANCE * max(m[k], 1):
                    problems.append(f'{name} {kind}: #{k} measured {m[k]} px, site.css {h[k]} px')
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if a height in site.css is more than 5%% off')
    args = ap.parse_args(argv)
    css = CSS.read_text(encoding='utf-8')
    for name in BLOCKS:
        _block(css, name)
    measured = measure(css)
    if args.check:
        problems = compare(measured, current(css))
        for p in problems:
            print(p)
        if problems:
            print(f'{len(problems)} height(s) out of date: run python scripts/build_section_sizes.py')
            return 1
        print('the section and chart heights in assets/site.css are current')
        return 0
    blocks = render(measured)
    for name, text in blocks.items():
        i, j = _block(css, name)
        css = css[:i] + text + css[j:]
    CSS.write_text(css, encoding='utf-8')
    n = sum(len(x) for v in measured.values() for x in v.values())
    print(f'wrote {n} heights to {CSS.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
