#!/usr/bin/env python3
"""Write the re-fetch drift table into index.html (Section 13) and README.md ("Reproduce").

The development run's price caches were lost with the working storage (2026-10-22), so its
numbers cannot be rebuilt from the input it pinned. The re-fetch reproduction
(results/v33_dev_refetch/, docs/IMPROVEMENT_PLAN.md A1) re-ran the same design, calendar and
code path on prices fetched afresh; this table puts every headline number the page quotes, and
the evidence-layer numbers the re-fetch also re-ran, beside the published value. Each value is a
marker that scripts/check_published_numbers.py checks: the published value under its own key,
the re-fetch's under study.refetch.values.<key>, the difference under study.refetch.diff.<key>.
The difference is the re-fetch's value as shown minus the published value as shown, so a 0 means
the two agree to the precision the page publishes.

The rows, labels and decimals are scripts/build_site_data.py's DRIFT_ROWS; a value's sign style
follows the page's own first marker of that key ('+' shown for positive values where the page
shows a sign).

It writes between <!-- drift-table:begin --> and <!-- drift-table:end --> in both files.
--check exits 1 if either file's copy differs from what this script writes.
"""
import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_site_data import DRIFT_ROWS  # noqa: E402

PAGE = ROOT / 'index.html'
README = ROOT / 'README.md'
STUDY = ROOT / 'assets' / 'study.json'
BEGIN, END = '<!-- drift-table:begin -->', '<!-- drift-table:end -->'
MINUS = '−'


def signed_keys(page_text):
    """Keys whose first marker on the page shows a sign ('+' or minus): their values are signed."""
    seen, signed = set(), set()
    for m in re.finditer(r'data-metric="([^"|]+)(?:\|\d)?"[^>]*>([^<]*)<', page_text):
        key, text = m.group(1), m.group(2).strip()
        if key in seen:
            continue
        seen.add(key)
        if text[:1] in ('+', MINUS, '-'):
            signed.add(key)
    return signed


def fmt(x, dp, signed):
    if x is None:
        return '—'
    s = f'{abs(x):,.{dp}f}'
    if float(f'{x:.{dp}f}') == 0:
        return f'{0:.{dp}f}'
    if x < 0:
        return MINUS + s
    return ('+' if signed else '') + s


def rows(study, page_text):
    r = study.get('refetch')
    if not r:
        return None
    signed = signed_keys(page_text)
    out = []
    for group, key, label, dp in DRIFT_ROWS:
        name = key[len('study.'):] if key.startswith('study.') else key
        old = _get(study, name.split('.')) if key.startswith('study.') else None
        new = _get(r['values'], name.split('.'))
        diff = _get(r['diff'], name.split('.'))
        out.append({'group': group, 'key': key, 'name': name, 'label': label, 'dp': dp,
                    'signed': key in signed, 'old': old, 'new': new, 'diff': diff})
    return out


def _get(d, parts):
    for p in parts:
        if isinstance(d, dict) and p in d:
            d = d[p]
        elif isinstance(d, list) and p.isdigit() and int(p) < len(d):
            d = d[int(p)]
        else:
            return None
    return d


def html_block(study, page_text, headline):
    rs = rows(study, page_text)
    if rs is None:
        return f'{BEGIN}\n{END}'
    lines = [BEGIN,
             '  <div class="tbl-wrap" id="t-refetch" role="region" aria-label="Re-fetch reproduction: published '
             'and re-fetched values" tabindex="0" data-phone="matrix">',
             '    <table class="tbl tbl-num">',
             '      <caption>Every headline number of this page, and the evidence-layer numbers the re-fetch re-ran: '
             'as published (prices fetched to 21 October 2026) and on prices fetched afresh on '
             f'{_day(study["refetch"]["run"]["timestamp_utc"])}. The difference is the re-fetch as shown minus the '
             'published value as shown, in the row\'s units.</caption>',
             '      <thead><tr><th scope="col">Measure</th><th scope="col" class="r">Published</th>'
             '<th scope="col" class="r">Re-fetch</th><th scope="col" class="r">Difference</th></tr></thead>',
             '      <tbody>']
    group = None
    for r in rs:
        if r['group'] != group:
            group = r['group']
            lines.append(f'        <tr class="grp-row"><th scope="rowgroup" colspan="4">{group}</th></tr>')
        old_value = r['old'] if r['key'].startswith('study.') else _get(headline, r['key'].split('.'))
        lines.append(
            f'        <tr><th scope="row">{r["label"]}</th>'
            f'<td class="r" data-metric="{r["key"]}">{fmt(old_value, r["dp"], r["signed"])}</td>'
            f'<td class="r" data-metric="study.refetch.values.{r["name"]}">{fmt(r["new"], r["dp"], r["signed"])}</td>'
            f'<td class="r" data-metric="study.refetch.diff.{r["name"]}">{fmt(r["diff"], r["dp"], True)}</td></tr>')
    lines += ['      </tbody>', '    </table>', '  </div>', END]
    return '\n'.join(lines)


def md_block(study, page_text, headline):
    rs = rows(study, page_text)
    if rs is None:
        return f'{BEGIN}\n{END}'
    lines = [BEGIN, '',
             '| Measure | Published | Re-fetch | Difference |', '|---|---:|---:|---:|']
    group = None
    for r in rs:
        if r['group'] != group:
            group = r['group']
            lines.append(f'| **{group}** | | | |')
        old_value = r['old'] if r['key'].startswith('study.') else _get(headline, r['key'].split('.'))
        lines.append(f'| {r["label"]} '
                     f'| <!--m:{r["key"]}-->{fmt(old_value, r["dp"], r["signed"])}<!--/m--> '
                     f'| <!--m:study.refetch.values.{r["name"]}-->{fmt(r["new"], r["dp"], r["signed"])}<!--/m--> '
                     f'| <!--m:study.refetch.diff.{r["name"]}-->{fmt(r["diff"], r["dp"], True)}<!--/m--> |')
    lines += ['', END]
    return '\n'.join(lines)


def _day(stamp):
    import datetime as dt
    d = dt.date.fromisoformat(str(stamp)[:10])
    return f'{d.day} {d.strftime("%B %Y")}'


def splice(text, block, path):
    if BEGIN not in text or END not in text:
        raise SystemExit(f'{path} has no {BEGIN} ... {END} block')
    a, b = text.index(BEGIN), text.index(END) + len(END)
    return text[:a] + block + text[b:]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if a file differs from a fresh build')
    args = ap.parse_args(argv)
    study = json.loads(STUDY.read_text(encoding='utf-8'))
    headline = json.loads((ROOT / 'results' / 'v33_dev' / 'headline_metrics.json').read_text())
    page = PAGE.read_text(encoding='utf-8')
    readme = README.read_text(encoding='utf-8')
    new_page = splice(page, html_block(study, page, headline), PAGE)
    new_readme = splice(readme, md_block(study, page, headline), README)
    stale = [p.name for p, old, new in ((PAGE, page, new_page), (README, readme, new_readme)) if old != new]
    if args.check:
        if stale:
            print(f'the drift table is stale in {", ".join(stale)}: run python scripts/build_drift_table.py',
                  file=sys.stderr)
            return 1
        print('the re-fetch drift table in index.html and README.md is current')
        return 0
    PAGE.write_text(new_page, encoding='utf-8')
    README.write_text(new_readme, encoding='utf-8')
    print(f'wrote the drift table ({", ".join(stale) or "unchanged"})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
