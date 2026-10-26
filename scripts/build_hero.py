#!/usr/bin/env python3
"""Build the hero figure of index.html, "the answer at a glance", from the published data.

The hero is a static chart in HTML and CSS (no script): every Sharpe ratio the note's
answer rests on, with its 95% interval, on one shared axis. It is a semantic table with
three columns: the row label (a link to the exhibit that shows the estimate), the track
(aria-hidden, drawn by assets/hero.css from inline custom properties) and the values.
Every number in it is a data-metric marker on a key that scripts/check_published_numbers.py
checks, and every drawn position is computed here from the number the row prints, so the
drawing cannot disagree with the text: tests/test_hero.py recomputes each position from the
row's own marker texts and the axis.

The title says that every interval spans zero and that neither period shows a detectable
edge. The build fails (exit 2) when the data would make that false: an interval that does not
contain zero, a rejected 2026 null, or arms that are not the registered ones.

Usage:  python scripts/build_hero.py            print the block
        python scripts/build_hero.py --write    write it between the hero markers of index.html
        python scripts/build_hero.py --check    exit 1 if the block in index.html is stale
Options --page, --study and --json name other files (the defaults are the repository's
index.html, assets/study.json and results/v33_dev/headline_metrics.json).

After a new run: build_site_data.py, check_published_numbers.py --write, then this script
with --write (the checker refreshes the marked numbers but not the drawn positions).

Exit codes: 0 written, printed or current; 1 the block is stale (--check); 2 the hero cannot be
built (missing or unreadable inputs, no markers in the page, or data that contradict the title).
"""

import argparse
import html
import importlib.util
import json
import pathlib
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PAGE = ROOT / 'index.html'
DEFAULT_STUDY = ROOT / 'assets' / 'study.json'
DEFAULT_JSON = ROOT / 'results' / 'v33_dev' / 'headline_metrics.json'

BEGIN = '<!-- hero:begin -->'
END = '<!-- hero:end -->'
INDENT = '  '                       # the block sits inside section#summary

AXIS_HALF = 2.5                     # the axis is [-AXIS_HALF, +AXIS_HALF] ...
AXIS_STEP = 0.5                     # ... widened symmetrically in these steps until every value fits

SIGNED = '+0.00'                    # marker templates, in check_published_numbers' format_like
P_VALUE = '0.000'
PLAIN = '0.00'
COUNT = '0'


def _load_checker():
    spec = importlib.util.spec_from_file_location('_hero_checker', ROOT / 'scripts' / 'check_published_numbers.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


chk = _load_checker()


class HeroError(Exception):
    """The hero cannot be built from these inputs."""


@dataclass(frozen=True)
class Row:
    label: str
    href: str
    colour: str                     # s1 v33 pairs, s2 Gatev, s3 Avellaneda-Lee, nu neutral
    x: str                          # marker keys: estimate, interval, one-sided upper bound
    lo: str
    hi: str
    ub: str = None
    sub: str = None                 # a second line under the label
    shape: str = 'circle'           # circle, square, diamond
    hollow: bool = False
    dashed: bool = False
    holm: str = None                # key of the Holm-adjusted p-value
    note: str = None                # text in place of a p-value


GROUPS = (
    ('Development period, 2023–2025', (
        Row('v33 pairs, net', '#ex-6', 's1', 'main.sharpe',
            'significance.main.boot_lo', 'significance.main.boot_hi', ub='study.dev.facts.sharpe_ucb'),
        Row('v33 pairs, before costs', '#ex-6', 's1', 'study.dev.facts.gross_sharpe',
            'study.dev.forest.1.lo', 'study.dev.forest.1.hi', hollow=True),
        Row('Walk-forward, net', '#ex-6', 's1', 'oos.pooled_sharpe',
            'significance.oos_daily.boot_lo', 'significance.oos_daily.boot_hi', ub='study.dev.facts.oos_ucb',
            sub='the same rule from February 2023'),
        Row('Avellaneda–Lee, net', '#ex-22', 's3', 'study.residual.sharpe',
            'study.residual.lo', 'study.residual.hi', sub='second strategy family', shape='square'),
        Row('Gatev distance method, net', '#ex-6', 's2', 'benchmarks.gatev.sharpe',
            'study.dev.facts.gatev_lo', 'study.dev.facts.gatev_hi', shape='diamond'),
    )),
    (('Pre-registered 2026 test, ', ('study.dev.facts.ho_days', COUNT), ' days'), (
        Row('H1 · S1 v33 pairs', '#ex-1', 's1', 'study.holdout.arms.0.sharpe',
            'study.holdout.arms.0.lo', 'study.holdout.arms.0.hi', ub='study.holdout.arms.0.ucb',
            holm='study.holdout.arms.0.p_holm'),
        Row('H2 · S2 Avellaneda–Lee', '#ex-1', 's3', 'study.holdout.arms.1.sharpe',
            'study.holdout.arms.1.lo', 'study.holdout.arms.1.hi', ub='study.holdout.arms.1.ucb',
            holm='study.holdout.arms.1.p_holm', shape='square'),
        Row('S3 v32 frozen', '#ex-1', 'nu', 'study.holdout.arms.2.sharpe',
            'study.holdout.arms.2.lo', 'study.holdout.arms.2.hi', ub='study.holdout.arms.2.ucb',
            hollow=True, dashed=True, note='descriptive'),
    )),
)

# the rows address list elements by index: each index must hold what its label says
IDENTITY = {
    'study.dev.forest.1.key': 'gross',
    'study.holdout.status': 'complete',
    'study.holdout.arms.0.key': 'v33_pairs', 'study.holdout.arms.0.hypothesis': 'H1',
    'study.holdout.arms.1.key': 'avellaneda_lee', 'study.holdout.arms.1.hypothesis': 'H2',
    'study.holdout.arms.2.key': 'v32_pairs', 'study.holdout.arms.2.hypothesis': None,
    'study.holdout.arms.2.role': 'descriptive',
}

TITLE = 'Every two-sided 95% interval spans zero: no detectable edge in development or in the pre-registered 2026 test'
SUBTITLE = ('Annualised Sharpe ratio with its 95% interval, net of costs unless stated; ticks mark the '
            'one-sided 95% upper bound where the note reports one. The walk-forward\'s one-sided bound is '
            'below zero: a loss, not an edge.')
LABEL = 'The answer at a glance'
NOTE = ('With the power stated in advance, the 2026 test detects with 80% probability only a Sharpe ratio '
        'of about ', ('study.dev.facts.ho_mde_025', PLAIN), '; not rejecting a null is not evidence that the '
        'edge is zero (<a href="#holdout">Section&nbsp;1</a>).')
LEGEND = (                          # (classes, mark, interval line, text), in two groups
    (('hz-s1', '', False, 'v33 pairs'),
     ('hz-s3 hz-sq', '', False, 'Avellaneda–Lee'),
     ('hz-s2 hz-dia', '', False, 'Gatev distance method')),
    (('hz-ink hz-hollow', '', False, 'before costs'),
     ('hz-nu hz-hollow hz-dashed', '', True, 'descriptive, not tested'),
     ('hz-ink', 'ub', False, 'one-sided 95% upper bound')),
)


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

def load_data(study_path=DEFAULT_STUDY, json_path=DEFAULT_JSON):
    """The headline JSON with the site data mounted under 'study', as the checker reads them."""
    try:
        headline = json.loads(pathlib.Path(json_path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise HeroError(f'cannot read {json_path}: {e}')
    site, problem = chk.load_site_data(study_path, json_path)
    if problem:
        raise HeroError(problem)
    return chk.with_site_data(headline, site)


def value(data, key):
    try:
        v = chk.resolve_key(data, key)
    except KeyError:
        raise HeroError(f'{key}: not in the data')
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise HeroError(f'{key}: not a number ({v!r})')
    return v


def marker(data, key, template, role=None, cls=None):
    """(html, shown value): the number as the page prints it, wrapped in its data-metric marker."""
    v = value(data, key)
    text = chk.format_like(v, template, key)
    shown, dp = chk.parse_marker_value(text)
    if not chk.matches(float(v), shown, dp):            # the checker must accept what is written
        raise HeroError(f'{key}: {text!r} does not show {v!r}')
    attrs = (f' class="{cls}"' if cls else '') + f' data-metric="{key}"' + (f' data-hz="{role}"' if role else '')
    return f'<span{attrs}>{text}</span>', shown


def check_identity(data):
    for key, want in IDENTITY.items():
        try:
            got = chk.resolve_key(data, key)
        except KeyError:
            got = '(absent)'
        if got != want:
            raise HeroError(f'{key} is {got!r}, the hero expects {want!r}')
    decision = chk.resolve_key(data, 'study.holdout.decision')
    if decision.get('rejected'):
        raise HeroError(f'the 2026 test rejected {decision["rejected"]}: the title says no detectable edge')
    for i in (0, 1):
        arm = chk.resolve_key(data, f'study.holdout.arms.{i}')
        if arm.get('edge') is not False or arm.get('p_holm_below_alpha') is not False:
            raise HeroError(f'arm {arm.get("key")}: the evaluation does not record "no edge"')


def axis_half(values):
    half = AXIS_HALF
    while max(abs(v) for v in values) > half:
        half += AXIS_STEP
    return half


def position(v, half):
    """Percent of the track for value v on the axis [-half, +half], as written in the page."""
    p = (v + half) / (2 * half) * 100
    s = f'{p:.3f}'.rstrip('0').rstrip('.')
    return ('0' if s == '-0' else s) + '%'


# ──────────────────────────────────────────────────────────────────────────────
# Markup
# ──────────────────────────────────────────────────────────────────────────────

def _text(data, parts):
    out = []
    for part in (parts if isinstance(parts, tuple) else (parts,)):
        out.append(part if isinstance(part, str) else marker(data, *part)[0])
    return ''.join(out)


def _mark_classes(row):
    cls = [f'hz-{row.colour}']
    cls += {'circle': [], 'square': ['hz-sq'], 'diamond': ['hz-dia']}[row.shape]
    cls += ['hz-hollow'] if row.hollow else []
    cls += ['hz-dashed'] if row.dashed else []
    return ' '.join(cls)


def build_rows(data):
    """[(group title html, [row dict])] with every value as printed."""
    groups = []
    for title, rows in GROUPS:
        built = []
        for r in rows:
            cells = {}
            for role, key in (('x', r.x), ('lo', r.lo), ('hi', r.hi), ('ub', r.ub)):
                if key:
                    cells[role] = marker(data, key, SIGNED, role, 'hz-e' if role == 'x' else None)
            lo, hi = cells['lo'][1], cells['hi'][1]
            raw_lo, raw_hi = value(data, r.lo), value(data, r.hi)
            if not (lo < 0 < hi and raw_lo < 0 < raw_hi):
                raise HeroError(f'{r.label}: the 95% interval [{raw_lo}, {raw_hi}] does not span zero, '
                                f'so the title "{TITLE}" would be false')
            built.append({'row': r, 'cells': cells,
                          'holm': marker(data, r.holm, P_VALUE)[0] if r.holm else None})
        groups.append((_text(data, title), built))
    return groups


def render(data):
    """The hero block, markers included, indented for the page."""
    check_identity(data)
    groups = build_rows(data)
    shown = [c[1] for _, rows in groups for b in rows for c in b['cells'].values()]
    half = axis_half(shown)
    ticks = [k for k in range(-int(half), int(half) + 1)]

    def tick_label(k):
        return '0' if k == 0 else ('−' if k < 0 else '+') + str(abs(k))

    legend = []
    for group in LEGEND:
        items = []
        for cls, kind, line, text in group:
            inner = ('<span class="hz-ci"></span>' if line else '') + \
                    ('<span class="hz-ub"></span>' if kind == 'ub' else '<span class="hz-pt"></span>')
            items.append(f'<span class="hz-lg"><span class="hz-k {cls}">{inner}</span>{text}</span>')
        legend.append(f'<span class="hz-lgg">{"".join(items)}</span>')

    axis = ''.join(f'<span class="hz-t" style="--t:{position(k, half)}">{tick_label(k)}</span>' for k in ticks)
    lines = [
        BEGIN,
        '<!-- Generated by scripts/build_hero.py from assets/study.json and the headline JSON: edit the script, not this block. -->',
        '<figure class="hero" id="answer" aria-labelledby="answer-h">',
        f'  <p class="hz-label">{LABEL}</p>',
        f'  <h2 class="hz-title" id="answer-h">{TITLE}</h2>',
        f'  <p class="hz-sub">{SUBTITLE}</p>',
        f'  <p class="hz-legend" aria-hidden="true">{"".join(legend)}</p>',
        f'  <table class="hz" data-axis="{-half:g} {half:g}" style="--zero:{position(0, half)}">',
        '    <caption class="vh">Annualised Sharpe ratio of each estimate, with its 95% interval</caption>',
        '    <colgroup><col class="hz-col-l"><col class="hz-col-t"><col class="hz-col-v"></colgroup>',
        '    <thead>',
        '      <tr class="hz-axis"><th scope="col"><span class="vh">Estimate</span></th>'
        f'<th class="hz-ax" scope="col"><span class="vh">95% interval on a common Sharpe-ratio axis</span>'
        f'<span aria-hidden="true">{axis}</span></th>'
        '<th scope="col" class="hz-valhead">Sharpe ratio [95% interval]</th></tr>',
        '    </thead>',
    ]
    for title, rows in groups:
        lines.append('    <tbody>')
        lines.append(f'      <tr class="hz-grp"><th scope="rowgroup" colspan="3">{title}</th></tr>')
        for b in rows:
            r, c = b['row'], b['cells']
            style = ';'.join(f'--{role}:{position(c[role][1], half)}' for role in ('x', 'lo', 'hi', 'ub') if role in c)
            sub = f'<span class="hz-q"><span class="vh">, </span>{r.sub}</span>' if r.sub else ''
            marks = '<span class="hz-ci"></span>' + ('<span class="hz-ub"></span>' if 'ub' in c else '') + \
                    '<span class="hz-pt"></span>'
            vals = f'{c["x"][0]} <span class="hz-i">[{c["lo"][0]}, {c["hi"][0]}]</span>'
            if 'ub' in c:
                vals += f'<span class="vh">; one-sided 95% upper bound {c["ub"][0]}</span>'
            if b['holm']:
                vals += f' <span class="hz-p"><span class="vh">; </span>Holm p {b["holm"]}</span>'
            elif r.note:
                vals += f' <span class="hz-p"><span class="vh">; </span>{html.escape(r.note)}</span>'
            lines.append(
                f'      <tr class="hz-r {_mark_classes(r)}" style="{style}">'
                f'<th scope="row"><a href="{r.href}">{html.escape(r.label)}</a>{sub}</th>'
                f'<td class="hz-tr" aria-hidden="true">{marks}</td>'
                f'<td class="hz-v">{vals}</td></tr>')
        lines.append('    </tbody>')
    lines += [
        '  </table>',
        f'  <p class="hz-note">{_text(data, NOTE)}</p>',
        '</figure>',
        END,
    ]
    return '\n'.join((INDENT + x) if x else x for x in lines)


# ──────────────────────────────────────────────────────────────────────────────
# Page
# ──────────────────────────────────────────────────────────────────────────────

def split_page(text):
    """(before, block, after) around the hero markers, each of which must occur once."""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise HeroError(f'the page must hold {BEGIN} and {END} once each '
                        f'(found {text.count(BEGIN)} and {text.count(END)})')
    a = text.index(BEGIN)
    b = text.index(END) + len(END)
    if b < a:
        raise HeroError(f'{END} comes before {BEGIN}')
    start = text.rfind('\n', 0, a) + 1            # the block owns its first line's indentation
    if text[start:a].strip():
        raise HeroError(f'{BEGIN} must start its own line')
    return text[:start], text[start:b], text[b:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true', help='write the block between the hero markers')
    mode.add_argument('--check', action='store_true', help='exit 1 if the block in the page is stale')
    ap.add_argument('--page', default=str(DEFAULT_PAGE), help='the page (default: index.html)')
    ap.add_argument('--study', default=str(DEFAULT_STUDY), help='site data (default: assets/study.json)')
    ap.add_argument('--json', default=str(DEFAULT_JSON),
                    help='headline JSON (default: results/v33_dev/headline_metrics.json)')
    args = ap.parse_args(argv)
    try:
        block = render(load_data(args.study, args.json))
        if not (args.write or args.check):
            print(block)
            return 0
        page = pathlib.Path(args.page)
        text = page.read_text(encoding='utf-8')
        before, current, after = split_page(text)
    except (HeroError, OSError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    if args.check:
        if current != block:
            print(f'STALE: the hero block in {page} is not what scripts/build_hero.py builds; '
                  f'run scripts/build_hero.py --write', file=sys.stderr)
            return 1
        print(f'OK: the hero block in {page} is current')
        return 0
    if current != block:
        tmp = page.with_name(page.name + '.tmp')
        tmp.write_text(before + block + after, encoding='utf-8')
        tmp.replace(page)
        print(f'Wrote the hero block into {page}')
    else:
        print(f'The hero block in {page} is already current')
    return 0


if __name__ == '__main__':
    sys.exit(main())
