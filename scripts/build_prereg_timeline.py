#!/usr/bin/env python3
"""Draw the pre-registration timeline in index.html (Section 1), as static SVG and a list.

The figure restates the dates Section 1, Section 11 and the run record give: the 2026 test
period, the project's development during it (versions 8 to 24 from 20 February 2026, known
only from the engineering log; versions 25 to 33 in git from 12 June 2026), and the October
record from the v32 run to the filing and the run. The test period and the run come from
assets/study.json; tests/test_site_links.py checks that every other date it shows is stated
in the page's own text.

It writes between <!-- prereg-timeline:begin --> and <!-- prereg-timeline:end -->.
--check exits 1 if the page's copy differs from what this script draws.
"""

import argparse
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import link_refs  # noqa: E402  (commit hashes link as everywhere else on the page)

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / 'index.html'
STUDY = ROOT / 'assets' / 'study.json'
BEGIN, END = '<!-- prereg-timeline:begin -->', '<!-- prereg-timeline:end -->'

# Dates stated in the page's text (Section 1's lede, the v32 comparison table, the run record,
# the registry note and the run manifest); the test checks each phrase is on the page.
DEV_LOG_FROM = dt.date(2026, 2, 20)       # "Versions 8 to 24, developed from 20 February 2026"
GIT_FROM = dt.date(2026, 6, 12)           # "the repository's first commit (12 June 2026, version 25)"
EVENTS = [
    # (date, time shown or None, what happened); the phrases are the page's
    (dt.date(2026, 10, 18), None, 'v32 published'),
    (dt.date(2026, 10, 20), '18:04 UTC', 'From commit <code>a1c76db</code>, five hours after the 2026 calendar was added '
                                         'to the code, the fetch code refuses any daily price history after 31 December '
                                         '2025 until the registered commit unseals it'),
    (dt.date(2026, 10, 21), '06:19 UTC', 'The v33 development run'),
    (dt.date(2026, 10, 22), '17:29 UTC', 'By this time the working storage outside git (price caches, raw downloads and '
                                         'the original v32 universe file) has been lost, when its container was recycled'),
]
PHRASES = ['20 February 2026', '12 June 2026', '18 Oct 2026', '18:04 UTC', '06:19 UTC', '17:29 UTC',
           'five hours after the 2026 calendar was added', 'before the filing']


def _d(s):
    return dt.date.fromisoformat(s[:10])


def facts():
    S = json.loads(STUDY.read_text(encoding='utf-8'))
    h = S['holdout']
    p = h['provenance']
    return {
        'start': _d(h['calendar_start']), 'end': _d(h['calendar_end']),
        'days': h['arms'][0]['days'],
        'run': _d(p['completed_utc']), 'commit': p['registered_commit'][:7],
        'registered': _d(p['registry']['registered_utc']),
    }


def fmt(d, year=False):
    return f'{d.day} {d.strftime("%b")}' + (f' {d.year}' if year else '')


def svg(F, width, compact):
    """The 2026 overview: the test period, development during it, and the filing."""
    lo, hi = dt.date(2026, 1, 1), dt.date(2026, 11, 1)
    x0, x1 = 6.0, width - 6.0

    def x(d):
        return x0 + (d - lo).days / (hi - lo).days * (x1 - x0)

    rows = []
    t = 'tlp-c' if compact else 'tlp-w'
    rows.append(f'<svg class="dg {"dg-compact" if compact else "dg-wide"}" viewBox="0 0 {width:g} @H@" '
                f'role="img" aria-labelledby="{t}-t {t}-d" focusable="false">')
    rows.append(f'<title id="{t}-t">The 2026 test period and the project\'s development</title>')
    rows.append(f'<desc id="{t}-d">The test period runs from {fmt(F["start"])} to {fmt(F["end"], True)}, '
                f'{F["days"]} trading days. The project was developed during it: versions 8 to 24 from '
                f'{fmt(DEV_LOG_FROM)}, known only from the engineering log, and versions 25 to 33 in git from '
                f'{fmt(GIT_FROM)}. The protocol was filed on {fmt(F["run"], True)}, after the period ended and before '
                f'any of its daily prices were fetched, and the test ran once the same day.</desc>')
    rows.append(f'<defs><pattern id="{t}-hatch" width="5" height="5" patternUnits="userSpaceOnUse" '
                f'patternTransform="rotate(45)"><rect class="tlp-hatch-bg" width="5" height="5"/>'
                f'<line class="tlp-hatch" x1="0" y1="0" x2="0" y2="5"/></pattern></defs>')
    ov_a, ov_b = x(DEV_LOG_FROM), x(F['end'])
    # row 1: the test data
    if compact:
        rows.append(f'<text class="dg-t" x="{x0:g}" y="20">Test period<tspan class="dg-s" dx="6">'
                    f'{fmt(F["start"])} to {fmt(F["end"])}, {F["days"]} days</tspan></text>')
    else:
        rows.append(f'<text class="dg-t" x="{x0:g}" y="20">Test period<tspan class="dg-s" dx="8">2026 daily prices, '
                    f'{fmt(F["start"])} to {fmt(F["end"])}: {F["days"]} trading days, none fetched into the project '
                    f'before the filing</tspan></text>')
    rows.append(f'<rect class="tl-hold is-done" x="{x(F["start"]):.1f}" y="28" width="{x(F["end"]) - x(F["start"]):.1f}" '
                f'height="10" rx="2"/>')
    # row 2: development
    y2 = 70
    if compact:
        rows.append(f'<text class="dg-t" x="{x0:g}" y="{y2}">Development<tspan class="dg-s" dx="6">versions 8 to 33</tspan></text>')
    else:
        rows.append(f'<text class="dg-t" x="{x0:g}" y="{y2}">Development<tspan class="dg-s" dx="8">versions 8 to 24 from '
                    f'{fmt(DEV_LOG_FROM)}, engineering log only (hatched); versions 25 to 33 in git from '
                    f'{fmt(GIT_FROM)}</tspan></text>')
    rows.append(f'<rect class="tlp-log" x="{x(DEV_LOG_FROM):.1f}" y="{y2 + 8}" width="{x(GIT_FROM) - x(DEV_LOG_FROM):.1f}" '
                f'height="10" rx="2" fill="url(#{t}-hatch)"/>')
    rows.append(f'<rect class="tlp-git" x="{x(GIT_FROM):.1f}" y="{y2 + 8}" width="{x(F["run"]) - x(GIT_FROM):.1f}" '
                f'height="10" rx="2"/>')
    # the overlap: a bracket under development, over the days it shares with the test period
    yb = y2 + 30
    rows.append(f'<path class="tlp-bracket" d="M{ov_a:.1f},{yb - 6} V{yb} H{ov_b:.1f} V{yb - 6}"/>')
    rows.append(f'<line class="tlp-guide" x1="{ov_b:.1f}" x2="{ov_b:.1f}" y1="40" y2="{yb - 6}"/>')
    if compact:
        rows.append(f'<text class="tlp-ov-t" x="{ov_a:.1f}" y="{yb + 17}">Developed during the test period:</text>')
        rows.append(f'<text class="tlp-ov-t" x="{ov_a:.1f}" y="{yb + 33}">sealed, not prospective</text>')
        yl = yb + 33
    else:
        rows.append(f'<text class="tlp-ov-t" x="{ov_a:.1f}" y="{yb + 17}">Developed during the test period: '
                    f'the test is sealed, not prospective</text>')
        yl = yb + 17
    # the filing and the run
    xf = x(F['run'])
    yf = yl + 26
    rows.append(f'<line class="tlp-file" x1="{xf:.1f}" x2="{xf:.1f}" y1="24" y2="{yf - 14}"/>')
    rows.append(f'<text class="dg-t" x="{xf:.1f}" y="{yf}" text-anchor="end">{fmt(F["run"])}: filed, then run once</text>')
    # month axis
    ya = yf + 14
    rows.append(f'<line class="dg-axis" x1="{x0:g}" x2="{x1:g}" y1="{ya}" y2="{ya}"/>')
    for m in range(1, 12):
        d = dt.date(2026, m, 1)
        xm = x(d)
        rows.append(f'<line class="dg-axis" x1="{xm:.1f}" x2="{xm:.1f}" y1="{ya}" y2="{ya + 4}"/>')
        if m < 11 and (not compact or m % 3 == 1):
            label = d.strftime('%b') + (' 2026' if m == 1 else '')
            rows.append(f'<text class="dg-m" x="{xm + 3:.1f}" y="{ya + 15}">{label}</text>')
    rows.append('</svg>')
    return '\n'.join(rows).replace('@H@', f'{ya + 22:g}')


def events(F):
    out = ['<ol class="tl-events" aria-label="The October 2026 record">']
    for d, t, what in EVENTS:
        when = fmt(d, True) + (f', {t}' if t else '')
        out.append(f'  <li><span class="tle-when">{when}</span> <span class="tle-what">{what}</span></li>')
    out.append(f'  <li class="is-key"><span class="tle-when">{fmt(F["run"], True)}</span> <span class="tle-what">'
               'A universe file for S3 is rebuilt from the v32 development run\'s price-fetch manifest; the protocol is filed '
               f'(<code>{F["commit"]}</code>); the runbook then runs the three arms and the evaluation in one attempt, '
               'and the trial is registered</span></li>')
    out.append('</ol>')
    return '\n'.join(out)


def block():
    F = facts()
    assert F['registered'] == F['run'], 'the run and its registration are drawn as one day'
    return link_refs.link_commits('\n'.join([
        BEGIN,
        '  <figure class="exhibit ex-diagram ex-unnumbered" id="prereg-timeline">',
        '    <figcaption class="ex-head">',
        '      <a class="ex-label" href="#prereg-timeline">Timeline</a>',
        '      <span class="ex-title">Developed during the test period; filed before any of its daily prices were '
        'fetched</span>',
        '      <span class="ex-sub">2026, and the record from the v32 run to the filing</span>',
        '    </figcaption>',
        '    <div class="dg-wrap">',
        svg(F, 880, False),
        svg(F, 360, True),
        '    </div>',
        events(F),
        '    <p class="ex-note">The test period had ended before the filing, so the test is sealed, not prospective; '
        'and because the project was developed during it, the designers\' general knowledge of 2026 markets cannot be '
        'sealed. The other 2026 '
        'information the project received is listed in <a class="xref" href="#threats">Section 11</a>.</p>',
        '  </figure>',
        END,
    ]), {})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv)
    page = PAGE.read_text(encoding='utf-8')
    if BEGIN not in page or END not in page:
        print('index.html has no prereg-timeline markers', file=sys.stderr)
        return 1
    a, b = page.index(BEGIN), page.index(END) + len(END)
    new = page[:a] + block() + page[b:]
    if args.check:
        if new != page:
            print('STALE: the pre-registration timeline in index.html; rebuild with python scripts/build_prereg_timeline.py')
            return 1
        print('the pre-registration timeline in index.html is current')
        return 0
    if new != page:
        PAGE.write_text(new, encoding='utf-8')
        print('drew the pre-registration timeline in index.html')
    else:
        print('index.html already current')
    return 0


if __name__ == '__main__':
    sys.exit(main())
