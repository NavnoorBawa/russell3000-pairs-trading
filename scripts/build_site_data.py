#!/usr/bin/env python3
"""Build assets/study.json: the data contract between the committed results and the site.

index.html states the study's numbers in its text (each one a data-metric marker that
scripts/check_published_numbers.py verifies); the charts in assets/exhibits.js draw from
this file. Every number the page derives from the results (the cost waterfall, the gross
edge per trade, the power of the Sharpe test, the rolling Sharpe, ...) is computed here,
once, so the text, the charts and their data tables cannot disagree.

usage:
    python scripts/build_site_data.py              # results/v32_dev -> assets/study.json
    python scripts/build_site_data.py --check      # exit 1 if assets/study.json is stale
    python scripts/build_site_data.py --dev results/v33_dev
    python scripts/build_site_data.py --dev outputs/my_run --out /tmp/study.json   # preview

--dev takes any run directory (a published results/<name>/ or a run's own output
directory). The page's text is checked against the headline JSON the file was built
from (meta.headline_sha256), so the committed file must come from the run whose
numbers the page quotes; build other runs to another --out for a preview.

Sources (only the development run is required; a missing source leaves its section out
of the file and the page shows that section as pending, with the reason):

    {dev}/headline_metrics.json            the run's published numbers (checker's source)
    {dev}/pairs_trading_results_*.json     the full export (not its _compact twin): daily
                                           equity, trades, walk-forward windows,
                                           significance, benchmarks, universe coverage and,
                                           from v33 on, the evidence block (AR(1) power
                                           report, multi-factor attribution)
    {dev}/fund_type_comparison.json        cost-schedule replay of the same trades
    {dev}/universe_meta.json               the universe file's as-of date and size
    {dev}/stats_battery.json               power report and DSR curve (scripts/stats_battery.py)
    {dev}/anatomy.json                     evidence layer (see ANATOMY_KEYS)
    results/variant_family/declaration.json, snooping.json   data-snooping tests
    results/residual_dev/residual_statarb.json, MANIFEST.json   Avellaneda-Lee arm, as
                                                             scripts/publish_run.py publishes
                                                             scripts/run_residual_statarb.py's
                                                             export
    results/holdout2026/evaluation.json                      pre-registered 2026 holdout
                                                             (scripts/evaluate_holdout.py)
    results/validation/synthetic_validation.json             known-answer checks

Output: deterministic (sorted keys, rounded floats, no wall-clock time), so a rebuild of
unchanged inputs is byte-identical and CI can test that the committed file is current.
meta.generated_utc is the newest input run's timestamp for that reason, and
meta.headline_sha256 ties the file to the headline JSON the checker reads.
"""
import argparse
import hashlib
import json
import math
import pathlib
import sys

import numpy as np
from scipy import stats as sps

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading.significance import (  # noqa: E402
    block_bootstrap_sharpe_ci, deflated_sharpe_ratio, probabilistic_sharpe_ratio,
)

SCHEMA = 1
DEFAULT_DEV = ROOT / 'results' / 'v32_dev'
DEFAULT_OUT = ROOT / 'assets' / 'study.json'
PERIODS = 252
ROLLING_WINDOW = 126                 # trading days (half a year), as in pyfolio's tear sheet
DSR_TRIALS = (1, 2, 5, 10, 32, 100, 300, 1000)
COST_MULTIPLIERS = tuple(k / 4 for k in range(9))          # 0, 0.25, ..., 2x modelled costs
Z_95_ONE_SIDED = float(sps.norm.ppf(0.95))
Z_80 = float(sps.norm.ppf(0.80))

EXIT_LABELS = {'target': 'Target', 'stop': 'Stop', 'time': 'Time stop', 'end_of_data': 'End of data'}
SIDE_LABELS = {'LONG': 'Long spread', 'SHORT': 'Short spread'}
Z_BUCKETS = ((None, 1.8, '<1.8'), (1.8, 2.0, '1.8–2.0'), (2.0, 2.5, '2.0–2.5'),
             (2.5, 3.0, '2.5–3.0'), (3.0, None, '≥3.0'))
COST_STEPS = (('commission', 'Commission'), ('bid_ask', 'Half-spread'),
              ('market_impact', 'Market impact'), ('borrow', 'Borrow'), ('financing', 'Financing'))
# Keys of {dev}/anatomy.json (written by the evidence layer) passed through unchanged.
ANATOMY_KEYS = ('shortfall', 'exit_race', 'decay', 'persistence', 'capacity', 'pvalue_hist')
# Ken French daily factors as the evidence block names them, in the order shown.
FACTOR_LABELS = {'Mkt-RF': 'Market', 'SMB': 'Size (SMB)', 'HML': 'Value (HML)', 'RMW': 'Profitability (RMW)',
                 'CMA': 'Investment (CMA)', 'Mom': 'Momentum', 'ST_Rev': 'Short-term reversal',
                 'LT_Rev': 'Long-term reversal'}
# The pre-registered holdout's strategies, as scripts/run_holdout.sh names them for
# scripts/evaluate_holdout.py, with the hypothesis each one tests.
HOLDOUT_ARMS = (('v33_pairs', 'H1', 'v33 pairs (pre-registered design)'),
                ('avellaneda_lee', 'H2', 'Avellaneda–Lee residual reversion'),
                ('v32_pairs', None, 'v32 as published, frozen (descriptive)'))


# ──────────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────────

def _r(x, dp=4):
    """Round for the file; None for missing or non-finite values."""
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    v = round(x, dp)
    return 0.0 if v == 0 else v          # no "-0.0" in the output


def _rl(xs, dp=4):
    return [_r(x, dp) for x in xs]


def _get(d, *path, default=None):
    """d[path[0]][path[1]]... or `default` if any step is missing or None."""
    for p in path:
        if not isinstance(d, dict) or d.get(p) is None:
            return default
        d = d[p]
    return d


def _sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class Sources:
    """Reads JSON inputs and records each file's sha256 under its repository path."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.hashes = {}

    def _name(self, path):
        path = pathlib.Path(path).resolve()
        try:
            return path.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def load(self, path, required=False):
        path = pathlib.Path(path)
        if not path.is_file():
            if required:
                raise FileNotFoundError(f'{path} not found')
            return None
        self.hashes[self._name(path)] = _sha256(path)
        return json.loads(path.read_text(encoding='utf-8'))


def _results_file(dev):
    """The run's full export. Its `_compact` twin (no trades, no trade statistics) sorts
    after it by name but cannot feed the trade-level exhibits, so it is never used."""
    found = sorted(p for p in pathlib.Path(dev).glob('pairs_trading_results_*.json')
                   if not p.stem.endswith('_compact'))
    if not found:
        raise FileNotFoundError(f'no full pairs_trading_results_*.json export in {dev}')
    if len(found) > 1:
        raise ValueError(f'{dev} holds several full exports ({", ".join(p.name for p in found)}); '
                         'a run directory must hold one')
    return found[0]


def _sharpe(r):
    r = np.asarray(r, dtype=float)
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    return float(r.mean() / sd * math.sqrt(PERIODS)) if sd > 1e-15 else None


def _cum_pct(daily_pct):
    """Cumulative return (%) of daily returns given in %."""
    return list((np.cumprod(1.0 + np.asarray(daily_pct, dtype=float) / 100.0) - 1.0) * 100.0)


# ──────────────────────────────────────────────────────────────────────────────
# Development run: series
# ──────────────────────────────────────────────────────────────────────────────

def daily_series(res):
    """Daily net return, cumulative return, drawdown, gross exposure and open positions.

    Runs exported by v33 code carry gross/cost/exposure per day. For v32 exports the
    exposure and position count are rebuilt from the trades exactly as the engine
    computes them (positions held through day k: entry fill <= k < exit fill; gross
    notional over the previous day's equity); the reconstruction reproduces the run's
    published average and maximum gross exposure. The gross/cost split of each day
    cannot be rebuilt from a v32 export (entry and exit costs are not separated), so
    those two series are null there.
    """
    curve = res['daily_equity_curve']
    dates = [d['date'] for d in curve]
    capital = float(_get(res, 'metadata', 'initial_capital', default=curve[0]['portfolio_value']))
    out = {
        'dates': dates,
        'net': _rl((d['daily_return_pct'] for d in curve), 5),
        'cum': _rl((d['cumulative_return_pct'] for d in curve), 4),
        'dd': _rl((d['drawdown_pct'] for d in curve), 4),
    }
    if all(d.get('gross_exposure_pct') is not None for d in curve):
        out['exposure'] = _rl((d['gross_exposure_pct'] for d in curve), 3)
        out['positions'] = [int(d['open_positions']) for d in curve]
    else:
        trades = res.get('all_trades') or []
        exposure, positions = [], []
        for i, day in enumerate(dates):
            equity_prev = curve[i - 1]['portfolio_value'] if i else capital
            held = [t for t in trades if t['entry_date'] <= day < t['exit_date']]
            exposure.append(sum(t['position_size_dollars'] for t in held) / equity_prev * 100.0)
            positions.append(len(held))
        out['exposure'] = _rl(exposure, 3)
        out['positions'] = positions
    has_split = all(d.get('gross_return_pct') is not None and d.get('cost_pct') is not None for d in curve)
    out['gross'] = _rl((d['gross_return_pct'] for d in curve), 5) if has_split else None
    out['cost'] = _rl((d['cost_pct'] for d in curve), 5) if has_split else None
    return out


def gatev_series(res):
    dm = _get(res, 'benchmarks', 'distance_method') or {}
    if not dm.get('daily_returns'):
        return None
    net_pct = [100.0 * x for x in dm['daily_returns']]
    return {'dates': [str(d)[:10] for d in dm['daily_dates']], 'net': _rl(net_pct, 5),
            'cum': _rl(_cum_pct(net_pct), 4)}


def random_band(res):
    """Per-day 5/25/50/75/95% quantiles of the random-pair draws' cumulative returns (%).

    Exports from commit 15f775e on carry them (benchmarks.random_control.
    cumulative_return_pct_quantiles, aligned with random_control.daily_dates); earlier
    exports get no band. The draws' MEAN daily return is deliberately not used instead:
    averaging 200 portfolios diversifies their noise away, so that series overstates
    what a single random-pair book earns.
    """
    rc = _get(res, 'benchmarks', 'random_control') or {}
    q, dates = rc.get('cumulative_return_pct_quantiles'), rc.get('daily_dates')
    if not q or not dates:
        return None
    keys = ('p05', 'p25', 'p50', 'p75', 'p95')
    bad = [k for k in keys if len(q.get(k) or []) != len(dates)]
    if bad:
        raise ValueError(f'random_control quantiles {bad} are not aligned with its {len(dates)} daily_dates')
    return {'dates': [str(d)[:10] for d in dates], 'n_draws': rc.get('n_draws'),
            **{k: _rl(q[k], 4) for k in keys}}


def universe_coverage(res):
    """Point-in-time membership at each formation date, and how much of it has prices.

    One row per formation (pair selection or re-formation): the index snapshot in force,
    its members, those with price history, and the index weight of the members without
    prices (mapped to a ticker but not fetched) and of holdings with no usable ticker.
    The two weights together are the study's survivorship gap at that date. Runs on a
    non-point-in-time universe (v32) export no rows and get no section.
    """
    rows = []
    for u in res.get('universe_by_formation') or []:
        missing_w = u.get('missing_value_weight')
        unmapped_w = u.get('unmapped_value_weight')
        rows.append({
            'formation_date': str(u['formation_date'])[:10], 'snapshot': str(u.get('snapshot'))[:10],
            'members': int(u['members']), 'with_prices': int(u['with_prices']), 'missing': int(u['missing']),
            'missing_weight_pct': _r(100 * missing_w, 3) if missing_w is not None else None,
            'unmapped_weight_pct': _r(100 * unmapped_w, 3) if unmapped_w is not None else None,
        })
    return rows or None


def rolling_sharpe(dates, net_pct, window=ROLLING_WINDOW):
    """Rolling annualised Sharpe with a +-1.96 SE band, SE = sqrt((1 + SR_d^2 / 2) / n).

    The SE is Lo's (2002) IID approximation per day, annualised; a window with no
    dispersion (the book flat throughout) has no Sharpe and is reported as null.
    """
    r = np.asarray(net_pct, dtype=float) / 100.0
    out = {'window': window, 'dates': [], 'sharpe': [], 'lo': [], 'hi': []}
    for i in range(window - 1, len(r)):
        w = r[i - window + 1:i + 1]
        sd = w.std(ddof=1)
        out['dates'].append(dates[i])
        if sd <= 1e-12:
            sr = se = None
        else:
            sr_d = w.mean() / sd
            se = math.sqrt((1.0 + 0.5 * sr_d * sr_d) / window) * math.sqrt(PERIODS)
            sr = sr_d * math.sqrt(PERIODS)
        out['sharpe'].append(_r(sr, 3))
        out['lo'].append(_r(sr - 1.96 * se, 3) if sr is not None else None)
        out['hi'].append(_r(sr + 1.96 * se, 3) if sr is not None else None)
    return out


def monthly_table(res):
    months = [{'ym': m['month'], 'ret_pct': _r(m['return_pct'], 4)} for m in res.get('monthly_performance') or []]
    years = {}
    for m in months:
        years.setdefault(m['ym'][:4], []).append(m['ret_pct'] or 0.0)
    annual = [{'year': y, 'months': len(v), 'ret_pct': _r((np.prod([1 + x / 100 for x in v]) - 1) * 100, 4)}
              for y, v in sorted(years.items())]
    return months, annual


def walk_forward(res):
    wf = res.get('walk_forward_validation') or {}
    windows = []
    for w in wf.get('windows') or []:
        windows.append({
            'n': w['window'], 'train_start': w.get('train_start'), 'train_end': w.get('train_end'),
            'test_start': w['test_start'], 'test_end': w['test_end'],
            'ret_pct': _r(w['total_return_pct'], 4), 'sharpe': _r(w.get('sharpe_ratio'), 3),
            'trades': int(w.get('total_trades') or 0), 'win_rate_pct': _r(w.get('win_rate_pct'), 2),
            'max_dd_pct': _r(w.get('max_drawdown_pct'), 4),
            'ranker_auc': _r(_get(w, 'ranker_oos', 'auc'), 4),
        })
    # windows are calendar slices of one continuous simulation, so compounding them
    # gives the stitched path (at window resolution) and its published total
    cum, stitched = 1.0, []
    for w in windows:
        cum *= 1.0 + (w['ret_pct'] or 0.0) / 100.0
        stitched.append({'date': w['test_end'], 'cum_pct': _r((cum - 1.0) * 100.0, 4)})
    out = {'windows': windows, 'stitched': stitched}
    daily = res.get('walk_forward_daily') or []
    if daily:
        net = [d['daily_return_pct'] for d in daily]
        out['daily'] = {'dates': [d['date'] for d in daily], 'net': _rl(net, 5), 'cum': _rl(_cum_pct(net), 4)}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Development run: statistics
# ──────────────────────────────────────────────────────────────────────────────

def _sr_variance(sr_d, skew, kurt):
    """Asymptotic variance of the per-period Sharpe estimator (non-normal IID; as the PSR)."""
    return max(1.0 - skew * sr_d + (kurt - 1.0) / 4.0 * sr_d * sr_d, 1e-12)


def power_from_returns(r):
    """Power of the one-sided 5% test of SR > 0 on IID non-normal returns.

    Used when no stats_battery.json (whose power report adds AR(1) dependence) exists.
    critical: the smallest observed annual Sharpe that rejects SR = 0; mde: the true
    Sharpe detected with 80% probability; ucb: the one-sided 95% upper confidence bound;
    p_ge[x]: p-value of H0 SR >= x; min_trl_years[x]: years of data a strategy with true
    Sharpe x needs before its Sharpe is significant (Bailey & Lopez de Prado 2012).
    """
    p = probabilistic_sharpe_ratio(r, 0.0, PERIODS)
    n, g3, g4, sr_d = p['n'], p['skew'], p['kurtosis'], p['sr_per_period']
    ann = math.sqrt(PERIODS)
    se = math.sqrt(_sr_variance(sr_d, g3, g4) / (n - 1))
    crit_d = Z_95_ONE_SIDED * math.sqrt(1.0 / (n - 1))
    mde_d = crit_d
    for _ in range(100):             # fixed point: x = crit + z80 * se(x)
        mde_d = crit_d + Z_80 * math.sqrt(_sr_variance(mde_d, g3, g4) / (n - 1))

    def min_trl_years(x_ann):
        x_d = x_ann / ann
        return (1.0 + _sr_variance(x_d, g3, g4) * (Z_95_ONE_SIDED / x_d) ** 2) / PERIODS

    def p_ge(x_ann):
        return float(sps.norm.cdf((sr_d - x_ann / ann) / se))

    return {
        'method': 'IID, non-normal (skew and kurtosis) Sharpe variance; one-sided 5% test, 80% power',
        'n': int(n), 'sharpe': _r(p['sr_ann'], 4), 'se': _r(se * ann, 4),
        'critical': _r(crit_d * ann, 4), 'mde': _r(mde_d * ann, 4), 'ucb': _r((sr_d + Z_95_ONE_SIDED * se) * ann, 4),
        'skew': _r(g3, 4), 'kurtosis': _r(g4, 4),
        'alternatives': [{'sharpe': x, 'p_ge': _r(p_ge(x), 4), 'min_trl_years': _r(min_trl_years(x), 3)}
                         for x in (0.5, 1.0, 1.5, 2.0)],
    }


def power_from_report(p, source):
    """The same fields from a power.power_report (AR(1)-aware): the stats battery's
    ('power' in stats_battery.json) or the run's own evidence block ('evidence.main')."""
    return {
        'method': f'{source}: non-normal AR(1) Sharpe variance; one-sided 5% test, 80% power',
        'n': p['n'], 'sharpe': _r(p['sr_ann']), 'se': _r(p['se_ann']), 'critical': _r(p['critical_sr_ann']),
        'mde': _r(p['min_detectable_sr_ann']), 'ucb': _r(p['upper_bound_ann']),
        'skew': _r(p['skew']), 'kurtosis': _r(p['kurtosis']),
        'alternatives': [{'sharpe': a['sr_ann'], 'p_ge': _r(a['p_sr_at_least']),
                          'min_trl_years': _r(a['min_trl_years'], 3)} for a in p['alternatives']],
    }


def dsr_curve(r, battery=None):
    """Deflated Sharpe ratio against the number of trials (the run's own DSR at N = 32)."""
    if battery and battery.get('dsr_curve'):
        return [{'n': int(x['n_trials']), 'dsr': _r(x['dsr']), 'sr_star': _r(x['sr_star_ann'])}
                for x in battery['dsr_curve']]
    rows = []
    for n in DSR_TRIALS:
        d = deflated_sharpe_ratio(r, n, None, PERIODS)
        rows.append({'n': n, 'dsr': _r(d['dsr']), 'sr_star': _r(d['sr_star_ann'])})
    return rows


def forest(res, gatev_daily_pct, gross_daily_pct=None):
    """Sharpe ratios with their 95% intervals, one row per series or comparison.

    The run's significance block covers the net series; the gross-of-cost series (exports
    from v33 on) and the Gatev baseline get the same block bootstrap here.
    """
    sig = res.get('significance') or {}
    bench = res.get('benchmarks') or {}
    rows = []

    def battery_row(key, label, block):
        b = sig.get(block) or {}
        ci = b.get('bootstrap_sharpe_ci') or {}
        if b.get('ann_sharpe') is not None:
            rows.append({'key': key, 'label': label, 'kind': 'ci', 'sharpe': _r(b['ann_sharpe']),
                         'lo': _r(ci.get('lo')), 'hi': _r(ci.get('hi')), 'days': b.get('n_days'),
                         'method': f"circular block bootstrap ({ci.get('n_boot')} resamples, "
                                   f"block {ci.get('block')} days)"})

    def bootstrap_row(key, label, daily_pct):
        r = np.asarray(daily_pct, dtype=float) / 100.0
        ci = block_bootstrap_sharpe_ci(r, periods=PERIODS)       # same method and seed as the run's
        rows.append({'key': key, 'label': label, 'kind': 'ci',
                     'sharpe': _r(ci['point']), 'lo': _r(ci['lo']), 'hi': _r(ci['hi']), 'days': len(r),
                     'method': f"circular block bootstrap ({ci['n_boot']} resamples, block {ci['block']} days)"})

    battery_row('main', 'Main backtest, net', 'main_backtest')
    if gross_daily_pct is not None:
        bootstrap_row('gross', 'Main backtest, gross of costs', gross_daily_pct)
    battery_row('oos', 'Walk-forward OOS, net', 'oos_daily')
    if gatev_daily_pct is not None:
        bootstrap_row('gatev', 'Gatev distance method, net', gatev_daily_pct)
    for key, label, src in (('diff_main', 'Main minus Gatev', _get(bench, 'vs_strategy', 'main_backtest')),
                            ('diff_oos', 'Walk-forward OOS minus Gatev', _get(bench, 'vs_strategy', 'walk_forward_oos'))):
        d = (src or {}).get('sharpe_difference_vs_distance') or {}
        if d.get('diff') is not None:
            rows.append({'key': key, 'label': label, 'kind': 'diff', 'sharpe': _r(d['diff']),
                         'lo': _r(d.get('ci_lo')), 'hi': _r(d.get('ci_hi')), 'days': d.get('n'),
                         'p': _r(d.get('pvalue')), 'method': 'Ledoit-Wolf studentized block bootstrap'})
    dist = _get(bench, 'random_control', 'sharpe_distribution') or {}
    if dist.get('median') is not None:
        rows.append({'key': 'random', 'label': 'Random pairs (median draw)', 'kind': 'spread',
                     'sharpe': _r(dist['median']), 'lo': _r(dist.get('p5')), 'hi': _r(dist.get('p95')),
                     'days': None, 'method': f"5th-95th percentile of {_get(bench, 'random_control', 'n_draws')} draws "
                                             "(a spread across draws, not a confidence interval)"})
    return rows


def trade_groups(trades):
    """P&L of the trades grouped by exit reason, side and |z| at entry (dollars and bp).

    |z| buckets use the exported z-score, which is rounded to three decimals: a trade
    entered just below 2.0 that exports as 2.000 falls in the 2.0-2.5 bucket here, while
    the run's own trade_statistics (computed before rounding) count it in 1.8-2.0.
    """
    def summarise(label, group):
        gross = sum(t['net_pnl_dollars'] + t['transaction_costs_dollars'] for t in group)
        cost = sum(t['transaction_costs_dollars'] for t in group)
        net = sum(t['net_pnl_dollars'] for t in group)
        net_bp = [(t['net_pnl_dollars'] / t['position_size_dollars']) * 1e4 for t in group]
        return {'label': label, 'n': len(group), 'wins': sum(t['net_pnl_dollars'] > 0 for t in group),
                'gross_usd': _r(gross, 2), 'cost_usd': _r(cost, 2), 'net_usd': _r(net, 2),
                'mean_net_bp': _r(np.mean(net_bp), 2) if group else None}

    by_exit = [summarise(lab, [t for t in trades if t['exit_reason'] == k]) for k, lab in EXIT_LABELS.items()]
    by_side = [summarise(lab, [t for t in trades if t['action'] == k]) for k, lab in SIDE_LABELS.items()]
    by_z = []
    for lo, hi, lab in Z_BUCKETS:
        g = [t for t in trades if (lo is None or abs(t['zscore']) >= lo) and (hi is None or abs(t['zscore']) < hi)]
        if g or lo is not None:          # the below-threshold bucket only when it is used
            by_z.append(summarise(lab, g))
    return {'by_exit': [g for g in by_exit if g['n']], 'by_side': by_side, 'by_z': by_z}


def waterfall(trades, net_usd):
    """Gross P&L -> each cost component -> net P&L, in dollars and bp of starting capital.

    Arithmetic is in integer cents and the gross bar is the net change of the book plus
    the costs, so the bars close exactly on the net P&L. (Summing the trades' own
    rounded gross figures instead differs by a few cents of rounding.)
    """
    cents = {k: round(sum(t['cost_breakdown_dollars'][k] for t in trades) * 100) for k, _ in COST_STEPS}
    net_c = round(net_usd * 100)
    gross_c = net_c + sum(cents.values())
    steps, level = [{'key': 'gross', 'step': 'Gross P&L', 'usd': gross_c / 100, 'start': 0.0,
                     'end': gross_c / 100}], gross_c
    for k, label in COST_STEPS:
        steps.append({'key': k, 'step': label, 'usd': -cents[k] / 100, 'start': level / 100,
                      'end': (level - cents[k]) / 100})
        level -= cents[k]
    assert level == net_c
    steps.append({'key': 'net', 'step': 'Net P&L', 'usd': net_c / 100, 'start': 0.0, 'end': net_c / 100})
    return steps


def factor_rows(res):
    """Factor loadings with 95% intervals (beta +- 1.96 beta/t, Newey-West t), and alphas.

    Exports from v33 on carry a multi-factor attribution in their evidence block
    (evidence.factors.{main, walk_forward_oos}: Fama-French five factors, momentum,
    short- and long-term reversal); when it is there the exhibit shows it. Otherwise the
    single market-proxy beta of factor_attribution is shown. `market` always holds the
    market-proxy betas, which the page's text quotes.
    """
    fa = res.get('factor_attribution') or {}
    ev = _get(res, 'evidence', 'factors') or {}
    series = (('main_backtest', 'main', 'Main backtest'), ('walk_forward_oos', 'walk_forward_oos', 'Walk-forward OOS'))
    multi = {key: ev[ev_key] for key, ev_key, _ in series
             if isinstance(ev.get(ev_key), dict) and ev[ev_key].get('factors')}

    def loading(series_label, name, v):
        b, t = v.get('beta'), v.get('tstat')
        se = abs(b / t) if b is not None and t not in (None, 0) else None
        ok = se is not None and math.isfinite(se)
        return {'series': series_label, 'name': name, 'beta': _r(b, 5), 't': _r(t, 3),
                'lo': _r(b - 1.96 * se, 5) if ok else None, 'hi': _r(b + 1.96 * se, 5) if ok else None}

    rows, alphas, market = [], [], []
    for key, _, label in series:
        f = fa.get(key) or {}
        if f.get('beta') is not None:
            market.append(loading(label, 'Market proxy', {'beta': f['beta'], 'tstat': f.get('beta_tstat')}))
        src = multi.get(key) if multi else f
        if not src:
            continue
        if multi:
            loads = src['factors']
            names = [n for n in FACTOR_LABELS if n in loads] + sorted(n for n in loads if n not in FACTOR_LABELS)
            rows.extend(loading(label, FACTOR_LABELS.get(n, n), loads[n]) for n in names)
        else:
            rows.extend(m for m in market if m['series'] == label)
        alphas.append({'series': label, 'alpha_ann_pct': _r(100 * src['alpha_ann'], 4) if src.get('alpha_ann') is not None else None,
                       't': _r(src.get('alpha_tstat'), 3), 'r2': _r(src.get('r2'), 4), 'n': src.get('n')})
    proxy = ('Fama–French five factors, momentum, short- and long-term reversal (Ken French data library)'
             if multi else fa.get('market_proxy'))
    return {'proxy': proxy, 'rows': rows, 'alpha': alphas, 'market': market, 'multi_factor': bool(multi)}


def cost_curve(daily):
    """Sharpe and total return when every cost is scaled by k (needs the daily cost split)."""
    if daily.get('gross') is None:
        return None
    gross = np.asarray(daily['gross'], dtype=float) / 100.0
    cost = np.asarray(daily['cost'], dtype=float) / 100.0
    rows = []
    for k in COST_MULTIPLIERS:
        r = gross - k * cost
        rows.append({'k': k, 'sharpe': _r(_sharpe(r), 4), 'ret_pct': _r((np.prod(1 + r) - 1) * 100, 4)})
    return rows


def cost_schedules(funds, calendar):
    """The cost-schedule replay, without the archetype names (labelled A-E by total cost).

    The replay re-sizes and re-costs the main backtest's own trades, so its curves run on
    the main backtest's calendar; a schedule carries its own dates only if they differ.
    """
    profiles = list((funds or {}).get('profiles', {}).values())
    if not profiles:
        return None
    curves = funds.get('equity_curves') or {}
    profiles.sort(key=lambda p: (p.get('total_cost_pct_of_capital') or 0.0, p['profile_key']))
    out = []
    for letter, p in zip('ABCDEFGH', profiles):
        curve = (curves.get(p['profile_key']) or {}).get('curve') or []
        v0 = curve[0]['value'] if curve else None
        dates = [c['date'] for c in curve]
        out.append({
            'id': letter, 'source_key': p['profile_key'],
            'commission_bps': p.get('commission_bps'), 'half_spread_bps': p.get('bid_ask_bps'),
            'impact_cap_bps': p.get('market_impact_cap_bps'), 'borrow_pct': p.get('borrow_rate_gc_pct'),
            'financing_pct': p.get('financing_spread_pct'),
            'position_pct': [p.get('base_position_pct'), p.get('max_position_pct')],
            'ret_pct': _r(p.get('total_return_pct'), 4), 'sharpe': _r(p.get('sharpe_ratio'), 3),
            'max_dd_pct': _r(p.get('max_drawdown_pct'), 4), 'cost_pct': _r(p.get('total_cost_pct_of_capital'), 4),
            'peak_gross_x': _r(p.get('max_gross_leverage'), 3), 'trades': p.get('total_trades'),
            **({'dates': dates} if dates != calendar else {}),
            'cum': _rl(((c['value'] / v0 - 1) * 100 for c in curve), 4) if v0 else [],
        })
    return out


def funnel(res, universe):
    fdr = res.get('fdr_diagnostic') or {}
    traded = len({t['pair'] for t in res.get('all_trades') or []})
    names = [{'stage': 'Names in the universe file', 'n': _get(universe, 'selected')},
             {'stage': 'Names with price history', 'n': _get(res, 'run_config', 'data', 'n_symbols')}]
    pairs = [{'stage': 'Pairs tested (Engle–Granger)', 'n': fdr.get('pairs_tested')},
             {'stage': 'Cointegrated at raw p < 0.05', 'n': fdr.get('significant_raw_p05'),
              'expected': _r(fdr.get('expected_false_positives_at_p05'), 1)},
             {'stage': 'Selected (half-life, quality)', 'n': fdr.get('final_selected_pairs')},
             {'stage': 'Traded at least once', 'n': traded}]
    return {'names': [s for s in names if s['n'] is not None], 'pairs': [s for s in pairs if s['n'] is not None],
            'bh_q05': fdr.get('survive_bh_fdr_q05'), 'bh_q10': fdr.get('survive_bh_fdr_q10'),
            'pvalue_hist': fdr.get('pvalue_histogram')}


# ──────────────────────────────────────────────────────────────────────────────
# Facts: the scalars the page quotes in its text (always present; null if unknown)
# ──────────────────────────────────────────────────────────────────────────────

def facts(res, dev):
    """Scalars quoted in the page's text, from the export `res` and the assembled section `dev`.

    Money is in $ thousands or millions; a *_loss_* or *_gain_* key is the size of a
    loss or gain (its sign is in the name, so the text can say "lost $9.80M").
    """
    daily, power, wf, groups = dev['daily'], dev['power'], dev['walk_forward'], dev['trades']
    steps, fac, capital, roll = dev['waterfall'], dev['factors'], dev['run']['capital'], dev['rolling_sharpe']
    trades = res.get('all_trades') or []
    perf = res.get('overall_performance') or {}
    sig = res.get('significance') or {}
    n = len(trades)
    gross_bp = np.array([t['spread_return_pct'] * 100.0 for t in trades])               # bp of gross notional
    cost_bp = np.array([t['transaction_costs_dollars'] / t['position_size_dollars'] * 1e4 for t in trades])
    net_bp = gross_bp - cost_bp

    def t_of(x):
        return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))) if len(x) > 2 else None

    wins = sum(t['net_pnl_dollars'] > 0 for t in trades)
    step = {s['key']: s['usd'] for s in steps}           # empty when the run made no trade
    notional = sum(t['position_size_dollars'] for t in trades)
    costs = -sum(step[k] for k, _ in COST_STEPS) if step else None
    flat = sum(1 for p in daily['positions'] if p == 0)
    months = res.get('monthly_performance') or []
    best = max(months, key=lambda m: m['return_pct']) if months else None
    alt = {a['sharpe']: a for a in power['alternatives']}
    group = {g['label']: g for k in ('by_exit', 'by_side') for g in groups[k]}
    market = {r['series']: r for r in fac['market']}
    fa = res.get('factor_attribution') or {}

    def proxy_alpha(key):         # the market-proxy regression's alpha, % a year (the text quotes it)
        a = _get(fa, key, 'alpha_ann')
        return _r(100 * a, 4) if a is not None else None
    beta_main = market.get('Main backtest') or {}
    beta_oos = market.get('Walk-forward OOS') or {}
    k = lambda usd: _r(usd / 1e3, 1) if usd is not None else None    # noqa: E731  ($ thousands)
    m = lambda usd: _r(usd / 1e6, 2) if usd is not None else None    # noqa: E731  ($ millions)
    forest_rows = {row['key']: row for row in dev['forest']}
    rolled = [(sr, lo, hi) for sr, lo, hi in zip(roll['sharpe'], roll['lo'], roll['hi']) if sr is not None]
    return {
        'capital_musd': _r(capital / 1e6, 0),
        'days': len(daily['dates']), 'flat_days': flat, 'flat_pct': _r(100 * flat / len(daily['dates']), 1),
        'exposure_max_pct': _r(max(daily['exposure']), 2), 'positions_max': max(daily['positions']),
        'trades': n, 'wins': wins,
        'win_lo_pct': _r(100 * sps.beta.ppf(0.025, wins + 1, n - wins + 1), 1) if n else None,
        'win_hi_pct': _r(100 * sps.beta.ppf(0.975, wins + 1, n - wins + 1), 1) if n else None,
        'gross_bp': _r(gross_bp.mean(), 2) if n else None, 'gross_t': _r(t_of(gross_bp), 3),
        'cost_bp': _r(cost_bp.mean(), 2) if n else None,
        'net_bp': _r(net_bp.mean(), 2) if n else None, 'net_t': _r(t_of(net_bp), 3),
        'cost_bp_notional': _r(costs / notional * 1e4, 2) if notional and costs is not None else None,
        # the cost multiple at which net P&L is zero; none exists when gross P&L is not positive
        'break_even_x': _r(step['gross'] / costs, 3) if costs and step['gross'] > 0 else None,
        'gross_usd_k': k(step.get('gross')), 'cost_usd_k': k(costs), 'net_usd_k': k(step.get('net')),
        **{f'{key}_usd_k': k(-step[key]) if step else None for key, _ in COST_STEPS},
        'impact_share_pct': _r(-100 * step['market_impact'] / costs, 1) if costs else None,
        'gross_bp_capital': _r(step['gross'] / capital * 1e4, 1) if step else None,
        'net_bp_capital': _r(step['net'] / capital * 1e4, 1) if step else None,
        'cost_bp_capital': _r(costs / capital * 1e4, 1) if step else None,
        'stop_loss_usd_m': m(-_get(group, 'Stop', 'net_usd', default=float('nan'))),
        'target_gain_usd_m': m(_get(group, 'Target', 'net_usd')),
        'long_gain_usd_m': m(_get(group, 'Long spread', 'net_usd')),
        'short_loss_usd_m': m(-_get(group, 'Short spread', 'net_usd', default=float('nan'))),
        'pairs_traded': len({t['pair'] for t in trades}),
        'adv_participation_pct': _r(perf.get('avg_max_leg_adv_participation_pct'), 2),
        'hold_days': _r(perf.get('avg_trading_days_held'), 1),
        'gate_blocked_days': _get(perf, 'signal_rejections', 'regime_hard_stop_day'),
        'sharpe_se': power['se'], 'sharpe_ucb': power['ucb'], 'sharpe_critical': power['critical'],
        'sharpe_mde': power['mde'], 'skew': power['skew'], 'kurtosis': power['kurtosis'],
        'p_sr_ge_0_5': _get(alt, 0.5, 'p_ge'), 'p_sr_ge_1': _get(alt, 1.0, 'p_ge'),
        'min_trl_years_0_5': _get(alt, 0.5, 'min_trl_years'), 'min_trl_years_1': _get(alt, 1.0, 'min_trl_years'),
        'dsr_trials': _get(sig, 'main_backtest', 'deflated_sharpe', 'n_trials'),
        'main_days': _get(sig, 'main_backtest', 'n_days'), 'oos_days': _get(sig, 'oos_daily', 'n_days'),
        'oos_overlap_days': _get(res, 'benchmarks', 'vs_strategy', 'walk_forward_oos', 'n_common_days'),
        'stitched_pct': wf['stitched'][-1]['cum_pct'] if wf['stitched'] else None,
        'best_month_pct': _r(best['return_pct'], 2) if best else None,
        'months': len(months), 'months_positive': sum(1 for m in months if m['return_pct'] > 0),
        'beta_main': beta_main.get('beta'), 'beta_main_t': beta_main.get('t'),
        'beta_oos': beta_oos.get('beta'), 'beta_oos_t': beta_oos.get('t'),
        'alpha_main_pct': proxy_alpha('main_backtest'), 'alpha_oos_pct': proxy_alpha('walk_forward_oos'),
        'coverage_pct': _r(100 * _get(res, 'run_config', 'data', 'universe_coverage', default=float('nan')), 1),
        'gatev_lo': _get(forest_rows, 'gatev', 'lo'), 'gatev_hi': _get(forest_rows, 'gatev', 'hi'),
        'rolling_windows': len(roll['dates']),
        'rolling_min': min((x[0] for x in rolled), default=None), 'rolling_max': max((x[0] for x in rolled), default=None),
        'rolling_clear_zero': sum(1 for _, lo, hi in rolled if lo > 0 or hi < 0),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Other study arms (optional sources)
# ──────────────────────────────────────────────────────────────────────────────

RESIDUAL_EXPORT = 'residual_statarb.json'          # scripts/run_residual_statarb.py --out


def load_residual(src, directory):
    """The Avellaneda-Lee arm's export as scripts/publish_run.py publishes it, or None.

    Pending (None) until `directory` holds both the export and the MANIFEST.json that lists
    it. An export whose sha256 is not the one its manifest lists is not the published file,
    and one that is not a complete run of the registered arm on the development calendar is
    not what the page labels it: either stops the build.
    """
    directory = pathlib.Path(directory)
    export, manifest_path = directory / RESIDUAL_EXPORT, directory / 'MANIFEST.json'
    if not (export.is_file() and manifest_path.is_file()):
        return None
    manifest = src.load(manifest_path)
    listed = _get(manifest, 'files', RESIDUAL_EXPORT, 'sha256')
    if listed != _sha256(export):
        raise ValueError(f'{export} is not the file {manifest_path} lists (sha256 {listed}); publish it again '
                         'with scripts/publish_run.py')
    doc = src.load(export)
    calendar = _get(doc, 'run_config', 'study', 'calendar', 'name')
    if calendar != 'dev' or doc.get('complete') is not True or doc.get('non_default_switches'):
        raise ValueError(f'{export} is not a complete run of the registered arm on the dev calendar (calendar '
                         f'{calendar}, complete {doc.get("complete")}, switches {doc.get("non_default_switches")})')
    return doc


def residual_summary(doc):
    """The numbers of the residual arm the page and the paper show: the net Sharpe with its
    block-bootstrap 95% interval and Newey-West p (the export's significance battery, the
    one the pairs headline carries), total return in %, trades, period and commit."""
    s, sig = doc.get('summary') or {}, doc.get('significance') or {}
    ret = s.get('total_return')
    return {'sharpe': _r(s.get('sharpe'), 2), 'ret_pct': _r(None if ret is None else 100 * ret, 2),
            'trades': doc.get('total_trades'), 'lo': _r(sig.get('boot_lo'), 2), 'hi': _r(sig.get('boot_hi'), 2),
            'p': _r(sig.get('hac_p'), 3), 'period': [s.get('start'), s.get('end')],
            'commit': _get(doc, 'run_config', 'git_commit')}


def holdout_section(evaluation):
    """The pre-registered 2026 test from scripts/evaluate_holdout.py's report, or 'sealed'.

    One row per strategy: the hypothesis it tests, its net Sharpe with the block-bootstrap
    95% interval, the one-sided Newey-West test and its Holm-adjusted p-value (the decision
    rule), and what the record could detect. Strategies the runbook does not name keep
    their own key as a label, after the three registered ones.
    """
    if evaluation is None:
        return {'status': 'sealed', 'calendar_start': '2026-01-02'}
    strategies = evaluation.get('strategies') or {}
    known = {key: (h, label) for key, h, label in HOLDOUT_ARMS}
    order = [k for k, _, _ in HOLDOUT_ARMS if k in strategies] + sorted(k for k in strategies if k not in known)
    arms = []
    for key in order:
        s = strategies[key]
        h, label = known.get(key, (None, key))
        lo, hi = (list(s.get('bootstrap_ci_95') or []) + [None, None])[:2]
        arms.append({'key': key, 'hypothesis': h, 'label': label, 'sharpe': _r(s.get('sharpe')), 'lo': _r(lo), 'hi': _r(hi),
                     't': _r(s.get('t'), 3), 'p_one_sided': _r(s.get('p_one_sided')), 'p_holm': _r(s.get('p_holm')),
                     'edge': s.get('edge_out_of_sample'), 'role': s.get('role', 'confirmatory'),
                     'days': s.get('days'), 'trades': s.get('trades'),
                     'ret_pct': _r(s.get('total_return_pct')), 'ucb': _r(s.get('upper_bound_95')),
                     'mde': _r(s.get('min_detectable_sharpe')), 'period': s.get('period')})
    return {'status': 'complete', 'alpha': evaluation.get('alpha'), 'test': evaluation.get('test'), 'arms': arms}


def snooping(declaration, results):
    if declaration is None:
        return None
    grid = declaration.get('grid') or {}
    sizes = [len(v) for k, v in grid.items() if isinstance(v, list)]
    out = {'declared_utc': declaration.get('declared_utc'),
           'grid_points': int(np.prod(sizes)) if sizes else 0,
           'toggles': len(declaration.get('toggles') or []), 'results': None}
    if results:
        spa = results.get('spa_vs_zero') or {}
        out['results'] = {
            'spa_p': _get(spa, 'pvalues', 'consistent'), 'reality_check_p': _get(spa, 'reality_check', 'pvalue'),
            'romano_wolf_rejected': _get(results, 'romano_wolf_vs_zero', 'rejected', default=[]),
            'mcs_included': _get(results, 'mcs', 'included', default=[]),
            'effective_trials': _get(results, 'effective_trials', 'effective_rank'), 'pbo': results.get('pbo'),
        }
    return out


def validation(report):
    if report is None:
        return None
    e, n, s = report.get('edge') or {}, report.get('forced_null') or {}, report.get('selection') or {}

    def pooled(x):
        p = x.get('pooled_gross_per_trade') or {}
        return {'trades': p.get('trades'), 'mean_bp': _r(p.get('mean_gross_bp'), 2), 'se_bp': _r(p.get('se_bp'), 2),
                't': _r(p.get('t'), 2)}
    return {'seeds': report.get('seeds'), 'all_pass': report.get('all_pass'),
            'edge': {**pooled(e), 'median_net_sharpe': _r(e.get('median_net_sharpe'), 2), 'pass': e.get('pass')},
            'forced_null': {**pooled(n), 'pass': n.get('pass')},
            'hedge_ratio': {'median_abs_error': _r(e.get('hedge_ratio_abs_error_median'), 3),
                            'p90_abs_error': _r(e.get('hedge_ratio_abs_error_p90'), 3)},
            'selection': {'recall': _r(s.get('planted_recall'), 3),
                          'unrelated_per_planted_market': _r(s.get('unrelated_pairs_selected_per_planted_market'), 2),
                          'per_null_market': _r(s.get('pairs_selected_per_null_market'), 2),
                          'worst_fp_rate': _r(s.get('worst_market_false_positive_rate'), 4), 'pass': s.get('pass')}}


# ──────────────────────────────────────────────────────────────────────────────
# Assembly
# ──────────────────────────────────────────────────────────────────────────────

def build(dev=DEFAULT_DEV, results_root=None, root=ROOT):
    """Return the study dict built from the development run directory `dev`."""
    dev = pathlib.Path(dev)
    results_root = pathlib.Path(results_root) if results_root else pathlib.Path(root) / 'results'
    src = Sources(root)
    headline_path = dev / 'headline_metrics.json'
    headline = src.load(headline_path, required=True)
    res = src.load(_results_file(dev), required=True)
    funds = src.load(dev / 'fund_type_comparison.json')
    universe = src.load(dev / 'universe_meta.json')
    battery = src.load(dev / 'stats_battery.json')
    anatomy = src.load(dev / 'anatomy.json') or {}
    declaration = src.load(results_root / 'variant_family' / 'declaration.json')
    snoop = src.load(results_root / 'variant_family' / 'snooping.json')
    residual = load_residual(src, results_root / 'residual_dev')
    holdout = src.load(results_root / 'holdout2026' / 'evaluation.json')
    known = src.load(results_root / 'validation' / 'synthetic_validation.json')

    run = res.get('run_config') or {}
    capital = float(_get(res, 'metadata', 'initial_capital', default=1e8))
    daily = daily_series(res)
    gatev = gatev_series(res)
    r_main = np.asarray(daily['net'], dtype=float) / 100.0
    evidence = res.get('evidence') or {}
    if battery and battery.get('power'):
        power = power_from_report(battery['power'], 'stats battery')
    elif _get(evidence, 'main', 'min_detectable_sr_ann') is not None:
        power = power_from_report(evidence['main'], "the run's evidence block")
    else:
        power = power_from_returns(r_main)
    wf = walk_forward(res)
    trades = res.get('all_trades') or []
    groups = trade_groups(trades)
    net_usd = float(_get(res, 'overall_performance', 'final_portfolio_value', default=capital)) - capital
    steps = waterfall(trades, net_usd) if trades else []
    fac = factor_rows(res)
    months, annual = monthly_table(res)
    rnd = _get(res, 'benchmarks', 'random_control') or {}
    stamps = [run.get('run_timestamp_utc'), _get(residual, 'run_config', 'run_timestamp_utc')]

    dev_out = {
        'run': {
            'name': dev.name, 'version': headline.get('version'), 'commit': run.get('git_commit'),
            'dirty': run.get('git_dirty'), 'timestamp_utc': run.get('run_timestamp_utc'),
            'period': [_get(headline, 'main', 'period_start'), _get(headline, 'main', 'period_end')],
            'oos_period': [_get(headline, 'oos', 'period_start'), _get(headline, 'oos', 'period_end')],
            'data_span': [_get(run, 'data', 'data_start'), _get(run, 'data', 'data_end')],
            'symbols': _get(run, 'data', 'n_symbols'), 'pairs': _get(run, 'data', 'n_pairs'),
            'coverage': _get(run, 'data', 'universe_coverage'),
            'price_cache_sha256': _get(run, 'data', 'price_cache', 'sha256'),
            'universe_as_of': _get(universe, 'as_of_utc'), 'versions': run.get('versions'),
            'seed': _get(run, 'env', 'PAIRS_SEED'), 'capital': capital,
        },
        'daily': daily,
        'gatev': gatev,
        'random_band': random_band(res),
        'random_sharpes': _rl(rnd.get('draw_sharpes') or [], 4),
        'strategy_sharpe': _r(_get(res, 'overall_performance', 'sharpe_ratio')),
        'gatev_sharpe': _r(_get(res, 'benchmarks', 'distance_method', 'sharpe_ratio')),
        'random_percentile': rnd.get('strategy_percentile'),
        'walk_forward': wf,
        'monthly': months, 'annual': annual,
        'rolling_sharpe': rolling_sharpe(daily['dates'], daily['net']),
        'forest': forest(res, gatev['net'] if gatev else None, daily['gross']),
        'power': power,
        'dsr_curve': dsr_curve(r_main, battery),
        'waterfall': steps,
        'trades': groups,
        'factors': fac,
        'funnel': funnel(res, universe),
        'universe_by_formation': universe_coverage(res),
        'cost_schedules': cost_schedules(funds, daily['dates']),
        'cost_curve': cost_curve(daily),
        'snooping': snooping(declaration, snoop),
        **{key: anatomy[key] for key in ANATOMY_KEYS if anatomy.get(key) is not None},
    }
    dev_out['facts'] = facts(res, dev_out)

    study = {
        'schema': SCHEMA,
        'meta': {
            'builder': 'scripts/build_site_data.py',
            'generated_utc': max(s for s in stamps if s),
            'commit': run.get('git_commit'),
            'headline_sha256': _sha256(headline_path),
            'sources': dict(sorted(src.hashes.items())),
        },
        'dev': dev_out,
        'holdout': holdout_section(holdout),
        'residual': residual_summary(residual) if residual else None,
        'validation': validation(known),
    }
    return study


def dumps(study):
    """Compact, key-sorted JSON (one line per top-level section keeps diffs readable)."""
    parts = [f'{json.dumps(k)}:{json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False)}'
             for k, v in sorted(study.items())]
    return '{\n' + ',\n'.join(parts) + '\n}\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--dev', default=str(DEFAULT_DEV), metavar='RUN_DIR',
                    help='development run directory: results/<name>/ or a run\'s output directory '
                         '(default results/v32_dev)')
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='output file (default assets/study.json)')
    ap.add_argument('--check', action='store_true', help='exit 1 if the output file differs from a fresh build')
    args = ap.parse_args(argv)
    text = dumps(build(args.dev))
    out = pathlib.Path(args.out)
    if args.check:
        current = out.read_text(encoding='utf-8') if out.exists() else None
        if current != text:
            print(f'{out} is stale: run python scripts/build_site_data.py', file=sys.stderr)
            return 1
        print(f'{out} is up to date ({len(text.encode()) / 1024:.0f} KB)')
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(out)
    print(f'wrote {out} ({len(text.encode()) / 1024:.0f} KB) from {args.dev}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
