#!/usr/bin/env python3
"""Build the study's paper, paper/pairs_study.pdf, from the same data as the site.

The paper is the site in print. It reads the site's data contract (assets/study.json,
built by scripts/build_site_data.py, and the headline JSON that file was built from), so
the two cannot disagree: every number the paper prints is formatted here, once, into
paper/build/paper_data.json, and paper/main.typ only places the formatted strings. A
result that does not exist yet (the data-snooping tests, the second strategy family, the
sealed 2026 holdout) is null in that file; its exhibit or table is left out of the body
and listed, with what it will show, in the note's table of forthcoming results. A number
that is null prints as "pending" with its reason, never as a number. Sentences whose
wording depends on the data ("every interval spans zero") name a claim that is computed
here; the compile stops if a claim the text makes is false.

Products (all committed; CI checks them with --check):

    paper/build/paper_data.json    every printed number and table cell, formatted as the
                                   site formats it; claims; pending reasons; layout
    paper/build/figures/*.svg      the exhibits (matplotlib; IBM Plex from paper/fonts/;
                                   colours from the light theme of assets/site.css)
    paper/pairs_study.pdf          Typst compile of paper/main.typ with a fixed timestamp
    paper/build/manifest.json      sha256 of every compile input and of the PDF

usage:
    python scripts/build_paper.py               # data, figures and PDF
    python scripts/build_paper.py --check       # exit 1 if a committed product is stale
    python scripts/build_paper.py --png DIR     # also render each page to DIR/page-N.png

Deterministic: no wall-clock time (the PDF's timestamp is the paper's date, the newest
dated input), fixed SVG ids, sorted JSON; a rebuild of unchanged inputs is byte-identical.
The typst Python package (pip install -e ".[paper]") is needed to compile the PDF only;
without it --check still verifies the data, the figures and the manifest.
"""
import argparse
import collections
import datetime as dt
import hashlib
import html
import io
import json
import math
import pathlib
import re
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading import power as pw  # noqa: E402
from pairs_trading.significance import _autocorrelations, _circular_block_indices, hac_tstat_mean  # noqa: E402
from pairs_trading.study_config import CALENDARS, PROFILES  # noqa: E402

SCHEMA = 1
PAPER = ROOT / 'paper'
BUILD = PAPER / 'build'
FIGURES = BUILD / 'figures'
FONTS = PAPER / 'fonts'
MAIN = PAPER / 'main.typ'
BIB = PAPER / 'references.bib'
PDF = PAPER / 'pairs_study.pdf'
DATA = BUILD / 'paper_data.json'
MANIFEST = BUILD / 'manifest.json'
SITE_CSS = ROOT / 'assets' / 'site.css'
SITE_INDEX = ROOT / 'index.html'

MINUS = '−'
PERIODS = 252
EXHIBIT_WIDTH_MM = 162.0                # A4 (210 mm) less 24 mm margins: exhibits and tables span this
MEASURE_MM = 130.0                      # running text: about 75 characters of 10.4 pt Plex Serif
COLUMN_GAP_MM = 6.0
BOOT_SEED, BOOT_RESAMPLES = 42, 5000    # the run's own bootstrap settings (seed, resamples)
_Z95, _Z80 = 1.6448536269514722, 0.8416212335729143   # one-sided 5% test, 80% power
HOLDOUT_DAYS = (126, 200, 252)          # six months, the registered calendar (2026-01-02 to 2026-10-19), a year
HOLM_FIRST_ALPHA = 0.05 / 2             # Holm's first step across the two confirmatory arms
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
          'October', 'November', 'December')
WORDS = ('no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')
# Sections of assets/study.json the paper prints. A section the site builder adds later
# (and the paper does not know) stops the build rather than going silently unprinted.
KNOWN_STUDY = {'schema', 'meta', 'dev', 'holdout', 'residual', 'validation'}
KNOWN_DEV = {'run', 'daily', 'gatev', 'random_band', 'random_sharpes', 'strategy_sharpe', 'gatev_sharpe',
             'random_percentile', 'walk_forward', 'monthly', 'annual', 'rolling_sharpe', 'forest', 'power',
             'dsr_curve', 'waterfall', 'trades', 'factors', 'funnel', 'universe_by_formation', 'cost_schedules',
             'cost_curve', 'snooping', 'facts',
             # the evidence layer's anatomy.json, passed through by the site builder
             'shortfall', 'exit_race', 'decay', 'persistence', 'capacity', 'pvalue_hist'}


class PaperDataError(ValueError):
    """The inputs hold something the paper cannot print truthfully."""


# ──────────────────────────────────────────────────────────────────────────────
# Formatting: one function, the site's conventions (U+2212 minus, explicit '+')
# ──────────────────────────────────────────────────────────────────────────────

_SPEC = re.compile(r'(?P<plus>\+?)(?P<comma>,?)\.(?P<dp>\d)(?P<suffix>.*)')


def fmt(x, spec):
    """`x` formatted by `spec`, e.g. '.2', '+.2%', ',.0', '.2×'; None for a missing value.

    '+' writes an explicit plus on positive values; ',' groups thousands; the digit is the
    number of decimals; anything after it is a suffix. A value that rounds to zero carries
    no sign, so '−0.00' cannot appear.
    """
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(f'not a number: {x!r}')
    x = float(x)
    if not math.isfinite(x):
        return None
    s = _SPEC.fullmatch(spec)
    if s is None:
        raise ValueError(f'bad format spec {spec!r}')
    dp = int(s['dp'])
    body = f'{abs(x):,.{dp}f}' if s['comma'] else f'{abs(x):.{dp}f}'
    nonzero = float(body.replace(',', '')) != 0.0
    sign = MINUS if x < 0 and nonzero else ('+' if s['plus'] and x > 0 and nonzero else '')
    return sign + body + s['suffix']


NBSP = '\u00a0'                         # dates never break across lines


def long_date(iso):
    """'2023-07-03' -> '3 July 2023'."""
    d = dt.date.fromisoformat(str(iso)[:10])
    return f'{d.day}{NBSP}{MONTHS[d.month - 1]}{NBSP}{d.year}'


def short_date(iso):
    """'2022-12-31' -> '31 Dec 2022'."""
    d = dt.date.fromisoformat(str(iso)[:10])
    return f'{d.day}{NBSP}{MONTHS[d.month - 1][:3]}{NBSP}{d.year}'


def month_name(ym):
    """'2024-07' (or a full date) -> 'July 2024'."""
    return f'{MONTHS[int(str(ym)[5:7]) - 1]}{NBSP}{str(ym)[:4]}'


def ordinal(n):
    n = int(round(n))
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or d.get(p) is None:
            return default
        d = d[p]
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Inputs
# ──────────────────────────────────────────────────────────────────────────────

def load_inputs(root=ROOT):
    """study.json, the headline JSON it was built from, and the point-in-time universe index.

    The headline JSON is found among study.json's own sources by its sha256, so the paper
    can only ever pair a study file with the run it was built from.
    """
    root = pathlib.Path(root)
    study_path = root / 'assets' / 'study.json'
    study = json.loads(study_path.read_text(encoding='utf-8'))
    meta = study['meta']
    rel = next((p for p, h in sorted(meta['sources'].items())
                if p.endswith('headline_metrics.json') and h == meta['headline_sha256']), None)
    if rel is None:
        raise PaperDataError('assets/study.json lists no headline JSON with its headline_sha256')
    headline_path = root / rel
    if not headline_path.is_file() or _sha256(headline_path) != meta['headline_sha256']:
        raise PaperDataError(f'{rel} is missing or is not the file assets/study.json was built from; '
                             'rebuild it with scripts/build_site_data.py')
    index_path = root / 'reference' / 'universe' / 'index.json'
    universe = json.loads(index_path.read_text(encoding='utf-8')) if index_path.is_file() else None

    def source(pattern):
        """A source of study.json whose path matches, checked against the sha256 recorded there."""
        hits = [p for p in sorted(meta['sources']) if re.search(pattern, p)]
        if not hits:
            return None, None
        path = root / hits[0]
        if not path.is_file() or _sha256(path) != meta['sources'][hits[0]]:
            raise PaperDataError(f'{hits[0]} changed after assets/study.json was built from it')
        return hits[0], json.loads(path.read_text(encoding='utf-8'))
    results_path, results = source(r'pairs_trading_results_.*(?<!_compact)\.json$')
    if results is None:
        raise PaperDataError('assets/study.json lists no full results export among its sources')
    _, declaration = source(r'variant_family/declaration\.json$')
    # The run's price-fetch manifest (what share of the universe has prices, and why the
    # rest has none) sits beside the results export; the site does not read it.
    manifest_path = root / results_path.rsplit('/', 1)[0] / 'price_fetch_manifest.json'
    fetch = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else None
    # The site's exhibit list, for the concordance of its exhibit numbers with the paper's.
    site_path = root / 'index.html'
    site = site_path.read_text(encoding='utf-8') if site_path.is_file() else None
    return {'study': study, 'study_sha256': _sha256(study_path),
            'headline': json.loads(headline_path.read_text(encoding='utf-8')), 'headline_path': rel,
            'results': results, 'results_path': results_path, 'declaration': declaration,
            'universe_index': universe,
            'universe_index_sha256': _sha256(index_path) if universe is not None else None,
            'fetch_manifest': fetch,
            'fetch_manifest_path': manifest_path.relative_to(root).as_posix() if fetch is not None else None,
            'fetch_manifest_sha256': _sha256(manifest_path) if fetch is not None else None,
            'site_exhibits': site_exhibits(site) if site is not None else None,
            'site_sha256': _sha256(site_path) if site is not None else None,
            'preregistered': (root / 'docs' / 'PREREGISTRATION.md').is_file()}


# Site exhibits drawn as diagrams carry no data-exhibit name; they are matched by title.
SITE_DIAGRAMS = {'The pipeline': 'pipeline', 'Data splits': 'timeline'}


def site_exhibits(page):
    """[{n, name, title}] for every numbered exhibit of the site, in its order."""
    out = []
    for fig in re.finditer(r'<figure class="exhibit[^"]*" id="ex-(\d+)"(?: data-exhibit="(\w+)")?[^>]*>(.*?)</figure>',
                           page, re.S):
        head = re.search(r'<span class="ex-title">(.*?)</span>\s*(?:<span class="ex-sub">|</figcaption>)',
                         fig.group(3), re.S)
        title = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', head.group(1))).split()) if head else ''
        name = fig.group(2) or next((v for k, v in SITE_DIAGRAMS.items() if title.startswith(k)), None)
        out.append({'n': int(fig.group(1)), 'name': name, 'title': title})
    return out


def site_tokens(css_path=SITE_CSS):
    """The light-theme colour tokens of the site (the first :root block of site.css)."""
    css = pathlib.Path(css_path).read_text(encoding='utf-8')
    block = re.search(r':root\s*\{(.*?)\}', css, re.S)
    if block is None:
        raise PaperDataError('no :root block in assets/site.css')
    tokens = dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;', block.group(1)))
    need = ('ink', 'ink-2', 'ink-3', 'rule', 'rule-2', 'accent', 'sunk', 'series-1', 'series-2', 'series-3',
            'neutral-series', 'pos', 'neg', 'div-mid', 'grid', 'axis', 'ord-1', 'ord-2', 'ord-3', 'ord-4')
    missing = [t for t in need if t not in tokens]
    if missing:
        raise PaperDataError(f'assets/site.css :root lacks {missing}')
    return {k: tokens[k].lower() for k in need}


# ──────────────────────────────────────────────────────────────────────────────
# Derived values (the 'paper' namespace)
# ──────────────────────────────────────────────────────────────────────────────

def _zero_month_runs(months):
    """Longest run of consecutive zero-return months: (first ym, last ym) or None."""
    best, cur = None, []
    for m in months:
        if m['ret_pct'] == 0:
            cur.append(m['ym'])
            if best is None or len(cur) > len(best):
                best = list(cur)
        else:
            cur = []
    return (best[0], best[-1]) if best else None


def _flat_window(w):
    """A walk-forward window whose daily returns are all zero: no return and no drawdown."""
    return not w['ret_pct'] and not w.get('max_dd_pct')


def _clearing_windows(dev):
    """(first day, last day) of every rolling window whose +-1.96 SE band excludes zero."""
    roll, dates = dev['rolling_sharpe'], dev['daily']['dates']
    index_of = {d: i for i, d in enumerate(dates)}
    return [(dates[index_of[d] - roll['window'] + 1], d)
            for d, sr, lo, hi in zip(roll['dates'], roll['sharpe'], roll['lo'], roll['hi'])
            if sr is not None and (lo > 0 or hi < 0)]


def holdout_power(daily_net_pct, days=HOLDOUT_DAYS):
    """Minimum detectable annual Sharpe of a holdout of n days (80% power, one-sided at
    HOLM_FIRST_ALPHA: the level the better of the two confirmatory arms must reach).

    Two return shapes: the development returns' (skew, non-excess kurtosis, lag-1
    autocorrelation; the non-normal AR(1) variance of pairs_trading.power) and i.i.d.
    normal returns. Stated before any 2026 price is seen.
    """
    r = np.asarray(daily_net_pct, dtype=float) / 100.0
    rep = pw.power_report(r, periods=PERIODS)
    rho = float(_autocorrelations(r, 1)[0])
    ann = math.sqrt(PERIODS)
    rows = []
    for n in days:
        rows.append({'days': n,
                     'mde_shape': pw.minimum_detectable_sharpe(0.0, n, rep['skew'], rep['kurtosis'], rho,
                                                               alpha=HOLM_FIRST_ALPHA) * ann,
                     'mde_normal': pw.minimum_detectable_sharpe(0.0, n, alpha=HOLM_FIRST_ALPHA) * ann})
    return {'skew': rep['skew'], 'kurtosis': rep['kurtosis'], 'rho': rho, 'rows': rows}


def universe_snapshots(index):
    """Point-in-time membership snapshots from IWV's N-PORT filings (development years only).

    The index lists filings dated in the sealed holdout without their holdings; only
    snapshots before index['sealed_from'] are read.
    """
    if not index:
        return None
    sealed_from = index.get('sealed_from') or '2026-01-01'
    snaps = [s for s in index.get('snapshots') or [] if s['period_date'] < sealed_from]
    if not snaps:
        return None
    rows = [{'period': s['period_date'], 'equity': int(s['n_equity']), 'mapped': int(s['n_mapped']),
             'unmapped_weight_pct': 100.0 * (1.0 - float(s['mapped_value_share']))} for s in snaps]
    return {'rows': rows, 'sealed_from': sealed_from, 'fund': index.get('fund'),
            'n': len(rows), 'first': rows[0]['period'], 'last': rows[-1]['period'],
            'equity_min': min(r['equity'] for r in rows), 'equity_max': max(r['equity'] for r in rows),
            'unmapped_min_pct': min(r['unmapped_weight_pct'] for r in rows),
            'unmapped_max_pct': max(r['unmapped_weight_pct'] for r in rows)}


def fetch_coverage(manifest, names_file):
    """How much of the universe file has prices, from the run's price-fetch manifest.

    The manifest has one outcome per distinct symbol: 'ok', 'invalid' (unknown to the
    vendor), 'short' (too little history), 'not_found' or 'error:...' (the fetch failed).
    The run's own 'coverage' counts only failed fetches as missing; the paper reports the
    share that has prices.
    """
    if not manifest or not manifest.get('outcomes'):
        return None
    counts = collections.Counter(manifest['outcomes'].values())
    n = len(manifest['outcomes'])
    return {'symbols': n, 'rows_removed': (names_file or n) - n, 'ok': counts.get('ok', 0),
            'ok_pct': 100.0 * counts.get('ok', 0) / n,
            'errors': sum(v for k, v in counts.items() if k.startswith('error')),
            'invalid': counts.get('invalid', 0), 'short': counts.get('short', 0),
            'not_found': counts.get('not_found', 0)}


def power_both(daily_net_pct, iid):
    """The development sample's power under two assumptions about dependence.

    'iid' is the site's (assets/study.json, dev.power): non-normal IID returns. 'ar1' adds
    the sample's lag-1 autocorrelation through the AR(1) Sharpe variance of
    pairs_trading.power (critical values and track-record lengths at the null, the
    upper bound at the estimate).
    """
    r = np.asarray(daily_net_pct, dtype=float) / 100.0
    rep = pw.power_report(r, periods=PERIODS, alternatives=[a['sharpe'] for a in iid['alternatives']])
    alts = [{'sharpe': a['sharpe'], 'p_ge_iid': a['p_ge'], 'trl_iid': a['min_trl_years'],
             'p_ge_ar1': b['p_sr_at_least'], 'trl_ar1': b['min_trl_years']}
            for a, b in zip(iid['alternatives'], rep['alternatives'])]
    at = {a['sharpe']: a for a in alts}
    return {'rho': rep['rho'], 'se': rep['se_ann'], 'ucb': rep['upper_bound_ann'], 'mde': rep['min_detectable_sr_ann'],
            'critical': rep['critical_sr_ann'], 'alternatives': alts,
            'p_ge_0_5': at[0.5]['p_ge_ar1'], 'p_ge_1': at[1.0]['p_ge_ar1'],
            'trl_0_5': at[0.5]['trl_ar1'], 'trl_1': at[1.0]['trl_ar1']}


def drawdown(r):
    """Maximum drawdown of a daily return series and its length in trading days.

    (max drawdown in %, days from the peak to the trough, days from the peak until the
    peak is regained or None if it never is)
    """
    w = np.cumprod(1.0 + np.asarray(r, dtype=float))
    dd = w / np.maximum.accumulate(w) - 1.0
    trough = int(np.argmin(dd))
    peak = int(np.argmax(w[:trough + 1]))
    back = next((j for j in range(trough, len(w)) if w[j] >= w[peak]), None)
    return 100.0 * float(dd[trough]), trough - peak, (back - peak) if back is not None else None


def volatility_interval(r, block):
    """Annualised volatility, % a year, with its circular block-bootstrap 95% interval."""
    r = np.asarray(r, dtype=float)
    idx = _circular_block_indices(np.random.default_rng(BOOT_SEED), len(r), int(block), BOOT_RESAMPLES)
    boots = r[idx].std(axis=1, ddof=1) * math.sqrt(PERIODS) * 100
    return (float(r.std(ddof=1) * math.sqrt(PERIODS) * 100), float(np.percentile(boots, 2.5)),
            float(np.percentile(boots, 97.5)))


def mean_interval(mean_daily, t):
    """Annualised mean return, % a year, with the 95% interval of its Newey-West t-statistic."""
    se = abs(mean_daily / t) if t else float('nan')
    return tuple(100 * PERIODS * v for v in (mean_daily, mean_daily - 1.96 * se, mean_daily + 1.96 * se))


def performance(inp):
    """The performance summary: main backtest, walk-forward and the Gatev baseline.

    The main backtest and the Gatev baseline have daily series; the walk-forward is
    exported as summary statistics only, so its volatility is the one implied by its
    mean and Sharpe ratio and it has no volatility interval or drawdown length.
    """
    res, head = inp['results'], inp['headline']
    perf, sig = res['overall_performance'], res['significance']
    main_r = np.array([d['daily_return_pct'] for d in res['daily_equity_curve']]) / 100.0
    gatev = res['benchmarks']['distance_method']
    gatev_r = np.asarray(gatev['daily_returns'], dtype=float)
    blocks = {r['key']: re.search(r'block (\d+) days', r['method']) for r in inp['study']['dev']['forest']}
    wf = res['walk_forward_validation']
    out = {}
    for key, r, s in (('main', main_r, sig['main_backtest']), ('gatev', gatev_r, None)):
        h = s['hac'] if s else hac_tstat_mean(gatev_r)
        dd, to_trough, to_back = drawdown(r)
        out[key] = {'ret': mean_interval(h['mean'], h['tstat']), 'vol': volatility_interval(r, int(blocks[key].group(1))),
                    'max_dd': dd, 'dd_days': (to_trough, to_back), 'total': 100.0 * (float(np.prod(1.0 + r)) - 1.0)}
    o = sig['oos_daily']
    ret = mean_interval(o['hac']['mean'], o['hac']['tstat'])
    out['wf'] = {'ret': ret, 'vol': (ret[0] / o['ann_sharpe'] if o['ann_sharpe'] else None, None, None),
                 'max_dd': wf['max_drawdown_pct'], 'dd_days': (None, None), 'total': wf['stitched_total_return_pct']}
    out['main'].update(trades=perf['total_trades'], hit=perf['win_rate_pct'], hold=perf['avg_trading_days_held'],
                       turnover=perf['annual_turnover_x_equity'], gross=perf['avg_gross_exposure_pct_of_equity'],
                       ret_gross=out['main']['ret'][0] / (perf['avg_gross_exposure_pct_of_equity'] / 100.0))
    out['wf'].update(trades=wf['total_trades'], hit=wf['win_rate_pct'], hold=None, turnover=None, gross=None,
                     ret_gross=None)
    out['gatev'].update(trades=gatev['n_trades'], hit=None, hold=gatev['avg_holding_days'], turnover=None, gross=None,
                        ret_gross=None)
    out['days'] = {'main': len(main_r), 'wf': o['n_days'], 'gatev': len(gatev_r)}
    out['sharpe'] = {'main': (head['significance']['main']['ann_sharpe'], head['significance']['main']['boot_lo'],
                              head['significance']['main']['boot_hi']),
                     'wf': (head['significance']['oos_daily']['ann_sharpe'], head['significance']['oos_daily']['boot_lo'],
                            head['significance']['oos_daily']['boot_hi'])}
    return out


def trade_edge(trades):
    """Gross and cost per trade on one basis: dollars over traded notional (signal-day size).

    The ratio of sums is the basis on which net P&L breaks even (gross / cost dollars);
    the t-statistic is that of the mean gross dollar P&L per trade.
    """
    if not trades:
        return None
    notional = sum(t['position_size_dollars'] for t in trades)
    cost = np.array([t['transaction_costs_dollars'] for t in trades])
    gross = np.array([t['net_pnl_dollars'] for t in trades]) + cost
    t_gross = float(gross.mean() / (gross.std(ddof=1) / math.sqrt(len(gross))))
    return {'gross_bp': 1e4 * gross.sum() / notional, 'cost_bp': 1e4 * cost.sum() / notional,
            'net_bp': 1e4 * (gross.sum() - cost.sum()) / notional, 'gross_t': t_gross}


def sign_exceptions(trades):
    """Trades whose net notional sign is not the one their hedge ratio implies.

    With legs of $1 and $beta, beta < 1 leaves a long-spread trade net long and a
    short-spread trade net short; share rounding at the fill can reverse a beta near one.
    """
    out = []
    for t in trades:
        if t.get('hedge_ratio') is None:
            continue
        net_long = t['long_notional_dollars'] > t['short_notional_dollars']
        if net_long != ((t['action'] == 'LONG') == (t['hedge_ratio'] < 1)):
            out.append(t['hedge_ratio'])
    return out


def derived(inp):
    """The 'paper' namespace: values the paper states that the site file holds only implicitly."""
    study, head = inp['study'], inp['headline']
    dev = study['dev']
    run = dev['run']
    calendar = CALENDARS['dev']
    months = dev['monthly']
    best = max(months, key=lambda m: m['ret_pct']) if months else None
    flat = _zero_month_runs(months)
    clearing = _clearing_windows(dev)
    sn = dev.get('snooping') or {}
    res = study.get('residual') or {}
    hold = study.get('holdout') or {}
    val = study.get('validation') or {}
    schedules = dev.get('cost_schedules') or []
    neg = [s for s in schedules if (s['ret_pct'] or 0) < 0]
    nonneg = [s for s in schedules if (s['ret_pct'] or 0) >= 0]
    forest = {r['key']: r for r in dev['forest']}
    snaps = universe_snapshots(inp['universe_index'])
    power = holdout_power(dev['daily']['net'])
    # the note's date: its newest dated input (the newest run behind study.json, or the
    # declaration of the variant family), never the build machine's clock
    dated = [study['meta']['generated_utc'][:10], (sn.get('declared_utc') or '')[:10]]
    paper_date = max(d for d in dated if d)
    version = run['version'] or head.get('version')
    snoop = sn.get('results') or {}
    trades = inp['results'].get('all_trades') or []
    long_t = [x for x in trades if x['action'] == 'LONG']
    short_t = [x for x in trades if x['action'] == 'SHORT']
    funds = head.get('fund_profiles') or {}
    ranked = sorted(schedules, key=lambda x: funds.get(x['source_key'], {}).get('total_return_pct', x['ret_pct']))
    boot = re.search(r'\((\d+) resamples, block (\d+) days\)', forest['main']['method'])
    boot_oos = re.search(r'block (\d+) days', forest['oos']['method'])
    diff_oos = forest.get('diff_oos') or {}
    export = inp['results']
    names_file = _get(dev, 'funnel', 'names', default=[{}])[0].get('n')
    fetch = fetch_coverage(inp['fetch_manifest'], names_file)
    power2 = power_both(dev['daily']['net'], dev['power'])
    edge = trade_edge(trades)
    exceptions = sign_exceptions(trades)
    wf_windows = export['walk_forward_validation']['windows']
    vs_wf = _get(export, 'benchmarks', 'vs_strategy', 'walk_forward_oos', default={})
    ranker = export.get('ranker') or {}
    net = np.asarray(dev['daily']['net'], dtype=float)
    exposure = np.asarray(dev['daily']['exposure'], dtype=float)
    compounded = float(np.prod([1 + m['ret_pct'] / 100 for m in months])) if months else None
    fdr = head['fdr']
    pos = [x['position_pct_of_equity'] for x in trades if x.get('position_pct_of_equity') is not None]
    return {
        'paper_date': paper_date, 'paper_date_long': long_date(paper_date),
        'run_date_long': long_date(run['timestamp_utc']),
        'run_time': run['timestamp_utc'][:16].replace('T', ' ') + ' UTC',
        'version': version, 'versions_count': int(str(version).split('.')[0]),
        'commit': run['commit'][:12], 'commit_short': run['commit'][:7],
        'clean': 'clean' if run['dirty'] is False else 'uncommitted changes',
        'years': f"{run['period'][0][:4]}–{run['period'][1][:4]}",
        'data_years': f"{run['data_span'][0][:4]}–{run['data_span'][1][:4]}",
        'data_first_year': run['data_span'][0][:4], 'formation_year': calendar.selection_cutoff[:4],
        'holdout_year': hold['calendar_start'][:4] if hold.get('calendar_start') else None,
        'period_start_long': long_date(run['period'][0]), 'period_end_long': long_date(run['period'][1]),
        'period_start_month': month_name(run['period'][0]), 'period_end_month': month_name(run['period'][1]),
        'oos_start_month': month_name(run['oos_period'][0]), 'oos_end_month': month_name(run['oos_period'][1]),
        'data_start_long': long_date(run['data_span'][0]), 'data_end_long': long_date(run['data_span'][1]),
        'formation_cutoff_long': long_date(calendar.selection_cutoff),
        'formation_cutoff_short': short_date(calendar.selection_cutoff),
        'universe_as_of_long': long_date(run['universe_as_of']) if run.get('universe_as_of') else None,
        'holdout_start_long': long_date(hold['calendar_start']) if hold.get('calendar_start') else None,
        'declared_long': long_date(sn['declared_utc']) if sn.get('declared_utc') else None,
        'best_month': month_name(best['ym']) if best else None,
        'flat_from': month_name(flat[0]) if flat else None, 'flat_to': month_name(flat[1]) if flat else None,
        'percentile_ordinal': ordinal(dev['random_percentile']) if dev.get('random_percentile') is not None else None,
        'names_file': _get(dev, 'funnel', 'names', default=[{}])[0].get('n'),
        'names_prices': run['symbols'],
        'universe_top': PROFILES['v32'].max_universe,
        'schedules_n': len(schedules), 'schedules_n_word': word(len(schedules)),
        'schedules_lose_word': word(len(neg)), 'schedules_even_word': word(len(nonneg)),
        'clear_first_end_long': long_date(clearing[0][1]) if clearing else None,
        'clear_last_end_long': long_date(clearing[-1][1]) if clearing else None,
        'holdout': {'status': hold.get('status'), 'sharpe': hold.get('sharpe'), 'lo': hold.get('lo'),
                    'hi': hold.get('hi'), 'p': hold.get('p'), 'trades': hold.get('trades'), 'ret_pct': hold.get('ret_pct')},
        'residual': {'sharpe': res.get('sharpe'), 'lo': res.get('lo'), 'hi': res.get('hi'), 'p': res.get('p'),
                     'trades': res.get('trades'), 'ret_pct': res.get('ret_pct')},
        'snooping': {'spa_p': snoop.get('spa_p'), 'reality_check_p': snoop.get('reality_check_p'),
                     'romano_wolf_rejected': len(snoop['romano_wolf_rejected']) if snoop else None,
                     'mcs_included': len(snoop['mcs_included']) if snoop else None,
                     'effective_trials': snoop.get('effective_trials'),
                     'pbo_pct': 100 * snoop['pbo'] if snoop.get('pbo') is not None else None},
        'validation': {'present': bool(val)},
        'iwv': ({'n': snaps['n'], 'first_long': long_date(snaps['first']), 'last_long': long_date(snaps['last']),
                 'equity_min': snaps['equity_min'], 'equity_max': snaps['equity_max'],
                 'unmapped_min_pct': snaps['unmapped_min_pct'], 'unmapped_max_pct': snaps['unmapped_max_pct'],
                 'sealed_from_long': long_date(snaps['sealed_from'])} if snaps else None),
        'holdout_power_rows': power['rows'],
        'holdout_power': {'rho': power['rho'], 'skew': power['skew'], 'kurtosis': power['kurtosis'],
                          'registered_days': HOLDOUT_DAYS[1],
                          **{f"mde_{r['days']}": r['mde_shape'] for r in power['rows']},
                          **{f"mde_normal_{r['days']}": r['mde_normal'] for r in power['rows']}},
        'v33_universe_top': PROFILES['v33'].max_universe,
        'v33_reselect_every': PROFILES['v33'].reselect_every,
        'v32_reselect_every': PROFILES['v32'].reselect_every,
        'v33_borrow_pct': 100 * PROFILES['v33'].borrow_rate,
        'v32_borrow_bp': 1e4 * PROFILES['v32'].borrow_rate, 'v32_financing_bp': 1e4 * PROFILES['v32'].pb_financing_spread,
        'v33_formation_years': PROFILES['v33'].formation_calendar_days / 365,
        'prereg_status': 'filed' if inp['preregistered'] else 'not yet filed',
        'results_path': inp['results_path'], 'run_dir': inp['results_path'].rsplit('/', 1)[0],
        'beta_below_one': sum(1 for x in trades if x.get('hedge_ratio') is not None and x['hedge_ratio'] < 1),
        'long_trades': len(long_t), 'short_trades': len(short_t),
        'long_net_long': sum(1 for x in long_t if x['long_notional_dollars'] > x['short_notional_dollars']),
        'short_net_short': sum(1 for x in short_t if x['short_notional_dollars'] > x['long_notional_dollars']),
        'boot_resamples': int(boot.group(1)) if boot else None,
        'boot_block_main': int(boot.group(2)) if boot else None,
        'boot_block_oos': int(boot_oos.group(1)) if boot_oos else None,
        'diff_oos': diff_oos.get('sharpe'), 'diff_oos_p': diff_oos.get('p'),
        'sched_best_id': ranked[-1]['id'] if ranked else None,
        'sched_worst_id': ranked[0]['id'] if ranked else None,
        'sched_best_ret': _get(funds, ranked[-1]['source_key'], 'total_return_pct') if ranked else None,
        'sched_worst_ret': _get(funds, ranked[0]['source_key'], 'total_return_pct') if ranked else None,
        'proxy': dev['factors'].get('proxy'),
        'iwv_unmapped_first_pct': snaps['rows'][0]['unmapped_weight_pct'] if snaps else None,
        'iwv_unmapped_last_pct': snaps['rows'][-1]['unmapped_weight_pct'] if snaps else None,
        'iwv_first_year': snaps['first'][:4] if snaps else None, 'iwv_last_year': snaps['last'][:4] if snaps else None,
        # the universe file and what share of it has prices (the run's fetch manifest)
        'fetch': fetch,
        'v32_formation_years': PROFILES['v32'].formation_calendar_days / 365,
        # power under IID returns (the site's) and allowing lag-1 autocorrelation
        'power_ar1': power2,
        # gross and cost per trade, notional-weighted (the break-even basis)
        'edge': edge,
        'sign_exceptions': len(exceptions), 'sign_exceptions_word': word(len(exceptions)),
        'sign_exception_max_gap': max((abs(b - 1) for b in exceptions), default=0.0),
        # Lo (2002) autocorrelation-adjusted annualisation of the Sharpe ratio
        'lo_sharpe_main': _get(export, 'significance', 'main_backtest', 'ann_sharpe_lo'),
        'lo_sharpe_oos': _get(export, 'significance', 'oos_daily', 'ann_sharpe_lo'),
        # factor-attribution t-statistics at full precision (study.json rounds them to 3 dp)
        'alpha_t_main': _get(export, 'factor_attribution', 'main_backtest', 'alpha_tstat'),
        'alpha_t_oos': _get(export, 'factor_attribution', 'walk_forward_oos', 'alpha_tstat'),
        'ranker_brier_pooled': _get(ranker, 'walk_forward_pooled_out_of_sample', 'brier'),
        'ranker_brier_base_pooled': _get(ranker, 'walk_forward_pooled_out_of_sample', 'brier_base_rate'),
        'position_min_pct': min(pos) if pos else None, 'position_max_pct': max(pos) if pos else None,
        # the walk-forward: the last window runs to the walk-forward's last day
        'wf_window_days': wf_windows[0]['n_days'], 'wf_last_days': wf_windows[-1]['n_days'],
        'wf_days': {w['window']: w['n_days'] for w in wf_windows},
        # windows (numbered 1..N in the paper) that opened no trade yet carried P&L, and
        # windows whose daily returns are all zero (no Sharpe ratio)
        'wf_carry_windows': ', '.join(str(i) for i, w in enumerate(dev['walk_forward']['windows'], 1)
                                      if not w['trades'] and w['ret_pct']),
        'wf_flat_windows': ', '.join(str(i) for i, w in enumerate(dev['walk_forward']['windows'], 1)
                                     if _flat_window(w)),
        'oos_end_long': long_date(run['oos_period'][1]),
        'gatev_wf_sharpe': vs_wf.get('distance_sharpe'), 'wf_common_sharpe': vs_wf.get('strategy_sharpe'),
        'wf_common_days': vs_wf.get('n_common_days'),
        'performance': performance(inp),
        # the month that carries the result, and the period without it
        'without_best_pct': 100 * (compounded / (1 + best['ret_pct'] / 100) - 1) if best else None,
        'compounded_pct': 100 * (compounded - 1) if compounded is not None else None,
        # chance rejections among the "cointegrated" pairs: an upper bound (every pair null)
        'chance_share_pct': 100 * dev['funnel']['pairs'][1]['expected'] / fdr['significant_raw_p05'],
        'zero_return_days': int((net == 0).sum()),
        'flat_nonzero_days': int(((exposure == 0) & (net != 0)).sum()),
        # how much longer than the minimum track record 80% power takes (normal approximation)
        'trl_power_ratio': ((_Z95 + _Z80) / _Z95) ** 2,
        'gatev_vol_pct': _get(export, 'benchmarks', 'distance_method', 'ann_volatility_pct'),
        'main_vol_pct': _get(export, 'overall_performance', 'annualized_volatility_pct'),
    }


# ──────────────────────────────────────────────────────────────────────────────
# The numbers the text quotes: key -> format (a key resolves like the publication
# checker's: into the headline JSON, 'study.' into assets/study.json, 'paper.' into
# derived() above). 'str' passes a text value through.
# ──────────────────────────────────────────────────────────────────────────────

METRICS = {
    # headline JSON (the checker's source)
    'main.total_return_pct': '.2%', 'main.sharpe': '.2', 'main.trades': '.0', 'main.win_rate_pct': '.1%',
    'main.max_drawdown_pct': '.2%', 'main.avg_gross_exposure_pct': '.1%', 'main.annual_turnover_x': '.1×',
    'main.exit_reasons.stop': '.0', 'main.exit_reasons.target': '.0', 'main.exit_reasons.time': '.0',
    'main.exit_reasons.end_of_data': '.0',
    'ranker.oos_auc': '.3', 'ranker.wf_pooled_auc': '.3',
    'oos.windows': '.0', 'oos.windows_positive': '.0', 'oos.windows_no_trades': '.0', 'oos.trades': '.0',
    'oos.avg_window_return_pct': '.3%', 'oos.pooled_sharpe': '.2', 'oos.total_return_pct': '.2%',
    'significance.main.ann_sharpe': '.2', 'significance.main.hac_t': '.2', 'significance.main.hac_p': '.3',
    'significance.main.psr_pct': '.1%', 'significance.main.dsr_pct': '.1%',
    'significance.main.boot_lo': '.2', 'significance.main.boot_hi': '+.2',
    'significance.oos_daily.ann_sharpe': '.2', 'significance.oos_daily.hac_t': '.2',
    'significance.oos_daily.hac_p': '.3', 'significance.oos_daily.psr_pct': '.1%',
    'significance.oos_daily.dsr_pct': '.1%', 'significance.oos_daily.boot_lo': '.2',
    'significance.oos_daily.boot_hi': '+.2',
    'significance.oos_windows.ci_lo_pct': '.3%', 'significance.oos_windows.ci_hi_pct': '+.3%',
    'significance.oos_windows.p': '.3', 'significance.oos_windows.t': '.2',
    'benchmarks.gatev.total_return_pct': '+.2%', 'benchmarks.gatev.sharpe': '+.2',
    'benchmarks.random_control.median_sharpe': '+.2', 'benchmarks.random_control.p5_sharpe': '+.2',
    'benchmarks.random_control.p95_sharpe': '+.2', 'benchmarks.random_control.n_draws': '.0',
    'benchmarks.random_control.strategy_percentile': '.0',
    'benchmarks.sharpe_diff_vs_gatev.diff': '.2', 'benchmarks.sharpe_diff_vs_gatev.p': '.3',
    'fdr.pairs_tested': ',.0', 'fdr.significant_raw_p05': ',.0', 'fdr.survive_bh_fdr_q05': '.0',
    'fdr.final_selected_pairs': ',.0',
    'fund_profiles.institutional.total_return_pct': '+.2%', 'fund_profiles.fundamental_ls.total_return_pct': '.2%',
    # assets/study.json: facts the site quotes
    **{f'study.dev.facts.{k}': v for k, v in {
        'gross_bp': '+.1', 'gross_t': '.2', 'cost_bp': '.1', 'net_bp': '.1', 'sharpe_ucb': '.2', 'sharpe_se': '.2',
        'sharpe_mde': '.2', 'sharpe_critical': '.2', 'oos_days': '.0', 'main_days': '.0', 'dsr_trials': '.0',
        'break_even_x': '.2×', 'capital_musd': '.0', 'flat_days': '.0', 'days': '.0',
        'exposure_max_pct': '.2%', 'best_month_pct': '+.2%', 'months_positive': '.0', 'months': '.0',
        'gate_blocked_days': '.0', 'rolling_min': '.1', 'rolling_max': '+.1', 'rolling_clear_zero': '.0',
        'rolling_windows': '.0', 'p_sr_ge_1': '.3', 'p_sr_ge_0_5': '.3', 'min_trl_years_0_5': '.1',
        'min_trl_years_1': '.1', 'gatev_lo': '.2', 'gatev_hi': '+.2', 'gross_usd_k': '.1', 'cost_usd_k': '.1',
        'net_usd_k': '.1', 'impact_share_pct': '.1%', 'market_impact_usd_k': '.1', 'bid_ask_usd_k': '.1',
        'commission_usd_k': '.1', 'borrow_usd_k': '.1', 'financing_usd_k': '.1',
        'stop_loss_usd_m': '.2', 'target_gain_usd_m': '.2', 'gross_bp_capital': '.1', 'cost_bp_capital': '.1',
        'net_bp_capital': '.1', 'cost_bp_notional': '.2', 'long_gain_usd_m': '.2', 'short_loss_usd_m': '.2',
        'wins': '.0', 'trades': '.0', 'win_lo_pct': '.1', 'win_hi_pct': '.1%', 'hold_days': '.1',
        'adv_participation_pct': '.2%', 'beta_main': '.3', 'beta_main_t': '.2', 'beta_oos': '.3',
        'beta_oos_t': '.2', 'alpha_main_pct': '.2%', 'alpha_oos_pct': '.2%', 'kurtosis': '.1', 'skew': '.2',
        'pairs_traded': '.0', 'oos_overlap_days': '.0', 'coverage_pct': '.1%', 'positions_max': '.0',
        'flat_pct': '.0%',
    }.items()},
    'study.dev.snooping.grid_points': '.0', 'study.dev.snooping.toggles': '.0',
    'study.dev.funnel.pairs.1.expected': ',.0', 'study.dev.funnel.bh_q10': '.0',
    'study.dev.factors.alpha.0.t': '.2', 'study.dev.factors.alpha.1.t': '.2',
    'study.dev.rolling_sharpe.window': '.0',
    # derived ('paper.')
    **{f'paper.{k}': 'str' for k in (
        'paper_date_long', 'run_date_long', 'run_time', 'version', 'commit', 'commit_short', 'clean', 'years',
        'data_years', 'period_start_long', 'period_end_long', 'period_start_month', 'period_end_month',
        'oos_start_month', 'oos_end_month', 'data_start_long', 'data_end_long', 'formation_cutoff_long',
        'universe_as_of_long', 'formation_cutoff_short', 'holdout_start_long', 'declared_long', 'best_month', 'flat_from', 'flat_to',
        'percentile_ordinal', 'data_first_year', 'formation_year', 'holdout_year', 'clear_first_end_long', 'clear_last_end_long', 'schedules_n_word',
        'results_path', 'run_dir', 'sched_best_id', 'sched_worst_id', 'proxy', 'iwv_first_year', 'iwv_last_year', 'schedules_lose_word', 'schedules_even_word',
        'prereg_status', 'iwv.first_long', 'iwv.last_long', 'iwv.sealed_from_long', 'oos_end_long',
        'sign_exceptions_word', 'wf_carry_windows', 'wf_flat_windows')},
    'paper.fetch.symbols': ',.0', 'paper.fetch.rows_removed': '.0', 'paper.fetch.ok': ',.0',
    'paper.fetch.ok_pct': '.1%', 'paper.fetch.errors': '.0', 'paper.fetch.invalid': '.0', 'paper.fetch.short': '.0',
    'paper.v32_formation_years': '.0',
    'paper.power_ar1.rho': '.2', 'paper.power_ar1.se': '.2', 'paper.power_ar1.ucb': '.2', 'paper.power_ar1.mde': '.2',
    'paper.power_ar1.critical': '.2', 'paper.power_ar1.p_ge_0_5': '.3', 'paper.power_ar1.p_ge_1': '.3',
    'paper.power_ar1.trl_0_5': '.1', 'paper.power_ar1.trl_1': '.1',
    'paper.edge.gross_bp': '+.1', 'paper.edge.cost_bp': '.1', 'paper.edge.net_bp': '.1', 'paper.edge.gross_t': '.2',
    'paper.lo_sharpe_main': '.2', 'paper.lo_sharpe_oos': '.2', 'paper.alpha_t_main': '.2', 'paper.alpha_t_oos': '.2',
    'paper.ranker_brier_pooled': '.4', 'paper.ranker_brier_base_pooled': '.4',
    'paper.position_min_pct': '.1%', 'paper.position_max_pct': '.1%',
    'paper.wf_window_days': '.0', 'paper.wf_last_days': '.0',
    'paper.gatev_wf_sharpe': '+.2', 'paper.wf_common_sharpe': '.2', 'paper.wf_common_days': '.0',
    'paper.without_best_pct': '+.2%', 'paper.compounded_pct': '+.2%', 'paper.chance_share_pct': '.0%',
    'paper.zero_return_days': '.0', 'paper.flat_nonzero_days': '.0',
    'paper.gatev_vol_pct': '.2%', 'paper.main_vol_pct': '.2%', 'paper.trl_power_ratio': '.1',
    'paper.versions_count': '.0', 'paper.names_file': ',.0', 'paper.names_prices': ',.0',
    'paper.universe_top': '.0', 'paper.v33_universe_top': '.0', 'paper.v33_reselect_every': '.0',
    'paper.v32_reselect_every': '.0', 'paper.v33_borrow_pct': '.2%', 'paper.v32_borrow_bp': '.0',
    'paper.v32_financing_bp': '.0', 'paper.v33_formation_years': '.0',
    'paper.iwv.n': '.0', 'paper.iwv.equity_min': ',.0', 'paper.iwv.equity_max': ',.0',
    'paper.iwv.unmapped_min_pct': '.1%', 'paper.iwv.unmapped_max_pct': '.1%',
    'paper.iwv_unmapped_first_pct': '.1%', 'paper.iwv_unmapped_last_pct': '.1%',
    'paper.beta_below_one': '.0', 'paper.long_trades': '.0', 'paper.short_trades': '.0',
    'paper.long_net_long': '.0', 'paper.short_net_short': '.0', 'paper.boot_resamples': ',.0',
    'paper.boot_block_main': '.0', 'paper.boot_block_oos': '.0', 'paper.diff_oos': '.2', 'paper.diff_oos_p': '.3',
    'paper.sched_best_ret': '+.2%', 'paper.sched_worst_ret': '.2%',
    'paper.holdout_power.registered_days': '.0', 'paper.holdout_power.rho': '.2', 'paper.holdout_power.skew': '.2', 'paper.holdout_power.kurtosis': '.1',
    **{f'paper.holdout_power.mde_{n}': '.1' for n in HOLDOUT_DAYS},
    **{f'paper.holdout_power.mde_normal_{n}': '.1' for n in HOLDOUT_DAYS},
    'paper.holdout.sharpe': '.2', 'paper.holdout.lo': '.2', 'paper.holdout.hi': '+.2', 'paper.holdout.p': '.3',
    'paper.residual.sharpe': '.2', 'paper.residual.lo': '.2', 'paper.residual.hi': '+.2', 'paper.residual.p': '.3',
    'paper.residual.trades': ',.0', 'paper.residual.ret_pct': '.2%',
    'paper.snooping.spa_p': '.3', 'paper.snooping.reality_check_p': '.3', 'paper.snooping.romano_wolf_rejected': '.0',
    'paper.snooping.mcs_included': '.0', 'paper.snooping.effective_trials': '.1', 'paper.snooping.pbo_pct': '.1%',
}

# A null is allowed only for results that do not exist yet; its reason prints in its place.
PENDING = {
    'paper.holdout.': 'pending (sealed until the pre-registration is filed)',
    'paper.residual.': 'pending (v33 development run)',
    'paper.snooping.': 'pending (v33 development run)',
    'paper.iwv': 'pending (point-in-time universe index)',
    'paper.fetch.': 'pending (price-fetch manifest)',
}


def resolve(data, key):
    """Value at a dotted path (dict keys or list indices). KeyError if a step is absent."""
    cur = data
    for part in key.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif cur is None:
            return None                # a whole optional section is absent (e.g. paper.iwv)
        else:
            raise KeyError(key)
    return cur


def pending_reason(key):
    return next((why for prefix, why in PENDING.items() if key.startswith(prefix)), None)


def format_metrics(data):
    """{key: formatted text or None}, {key: reason} for the None entries."""
    out, why = {}, {}
    for key, spec in METRICS.items():
        value = resolve(data, key)
        text = (None if value is None else str(value)) if spec == 'str' else fmt(value, spec)
        if text is None:
            reason = pending_reason(key)
            if reason is None:
                raise PaperDataError(f'{key} is null in the inputs but is not a pending result')
            why[key] = reason
        out[key] = text
    return out, why


# ──────────────────────────────────────────────────────────────────────────────
# Claims: statements of the prose whose truth depends on the data. main.typ asserts
# each one it makes (#claim("name")); a false claim stops the compile.
# ──────────────────────────────────────────────────────────────────────────────

def claims(data):
    head, study, P = data, data['study'], data['paper']
    dev, facts = study['dev'], study['dev']['facts']
    forest = {r['key']: r for r in dev['forest']}
    ci_rows = [r for r in dev['forest'] if r['kind'] in ('ci', 'diff')]
    groups = {g['label']: g for k in ('by_exit', 'by_side') for g in dev['trades'][k]}
    steps = {s['key']: s['usd'] for s in dev['waterfall']}
    costs = {k: -v for k, v in steps.items() if k not in ('gross', 'net')}
    best = max(dev['monthly'], key=lambda m: m['ret_pct'])
    clearing = _clearing_windows(dev)
    schedules = dev.get('cost_schedules') or []
    nonneg = [s for s in schedules if s['ret_pct'] >= 0]
    rnd = head['benchmarks']['random_control']
    sig = head['significance']
    ar1, edge = P['power_ar1'], P['edge']
    ar1_at = {a['sharpe']: a for a in ar1['alternatives']}
    return {
        # gross edge per trade, on both bases the text quotes
        'edge_not_significant': abs(edge['gross_t']) < 1.96 and abs(facts['gross_t']) < 1.96,
        'edge_below_cost': edge['gross_bp'] < edge['cost_bp'] and facts['gross_bp'] < facts['cost_bp'],
        'break_even_is_edge_over_cost': abs(edge['gross_bp'] / edge['cost_bp'] - facts['break_even_x']) < 0.01,
        # power under IID returns and allowing lag-1 autocorrelation
        'sharpe_1_borderline_both': 0.01 < facts['p_sr_ge_1'] < 0.10 and 0.01 < ar1['p_ge_1'] < 0.10,
        'sharpe_1_rejected_only_if_iid': facts['p_sr_ge_1'] < 0.05 <= ar1['p_ge_1'],
        'both_reject_sharpe_1_5_and_2': all(a['p_ge'] < 0.05 for a in dev['power']['alternatives'] if a['sharpe'] >= 1.5)
                                        and all(a['p_ge_ar1'] < 0.05 for x, a in ar1_at.items() if x >= 1.5),
        'both_cannot_reject_sharpe_half': facts['p_sr_ge_0_5'] > 0.05 and ar1['p_ge_0_5'] > 0.05,
        'both_bounds_about_one': all(0.75 <= u <= 1.25 for u in (facts['sharpe_ucb'], ar1['ucb'])),
        'both_mde_above_bound': facts['sharpe_mde'] > facts['sharpe_ucb'] and ar1['mde'] > ar1['ucb'],
        'dependence_widens': ar1['se'] > facts['sharpe_se'] and ar1['ucb'] > facts['sharpe_ucb'],
        'without_best_month_lower': P['without_best_pct'] < head['main']['total_return_pct'] < best['ret_pct'],
        'sign_exceptions_near_one': P['sign_exception_max_gap'] < 0.05,
        'fetch_ok_is_price_history': P['fetch'] is None or P['fetch']['ok'] == P['names_prices'],
        'last_window_longer': P['wf_last_days'] > P['wf_window_days'],
        'flat_days_reconcile': P['zero_return_days'] + P['flat_nonzero_days'] == facts['flat_days'],
        'ranker_brier_worse_than_base': P['ranker_brier_pooled'] > P['ranker_brier_base_pooled'],
        # "the 1,775 expected by chance and the 1,776 selected are close by coincidence"
        'chance_count_near_selected': abs(dev['funnel']['pairs'][1]['expected'] - head['fdr']['final_selected_pairs'])
                                      <= 0.01 * head['fdr']['final_selected_pairs'],
        'wf_carry_window_exists': bool(P['wf_carry_windows']),
        'wf_flat_window_exists': bool(P['wf_flat_windows']),
        'main_negative': head['main']['total_return_pct'] < 0,
        'oos_negative': head['oos']['pooled_sharpe'] < 0,
        'every_interval_spans_zero': all(r['lo'] < 0 < r['hi'] for r in ci_rows),
        'main_ci_spans_zero': sig['main']['boot_lo'] < 0 < sig['main']['boot_hi'],
        'oos_ci_spans_zero': sig['oos_daily']['boot_lo'] < 0 < sig['oos_daily']['boot_hi'],
        'not_different_from_gatev': head['benchmarks']['sharpe_diff_vs_gatev']['p'] > 0.05
                                    and all(r['p'] > 0.05 for r in dev['forest'] if r['kind'] == 'diff'),
        'inside_random_spread': rnd['p5_sharpe'] < head['main']['sharpe'] < rnd['p95_sharpe']
                                and 5 < rnd['strategy_percentile'] < 95,
        'gatev_above_strategy': forest['gatev']['sharpe'] > forest['main']['sharpe'],
        'gross_not_significant': abs(facts['gross_t']) < 1.96,
        'gross_below_cost': facts['gross_bp'] < facts['cost_bp'],
        'gross_pnl_below_costs': facts['gross_usd_k'] < facts['cost_usd_k'],
        'break_even_below_one': facts['break_even_x'] is not None and facts['break_even_x'] < 1,
        'impact_largest_cost': max(costs, key=costs.get) == 'market_impact',
        'stops_lost_more_than_targets_earned': -groups['Stop']['net_usd'] > groups['Target']['net_usd'],
        'long_gained_short_lost': groups['Long spread']['net_usd'] > 0 > groups['Short spread']['net_usd'],
        'short_loss_near_long_gain': 2 / 3 <= -groups['Short spread']['net_usd'] / groups['Long spread']['net_usd'] <= 1.5,
        'most_hedge_ratios_below_one': P['beta_below_one'] > 0.5 * facts['trades'],
        'sides_carry_their_sign': P['long_net_long'] > 0.5 * P['long_trades'] and P['short_net_short'] > 0.5 * P['short_trades'],
        'best_month_exceeds_total': best['ret_pct'] > head['main']['total_return_pct'],
        'clearing_windows_contain_best_month': bool(clearing) and all(
            a <= best['ym'] + '-31' and b >= best['ym'] + '-01' for a, b in clearing),
        'no_schedule_significant': all(s['sharpe'] < facts['sharpe_critical'] for s in schedules),
        'ucb_below_one': facts['sharpe_ucb'] < 1.0,
        'dsr_low': sig['main']['dsr'] < 0.05 and sig['oos_daily']['dsr'] < 0.05,
        'beta_small': abs(facts['beta_main']) < 0.05 and abs(facts['beta_oos']) < 0.05,
        'beta_oos_significant': abs(facts['beta_oos_t']) > 1.96,
        'beta_main_not_significant': abs(facts['beta_main_t']) < 1.96,
        'alpha_negative': facts['alpha_main_pct'] < 0 and facts['alpha_oos_pct'] < 0,
        'alpha_not_significant': all(abs(a['t']) < 1.96 for a in dev['factors']['alpha']),
        'iwv_gap_shrinks': P['iwv'] is not None and P['iwv_unmapped_first_pct'] > P['iwv_unmapped_last_pct'],
        'excess_cointegration': head['fdr']['significant_raw_p05'] > dev['funnel']['pairs'][1]['expected'],
        'chance_accounts_for_most': dev['funnel']['pairs'][1]['expected'] > 0.5 * head['fdr']['significant_raw_p05'],
        'bh_survivors_few': head['fdr']['survive_bh_fdr_q05'] < 0.01 * head['fdr']['significant_raw_p05'],
        'ranker_no_skill': head['ranker']['oos_auc'] < 0.55 and head['ranker']['wf_pooled_auc'] < 0.55,
        'schedules_some_lose_rest_break_even': len(schedules) > len(nonneg) >= 1
                                               and all(abs(s['ret_pct']) < 0.1 for s in nonneg),
        'best_schedule_cheapest': bool(schedules) and (
            min(schedules, key=lambda s: s['cost_pct'])['id'] == P['sched_best_id']
            and min(schedules, key=lambda s: s['position_pct'][1])['id'] == P['sched_best_id']),
        'kurtosis_fat': facts['kurtosis'] > 3,
        'flat_run_exists': _zero_month_runs(dev['monthly']) is not None,
        'holdout_sealed': (study.get('holdout') or {}).get('status') == 'sealed',
        'residual_pending': study.get('residual') is None,
        'snooping_pending': (dev.get('snooping') or {}).get('results') is None,
        'validation_pending': study.get('validation') is None,
        'gross_split_pending': dev.get('cost_curve') is None,
        'universe_not_point_in_time': dev.get('universe_by_formation') is None,
        'multi_factor_pending': not dev['factors']['multi_factor'],
    }


def flags(data):
    """Which optional results exist: main.typ words its notes by these (no assertion)."""
    study = data['study']
    dev = study['dev']
    return {'random_band': dev.get('random_band') is not None,
            'wf_daily': bool(dev['walk_forward'].get('daily')),
            'cost_split': dev.get('cost_curve') is not None,
            'snooping': (dev.get('snooping') or {}).get('results') is not None,
            'residual': study.get('residual') is not None,
            'validation': study.get('validation') is not None,
            'holdout_complete': (study.get('holdout') or {}).get('status') == 'complete',
            'universe_pit': dev.get('universe_by_formation') is not None,
            'multi_factor': bool(dev['factors'].get('multi_factor')),
            'iwv': data['paper']['iwv'] is not None,
            'preregistered': data['paper']['prereg_status'] == 'filed',
            'fetch': data['paper']['fetch'] is not None}


# ──────────────────────────────────────────────────────────────────────────────
# Tables: rows of formatted cells (the same formatter as the text)
# ──────────────────────────────────────────────────────────────────────────────

def tables(data, m):
    study, dev = data['study'], data['study']['dev']
    P = data['paper']

    def cell(key):
        return m[key] if m[key] is not None else 'pending'

    def ci(lo, hi):
        return f'[{cell(lo)}, {cell(hi)}]'

    significance = [
        ['Annualised Sharpe ratio', cell('significance.main.ann_sharpe'), cell('significance.oos_daily.ann_sharpe')],
        ['Newey–West t (mean ≠ 0)', cell('significance.main.hac_t'), cell('significance.oos_daily.hac_t')],
        ['Newey–West p', cell('significance.main.hac_p'), cell('significance.oos_daily.hac_p')],
        ['Probabilistic Sharpe, P(SR > 0)', cell('significance.main.psr_pct'), cell('significance.oos_daily.psr_pct')],
        [f"Deflated Sharpe ({m['study.dev.facts.dsr_trials']} trials)", cell('significance.main.dsr_pct'),
         cell('significance.oos_daily.dsr_pct')],
        ['Block-bootstrap 95% interval', ci('significance.main.boot_lo', 'significance.main.boot_hi'),
         ci('significance.oos_daily.boot_lo', 'significance.oos_daily.boot_hi')],
        ['Gatev distance method, Sharpe [95% interval]',
         f"{cell('benchmarks.gatev.sharpe')} {ci('study.dev.facts.gatev_lo', 'study.dev.facts.gatev_hi')}",
         f"{cell('paper.gatev_wf_sharpe')} (on {cell('paper.wf_common_days')} shared days)"
         if m['paper.gatev_wf_sharpe'] is not None else '—'],
        ['Strategy minus Gatev, Sharpe (Ledoit–Wolf p)',
         f"{cell('benchmarks.sharpe_diff_vs_gatev.diff')} ({cell('benchmarks.sharpe_diff_vs_gatev.p')})",
         f"{cell('paper.diff_oos')} ({cell('paper.diff_oos_p')})" if m['paper.diff_oos'] is not None else '—'],
    ]
    forest = [[r['label'], fmt(r['sharpe'], '+.2'), fmt(r['lo'], '.2'), fmt(r['hi'], '+.2'),
               fmt(r['days'], ',.0') if r['days'] else '—', r['method']] for r in dev['forest']]
    alternatives = [[fmt(a['sharpe'], '.1'), fmt(a['p_ge_iid'], '.3'), fmt(a['p_ge_ar1'], '.3'),
                     fmt(a['trl_iid'], '.1'), fmt(a['trl_ar1'], '.1')] for a in P['power_ar1']['alternatives']]
    perf = P['performance']

    def interval(v, signed=True):
        spec = '+.2' if signed else '.2'
        if v[1] is None:
            return fmt(v[0], spec) or '—'
        return f"{fmt(v[0], spec)} [{fmt(v[1], spec)}, {fmt(v[2], spec)}]"

    def opt(v, spec):
        return fmt(v, spec) if v is not None else '—'

    def dd_days(v):
        return '—' if v[0] is None else f"{v[0]} / {v[1] if v[1] is not None else 'not regained'}"
    cols = ('main', 'wf', 'gatev')
    performance_rows = [
        ['Trading days', *(fmt(perf['days'][c], '.0') for c in cols)],
        ['Total net return, %', *(fmt(perf[c]['total'], '+.2') for c in cols)],
        ['Annualised net return, % (95% interval)', *(interval(perf[c]['ret']) for c in cols)],
        ['Annualised volatility, % (95% interval)', *(interval(perf[c]['vol'], signed=False) for c in cols)],
        ['Sharpe ratio (95% interval)', interval(perf['sharpe']['main']), interval(perf['sharpe']['wf']),
         f"{cell('benchmarks.gatev.sharpe')} [{cell('study.dev.facts.gatev_lo')}, {cell('study.dev.facts.gatev_hi')}]"],
        ['Maximum drawdown, %', *(fmt(perf[c]['max_dd'], '.2') for c in cols)],
        ['Drawdown length, trading days: to trough / to recovery', *(dd_days(perf[c]['dd_days']) for c in cols)],
        ['Average gross exposure, % of capital', *(opt(perf[c]['gross'], '.1') for c in cols)],
        ['Net return on average gross exposure, % a year', *(opt(perf[c]['ret_gross'], '+.2') for c in cols)],
        ['Trades', *(opt(perf[c]['trades'], '.0') for c in cols)],
        ['Hit rate, % of trades', *(opt(perf[c]['hit'], '.1') for c in cols)],
        ['Average holding period, trading days', *(opt(perf[c]['hold'], '.1') for c in cols)],
        ['Annual turnover, × capital', *(opt(perf[c]['turnover'], '.1') for c in cols)],
    ]
    funds = data.get('fund_profiles') or {}

    def fund(s, key):          # the headline JSON's figure (as the site prints it), else the replay's
        return _get(funds, s['source_key'], key, default=s[{'total_return_pct': 'ret_pct', 'sharpe': 'sharpe',
                                                              'max_drawdown_pct': 'max_dd_pct'}[key]])
    schedules = [[s['id'], fmt(s['commission_bps'], '.1'), fmt(s['half_spread_bps'], '.1'),
                  fmt(s['impact_cap_bps'], '.0'), fmt(s['borrow_pct'], '.2'), fmt(s['financing_pct'], '.2'),
                  f"{fmt(s['position_pct'][0], '.0')}–{fmt(s['position_pct'][1], '.0')}",
                  fmt(fund(s, 'total_return_pct'), '+.2'), fmt(fund(s, 'sharpe'), '+.2'),
                  fmt(fund(s, 'max_drawdown_pct'), '.2'), fmt(s['cost_pct'], '.2'), fmt(s['peak_gross_x'], '.2'),
                  fmt(s['trades'], '.0')]
                 for s in dev.get('cost_schedules') or []]
    declaration = data['_declaration'] or {}
    grid = {k: v for k, v in (declaration.get('grid') or {}).items() if isinstance(v, list)}
    variants = [[k, 'grid values ' + ', '.join(fmt(x, '.2') for x in v)] for k, v in grid.items()]
    variants += [[tg['name'], tg.get('why', '').replace('>=', '≥').replace('t+1', 't + 1')]
                 for tg in declaration.get('toggles') or []]
    # Windows are numbered 1..N here (the run numbers them on a grid that starts in 2020);
    # the last one runs to the walk-forward's last day, so it can be longer than the rest.
    wins = dev['walk_forward']['windows']
    windows = [[str(i), short_date(w['train_start']), short_date(w['test_start']),
                short_date(dev['run']['oos_period'][1] if i == len(wins) else w['test_end']), str(P['wf_days'][w['n']]),
                fmt(w['ret_pct'], '+.2'), fmt(w['sharpe'], '+.2') if w['sharpe'] is not None and not _flat_window(w) else '—',
                str(w['trades']), fmt(w['ranker_auc'], '.3')] for i, w in enumerate(wins, 1)]
    holdout_power_rows = [[str(r['days']), fmt(r['mde_shape'], '.1'), fmt(r['mde_normal'], '.1')]
                          for r in P['holdout_power_rows']]
    status = (study.get('holdout') or {}).get('status')
    if status != 'sealed':
        raise PaperDataError(f'the holdout is {status!r}: its per-arm results need a table the paper does '
                             'not have yet (extend tables() before publishing them)')
    design = 'pre-registered design' if P['prereg_status'] == 'filed' else 'design proposed for pre-registration'
    hypotheses = [['H1', f'v33 pairs ({design})', 'mean daily net return > 0'],
                  ['H2', 'Avellaneda–Lee residual reversion', 'mean daily net return > 0'],
                  ['S3', 'v32 as published, frozen', 'reported, not tested']]
    snooping = [['Hansen SPA p (consistent)', cell('paper.snooping.spa_p')],
                ['White Reality Check p', cell('paper.snooping.reality_check_p')],
                ['Romano–Wolf: variants rejected at 5%', cell('paper.snooping.romano_wolf_rejected')],
                ['Model confidence set (90%): variants kept', cell('paper.snooping.mcs_included')],
                ['Effective number of trials', cell('paper.snooping.effective_trials')],
                ['Probability of backtest overfitting', cell('paper.snooping.pbo_pct')]]
    val = study.get('validation')
    if val:
        e, n, h, s = val['edge'], val['forced_null'], val['hedge_ratio'], val['selection']
        results = [f"{fmt(e['trades'], ',.0')} trades, {fmt(e['mean_bp'], '+.1')} bp gross per trade "
                   f"(t = {fmt(e['t'], '.1')}), median net Sharpe {fmt(e['median_net_sharpe'], '.1')}",
                   f"{fmt(n['trades'], ',.0')} trades, {fmt(n['mean_bp'], '+.1')} bp (t = {fmt(n['t'], '.2')})",
                   f"median absolute error {fmt(h['median_abs_error'], '.3')} (90th percentile {fmt(h['p90_abs_error'], '.3')})",
                   f"{fmt(100 * s['recall'], '.0%')} of planted pairs found; worst market admitted "
                   f"{fmt(100 * s['worst_fp_rate'], '.1%')} of unrelated pairs"]
    else:
        results = ['pending'] * 4
    validation = [['Planted cointegrated pairs (OU spreads, half-life 5–14 days)', 'a large positive gross edge', results[0]],
                  ['Correlated, not cointegrated pairs (random-walk spread), forced into the universe',
                   'no edge; a positive mean would be look-ahead', results[1]],
                  ['Kalman hedge ratio against the true slope', 'recover it', results[2]],
                  ['Pair selection with planted pairs among unrelated names',
                   'find them; admit at most 5% of unrelated pairs', results[3]]]
    run = dev['run']
    v = run['versions'] or {}
    manifest = [['Commit', f"{run['commit'][:12]} ({P['clean']})"],
                ['Run', P['run_time']],
                ['Price cache', f"sha256 {run['price_cache_sha256']}"],
                ['Headline JSON', f"{data['_headline_path']}, sha256 {study['meta']['headline_sha256']}"],
                ['Site data', f"assets/study.json, sha256 {data['_study_sha256']}"],
                ['Universe', f"Nasdaq screener, {P['universe_as_of_long']}; "
                 + (f"{m['paper.fetch.ok']} of {m['paper.fetch.symbols']} symbols with prices"
                    if P['fetch'] else f"{m['study.dev.facts.coverage_pct']} fetched")],
                ['Seed', f"PAIRS_SEED={run['seed']}"],
                ['Stack', ' · '.join(f'{k} {v[k]}' for k in ('python', 'numpy', 'pandas', 'scipy', 'statsmodels', 'torch')
                                     if v.get(k))]]
    sources = [[path, digest] for path, digest in sorted(study['meta']['sources'].items())]
    for path, digest in ((data['_fetch_manifest_path'], data['_fetch_manifest_sha256']),
                         ('reference/universe/index.json', data['_universe_index_sha256']),
                         ('index.html', data['_site_sha256'])):
        if digest:
            sources.append([path, digest])
    profiles = [['Universe', f"the {m['paper.names_file']} largest US stocks by market cap on {P['universe_as_of_long']}",
                 'point-in-time members (IWV N-PORT)'],
                ['Pair search', f"{PROFILES['v32'].max_universe} most liquid names, all pairs",
                 f"{PROFILES['v33'].max_universe} most liquid names, same Fama–French 49 industry"],
                ['Re-selection', f"re-test the 2022 pool every {PROFILES['v32'].reselect_every} trading days",
                 f"full re-formation every {PROFILES['v33'].reselect_every} trading days on the trailing "
                 f"{PROFILES['v33'].formation_calendar_days // 365} years"],
                ['Regime gate', 'on' if PROFILES['v32'].regime_gate else 'off',
                 'on' if PROFILES['v33'].regime_gate else 'off (a declared variant)'],
                ['Ranker', 'learned classifier orders same-day candidates', 'none (classical ranking; ablation arm)'],
                ['Borrow and financing', f"{fmt(1e4 * PROFILES['v32'].borrow_rate, '.0')} bp borrow + "
                 f"{fmt(1e4 * PROFILES['v32'].pb_financing_spread, '.0')} bp financing a year",
                 f"one {fmt(100 * PROFILES['v33'].borrow_rate, '.2')}% fee a year"]]
    return {'significance': significance, 'forest': forest, 'alternatives': alternatives, 'schedules': schedules,
            'windows': windows, 'holdout_power': holdout_power_rows, 'variants': variants, 'hypotheses': hypotheses, 'snooping': snooping,
            'validation': validation, 'manifest': manifest, 'sources': sources, 'profiles': profiles,
            'performance': performance_rows}


# ──────────────────────────────────────────────────────────────────────────────
# Figures
# ──────────────────────────────────────────────────────────────────────────────

MM = 1 / 25.4
FULL = EXHIBIT_WIDTH_MM * MM
HALF = (EXHIBIT_WIDTH_MM - COLUMN_GAP_MM) / 2 * MM
PAIR_HEIGHT = 1.6                       # inches: side-by-side exhibits share a height


def _mpl(tokens):
    """matplotlib with IBM Plex from paper/fonts and the site's light-theme colours."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager
    for path in sorted(FONTS.glob('*.ttf')):
        font_manager.fontManager.addfont(str(path))
    matplotlib.rcParams.update({
        'font.family': 'IBM Plex Sans', 'font.size': 7.0, 'axes.titlesize': 7.5, 'axes.labelsize': 7.0,
        'xtick.labelsize': 6.8, 'ytick.labelsize': 6.8, 'legend.fontsize': 7.0,
        'text.color': tokens['ink'], 'axes.labelcolor': tokens['ink-2'], 'xtick.color': tokens['axis'],
        'ytick.color': tokens['axis'], 'xtick.labelcolor': tokens['ink-2'], 'ytick.labelcolor': tokens['ink-2'],
        'axes.edgecolor': tokens['axis'], 'axes.linewidth': 0.6, 'axes.grid': True, 'axes.axisbelow': True,
        'grid.color': tokens['grid'], 'grid.linewidth': 0.5, 'axes.spines.top': False, 'axes.spines.right': False,
        'axes.spines.left': False, 'xtick.major.size': 2.5, 'xtick.major.width': 0.6, 'ytick.major.size': 0,
        'ytick.major.pad': 3, 'xtick.major.pad': 2.5, 'lines.linewidth': 1.1, 'lines.solid_capstyle': 'round',
        'lines.solid_joinstyle': 'round', 'legend.frameon': False, 'axes.unicode_minus': True,
        'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
        # text stays text (searchable and copyable in the PDF); Typst sets it in the same Plex files
        'svg.fonttype': 'none', 'svg.hashsalt': 'pairs-study', 'svg.image_inline': True, 'path.simplify': False,
        'axes.titlelocation': 'left', 'axes.titlepad': 4, 'axes.titleweight': 'semibold',
        'hatch.linewidth': 0.5, 'hatch.color': tokens['neutral-series'],
    })
    import matplotlib.pyplot as plt
    return plt


def _signed(v, dp=1, suffix=''):
    return fmt(v, f'+.{dp}{suffix}')


# Typst knows the static Plex Medium and SemiBold files by their own family names, so a
# weight that matplotlib writes as 'IBM Plex Sans' + font-weight names that family instead.
_SVG_WEIGHTS = {'500': 'IBM Plex Sans Medm', '600': 'IBM Plex Sans SmBld'}


def _svg_family(match):
    style = match.group(1)
    weight = re.search(r'font-weight: (\d+)', style)
    if weight and weight.group(1) in _SVG_WEIGHTS:
        style = re.sub(r'font-weight: \d+;? ?', '', style)
        style = style.replace("font-family: 'IBM Plex Sans'", f"font-family: '{_SVG_WEIGHTS[weight.group(1)]}'")
    return f'style="{style.rstrip("; ")}"'


def _svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format='svg', metadata={'Date': None, 'Creator': None, 'Format': None, 'Type': None})
    import matplotlib.pyplot as plt
    plt.close(fig)
    text = re.sub(r'style="([^"]*font-family[^"]*)"', _svg_family, buf.getvalue())
    # ids are salted (svg.hashsalt) and so deterministic; drop trailing spaces
    return '\n'.join(line.rstrip() for line in text.splitlines()) + '\n'


def _dates(xs):
    import matplotlib.dates as mdates
    return mdates.datestr2num(list(xs))


def _year_axis(ax, minor=True):
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    if minor:
        ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(4, 7, 10)))
        ax.tick_params(axis='x', which='minor', length=1.5, width=0.4, color=ax.spines['bottom'].get_edgecolor())


def _end_label(ax, x, y, text, color, t, label_y=None, weight='semibold'):
    """An end dot on (x, y) and its label to the right, at label_y when labels must be kept apart."""
    from matplotlib.transforms import ScaledTranslation
    ax.plot([x], [y], marker='o', markersize=3.6, color=color, markeredgecolor='white', markeredgewidth=0.9,
            zorder=5, clip_on=False)
    shift = ScaledTranslation(5 / 72, 0, ax.figure.dpi_scale_trans)
    ax.text(x, y if label_y is None else label_y, text, transform=ax.transData + shift, va='center', ha='left',
            fontsize=7, color=t['ink'], fontweight=weight, clip_on=False)


def _legend(ax, handles, t, loc='lower left', ncol=None, anchor=(0, 1.0)):
    """One row of legend entries; by default just above the axes, clear of the data."""
    leg = ax.legend(handles=handles, loc=loc, ncol=ncol or len(handles), handlelength=1.4, handletextpad=0.5,
                    columnspacing=1.4, borderaxespad=0.2, bbox_to_anchor=anchor)
    for txt in leg.get_texts():
        txt.set_color(t['ink-2'])
    return leg


def _zero(ax, t, axis='y'):
    (ax.axhline if axis == 'y' else ax.axvline)(0, color=t['axis'], linewidth=0.8, zorder=1.5)


def fig_equity(dev, t, plt):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    D, G, B = dev['daily'], dev.get('gatev'), dev.get('random_band')
    x = _dates(D['dates'])
    fig, axes = plt.subplots(3, 1, figsize=(FULL, 3.25), sharex=True,
                             gridspec_kw={'height_ratios': [2.7, 1.05, 1.05], 'hspace': 0.18})
    ax = axes[0]
    handles = [Line2D([], [], color=t['series-1'], lw=1.3, label='Strategy (net)')]
    if B:
        xb = _dates(B['dates'])
        ax.fill_between(xb, B['p05'], B['p95'], color=t['neutral-series'], alpha=0.16, lw=0, zorder=1)
        handles.append(Patch(color=t['neutral-series'], alpha=0.3, lw=0,
                             label=f"Random pairs, 5th–95th percentile ({B['n_draws']} draws)"))
    _zero(ax, t)
    if G:
        xg = _dates(G['dates'])
        ax.plot(xg, G['cum'], color=t['series-2'], lw=1.1, zorder=3)
        handles.insert(1, Line2D([], [], color=t['series-2'], lw=1.1, label='Gatev distance method (net)'))
    ax.plot(x, D['cum'], color=t['series-1'], lw=1.3, zorder=4)
    ends = [[x[-1], D['cum'][-1], 'Strategy ' + fmt(D['cum'][-1], '+.2%'), t['series-1'], D['cum'][-1]]]
    if G:
        ends.append([xg[-1], G['cum'][-1], 'Gatev ' + fmt(G['cum'][-1], '+.2%'), t['series-2'], G['cum'][-1]])
    span = max(max(D['cum']), max(G['cum']) if G else 0) - min(min(D['cum']), min(G['cum']) if G else 0)
    if len(ends) == 2 and abs(ends[0][1] - ends[1][1]) < 0.1 * span:       # keep the two labels apart
        lo, hi = sorted(ends, key=lambda e: e[1])
        centre = (lo[1] + hi[1]) / 2
        lo[4], hi[4] = centre - 0.05 * span, centre + 0.05 * span
    for e in ends:
        _end_label(ax, e[0], e[1], e[2], e[3], t, label_y=e[4])
    ax.set_ylabel('Cumulative net\nreturn, %')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    _legend(ax, handles, t)
    ax.margins(x=0)
    for a in axes[:2]:
        a.tick_params(axis='x', which='both', length=0)
        a.spines['bottom'].set_visible(False)
    ax2 = axes[1]
    ax2.fill_between(x, D['dd'], 0, color=t['neg'], alpha=0.16, lw=0)
    ax2.plot(x, D['dd'], color=t['neg'], lw=0.8)
    i = int(np.argmin(D['dd']))
    # below the trough, clear of the line
    ax2.annotate('max ' + fmt(D['dd'][i], '.2%'), (x[i], D['dd'][i]), xytext=(0, -3), textcoords='offset points',
                 fontsize=6.8, color=t['ink'], ha='center', va='top')
    ax2.set_ylabel('Drawdown, %')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '.1')))
    ax2.set_ylim(min(D['dd']) * 1.75, 0.15)
    ax3 = axes[2]
    ax3.fill_between(x, D['exposure'], 0, color=t['series-1'], alpha=0.14, lw=0, step='post')
    ax3.plot(x, D['exposure'], color=t['series-1'], lw=0.7, drawstyle='steps-post')
    cap = 30.0
    ax3.axhline(cap, color=t['ink-3'], lw=0.6)
    ax3.annotate('30% gross cap', (x[-1], cap), xytext=(0, 2), textcoords='offset points', ha='right', va='bottom',
                 fontsize=6.6, color=t['ink-2'])
    ax3.set_ylim(0, cap * 1.25)
    ax3.set_yticks([0, 10, 20, 30])
    ax3.set_ylabel('Gross exposure,\n% of capital')
    _year_axis(ax3)
    for a in axes:
        a.yaxis.set_label_coords(-0.075, 0.5)
    fig.subplots_adjust(left=0.1, right=0.86, top=0.93, bottom=0.07)
    return fig


def fig_walkforward(dev, t, plt):
    WF = dev['walk_forward']
    W = WF['windows']
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(FULL, 2.45), sharex=True,
                                  gridspec_kw={'height_ratios': [1.7, 1.0], 'hspace': 0.16})
    a = _dates([w['test_start'] for w in W])
    b = _dates([w['test_end'] for w in W])
    r = [w['ret_pct'] or 0.0 for w in W]
    width = (b - a) * 0.86
    mid = a + (b - a) / 2
    colors = [t['pos'] if v >= 0 else t['neg'] for v in r]
    ax.bar(mid, r, width=width, color=colors, zorder=3)
    _zero(ax, t)
    ext = max(abs(v) for v in r)
    for xm, v, w in zip(mid, r, W):
        ax.annotate(str(w['trades']), (xm, v), xytext=(0, 2.5 if v >= 0 else -2.5), textcoords='offset points', ha='center',
                    va='bottom' if v >= 0 else 'top', fontsize=6.4, color=t['ink-2'])
    ax.set_ylim(-ext * 1.3, ext * 1.3)
    ax.tick_params(axis='x', which='both', length=0)
    ax.spines['bottom'].set_visible(False)
    ax.set_ylabel('Window net\nreturn, %')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    if WF.get('daily'):
        px, py = _dates(WF['daily']['dates']), WF['daily']['cum']
        ax2.plot(px, py, color=t['series-1'], lw=1.2)
    else:
        px = np.concatenate([[a[0]], b])
        py = [0.0] + [s['cum_pct'] for s in WF['stitched']]
        ax2.plot(px, py, color=t['series-1'], lw=1.2, marker='o', markersize=2.6, markeredgecolor='white',
                 markeredgewidth=0.6)
    _zero(ax2, t)
    _end_label(ax2, px[-1], py[-1], fmt(py[-1], '+.2%'), t['series-1'], t)
    lo, hi = min(py), max(py)
    ax2.set_ylim(min(lo, 0) - 0.25 * (hi - lo + 0.1), max(hi, 0) + 0.25 * (hi - lo + 0.1))
    ax2.set_ylabel('Stitched path, %')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    _year_axis(ax2)
    for a_ in (ax, ax2):
        a_.yaxis.set_label_coords(-0.075, 0.5)
    fig.subplots_adjust(left=0.1, right=0.9, top=0.97, bottom=0.09)
    return fig


def _diverging(t):
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list('div', [t['neg'], t['div-mid'], t['pos']])


def _luminance(rgb):
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])


def fig_monthly(dev, t, plt):
    from matplotlib.colors import to_rgb
    months, annual = dev['monthly'], dev['annual']
    years = sorted({m['ym'][:4] for m in months})
    cols = [mn[:3] for mn in MONTHS] + ['Year']
    vals = {(m['ym'][:4], int(m['ym'][5:7]) - 1): m['ret_pct'] for m in months}
    for a in annual:
        vals[(a['year'], 12)] = a['ret_pct']
    vmax = max(abs(v) for v in vals.values()) or 1.0
    cmap = _diverging(t)
    fig, ax = plt.subplots(figsize=(FULL, 0.42 + 0.27 * len(years)))
    ink = to_rgb(t['ink'])
    for (y, c), v in vals.items():
        row = years.index(y)
        rgba = cmap(0.5 + 0.5 * v / vmax)
        x0 = c + (0.25 if c == 12 else 0)
        ax.add_patch(plt.Rectangle((x0 + 0.04, row + 0.06), 0.92, 0.88, facecolor=rgba, edgecolor='none'))
        lum = _luminance(rgba[:3])
        light = (1.05) / (lum + 0.05) > (lum + 0.05) / (_luminance(ink) + 0.05)
        ax.text(x0 + 0.5, row + 0.5, fmt(v, '+.2'), ha='center', va='center', fontsize=6.5,
                color='white' if light else t['ink'], fontweight='semibold' if light else 'normal')
    ax.set_xlim(0, 13.25)
    ax.set_ylim(len(years), 0)
    ax.set_xticks([i + 0.5 + (0.25 if i == 12 else 0) for i in range(13)])
    ax.set_xticklabels(cols)
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(years))])
    ax.set_yticklabels(years)
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.subplots_adjust(left=0.06, right=0.995, top=0.8, bottom=0.03)
    return fig


def fig_rolling(dev, t, plt):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    R = dev['rolling_sharpe']
    x = _dates(R['dates'])
    sr = np.array([np.nan if v is None else v for v in R['sharpe']])
    lo = np.array([np.nan if v is None else v for v in R['lo']])
    hi = np.array([np.nan if v is None else v for v in R['hi']])
    fig, ax = plt.subplots(figsize=(FULL, 1.9))
    ax.fill_between(x, lo, hi, color=t['neutral-series'], alpha=0.2, lw=0)
    _zero(ax, t)
    ax.plot(x, sr, color=t['series-1'], lw=1.2)
    ax.set_ylabel('Sharpe ratio, annualised')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    _year_axis(ax)
    ax.margins(x=0)
    _legend(ax, [Line2D([], [], color=t['series-1'], lw=1.2, label=f"Rolling {R['window']}-day Sharpe"),
                 Patch(color=t['neutral-series'], alpha=0.35, lw=0, label='±1.96 standard errors')], t)
    fig.subplots_adjust(left=0.075, right=0.99, top=0.88, bottom=0.12)
    return fig


# The paper calls the walk-forward "out of sample" only with its qualification (Section
# 3.5), so the site's short labels lose the "OOS".
def _wf_label(label):
    return label.replace('Walk-forward OOS', 'Walk-forward')


def fig_forest(dev, study, power, t, plt):
    """Sharpe ratios with intervals; `power` is the dependence-aware bound and MDE drawn."""
    F = dev['forest']
    color = {'main': t['series-1'], 'oos': t['series-1'], 'gatev': t['series-2'], 'diff_main': t['ink-2'],
             'diff_oos': t['ink-2'], 'random': t['neutral-series'], 'gross': t['series-1'],
             'residual': t['series-3'], 'holdout': t['series-3']}
    rows = [dict(r, label=_wf_label(r['label'])) for r in F]
    res = study.get('residual')
    if res and res.get('sharpe') is not None:
        rows.append({'key': 'residual', 'label': 'Avellaneda–Lee, net', 'kind': 'ci', 'sharpe': res['sharpe'],
                     'lo': res['lo'], 'hi': res['hi']})
    hold = study.get('holdout') or {}
    if hold.get('status') == 'complete' and hold.get('sharpe') is not None:
        rows.append({'key': 'holdout', 'label': 'Holdout 2026, net', 'kind': 'ci', 'sharpe': hold['sharpe'],
                     'lo': hold['lo'], 'hi': hold['hi']})
    n = len(rows)
    fig, ax = plt.subplots(figsize=(FULL, 0.62 + 0.215 * n))
    for i, r in enumerate(rows):
        c = color.get(r['key'], t['ink-2'])
        ax.plot([r['lo'], r['hi']], [i, i], color=c, lw=1.4, solid_capstyle='butt', zorder=3)
        ax.plot([r['sharpe']], [i], marker='o', markersize=4.2, color=c, markeredgecolor='white',
                markeredgewidth=0.9, zorder=4)
    _zero(ax, t, 'x')
    # the one-sided bound and the 80%-power Sharpe, each a full-height rule labelled at its top
    for v, text, ls, ha, dx in ((power['ucb'], f"one-sided 95% bound {fmt(power['ucb'], '.2')}", (0, (3, 2)), 'right', -3),
                                (power['mde'], f"80% power at {fmt(power['mde'], '.2')}", '-', 'left', 3)):
        ax.plot([v, v], [-0.75, n - 0.5], color=t['ink-2'], lw=0.8, ls=ls, zorder=2)
        ax.annotate(text, (v, -0.75), xytext=(dx, 0), textcoords='offset points', va='center', ha=ha,
                    fontsize=6.6, color=t['ink-2'])
    ax.set_yticks(range(n))
    ax.set_yticklabels([r['label'] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(n - 0.5, -1.2)
    lows = [r['lo'] for r in rows] + [0.0]
    highs = [r['hi'] for r in rows] + [power['mde']]
    pad = 0.04 * (max(highs) - min(lows))
    ax.set_xlim(min(lows) - pad, max(highs) + 6 * pad)
    ax.xaxis.set_major_locator(plt.MultipleLocator(0.5))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    ax.set_xlabel('Annualised Sharpe ratio')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.2, right=0.99, top=0.985, bottom=0.6 / (0.62 + 0.215 * n))
    return fig


def fig_randomnull(dev, t, plt, width=FULL):
    R = dev['random_sharpes']
    s, g = dev['strategy_sharpe'], dev['gatev_sharpe']
    lo = math.floor(min(R + [s, g]) * 5) / 5 - 0.2
    hi = math.ceil(max(R + [s, g]) * 5) / 5 + 0.2
    bins = np.arange(lo, hi + 1e-9, 0.2)
    fig, ax = plt.subplots(figsize=(width, 1.95))
    counts, _, _ = ax.hist(R, bins=bins, color=t['neutral-series'], alpha=0.55, rwidth=0.9, zorder=2)
    _zero(ax, t, 'y')
    top = counts.max() * 1.32
    ax.set_ylim(0, top)
    marks = [(s, 'Strategy ' + fmt(s, '+.2'), t['series-1']), (g, 'Gatev ' + fmt(g, '+.2'), t['series-2'])]
    marks.sort(key=lambda m: m[0])
    for k, (xv, text, c) in enumerate(marks):
        ax.axvline(xv, color=c, lw=1.3, zorder=3)
        left = k == 0
        ax.annotate(text, (xv, top), xytext=(-3 if left else 3, -1), textcoords='offset points',
                    ha='right' if left else 'left', va='top', fontsize=6.8, color=t['ink'], fontweight='semibold')
    ax.set_xlim(lo, hi)
    ax.xaxis.set_major_locator(plt.MultipleLocator(0.5))
    ax.set_ylabel('Draws')
    ax.set_xlabel('Annualised Sharpe ratio of a random-pair draw')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.075 * FULL / width, right=0.975, top=0.97, bottom=0.2)
    return fig


def fig_dsr(dev, t, plt, width=FULL):
    C = dev['dsr_curve']
    n = [r['n'] for r in C]
    d = [100 * r['dsr'] for r in C]
    at = dev['facts']['dsr_trials']
    fig, ax = plt.subplots(figsize=(width, 1.95))
    ax.plot(n, d, color=t['series-1'], lw=1.2, marker='o', markersize=3, markeredgecolor='white',
            markeredgewidth=0.6, zorder=3)
    _zero(ax, t)
    for r in C:
        if r['n'] == at:
            v = 100 * r['dsr']
            ax.plot([r['n']], [v], marker='o', markersize=6, markerfacecolor='white', markeredgecolor=t['series-1'],
                    markeredgewidth=1.1, zorder=4)
            ax.annotate(f"N = {at} (reported): {fmt(v, '.1%')}", (r['n'], v), xytext=(6, 7),
                        textcoords='offset points', fontsize=6.8, color=t['ink'], fontweight='semibold')
    ax.set_xscale('log')
    ax.set_xlim(n[0] * 0.8, n[-1] * 1.25)
    ax.set_ylim(0, max(50, d[0] * 1.1))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    ax.set_xlabel('Number of independent trials N (log scale)')
    ax.set_ylabel('Deflated Sharpe, %')
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.075 * FULL / width, right=0.99, top=0.97, bottom=0.2)
    return fig


def fig_waterfall(dev, t, plt):
    steps = dev.get('shortfall') or dev['waterfall']
    rows = [{'step': s['step'], 'a': s['start'] / 1e3, 'b': s['end'] / 1e3, 'usd': s['usd'],
             'total': s['key'] in ('gross', 'net', 'paper')} for s in steps]
    fig, ax = plt.subplots(figsize=(FULL, 0.38 + 0.2 * len(rows)))
    for i, r in enumerate(rows):
        c = t['ink-2'] if r['total'] else (t['pos'] if r['usd'] >= 0 else t['neg'])
        left, w = min(r['a'], r['b']), abs(r['b'] - r['a'])
        ax.barh(i, w, left=left, height=0.62, color=c, zorder=3)
        label = fmt(r['usd'] / 1e3, '+.1') + 'k'
        if r['b'] >= r['a']:
            ax.annotate(label, (max(r['a'], r['b']), i), xytext=(3, 0), textcoords='offset points', va='center',
                        ha='left', fontsize=6.8, color=t['ink'])
        else:
            ax.annotate(label, (min(r['a'], r['b']), i), xytext=(-3, 0), textcoords='offset points', va='center',
                        ha='right', fontsize=6.8, color=t['ink'])
        if i + 1 < len(rows) and not rows[i + 1]['total']:
            ax.plot([r['b'], r['b']], [i + 0.31, i + 0.69], color=t['rule-2'], lw=0.5, zorder=2)
    _zero(ax, t, 'x')
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r['step'] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.4, -0.6)
    vals = [r['a'] for r in rows] + [r['b'] for r in rows] + [0]
    span = max(vals) - min(vals)
    ax.set_xlim(min(vals) - 0.17 * span, max(vals) + 0.17 * span)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    ax.set_xlabel('$ thousands')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.115, right=0.99, top=0.98, bottom=0.42 / (0.38 + 0.2 * len(rows)) + 0.02)
    return fig


def fig_anatomy(dev, t, plt):
    T = dev['trades']
    panels = [('By exit', T['by_exit']), ('By side of the spread', T['by_side']), ('By |z| at entry', T['by_z'])]
    allv = [g['net_usd'] / 1e6 for _, gs in panels for g in gs]
    span = max(allv + [0]) - min(allv + [0])
    xl = (min(allv + [0]) - 0.36 * span, max(allv + [0]) + 0.36 * span)
    nmax = max(len(gs) for _, gs in panels)
    fig, axes = plt.subplots(1, 3, figsize=(FULL, 0.62 + 0.2 * nmax), sharex=True)
    for ax, (title, gs) in zip(axes, panels):
        for i, g in enumerate(gs):
            v = g['net_usd'] / 1e6
            ax.barh(i, v, height=0.6, color=t['pos'] if v >= 0 else t['neg'], zorder=3)
            # right of the bar, or of zero for a loss: never beside the category label
            ax.annotate(f"n = {g['n']}", (max(v, 0.0), i), xytext=(3, 0), textcoords='offset points',
                        va='center', ha='left', fontsize=6.4, color=t['ink-2'])
        _zero(ax, t, 'x')
        ax.set_yticks(range(len(gs)))
        ax.set_yticklabels([g['label'] for g in gs])
        for lab in ax.get_yticklabels():
            lab.set_color(t['ink'])
        ax.set_ylim(nmax - 0.5, -0.6)
        ax.set_xlim(*xl)
        ax.set_title(title, fontsize=7, color=t['ink'])
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
        ax.set_xlabel('$ millions')
        ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.085, right=0.995, top=0.86, bottom=0.25, wspace=0.62)
    return fig


def fig_schedules(dev, t, plt):
    C = dev['cost_schedules']
    dates = dev['daily']['dates']
    allv = [v for s in C for v in s['cum']] + [0.0]
    span = max(allv) - min(allv)
    yl = (min(allv) - 0.08 * span, max(allv) + 0.08 * span)
    fig, axes = plt.subplots(1, len(C), figsize=(FULL, 1.35), sharey=True)
    for ax, s in zip(np.atleast_1d(axes), C):
        x = _dates(s.get('dates') or dates)
        _zero(ax, t)
        ax.plot(x, s['cum'], color=t['series-1'], lw=1.0)
        ax.plot([x[-1]], [s['cum'][-1]], marker='o', markersize=3, color=t['series-1'], markeredgecolor='white',
                markeredgewidth=0.7)
        ax.set_title(f"Schedule {s['id']}: {fmt(s['ret_pct'], '+.2%')}", fontsize=7, color=t['ink'])
        ax.set_ylim(*yl)
        import matplotlib.dates as mdates
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.yaxis.set_major_locator(plt.MaxNLocator(4, integer=True))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
        ax.margins(x=0.02)
    np.atleast_1d(axes)[0].set_ylabel('Cumulative net, %')
    fig.subplots_adjust(left=0.065, right=0.975, top=0.84, bottom=0.15, wspace=0.14)
    return fig


def _dotplot(ax, rows, t, label_key='label', tlabel=True):
    for i, r in enumerate(rows):
        c = r.get('color', t['series-1'])
        ax.plot([r['lo'], r['hi']], [i, i], color=c, lw=1.4, solid_capstyle='butt', zorder=3)
        ax.plot([r['v']], [i], marker='o', markersize=4.2, color=c, markeredgecolor='white', markeredgewidth=0.9,
                zorder=4)
        if tlabel and r.get('t') is not None:
            ax.annotate(f"t = {fmt(r['t'], '.2')}", (r['hi'], i), xytext=(4, 0), textcoords='offset points',
                        va='center', fontsize=6.6, color=t['ink-2'])
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[label_key] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.grid(axis='y', visible=False)


def fig_factors(dev, t, plt):
    F = dev['factors']
    rows = [{'label': _wf_label(r['series']) + (': ' + r['name'] if F['multi_factor'] else ''), 'v': r['beta'],
             'lo': r['lo'], 'hi': r['hi'], 't': r['t']} for r in F['rows']]
    fig, ax = plt.subplots(figsize=(HALF, PAIR_HEIGHT))
    _dotplot(ax, rows, t)
    _zero(ax, t, 'x')
    lo = min([r['lo'] for r in rows] + [0])
    hi = max([r['hi'] for r in rows] + [0])
    pad = 0.12 * (hi - lo)
    ax.set_xlim(lo - pad, hi + 3.2 * pad)
    ax.set_ylim(len(rows) - 0.4, -0.6)
    ax.xaxis.set_major_locator(plt.MaxNLocator(4, steps=[1, 2, 5, 10]))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '+.2') if abs(v) > 1e-12 else '0'))
    ax.set_xlabel('Beta to the market proxy (95% interval)')
    fig.subplots_adjust(left=0.3, right=0.985, top=0.95, bottom=0.25)
    return fig


def fig_distribution(dev, t, plt):
    bp = np.asarray(dev['daily']['net'], dtype=float) * 100
    lo, hi = math.floor(bp.min() / 5) * 5, math.ceil(bp.max() / 5) * 5
    bins = np.arange(lo - 1.25, hi + 2.5, 2.5)
    fig, ax = plt.subplots(figsize=(HALF, PAIR_HEIGHT))
    counts, _, _ = ax.hist(bp, bins=bins, color=t['series-1'], alpha=0.8, rwidth=0.92, zorder=2)
    _zero(ax, t)
    zero_days = int((bp == 0).sum())
    centre = int(np.searchsorted(bins, 0.0, side='right')) - 1          # the bin around zero
    ax.annotate(f'{fmt(counts[centre], ",.0")} days within ±1.25 bp,\nof which {fmt(zero_days, ",.0")} exactly zero',
                (0, counts[centre]), xytext=(6, -2), textcoords='offset points', va='top', fontsize=6.6,
                color=t['ink-2'], linespacing=1.15)
    ax.set_xlabel('Daily net return, bp of capital')
    ax.set_ylabel('Days')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.15, right=0.985, top=0.95, bottom=0.25)
    return fig


def fig_funnel(dev, t, plt):
    F = dev['funnel']
    ramp = [t['ord-1'], t['ord-2'], t['ord-3'], t['ord-4'], t['ord-4']]
    rows = F['pairs']
    fig, ax = plt.subplots(figsize=(FULL, 0.42 + 0.3 * len(rows)))
    # log scale: the last stage (100 pairs) is a hairline on a linear axis to 35,000
    for i, r in enumerate(rows):
        ax.barh(i, r['n'], height=0.5, color=ramp[min(i, len(ramp) - 1)], zorder=3)
        count = fmt(r['n'], ',.0')
        ax.annotate(count, (r['n'], i), xytext=(3, 0), textcoords='offset points', va='center',
                    fontsize=6.8, color=t['ink'], fontweight='semibold')
        if r.get('expected'):
            # the chance tick, labelled directly in the gap below its bar
            ax.plot([r['expected']] * 2, [i - 0.36, i + 0.36], color=t['ink'], lw=1.3, zorder=4)
            ax.annotate(f"{fmt(r['expected'], ',.0')} expected by chance", (r['expected'], i + 0.36),
                        xytext=(0, -0.5), textcoords='offset points', va='top', ha='center', fontsize=6.6,
                        color=t['ink-2'], zorder=5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r['stage'] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xscale('log')
    ax.set_xlim(10, max(r['n'] for r in rows) * 2.2)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    ax.set_xlabel('Pairs (log scale)')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.2, right=0.99, top=0.97, bottom=0.4 / (0.42 + 0.3 * len(rows)) + 0.03)
    return fig


def fig_timeline(dev, study, t, plt, preregistered=False):
    run = dev['run']
    W = dev['walk_forward']['windows']
    cal = CALENDARS['dev']
    hold_start = (study.get('holdout') or {}).get('calendar_start')
    fig, ax = plt.subplots(figsize=(FULL, 1.45))
    prereg = 'pre-registered' if preregistered else 'to be pre-registered'
    lanes = [('Formation', f'pairs selected on data to {long_date(cal.selection_cutoff)}'),
             ('Walk-forward', f"{len(W)} test windows, each after its training year"),
             ('Main backtest', f"entries {long_date(run['period'][0])} to {long_date(run['period'][1])}"),
             ('Holdout', f"from {long_date(hold_start)}; sealed, {prereg}" if hold_start else prereg)]
    h = 0.34
    form = _dates([run['data_span'][0], cal.selection_cutoff])
    ax.barh(0, form[1] - form[0], left=form[0], height=h, color=t['ord-2'])
    tr = _dates([W[0]['train_start'], W[0]['train_end']])
    ax.barh(1, tr[1] - tr[0], left=tr[0], height=h * 0.7, color=t['ord-1'])
    for w in W:
        a, b = _dates([w['test_start'], w['test_end']])
        ax.barh(1, (b - a) * 0.94, left=a, height=h, color=t['series-1'])
    mb = _dates(run['period'])
    ax.barh(2, mb[1] - mb[0], left=mb[0], height=h, color=t['ord-4'])
    first_year = int(run['data_span'][0][:4])
    last_year = int((hold_start or run['period'][1])[:4])
    x0, x1 = _dates([f'{first_year}-01-01', f'{last_year}-12-31'])
    if hold_start:          # open-ended: the holdout's last day is fixed by the pre-registration
        hs = _dates([hold_start])[0]
        ax.barh(3, x1 - hs, left=hs, height=h * 0.8, color='white', edgecolor=t['series-3'], hatch='////', lw=0.7)
    for i, (name, desc) in enumerate(lanes):
        ax.annotate(name, (0, i), xycoords=('axes fraction', 'data'), xytext=(0, 7.5), textcoords='offset points',
                    fontsize=7, fontweight='semibold', color=t['ink'], va='bottom')
        ax.annotate(desc, (0, i), xycoords=('axes fraction', 'data'), xytext=(62, 7.5), textcoords='offset points',
                    fontsize=6.7, color=t['ink-2'], va='bottom')
    ax.set_xlim(x0 - 25, x1 + 25)
    ax.set_ylim(3.45, -0.9)
    ax.set_yticks([])
    ax.grid(False)
    ax.set_xticks(_dates([f'{y}-01-01' for y in range(first_year, last_year + 1)]))
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.spines['bottom'].set_color(t['axis'])
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.14)
    return fig


def fig_snapshots(snaps, t, plt):
    if not snaps:
        return None
    rows = snaps['rows']
    x = _dates([r['period'] for r in rows])
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(FULL, 1.75))
    w = 55
    ax.bar(x, [r['mapped'] for r in rows], width=w, color=t['series-1'], zorder=3, label='Mapped to a ticker')
    ax.bar(x, [r['equity'] - r['mapped'] for r in rows], bottom=[r['mapped'] for r in rows], width=w,
           color=t['neutral-series'], alpha=0.55, zorder=3, label='No usable ticker')
    ax.set_title('Equity holdings per snapshot', fontsize=7, color=t['ink'], pad=13)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    _legend(ax, ax.get_legend_handles_labels()[0], t, anchor=(0, 0.99))
    _year_axis(ax, minor=False)
    ax.grid(axis='x', visible=False)
    ax2.bar(x, [r['unmapped_weight_pct'] for r in rows], width=w, color=t['neutral-series'], zorder=3)
    ax2.set_title('Index weight without a usable ticker, %', fontsize=7, color=t['ink'], pad=13)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '.1')))
    _year_axis(ax2, minor=False)
    ax2.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.065, right=0.99, top=0.8, bottom=0.13, wspace=0.18)
    return fig


def fig_universe(dev, t, plt):
    U = dev.get('universe_by_formation')
    if not U:
        return None
    labels = [long_date(u['formation_date']) for u in U]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(FULL, 0.55 + 0.22 * len(U)), sharey=True)
    for i, u in enumerate(U):
        ax.barh(i, u['with_prices'], height=0.6, color=t['series-1'], zorder=3)
        ax.barh(i, u['missing'], left=u['with_prices'], height=0.6, color=t['neutral-series'], alpha=0.55, zorder=3)
        ax.annotate(fmt(100 * u['with_prices'] / u['members'], '.1%'), (u['members'], i), xytext=(3, 0),
                    textcoords='offset points', va='center', fontsize=6.4, color=t['ink-2'])
        miss, unm = u['missing_weight_pct'] or 0.0, u['unmapped_weight_pct'] or 0.0
        ax2.barh(i, miss, height=0.6, color=t['neutral-series'], zorder=3)
        ax2.barh(i, unm, left=miss, height=0.6, color=t['neutral-series'], alpha=0.45, zorder=3)
        ax2.annotate(fmt(miss + unm, '.2%'), (miss + unm, i), xytext=(3, 0), textcoords='offset points',
                     va='center', fontsize=6.4, color=t['ink-2'])
    ax.set_yticks(range(len(U)))
    ax.set_yticklabels(labels)
    ax.set_ylim(len(U) - 0.5, -0.5)
    ax.set_title('Index members; labels: share with price history', fontsize=7, color=t['ink'])
    ax2.set_title('Index weight not covered, %', fontsize=7, color=t['ink'])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    for a in (ax, ax2):
        a.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.13, right=0.97, top=0.9, bottom=0.12, wspace=0.12)
    return fig


def fig_costcurve(dev, t, plt, width=HALF):
    C = dev.get('cost_curve')
    if not C:
        return None
    fig, ax = plt.subplots(figsize=(width, 1.7))
    k = [r['k'] for r in C]
    s = [r['sharpe'] for r in C]
    ax.plot(k, s, color=t['series-1'], lw=1.2, marker='o', markersize=3, markeredgecolor='white', markeredgewidth=0.6)
    _zero(ax, t)
    ax.axvline(1.0, color=t['ink-3'], lw=0.6)
    ax.annotate('modelled', (1.0, ax.get_ylim()[1]), xytext=(3, -2), textcoords='offset points', va='top',
                fontsize=6.6, color=t['ink-2'])
    for i in range(1, len(C)):
        if (s[i - 1] >= 0) != (s[i] >= 0):
            be = k[i - 1] + (k[i] - k[i - 1]) * s[i - 1] / (s[i - 1] - s[i])
            ax.annotate(f"break-even {fmt(be, '.2')}×", (be, 0), xytext=(0, 5), textcoords='offset points',
                        ha='center', fontsize=6.6, color=t['ink'])
    ax.set_xlabel('Multiple of modelled costs')
    ax.set_ylabel('Net Sharpe')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '.1') + '×'))
    fig.subplots_adjust(left=0.16, right=0.98, top=0.95, bottom=0.24)
    return fig


def fig_exitrace(dev, t, plt, width=HALF):
    E = dev.get('exit_race')
    if not E:
        return None
    rows = [('Targets hit first', E['targets'], E['expected_targets']),
            ('Stops hit first', E['stops'], E['targets'] + E['stops'] - E['expected_targets'])]
    fig, ax = plt.subplots(figsize=(width, 1.2))
    for i, (lab, v, e) in enumerate(rows):
        ax.barh(i, v, height=0.55, color=t['series-1'], zorder=3)
        ax.plot([e, e], [i - 0.36, i + 0.36], color=t['ink'], lw=1.3, zorder=4)
    ax.set_yticks([0, 1])
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_ylim(1.5, -0.5)
    ax.set_xlabel('Trades (tick: expected with no mean reversion)')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.32, right=0.97, top=0.95, bottom=0.32)
    return fig


def fig_decay(dev, t, plt, width=HALF):
    D = dev.get('decay')
    if not D:
        return None
    rows = [{'label': r['period'], 'v': r['bp'], 'lo': r['lo'], 'hi': r['hi']} for r in D]
    fig, ax = plt.subplots(figsize=(width, 0.55 + 0.27 * len(rows)))
    _dotplot(ax, rows, t, tlabel=False)
    _zero(ax, t, 'x')
    ax.set_xlabel('Gross bp per trade')
    fig.subplots_adjust(left=0.36, right=0.97, top=0.95, bottom=0.3)
    return fig


def fig_persistence(dev, t, plt, width=HALF):
    Pd = dev.get('persistence')
    if not Pd or not Pd.get('windows'):
        return None
    fig, ax = plt.subplots(figsize=(width, 1.6))
    xs = range(len(Pd['windows']))
    ax.bar(xs, [w['pct'] for w in Pd['windows']], width=0.6, color=t['series-1'], zorder=3)
    ax.axhline(Pd['chance_pct'], color=t['ink'], lw=1.0)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([w['window'] for w in Pd['windows']], rotation=0)
    ax.set_ylabel('Still cointegrated, %')
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.95, bottom=0.2)
    return fig


def fig_capacity(dev, t, plt, width=HALF):
    C = dev.get('capacity')
    if not C:
        return None
    fig, ax = plt.subplots(figsize=(width, 1.6))
    ax.plot([r['aum_musd'] for r in C], [r['net_bp'] for r in C], color=t['series-1'], lw=1.2)
    _zero(ax, t)
    ax.set_xscale('log')
    ax.set_xlabel('Book size, $M')
    ax.set_ylabel('Net bp per trade')
    fig.subplots_adjust(left=0.16, right=0.98, top=0.95, bottom=0.24)
    return fig


def fig_pvalues(dev, t, plt, width=HALF):
    H = (dev.get('funnel') or {}).get('pvalue_hist') or dev.get('pvalue_hist')
    if not H or not H.get('counts'):
        return None
    edges, counts = H['edges'], H['counts']
    fig, ax = plt.subplots(figsize=(width, 1.6))
    ax.bar(edges[:-1], counts, width=np.diff(edges) * 0.9, align='edge', color=t['series-1'], zorder=3)
    ax.axhline(sum(counts) / len(counts), color=t['ink'], lw=1.0)
    ax.set_xlim(0, 1)
    ax.set_xlabel('Engle–Granger p-value')
    ax.set_ylabel('Pairs')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.18, right=0.98, top=0.95, bottom=0.24)
    return fig


def _arms(rows, t, plt):
    fig, ax = plt.subplots(figsize=(FULL, 0.55 + 0.27 * len(rows)))
    _dotplot(ax, rows, t, tlabel=False)
    _zero(ax, t, 'x')
    ax.set_xlabel('Annualised Sharpe ratio (95% interval)')
    fig.subplots_adjust(left=0.24, right=0.98, top=0.95, bottom=0.42 / (0.55 + 0.27 * len(rows)) + 0.02)
    return fig


def fig_residual(dev, study, t, plt):
    R = study.get('residual')
    if not R or R.get('sharpe') is None:
        return None
    main = next(r for r in dev['forest'] if r['key'] == 'main')
    return _arms([{'label': 'Avellaneda–Lee, net', 'v': R['sharpe'], 'lo': R['lo'], 'hi': R['hi'], 'color': t['series-3']},
                  {'label': 'Pairs, main backtest, net', 'v': main['sharpe'], 'lo': main['lo'], 'hi': main['hi']}], t, plt)


def fig_holdout(study, t, plt):
    H = study.get('holdout') or {}
    if H.get('status') != 'complete' or H.get('sharpe') is None:
        return None
    return _arms([{'label': 'Holdout 2026, net', 'v': H['sharpe'], 'lo': H['lo'], 'hi': H['hi'], 'color': t['series-3']}],
                 t, plt)


def fig_validation(study, t, plt):
    V = study.get('validation')
    if not V:
        return None
    rows = []
    for label, key, c in (('Planted edge', 'edge', t['series-1']), ('Forced null', 'forced_null', t['neutral-series'])):
        m_, se = V[key].get('mean_bp'), V[key].get('se_bp')
        if m_ is not None and se is not None:
            rows.append({'label': label, 'v': m_, 'lo': m_ - 1.96 * se, 'hi': m_ + 1.96 * se, 'color': c})
    if not rows:
        return None
    fig = _arms(rows, t, plt)
    fig.axes[0].set_xlabel('Gross bp per trade (95% interval)')
    return fig


def figures(data, tokens):
    """{name: svg text or None}. None: the data for that exhibit do not exist yet."""
    plt = _mpl(tokens)
    study = data['study']
    dev = study['dev']
    makers = {
        'equity': lambda: fig_equity(dev, tokens, plt),
        'walkforward': lambda: fig_walkforward(dev, tokens, plt),
        'monthly': lambda: fig_monthly(dev, tokens, plt),
        'rolling': lambda: fig_rolling(dev, tokens, plt),
        'forest': lambda: fig_forest(dev, study, data['paper']['power_ar1'], tokens, plt),
        'randomnull': lambda: fig_randomnull(dev, tokens, plt),
        'dsr': lambda: fig_dsr(dev, tokens, plt),
        'waterfall': lambda: fig_waterfall(dev, tokens, plt),
        'anatomy': lambda: fig_anatomy(dev, tokens, plt),
        'schedules': lambda: fig_schedules(dev, tokens, plt) if dev.get('cost_schedules') else None,
        'factors': lambda: fig_factors(dev, tokens, plt),
        'distribution': lambda: fig_distribution(dev, tokens, plt),
        'funnel': lambda: fig_funnel(dev, tokens, plt),
        'timeline': lambda: fig_timeline(dev, study, tokens, plt, data['paper']['prereg_status'] == 'filed'),
        'snapshots': lambda: fig_snapshots(universe_snapshots(data['_universe_index']), tokens, plt),
        'universe': lambda: fig_universe(dev, tokens, plt),
        'costcurve': lambda: fig_costcurve(dev, tokens, plt),
        'exitrace': lambda: fig_exitrace(dev, tokens, plt),
        'decay': lambda: fig_decay(dev, tokens, plt),
        'persistence': lambda: fig_persistence(dev, tokens, plt),
        'capacity': lambda: fig_capacity(dev, tokens, plt),
        'pvalues': lambda: fig_pvalues(dev, tokens, plt),
        'residual': lambda: fig_residual(dev, study, tokens, plt),
        'holdout': lambda: fig_holdout(study, tokens, plt),
        'validation': lambda: fig_validation(study, tokens, plt),
    }
    out = {}
    for name, make in makers.items():
        fig = make()
        out[name] = _svg(fig) if fig is not None else None
    return out


# Why each exhibit without data is pending (printed in its place).
FIGURE_PENDING = {
    'universe': 'Pending: v33 development run.', 'costcurve': 'Pending: v33 development run.',
    'exitrace': 'Pending: evidence layer.', 'decay': 'Pending: evidence layer.',
    'persistence': 'Pending: evidence layer.', 'capacity': 'Pending: evidence layer.',
    'pvalues': 'Pending: v33 development run.', 'residual': 'Pending: v33 development run.',
    'holdout': 'Sealed.', 'validation': 'Pending: committed validation run.',
    'snapshots': 'Pending: point-in-time universe index.', 'schedules': 'Pending: cost-schedule replay.',
}

# Results the study will add. While one is absent its exhibit or table is left out of the
# body and the note lists it here instead: (key, analysis, what it will show, what it awaits).
# The key is a figure name, or a flag for results that are not a figure of their own.
V33 = 'The v33 development run'
FORTHCOMING = (
    ('validation', 'Known-answer validation',
     'The engine and its full cost model on synthetic markets with a known answer: the gross edge on planted '
     'cointegrated pairs, no edge on forced non-cointegrated pairs, the hedge-ratio error and pair-selection recall',
     'A committed validation run'),
    ('universe', 'Point-in-time universe coverage',
     'Index members with and without price history at each formation date, and the index weight the price data '
     'do not cover: the survivorship gap', V33),
    ('pvalues', 'Engle–Granger p-values',
     'The distribution of the {pairs} p-values against the uniform distribution expected if no pair were '
     'cointegrated', V33),
    ('snooping', 'Data-snooping tests',
     "White's Reality Check, Hansen's SPA test, the Romano–Wolf stepdown, the model confidence set and the "
     'probability of backtest overfitting over the declared family ({grid}-point grid, {toggles} toggles)',
     "The family's run on the development calendar"),
    ('costcurve', 'Cost sensitivity',
     'Net Sharpe ratio from 0× to 2× modelled costs with the break-even multiple, the Sharpe ratio gross of costs, '
     'and the impact coefficient at 0.3, 0.6 and 1.0 crossed with two borrow fees', V33),
    ('exitrace', 'Exit race',
     'Targets against stops, compared with the count expected for a spread that does not mean-revert', V33),
    ('decay', 'Decay from formation to trading',
     'Gross return per trade of the same rule on the same pairs, formation period against trading period', V33),
    ('persistence', 'Persistence of cointegration',
     'The share of selected pairs still cointegrated in later windows, against the 5% expected by chance', V33),
    ('capacity', 'Capacity',
     'Impact cost against book size for a stated hypothetical gross edge (the measured edge is not significant)', V33),
    ('multi_factor', 'Multi-factor attribution',
     'Loadings on the five Fama–French factors, momentum and short- and long-term reversal, with Newey–West '
     'errors', V33),
    ('random_band', 'Random-pair band',
     "Each day's 5th–95th percentile of the random-pair draws' cumulative returns, drawn around the equity curve",
     V33),
    ('residual', 'Avellaneda–Lee residual reversion',
     'The second strategy family\'s development-period net Sharpe ratio and 95% interval, beside the pairs strategy',
     'Its run on the development calendar'),
    ('holdout', 'The 2026 holdout',
     "Each arm's net Sharpe ratio, Holm-adjusted p-value and decision (H1 and H2; the v32 arm descriptive), and its cumulative return",
     'The pre-registration, then a single run on 2026 data'),
)


def forthcoming(figs, flags_, m):
    """[[key, analysis, what it will show, what it awaits]] for every result still absent."""
    present = {k: v is not None for k, v in figs.items()}
    present.update({'snooping': flags_['snooping'], 'multi_factor': flags_['multi_factor'],
                    'random_band': flags_['random_band'], 'validation': flags_['validation']})
    fill = {'pairs': m['fdr.pairs_tested'], 'grid': m['study.dev.snooping.grid_points'],
            'toggles': m['study.dev.snooping.toggles']}
    return [[key, what, shows.format(**fill), awaits] for key, what, shows, awaits in FORTHCOMING
            if not present[key]]


def concordance(site, figs, later):
    """The site's exhibits and where each one is in the paper: [site n, site title, target].

    target: the paper's label ('ex-<name>' or 'tab-validation'), 'forthcoming' for a
    result the paper lists as forthcoming, or None for one it does not show.
    """
    if not site:
        return None
    out = []
    for e in site:
        name = e['name']
        if name in ('pipeline', 'timeline') or figs.get(name) is not None:
            target = 'ex-' + name if name != 'validation' else 'tab-validation'
        elif name in later:
            target = 'forthcoming'
        else:
            target = None
        out.append([e['n'], e['title'], target])
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Assembly
# ──────────────────────────────────────────────────────────────────────────────

def build_data(inp):
    """(paper_data dict, {figure name: svg or None})."""
    study, head = inp['study'], inp['headline']
    if study.get('schema') != 1:
        raise PaperDataError(f"assets/study.json has schema {study.get('schema')!r}; the paper reads schema 1")
    unknown = sorted((set(study) - KNOWN_STUDY) | (set(study['dev']) - KNOWN_DEV))
    if unknown:
        raise PaperDataError(f'assets/study.json has sections the paper does not print yet: {unknown}')
    if 'study' in head or 'paper' in head:
        raise PaperDataError('the headline JSON has a top-level study/paper key')
    data = {**head, 'study': study, '_universe_index': inp['universe_index'], '_declaration': inp['declaration'],
            '_headline_path': inp['headline_path'], '_study_sha256': inp['study_sha256'],
            '_universe_index_sha256': inp['universe_index_sha256'],
            '_fetch_manifest_path': inp['fetch_manifest_path'], '_fetch_manifest_sha256': inp['fetch_manifest_sha256'],
            '_site_sha256': inp['site_sha256']}
    data['paper'] = derived(inp)
    m, why = format_metrics(data)
    tokens = site_tokens()
    figs = figures(data, tokens)
    missing = {k: FIGURE_PENDING[k] for k, v in figs.items() if v is None}
    unexplained = [k for k, v in figs.items() if v is None and k not in FIGURE_PENDING]
    if unexplained:
        raise PaperDataError(f'exhibits {unexplained} have no data and no pending reason')
    flags_ = flags(data)
    later = forthcoming(figs, flags_, m)
    paper = {
        'schema': SCHEMA,
        'meta': {'builder': 'scripts/build_paper.py', 'paper_date': data['paper']['paper_date'],
                 'commit': study['meta']['commit'], 'headline': inp['headline_path'],
                 'headline_sha256': study['meta']['headline_sha256'], 'study_sha256': inp['study_sha256'],
                 'universe_index_sha256': inp['universe_index_sha256'],
                 'fetch_manifest': inp['fetch_manifest_path']},
        'layout': {'exhibit_width_mm': EXHIBIT_WIDTH_MM, 'measure_mm': MEASURE_MM, 'column_gap_mm': COLUMN_GAP_MM},
        'colors': tokens,
        'm': m,
        'why': why,
        'claims': {k: bool(v) for k, v in claims(data).items()},     # numpy comparisons give numpy bools
        'flags': flags_,
        'tables': tables(data, m),
        'figures': {k: (f'build/figures/{k}.svg' if v is not None else None) for k, v in sorted(figs.items())},
        'pending': dict(sorted(missing.items())),
        'forthcoming': later,
        'concordance': concordance(inp['site_exhibits'], figs, {row[0] for row in later}),
    }
    return paper, {k: v for k, v in figs.items() if v is not None}


def dumps(paper):
    return json.dumps(paper, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + '\n'


def _rel(path):
    """`path` relative to the repository when it lies inside it (for messages and keys)."""
    try:
        return pathlib.Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return pathlib.Path(path).as_posix()


def compile_inputs():
    """The files the PDF depends on, by repository path (fonts, the Typst source, data, figures)."""
    files = [MAIN, BIB, DATA] + sorted(FIGURES.glob('*.svg')) + sorted(FONTS.glob('*.ttf'))
    return {_rel(p): _sha256(p) for p in files if p.is_file()}


def pdf_timestamp(paper):
    d = dt.date.fromisoformat(paper['meta']['paper_date'])
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def compile_pdf(paper, output=None, fmt_='pdf', ppi=None):
    import typst
    kwargs = {'root': str(ROOT), 'font_paths': [str(FONTS)], 'ignore_system_fonts': True,
              'timestamp': pdf_timestamp(paper)}
    if fmt_ != 'pdf':
        kwargs.update(format=fmt_, ppi=ppi)
    return typst.compile(str(MAIN), output=str(output) if output else None, **kwargs)


def _typst_version():
    try:
        import importlib.metadata
        return importlib.metadata.version('typst')
    except Exception:
        return None


def _mpl_version():
    import matplotlib
    return matplotlib.__version__


def write_all(png_dir=None):
    inp = load_inputs()
    paper, figs = build_data(inp)
    FIGURES.mkdir(parents=True, exist_ok=True)
    for old in FIGURES.glob('*.svg'):
        if old.stem not in figs:
            old.unlink()
    for name, svg in figs.items():
        (FIGURES / f'{name}.svg').write_text(svg, encoding='utf-8')
    DATA.write_text(dumps(paper), encoding='utf-8')
    if _typst_version() is None:
        print('typst is not installed (pip install -e ".[paper]"): wrote the data and figures, not the PDF',
              file=sys.stderr)
        return 1
    pdf = compile_pdf(paper)
    PDF.write_bytes(pdf)
    manifest = {'inputs': compile_inputs(), 'pdf_sha256': hashlib.sha256(pdf).hexdigest(),
                'tools': {'typst': _typst_version(), 'matplotlib': _mpl_version()}}
    MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    if png_dir:
        out = pathlib.Path(png_dir)
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob('page-*.png'):
            old.unlink()
        compile_pdf(paper, out / 'page-{p}.png', 'png', 110)
    print(f'wrote {_rel(DATA)}, {len(figs)} figures and {_rel(PDF)} '
          f'({len(pdf) / 1024:.0f} KB, paper date {paper["meta"]["paper_date"]})')
    return 0


def check():
    """0 if every committed product matches a fresh build of the current inputs, else 1."""
    problems = []
    inp = load_inputs()
    paper, figs = build_data(inp)
    text = dumps(paper)
    if not DATA.is_file() or DATA.read_text(encoding='utf-8') != text:
        problems.append(f'{_rel(DATA)} is stale')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.is_file() else None
    if manifest is None:
        problems.append(f'{_rel(MANIFEST)} is missing')
    same_mpl = manifest is not None and manifest['tools'].get('matplotlib') == _mpl_version()
    committed = {p.stem for p in FIGURES.glob('*.svg')}
    if committed != set(figs):
        problems.append(f'figures differ: committed {sorted(committed ^ set(figs))} out of step with the data')
    elif same_mpl:
        for name, svg in figs.items():
            if (FIGURES / f'{name}.svg').read_text(encoding='utf-8') != svg:
                problems.append(f'{_rel(FIGURES / f"{name}.svg")} is stale')
    else:
        print('note: matplotlib differs from the one that drew the committed figures; '
              'figures checked against the manifest only')
    if manifest is not None:
        if manifest['inputs'] != compile_inputs():
            changed = sorted(set(manifest['inputs'].items()) ^ set(compile_inputs().items()))
            problems.append(f'the PDF was compiled from other inputs ({", ".join(sorted({c[0] for c in changed}))})')
        if not PDF.is_file() or _sha256(PDF) != manifest.get('pdf_sha256'):
            problems.append(f'{_rel(PDF)} is not the PDF the manifest records')
        elif _typst_version() is not None and _typst_version() == manifest['tools'].get('typst') and not problems:
            if compile_pdf(paper) != PDF.read_bytes():
                problems.append(f'{_rel(PDF)} differs from a fresh compile')
    for p in problems:
        print(f'STALE: {p}', file=sys.stderr)
    if problems:
        print('rebuild with: python scripts/build_paper.py', file=sys.stderr)
        return 1
    print(f'{_rel(DATA)}, {len(figs)} figures and {_rel(PDF)} are up to date')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if a committed product is stale')
    ap.add_argument('--png', metavar='DIR', help='also render every page to DIR/page-N.png (110 ppi)')
    args = ap.parse_args(argv)
    try:
        return check() if args.check else write_all(args.png)
    except PaperDataError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
