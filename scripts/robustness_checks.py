#!/usr/bin/env python3
"""Robustness checks of the development study, as a sceptical reviewer asked for them.

Development data only (study calendar 'dev', prices 2020-2025). Nothing here feeds back into
the design: no section re-chooses a parameter, and every run is the published design.

(a) start_dates    Path dependence of S1's main backtest. The v33 study is prepared once,
                   as run_complete_system prepares it (CompleteFixedRussell3000TradingSystem(
                   profile='v33', calendar='dev'): load_study_data, prepare_study), and
                   run_comprehensive_backtest is re-run with the start moved forward by 0, 21,
                   42, ... trading days (12 starts, all to the same end), then on the two
                   halves of the window as separate runs. Same pairs, same re-selection
                   schedule, same rules: only the day the book starts empty changes. Per run:
                   Sharpe, total return, trades; across runs: their spread, and each run's
                   Sharpe on the days all twelve share (path dependence on identical days).
                   The offset-0 run must reproduce the published main backtest to the cent.
(b) regimes        The published main backtest's daily net (and gross) returns
                   (results/v33_dev) by terciles of the previous trading day's VIX close and
                   of the previous day's cross-sectional dispersion of the 11 sector-ETF
                   returns (data/macro_data.pkl), and by calendar year: days, mean daily
                   return (bp), annualised Sharpe and a Newey-West t, with the
                   high-minus-low difference.
(c) persistence    The anatomy's year-by-year cointegration-persistence table (Clegg 2014;
                   pairs_trading.anatomy.cointegration_persistence: same test, screen, alpha,
                   one-year windows) recomputed on the candidate pairs S1 itself searches
                   instead of every pair of the 300 most liquid names: the same-Fama-French-
                   49-industry pairs of the 500 most liquid point-in-time members that pass
                   S1's screen at the first formation (data to 2022-12-31, the anatomy
                   table's cutoff); and, as a sensitivity, the union of those candidate sets
                   over every formation of the run.
(d) s2_trade_edge  S2's per-trade gross (and net) edge, results/residual_dev/residual_statarb.
                   json, with standard errors clustered by entry month (CR1), next to the
                   independent-trades t of the export; entry date and symbol as alternative
                   clusters.

Writes results/v33_dev/robustness.json (or --out) and lists it in that directory's
MANIFEST.json (publish_run's format; --no-manifest skips it). The output is deterministic for
given inputs and code (no timestamps); every input's sha256 is recorded, and the price cache,
its fetch manifest and the macro cache are hashed again at the end and must be unchanged.
The caches are only read: the script stops before loading if the study's universe names a
symbol the price cache's fetch manifest has no outcome for (load_study_data would then fetch
it and rewrite the cache), and the data processor's fetch and cache-write methods are
disabled for the run. BLAS runs on one thread (threadpoolctl), as in run_complete_system.

usage: PYTHONHASHSEED=0 python scripts/robustness_checks.py [--out FILE] [--sections a b c d]
                                                           [--n-jobs N] [--no-manifest]
About 20 minutes on four cores: one load and one preparation of the study, 14 backtests,
and the persistence tests.
"""
import argparse
import hashlib
import json
import logging
import os
import pathlib
import sys
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sps

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

from pairs_trading import anatomy as A  # noqa: E402
from pairs_trading.json_export import _atomic_write_json, _git_state  # noqa: E402
from pairs_trading.pair_selector import formation_window, screen_symbols  # noqa: E402
from pairs_trading.significance import _newey_west_lags, annualized_sharpe, hac_tstat_mean  # noqa: E402
from pairs_trading.trading_system import TRADING_DAYS_PER_YEAR, _align_ts  # noqa: E402

SCHEMA = 1
PROFILE, CALENDAR = 'v33', 'dev'          # fixed: this script never runs another calendar
SEED = 42                                 # PAIRS_SEED of the published run
N_STARTS, START_STEP = 12, 21             # starts 0, 21, ..., 231 trading days after the first
TERCILES = ('low', 'mid', 'high')
DEV = ROOT / 'results' / 'v33_dev'
RESULTS_FILE = DEV / 'pairs_trading_results_2023_2025_unbiased.json'
ANATOMY_FILE = DEV / 'anatomy.json'
RESIDUAL_FILE = ROOT / 'results' / 'residual_dev' / 'residual_statarb.json'
DEFAULT_OUT = DEV / 'robustness.json'
# The exported equity curve is rounded to cents: a re-run within a cent per day reproduces it.
EQUITY_TOLERANCE_USD = 0.01

log = logging.getLogger('robustness_checks')


# ──────────────────────────────────────────────────────────────────────────────
# Inputs: fingerprints, the read-only guard
# ──────────────────────────────────────────────────────────────────────────────

def _rel(path) -> str:
    path = pathlib.Path(path).absolute()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(pathlib.Path(path.parent.name) / path.name)


def fingerprint(path) -> Dict:
    """Path (repository-relative), size and sha256 of a file."""
    path = pathlib.Path(path)
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return {'path': _rel(path), 'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def never_attempted(wanted: Sequence[str], manifest: Dict) -> List[str]:
    """The symbols of `wanted` that a price cache's fetch manifest neither holds nor records an
    outcome for: exactly the symbols load_or_fetch_data's top-up would fetch (and then rewrite
    the cache and its manifest)."""
    outcomes = manifest.get('outcomes') or {}
    cached = set(manifest.get('cached_symbols') or [])
    return sorted(s for s in set(wanted) if s not in outcomes and s not in cached)


def _refuse(*_args, **_kwargs):
    raise RuntimeError('robustness_checks only reads the caches: the data processor tried to fetch or '
                       'to write a cache')


def disable_fetch_and_cache_writes(processor) -> None:
    """Shadow every method through which the data processor fetches or writes a cache (its
    top-up still runs, and returns the cache unchanged when no symbol is missing), and make
    the macro loader read its cache only (fetch=False: a missing cache raises)."""
    for name in ('_fetch_many', '_fetch_pass', 'fetch_stock_data', '_download_history', '_atomic_pickle'):
        setattr(processor, name, _refuse)
    read_macro = processor.load_macro_data
    processor.load_macro_data = lambda fetch=False: read_macro(fetch=False)


def check_caches_are_read_only(system) -> Dict:
    """Stop unless load_study_data would only read the price and macro caches; returns the
    caches' fingerprints."""
    proc = system.data_processor
    manifest_path = proc.data_file.replace('.pkl', '_manifest.json')
    for path in (proc.data_file, manifest_path, proc.macro_file):
        if not os.path.exists(path):
            raise SystemExit(f'{path} not found: this script reads the existing caches and never fetches')
    manifest = json.loads(pathlib.Path(manifest_path).read_text())
    if (manifest.get('start'), manifest.get('end')) != (system.calendar.data_start, system.calendar.data_end):
        raise SystemExit(f"{manifest_path} describes {manifest.get('start')} -> {manifest.get('end')}, not the "
                         f"{system.calendar.name} calendar")
    missing = never_attempted(system._study_symbols(), manifest)
    if missing:
        raise SystemExit(f'load_study_data would top up the price cache ({len(missing)} universe symbols were '
                         f'never fetched: {missing[:10]}); this script does not fetch. Stopped before loading.')
    disable_fetch_and_cache_writes(proc)
    return {'price_cache': fingerprint(proc.data_file), 'price_fetch_manifest': fingerprint(manifest_path),
            'macro_cache': fingerprint(proc.macro_file)}


# ──────────────────────────────────────────────────────────────────────────────
# Small statistics
# ──────────────────────────────────────────────────────────────────────────────

def spread(values) -> Dict:
    """n, min, max, range, mean, median and sample sd of a set of values."""
    v = np.asarray(values, dtype=float)
    return {'n': int(v.size), 'min': float(v.min()), 'max': float(v.max()), 'range': float(v.max() - v.min()),
            'mean': float(v.mean()), 'median': float(np.median(v)),
            'sd': float(v.std(ddof=1)) if v.size > 1 else None}


def compounded_pct(r) -> float:
    r = np.asarray(r, dtype=float)
    return float((np.prod(1.0 + r) - 1.0) * 100.0) if r.size else 0.0


def hac_bucket_means(r, labels, order: Sequence, lags: Optional[int] = None) -> Dict:
    """Mean of `r` in each bucket with Newey-West standard errors, from one regression.

    r_t = sum_j b_j 1{label_t = j} + e_t over the whole series (no intercept, so b_j is the
    bucket's mean), with the Bartlett-kernel HAC covariance (X'X)^-1 S (X'X)^-1 at `lags`
    (default: the Newey-West rule for the full length, significance._newey_west_lags) and no
    small-sample correction, as significance.hac_tstat_mean. Autocovariances are taken at
    their true distance in the series, not between consecutive days of one bucket; with one
    bucket the t is hac_tstat_mean's. The difference is the last bucket of `order` minus the
    first, with its HAC t. p-values are two-sided normal.
    """
    r = np.asarray(r, dtype=float)
    labels = np.asarray(labels)
    n = r.size
    L = _newey_west_lags(n) if lags is None else int(lags)
    X = np.column_stack([(labels == g).astype(float) for g in order])
    nj = X.sum(axis=0)
    b = np.divide(X.T @ r, nj, out=np.full(len(order), np.nan), where=nj > 0)
    e = r - X @ np.nan_to_num(b)
    U = X * e[:, None]
    S = U.T @ U
    for k in range(1, min(L, n - 1) + 1):
        w = 1.0 - k / (L + 1.0)
        G = U[k:].T @ U[:-k]
        S += w * (G + G.T)
    with np.errstate(divide='ignore', invalid='ignore'):
        V = S / np.outer(nj, nj)
    se = np.sqrt(np.clip(np.diag(V), 0.0, None))
    rows = []
    for j, g in enumerate(order):
        sub = r[labels == g]
        t = float(b[j] / se[j]) if nj[j] > 0 and se[j] > 0 else None
        rows.append({'bucket': g if isinstance(g, str) else int(g), 'days': int(nj[j]),
                     'mean_daily_bp': float(b[j] * 1e4) if nj[j] > 0 else None,
                     'sharpe': annualized_sharpe(sub, TRADING_DAYS_PER_YEAR) if sub.size else None,
                     'nw_t': t, 'nw_p': float(2.0 * sps.norm.sf(abs(t))) if t is not None else None,
                     'return_pct_on_these_days': compounded_pct(sub)})
    hi, lo = len(order) - 1, 0
    d = float(b[hi] - b[lo]) if nj[hi] > 0 and nj[lo] > 0 else None
    var_d = float(V[hi, hi] + V[lo, lo] - 2.0 * V[hi, lo]) if d is not None else None
    t_d = float(d / np.sqrt(var_d)) if d is not None and var_d > 0 else None
    return {'nw_lags': int(L), 'buckets': rows,
            'last_minus_first': {'buckets': [rows[hi]['bucket'], rows[lo]['bucket']],
                                 'mean_daily_bp': d * 1e4 if d is not None else None, 'nw_t': t_d,
                                 'nw_p': float(2.0 * sps.norm.sf(abs(t_d))) if t_d is not None else None}}


def clustered_mean(values, groups) -> Dict:
    """Mean of `values` with independent and cluster-robust (CR1) standard errors.

    CR1: Var = G/(G-1) * sum_g (sum_{i in g} (x_i - mean))^2 / n^2 (anatomy._clustered_t; the
    (n-1)/(n-k) factor is 1 for a mean). The clustered p uses Student t with G - 1 degrees of
    freedom, the independent one n - 1. design_effect = (SE_clustered / SE_independent)^2 and
    effective_n = n / design_effect.
    """
    x = np.asarray(values, dtype=float)
    g = np.asarray(groups)
    keep = np.isfinite(x)
    x, g = x[keep], g[keep]
    n = int(x.size)
    mean = float(x.mean())
    sd = float(x.std(ddof=1))
    se_iid = sd / np.sqrt(n)
    codes, uniques = pd.factorize(g, sort=True)
    G = int(len(uniques))
    u = np.bincount(codes, weights=x - mean, minlength=G)
    se_cl = float(np.sqrt((u ** 2).sum() / n ** 2 * G / (G - 1))) if G > 1 else None
    t_iid, t_cl = mean / se_iid, (mean / se_cl if se_cl else None)
    deff = (se_cl / se_iid) ** 2 if se_cl else None
    sizes = np.bincount(codes, minlength=G)
    return {'n': n, 'clusters': G, 'largest_cluster': int(sizes.max()), 'median_cluster': float(np.median(sizes)),
            'mean': mean, 'sd': sd,
            'se_independent': float(se_iid), 't_independent': float(t_iid),
            'p_independent': float(2.0 * sps.t.sf(abs(t_iid), n - 1)),
            'se_clustered': se_cl, 't_clustered': float(t_cl) if t_cl is not None else None,
            'p_clustered': float(2.0 * sps.t.sf(abs(t_cl), G - 1)) if t_cl is not None else None,
            'design_effect': float(deff) if deff is not None else None,
            'effective_n': float(n / deff) if deff else None}


# ──────────────────────────────────────────────────────────────────────────────
# (a) Start-date sensitivity
# ──────────────────────────────────────────────────────────────────────────────

def summarise_run(res: Dict) -> Dict:
    r = np.asarray(res['daily_returns'], dtype=float)
    dates = list(res['daily_dates'])
    return {'first_day': dates[0] if dates else None, 'last_day': dates[-1] if dates else None, 'days': int(r.size),
            'sharpe': float(res['sharpe_ratio']), 'total_return_pct': float(res['total_return'] * 100.0),
            'trades': int(res['total_trades']), 'max_drawdown_pct': float(res['max_drawdown'] * 100.0),
            'nw_t': hac_tstat_mean(r)['tstat']}


def _on_days(res: Dict, first: str, last: str) -> Dict:
    """A run's Sharpe and compounded return on its days in [first, last]."""
    r = pd.Series(np.asarray(res['daily_returns'], dtype=float), index=list(res['daily_dates']))
    sub = r[(r.index >= first) & (r.index <= last)].to_numpy()
    return {'days': int(sub.size), 'sharpe': annualized_sharpe(sub, TRADING_DAYS_PER_YEAR),
            'total_return_pct': compounded_pct(sub)}


def reproduces_published(res: Dict, published: Dict) -> Dict:
    """Whether a re-run is the published main backtest: same days and trades, and an equity
    curve within EQUITY_TOLERANCE_USD of the exported one (rounded to cents) on every day."""
    curve = published.get('daily_equity_curve') or []
    same_days = [c['date'] for c in curve] == list(res['daily_dates'])
    diff = (float(np.abs(np.array([c['portfolio_value'] for c in curve]) - np.asarray(res['equity_curve'])).max())
            if same_days and curve else None)
    trades = len(published.get('all_trades') or [])
    return {'same_days': bool(same_days), 'max_abs_equity_diff_usd': diff,
            'trades_run': int(res['total_trades']), 'trades_published': int(trades),
            'verified': bool(same_days and diff is not None and diff <= EQUITY_TOLERANCE_USD
                             and trades == res['total_trades'])}


def start_date_sensitivity(system, test_spreads: Dict, pair_windows: Dict, start, end,
                           n_starts: int = N_STARTS, step: int = START_STEP) -> Tuple[Dict, Dict]:
    """Main backtests from `n_starts` start dates `step` trading days apart, all to `end`, and on
    the two halves of the window; returns (section, the offset-0 run's results).

    The trading days are the offset-0 run's days up to `end` (the engine's calendar). The
    common window runs from the last start to `end`: every run holds those days. The halves
    split the window's days in two (the first half one day shorter when their number is odd);
    each is a separate run, so the first half's positions open at its end run off on the
    days after it (the engine's rule: no new entries, own exit rules) and its book starts
    empty, unlike the same days inside the continuous run (main_run_same_days).
    """
    base = system.run_comprehensive_backtest(test_spreads, pair_windows=pair_windows, date_range=(start, end))
    end_day = str(pd.Timestamp(end).date())
    window = [d for d in base['daily_dates'] if d <= end_day]
    if (n_starts - 1) * step >= len(window):
        raise ValueError(f'{n_starts} starts {step} days apart need more than {len(window)} trading days')
    starts = [window[i * step] for i in range(n_starts)]
    common = (starts[-1], window[-1])
    runs = []
    for i, s in enumerate(starts):
        res = base if i == 0 else system.run_comprehensive_backtest(test_spreads, pair_windows=pair_windows,
                                                                    date_range=(s, end))
        row = {'offset_trading_days': i * step, 'start': s, **summarise_run(res),
               'common_window': _on_days(res, *common)}
        runs.append(row)
        log.info(f"start {s}: Sharpe {row['sharpe']:+.3f}, return {row['total_return_pct']:+.3f}%, "
                 f"{row['trades']} trades; common window Sharpe {row['common_window']['sharpe']:+.3f}")
    half = len(window) // 2
    halves = []
    for label, (a, b) in (('first', (window[0], window[half - 1])), ('second', (window[half], window[-1]))):
        res = system.run_comprehensive_backtest(test_spreads, pair_windows=pair_windows, date_range=(a, b))
        summary = summarise_run(res)
        halves.append({'half': label, 'entry_window': [a, b], 'entry_days': int(sum(a <= d <= b for d in window)),
                       **summary, 'run_off_days': int(sum(d > b for d in res['daily_dates'])),
                       'main_run_same_days': _on_days(base, a, b)})
        log.info(f"{label} half {a} -> {b}: Sharpe {summary['sharpe']:+.3f}, {summary['trades']} trades")
    section = {
        'design': {'starts': n_starts, 'step_trading_days': step, 'end': end_day,
                   'window': [window[0], window[-1]], 'window_trading_days': len(window)},
        'runs': runs,
        'common_window': {'first': common[0], 'last': common[1], 'days': runs[0]['common_window']['days']},
        'spread': {'sharpe': spread([r['sharpe'] for r in runs]),
                   'sharpe_common_window': spread([r['common_window']['sharpe'] for r in runs]),
                   'total_return_pct': spread([r['total_return_pct'] for r in runs]),
                   'total_return_pct_common_window': spread([r['common_window']['total_return_pct'] for r in runs]),
                   'trades': spread([r['trades'] for r in runs])},
        'halves': halves,
    }
    return section, base


# ──────────────────────────────────────────────────────────────────────────────
# (b) Regimes
# ──────────────────────────────────────────────────────────────────────────────

def _naive_index(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return pd.Series(s.to_numpy(), index=idx.normalize()).sort_index()


def previous_value(series: pd.Series, dates) -> np.ndarray:
    """For each date, the latest observation of `series` dated strictly before it (NaN if none)."""
    s = _naive_index(series.dropna())
    pos = s.index.searchsorted(pd.DatetimeIndex(dates), side='left') - 1
    values = s.to_numpy(dtype=float)
    return np.where(pos >= 0, values[np.clip(pos, 0, None)], np.nan)


def sector_dispersion(sectors: Dict[str, pd.Series]) -> pd.Series:
    """Cross-sectional sample standard deviation (ddof 1) of the sector ETFs' close-to-close
    returns, on the days on which every ETF has a return."""
    rets = pd.DataFrame({k: _naive_index(v).pct_change(fill_method=None) for k, v in sorted(sectors.items())})
    return rets.dropna(how='any').std(axis=1, ddof=1)


def terciles(values) -> Tuple[np.ndarray, List[float]]:
    """Labels low / mid / high at the sample's 1/3 and 2/3 quantiles (low <= q1 < mid <= q2 < high)."""
    v = np.asarray(values, dtype=float)
    q1, q2 = (float(q) for q in np.quantile(v, [1.0 / 3.0, 2.0 / 3.0]))
    return np.where(v <= q1, 'low', np.where(v <= q2, 'mid', 'high')), [q1, q2]


def regime_breakdown(results: Dict, macro: Dict) -> Dict:
    """Section (b): the main backtest's daily returns by VIX and dispersion terciles and by year."""
    daily = A.daily_series(results, pd.DataFrame())
    dates = pd.DatetimeIndex(daily['dates'])
    series = {'net': np.asarray(daily['net'], dtype=float)}
    if daily['gross'] is not None:
        series['gross'] = np.asarray(daily['gross'], dtype=float)
    states = {'vix': previous_value(macro['VIX'], dates),
              'sector_dispersion': previous_value(sector_dispersion(macro['sectors']), dates)}
    out = {'days': int(len(dates)), 'first_day': str(dates[0].date()), 'last_day': str(dates[-1].date()),
           'returns': {'net': 'daily net return: change in equity / previous equity (the exported equity curve)',
                       'gross': 'daily gross return: mark-to-market P&L before costs / previous equity '
                                '(the export\'s gross_return_pct)'}}
    for name, state in states.items():
        if np.isnan(state).any():
            raise ValueError(f'{name}: no observation before {dates[np.isnan(state)][0].date()}')
        labels, breaks = terciles(state)
        out[name] = {'breakpoints': breaks, 'min': float(state.min()), 'max': float(state.max()),
                     **{k: hac_bucket_means(r, labels, TERCILES) for k, r in series.items()}}
    years = np.asarray(dates.year)
    out['calendar_year'] = {k: hac_bucket_means(r, years, sorted(set(years.tolist()))) for k, r in series.items()}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# (c) Cointegration persistence on S1's candidate pairs
# ──────────────────────────────────────────────────────────────────────────────

def persistence_on_pairs(prices: Dict[str, pd.DataFrame], pairs, years: Sequence[int] = A.PERSISTENCE_YEARS,
                         alpha: float = A.PERSISTENCE_ALPHA, n_jobs: int = 1) -> Dict:
    """anatomy.cointegration_persistence on a given set of pairs instead of every pair of a
    symbol list; identical otherwise (tests/test_robustness_checks.py checks that on every pair
    of a symbol list the two tables are equal)."""
    pairs = sorted({tuple(sorted(p)) for p in pairs})
    symbols = sorted({s for p in pairs for s in p})
    threshold = A._persistence_selector().correlation_threshold
    naive = {s: A._naive(prices[s])[['Close', 'Returns']] for s in symbols}

    def year_frames(y):
        lo, hi = pd.Timestamp(f'{y}-01-01'), pd.Timestamp(f'{y}-12-31')
        return {s: df[(df.index >= lo) & (df.index <= hi)] for s, df in naive.items()}

    screened = {y: A._run_tests(year_frames(y), pairs, True, n_jobs) for y in sorted({*years, max(years) + 1})}
    tested = {y: [(pair, p) for pair, (_, p) in zip(pairs, res) if p is not None] for y, res in screened.items()}
    base = {y: A._share(sum(p < alpha for _, p in t), len(t), alpha) for y, t in tested.items()}
    rows = []
    for y in years:
        sig = [pair for pair, p in tested[y] if p < alpha]
        nxt = A._run_tests(year_frames(y + 1), sig, False, n_jobs) if sig else []
        testable = [p for _, p in nxt if p is not None]
        k = sum(p < alpha for p in testable)
        rows.append({'year': int(y), 'next_year': int(y + 1),
                     'correlated_pairs': int(sum(1 for c, _ in screened[y] if c is not None and c >= threshold)),
                     'cointegrated': base[y],
                     'still_cointegrated_next_year': {
                         **A._share(k, len(testable), alpha),
                         'next_year_base_rate': base[y + 1]['share'],
                         'binom_p_vs_next_year_base_rate': A._against_base_rate(k, len(testable), base[y + 1]['share'])},
                     'untestable_next_year': int(len(nxt) - len(testable))})
    return {'schema': A.PERSISTENCE_SCHEMA, 'symbols': len(symbols), 'pairs': len(pairs), 'alpha': alpha,
            'test': 'two-direction Engle-Granger, Bonferroni p = min(1, 2 min(p12, p21)) (PairSelector.cointegration_pvalue)',
            'correlation_screen': threshold, 'min_common_days': A.PERSISTENCE_MIN_DAYS, 'years': rows,
            'base_rates': [{'year': int(y), **b} for y, b in base.items()],
            'pooled_still_cointegrated': A._pooled_persistence([r['still_cointegrated_next_year'] for r in rows], alpha)}


def formation_candidates(system, date, initial: bool) -> Tuple[List[str], List[Tuple[str, str]]]:
    """The symbols and candidate pairs of S1's pair search at a formation date.

    The data the system hands to find_quality_pairs (prepare_study for the initial selection:
    each point-in-time member's bars to the cutoff; _full_reselection for the others: the
    trailing formation window), >= 100 bars; then the selector's own screen, its max_universe
    most liquid names and its candidate_pairs (same industry when the profile says so).
    """
    members = set(system.pit_universe.members_asof(date)) if system.pit_universe is not None else None
    data = {}
    for sym, df in system.processed_data.items():
        if len(df.index) == 0 or (members is not None and sym not in members):
            continue
        w = (df[df.index <= _align_ts(date, df.index[0])] if initial
             else formation_window(df, date, system.profile.formation_calendar_days))
        if len(w) >= 100:
            data[sym] = w
    selector = system._new_pair_selector()
    symbols = sorted(s for s, _ in screen_symbols(data, selector.min_dollar_volume)[:selector.max_universe])
    return symbols, selector.candidate_pairs(symbols)


def _table_summary(table: Dict) -> List[Dict]:
    """Per year: the share cointegrated, the share still cointegrated a year later and the
    next year's base rate (for the side-by-side with the anatomy's table)."""
    return [{'year': r['year'], 'cointegrated_share': r['cointegrated']['share'],
             'cointegrated_of': r['cointegrated']['of'],
             'still_share': r['still_cointegrated_next_year']['share'],
             'still_of': r['still_cointegrated_next_year']['of'],
             'next_year_base_rate': r['still_cointegrated_next_year']['next_year_base_rate']}
            for r in table['years']]


def persistence_section(system, n_jobs: int, anatomy: Optional[Dict]) -> Dict:
    """Section (c): the persistence table on the first formation's candidate pairs and on the
    union of every formation's."""
    formations = [row['formation_date'] for row in system.universe_coverage_log]
    first = str(pd.Timestamp(system.calendar.selection_cutoff).date())
    if not formations or formations[0] != first:
        raise RuntimeError(f'the first formation is not the selection cutoff {first}: {formations[:2]}')
    symbols, pairs = formation_candidates(system, first, initial=True)
    searched = list(getattr(system.pair_selector, 'last_quality_symbols', []) or [])
    if symbols != searched:
        raise RuntimeError('the rebuilt first-formation universe differs from the one the pair search used')
    per_formation, union = [], set(pairs)
    per_formation.append({'formation_date': first, 'symbols': len(symbols), 'candidate_pairs': len(pairs)})
    for date in formations[1:]:
        s, p = formation_candidates(system, date, initial=False)
        per_formation.append({'formation_date': date, 'symbols': len(s), 'candidate_pairs': len(p),
                              'shared_with_first': len(set(p) & set(pairs))})
        union.update(p)
    log.info(f'Persistence on the first formation\'s {len(pairs):,} candidate pairs ({len(symbols)} names)')
    first_table = persistence_on_pairs(system.processed_data, pairs, n_jobs=n_jobs)
    log.info(f'Persistence on the union of {len(per_formation)} formations\' candidate pairs ({len(union):,})')
    union_table = persistence_on_pairs(system.processed_data, sorted(union), n_jobs=n_jobs)
    reference = ((anatomy or {}).get('persistence_detail') or {}).get('clegg')
    return {
        'definition': (
            "Clegg (2014) persistence, the anatomy's table (pairs_trading.anatomy.cointegration_persistence) "
            "with only the set of pairs changed. For each calendar year Y of 2020-2024 and for Y + 1: a pair "
            "is tested if its daily return correlation in that year is at least the selector's screen (0.25) "
            "and both legs have at least 200 common days; it is cointegrated in the year if the two-direction "
            "Engle-Granger test on the year's log closes gives Bonferroni p < 0.05. The year's base rate is "
            "the share of its tested pairs that are cointegrated. 'Still cointegrated' is the share of the "
            "pairs cointegrated in Y that test p < 0.05 on Y + 1's data (no correlation screen in Y + 1; pairs "
            "without 200 common days in Y + 1 are untestable and counted apart). Two references: alpha = 0.05 "
            "is the nominal rate of a test at its size under no cointegration, and the base rate of Y + 1 is "
            "the model-free one (if cointegration in Y carried no information about Y + 1, the conditional "
            "share would equal it). Pairs share legs, so the binomial intervals overstate the precision. "
            "Prices: the study's loaded price cache (Close and Returns; the point-in-time anchoring does not "
            "change Close)."),
        'candidate_sets': {
            'first_formation': (
                f"The pairs S1's first pair search tested: the point-in-time Russell 3000 members on {first} "
                "with price history (>= 100 bars to the cutoff) that pass S1's screen (>= 300 bars, mean "
                "point-in-time price >= $5 and dollar volume >= $10M, annualised volatility 5-80%, < 10% "
                f"missing closes), the {system.profile.max_universe} most liquid of them, and of those every "
                "pair in the same Fama-French 49 industry. The universe is fixed at the cutoff for every year "
                "(the anatomy's 300-name table uses the same cutoff), so 2020-2021 are seen through a universe "
                "chosen on data to 2022."),
            'union_of_formations': (
                "The union of the candidate pairs of every formation of the run (the first and each full "
                "re-selection on its trailing 1,095-day window, each with that date's point-in-time members), "
                "tested on the same years."),
        },
        'formations': per_formation,
        'first_formation': first_table,
        'union_of_formations': union_table,
        'reference_300_names_all_pairs': (
            {'symbols': reference.get('symbols'), 'pairs': reference.get('pairs'),
             'universe_cutoff': reference.get('universe_cutoff'), 'years': _table_summary(reference),
             'pooled_still_cointegrated': reference.get('pooled_still_cointegrated')} if reference else None),
    }


# ──────────────────────────────────────────────────────────────────────────────
# (d) S2's per-trade edge, clustered
# ──────────────────────────────────────────────────────────────────────────────

def s2_trade_edge(residual: Dict) -> Dict:
    """Section (d): S2's per-trade gross and net edge (bp of the trade's stock notional,
    equal-weighted) with independent and clustered standard errors."""
    trades = residual['trades']
    groups = {'entry_month': [t['entry_date'][:7] for t in trades],
              'entry_date': [t['entry_date'] for t in trades],
              'symbol': [t['symbol'] for t in trades]}
    out = {'trades': len(trades),
           'definition': ("Per trade, gross_bp and net_bp of the export (P&L of the stock leg and its ETF hedge "
                          "per stock notional, in bp; net after costs), averaged over trades with equal "
                          "weights. 'independent' treats the trades as independent draws (the export's t); "
                          "'clustered' allows any correlation between trades in the same cluster (CR1, "
                          "Student t with clusters - 1 degrees of freedom). Entry month is the primary "
                          "clustering: trades entered in the same month overlap in time and share market "
                          "moves; entry date and symbol are alternatives.")}
    for field in ('gross_bp', 'net_bp'):
        x = [t[field] for t in trades]
        out[field] = {name: clustered_mean(x, g) for name, g in groups.items()}
    summary = residual.get('summary') or {}
    exported = summary.get('gross_bp_per_trade') or {}
    mine = out['gross_bp']['entry_month']
    out['export_check'] = {
        'gross_bp_per_trade': exported,
        'reproduced': bool(exported and np.isclose(exported.get('mean'), mine['mean'], rtol=0, atol=1e-9)
                           and np.isclose(exported.get('se'), mine['se_independent'], rtol=0, atol=1e-9)
                           and exported.get('n') == mine['n'])}
    out['daily_series_nw_t'] = {'gross': summary.get('hac_t_gross'), 'net': summary.get('hac_t_net'),
                                'note': "the export's Newey-West t of the daily gross and net return series, "
                                        "for comparison"}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────────────

def record_in_manifest(out: pathlib.Path) -> Optional[pathlib.Path]:
    """List `out` (sha256, bytes) in MANIFEST.json beside it, in publish_run's format
    (indent 1, sorted keys, newline); None when there is no manifest."""
    manifest_path = out.parent / 'MANIFEST.json'
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text())
    digest = fingerprint(out)
    manifest.setdefault('files', {})[out.name] = {'sha256': digest['sha256'], 'bytes': digest['bytes']}
    manifest['files'] = dict(sorted(manifest['files'].items()))
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    return manifest_path


def _study_sections(sections: Sequence[str], n_jobs: int, results: Dict, anatomy: Optional[Dict]) -> Dict:
    """Sections (a) and (c), on the loaded and prepared v33 development study."""
    from threadpoolctl import threadpool_limits

    from pairs_trading.main import seed_everything
    from pairs_trading.study_config import describe
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem

    out = {}
    with threadpool_limits(limits=1, user_api='blas'):          # as run_complete_system
        seed_everything(SEED)
        system = CompleteFixedRussell3000TradingSystem(profile=PROFILE, calendar=CALENDAR)
        caches = check_caches_are_read_only(system)
        system.load_study_data()
        test_spreads, pair_windows, last_test = system.prepare_study()
        out['study'] = describe(system.profile, system.calendar)
        if 'a' in sections:
            section, base = start_date_sensitivity(system, test_spreads, pair_windows,
                                                   system.calendar.backtest_start, last_test)
            section['offset_0_reproduces_published_main_backtest'] = reproduces_published(base, results)
            out['start_dates'] = section
        if 'c' in sections:
            out['persistence'] = persistence_section(system, n_jobs, anatomy)
    after = {k: fingerprint(v['path']) for k, v in caches.items()}
    if after != caches:
        raise RuntimeError(f'a cache changed during the run: {caches} -> {after}')
    out['caches'] = caches
    return out


def build(sections: Sequence[str], n_jobs: int) -> Dict:
    results = json.loads(RESULTS_FILE.read_text())
    anatomy = json.loads(ANATOMY_FILE.read_text())
    inputs = {'results': fingerprint(RESULTS_FILE), 'anatomy': fingerprint(ANATOMY_FILE)}
    commit, dirty = _git_state()
    out = {'schema': SCHEMA, 'builder': 'scripts/robustness_checks.py',
           'code': {'git_commit': commit, 'git_dirty': dirty, 'seed': SEED,
                    'pythonhashseed': os.environ.get('PYTHONHASHSEED')},
           'profile': PROFILE, 'calendar': CALENDAR, 'sections': sorted(sections), 'inputs': inputs}
    if {'a', 'c'} & set(sections):
        study = _study_sections(sections, n_jobs, results, anatomy)
        out['study'] = study.pop('study')
        inputs.update(study.pop('caches'))
        out.update(study)
    if 'b' in sections:
        from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
        from pairs_trading.study_config import get_calendar
        macro_path = ROOT / get_calendar(CALENDAR).macro_cache
        inputs.setdefault('macro_cache', fingerprint(macro_path))
        macro = EnhancedRussell3000DataProcessor._load_pickle_or_raise(str(macro_path))
        out['regimes'] = regime_breakdown(results, macro)
    if 'd' in sections:
        inputs['residual'] = fingerprint(RESIDUAL_FILE)
        out['s2_trade_edge'] = s2_trade_edge(json.loads(RESIDUAL_FILE.read_text()))
    out['inputs'] = dict(sorted(inputs.items()))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    ap.add_argument('--sections', nargs='+', default=['a', 'b', 'c', 'd'], choices=['a', 'b', 'c', 'd'])
    ap.add_argument('--n-jobs', type=int, default=None, help='persistence-test workers (default PAIRS_N_JOBS, '
                                                             'else min(4, CPUs))')
    ap.add_argument('--no-manifest', action='store_true', help='do not list the output in MANIFEST.json beside it')
    args = ap.parse_args(argv)
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise SystemExit('set PYTHONHASHSEED=0, as the published run did (scripts/run_dev_studies.sh)')
    os.chdir(ROOT)                                    # the study's cache paths are repository-relative
    env_jobs = os.environ.get('PAIRS_N_JOBS')
    n_jobs = max(1, args.n_jobs if args.n_jobs is not None else int(env_jobs) if env_jobs
                 else min(4, os.cpu_count() or 1))
    report = build(sorted(set(args.sections)), n_jobs)
    out = pathlib.Path(args.out)
    _atomic_write_json(report, out)
    log.info(f'Wrote {_rel(out)}')
    if not args.no_manifest:
        manifest = record_in_manifest(out)
        if manifest is not None:
            log.info(f'Listed it in {_rel(manifest)}')
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logging.getLogger('pairs_trading').setLevel(logging.WARNING)
    sys.exit(main())
