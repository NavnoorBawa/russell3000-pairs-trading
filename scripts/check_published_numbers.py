#!/usr/bin/env python3
"""Fail if README.md / index.html publish numbers that no longer match the run log.

This exists because of the v31 audit. The site and README spent weeks advertising
v29 figures (+0.90% / Sharpe 0.50, "beats the textbook") that the corrected code no
longer produced, and nothing in CI could tell. Stale published numbers are the most
damaging defect class in a research repo — they are wrong in public, they look
authoritative, and no test suite touches them.

Usage:
    python3.12 scripts/check_published_numbers.py [--log logs/backtest_v31.log]

Exit code 0 if every checked figure appears in the published files, 1 otherwise.
This is a *drift detector*, not a full parser: it asserts that the specific headline
figures parsed out of the log are present verbatim in the published text.
"""

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def parse_log(path):
    """Pull the headline figures out of a backtest log."""
    text = path.read_text(errors='replace')
    got = {}

    m = re.search(r'Total Return:\s*(-?[\d.]+)%', text)
    if m:
        got['main_return'] = float(m.group(1))
    m = re.search(r'Sharpe Ratio:\s*(-?[\d.]+)', text)
    if m:
        got['main_sharpe'] = float(m.group(1))
    m = re.search(r'Total Trades:\s*(\d+)', text)
    if m:
        got['main_trades'] = int(m.group(1))

    m = re.search(r'mean\s+(-?[\d.]+)%/qtr\s*\|\s*t-stat\s+(-?[\d.]+)\s*\|\s*p=([\d.]+)'
                  r'\s*\|\s*(\d+)/(\d+) positive', text)
    if m:
        got['oos_mean'] = float(m.group(1))
        got['oos_p'] = float(m.group(3))
        got['oos_positive'] = int(m.group(4))
        got['oos_windows'] = int(m.group(5))

    m = re.search(r'Pooled Sharpe \(OOS only\)\s*:\s*(-?[\d.]+)', text)
    if m:
        got['oos_pooled_sharpe'] = float(m.group(1))

    m = re.search(r'Distance method \(Gatev\)\s+return\s+(-?[\d.]+)%\s*\|\s*Sharpe\s+(-?[\d.]+)', text)
    if m:
        got['gatev_return'] = float(m.group(1))
        got['gatev_sharpe'] = float(m.group(2))

    m = re.search(r'survive BH-FDR q<0\.05:\s*(\d+)', text)
    if m:
        got['bh_survivors'] = int(m.group(1))

    return got


def _variants(value, decimals):
    """Number spellings a human might have typed, incl. the Unicode minus sign."""
    s = f'{value:.{decimals}f}'
    out = {s}
    if s.startswith('-'):
        out.add('−' + s[1:])          # − U+2212
    elif value > 0:
        out.add('+' + s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--log', default='logs/backtest_v31.log')
    args = ap.parse_args()

    log_path = ROOT / args.log
    if not log_path.exists():
        print(f'SKIP: {args.log} not found (run the backtest first)')
        return 0

    got = parse_log(log_path)
    if not got:
        print(f'SKIP: no headline figures parsed from {args.log}')
        return 0

    published = {}
    for name in ('README.md', 'index.html'):
        p = ROOT / name
        if p.exists():
            published[name] = p.read_text(errors='replace')
    if not published:
        print('SKIP: no published files found')
        return 0

    # (log key, decimals, human label) — checked as "appears verbatim somewhere"
    checks = [
        ('main_return', 2, 'main backtest return'),
        ('main_sharpe', 2, 'main backtest Sharpe'),
        ('oos_mean', 2, 'OOS mean %/qtr'),
        ('oos_pooled_sharpe', 2, 'OOS pooled Sharpe'),
        ('gatev_return', 2, 'Gatev baseline return'),
        ('gatev_sharpe', 2, 'Gatev baseline Sharpe'),
    ]

    failures = []
    for key, dp, label in checks:
        if key not in got:
            continue
        wanted = _variants(got[key], dp)
        if not any(any(v in text for v in wanted) for text in published.values()):
            failures.append(f'  {label}: log says {got[key]:.{dp}f} — not found in '
                            f'{" or ".join(published)}')

    # integer counts
    for key, label in (('oos_windows', 'OOS window count'),
                       ('oos_positive', 'OOS profitable windows'),
                       ('main_trades', 'main backtest trades')):
        if key not in got:
            continue
        if not any(str(got[key]) in text for text in published.values()):
            failures.append(f'  {label}: log says {got[key]} — not found in published text')

    print(f'Checked {len(checks) + 3} headline figures from {args.log}')
    for k, v in sorted(got.items()):
        print(f'  log: {k:22} = {v}')

    if failures:
        print('\nPUBLISHED NUMBERS OUT OF DATE:')
        print('\n'.join(failures))
        print('\nRefresh README.md / index.html (and og-image.png via '
              'scripts/make_og_image.py) to match the logged run.')
        return 1

    print('\nOK: every checked figure appears in the published text.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
