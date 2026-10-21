#!/usr/bin/env python3
"""Build assets/study.json: the data contract between the committed results and the site.

index.html states the study's numbers in its text (each one a data-metric marker that
scripts/check_published_numbers.py verifies); the charts in assets/exhibits.js draw from
this file. Every number the page derives from the results (the cost waterfall, the gross
edge per trade, the power of the Sharpe test, the rolling Sharpe, ...) is computed here,
once, so the text, the charts and their data tables cannot disagree.

usage:
    python scripts/build_site_data.py              # results/v33_dev -> assets/study.json
    python scripts/build_site_data.py --check      # exit 1 if assets/study.json is stale
    python scripts/build_site_data.py --dev results/v32_dev --out /tmp/study.json   # preview
    python scripts/build_site_data.py --dev outputs/my_run --out /tmp/study.json    # preview

--dev takes any run directory (a published results/<name>/ or a run's own output
directory). The page's text is checked against the headline JSON the file was built
from (meta.headline_sha256), so the committed file must come from the run whose
numbers the page quotes (results/v33_dev, the v33 design on the development calendar);
build other runs to another --out for a preview.

Sources (only the development run is required; a missing source leaves its section out
of the file, or null in a section of fixed shape, and the page shows it as pending):

    {dev}/headline_metrics.json            the run's published numbers (checker's source)
    {dev}/pairs_trading_results_*.json     the full export (not its _compact twin): daily
                                           equity, trades, walk-forward windows,
                                           significance, benchmarks, universe coverage
                                           (universe_by_formation) and, from v33 on, the
                                           evidence block (AR(1) power report, Sharpe
                                           hurdles, gross-of-cost series, eight-factor
                                           attribution, T-bill return)
    {dev}/fund_type_comparison.json        cost-schedule replay of the same trades
    {dev}/cost_sensitivity.json            the declared cost and capacity scenarios, each a
                                           full re-run of the backtest
                                           (scripts/cost_sensitivity.py)
    {dev}/universe_meta.json               the universe file's as-of date and size (v32)
    {dev}/stats_battery.json               power report and DSR curve (scripts/stats_battery.py)
    {dev}/anatomy.json                     evidence layer (scripts/anatomy_of_the_null.py):
                                           the sections in ANATOMY_KEYS pass through, and
                                           anatomy_facts() takes the numbers the text quotes
    {dev}/robustness.json                  robustness checks (scripts/robustness_checks.py):
                                           start dates, regimes, persistence on the strategy's
                                           candidate pairs, S2's clustered per-trade t
    results/v32_dev/                       the published v32 run (history; the frozen arm S3)
    results/variant_family/declaration.json, snooping.json,  the declared variant family and
        runs.json, daily_returns.csv                         its data-snooping tests
    results/residual_dev/residual_statarb.json, MANIFEST.json   Avellaneda-Lee arm, as
                                                             scripts/publish_run.py publishes
                                                             scripts/run_residual_statarb.py's
                                                             export
    results/holdout2026/evaluation.json                      pre-registered 2026 holdout
                                                             (scripts/evaluate_holdout.py)
    results/validation/synthetic_validation.json             known-answer checks
    results/trial_registry.jsonl                             every trial whose result was seen

Every number the page's text quotes from a section that a run may lack sits in a section
of fixed shape (dev.facts, dev.cost_sensitivity): its keys are always present and null
when the source is missing, so a marker names a key that every build has.

Output: deterministic (sorted keys, rounded floats, no wall-clock time), so a rebuild of
unchanged inputs is byte-identical and CI can test that the committed file is current.
meta.generated_utc is the newest input run's timestamp for that reason, and
meta.headline_sha256 ties the file to the headline JSON the checker reads.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import pathlib
import re
import sys

import numpy as np
from scipy import stats as sps

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading import power as pw  # noqa: E402
from pairs_trading.significance import (  # noqa: E402
    _circular_block_indices, block_bootstrap_sharpe_ci, deflated_sharpe_ratio, dsr_curve as _dsr_curve,
    hac_tstat_mean, probabilistic_sharpe_ratio, trial_sharpe_variance,
)
from pairs_trading.universe import normalise_ticker  # noqa: E402

SCHEMA = 1
DEFAULT_DEV = ROOT / 'results' / 'v33_dev'
DEFAULT_OUT = ROOT / 'assets' / 'study.json'
V32_RUN = 'v32_dev'                  # results/v32_dev: the published v32 run, the frozen arm S3
REGISTRY = 'trial_registry.jsonl'    # results/trial_registry.jsonl (scripts/register_trial.py)
# The registered holdout: 2026-01-02 to 2026-10-19 (study_config.CALENDARS['holdout2026']),
# 200 sessions on the NYSE's published 2026 holiday schedule. A design value, not a result:
# the power the holdout has is stated from the development returns before any 2026 price.
HOLDOUT_SESSIONS = 200
HOLM_FIRST_ALPHA = 0.025             # Holm's first step across the two confirmatory arms
HOLDOUT_ALTERNATIVES = (1.0, 2.0, 3.0)
PERIODS = 252
BOOT_SEED, BOOT_RESAMPLES = 42, 5000  # the run's own bootstrap settings (seed, resamples)
PRICE_MANIFEST = 'price_fetch_manifest.json'   # {dev}/: the price cache's fetch manifest, as the run left it
UNIVERSE_DIR = ('reference', 'universe')       # the committed IWV snapshots (iwv_<period>.csv)
HEAVIEST_MEMBERS = 500               # the survivorship gap among the heaviest members of a snapshot
# A member without price history, by the outcome its symbol's last fetch recorded in the price
# manifest (data_processor._download_history): the vendor answered 404, the fetch itself failed
# (an HTTP error or an empty answer on the last attempt), the history failed the data checks
# (too short or invalid), or the symbol was never requested.
GAP_OUTCOMES = (('not_found', 'No longer served by the vendor (HTTP 404)'),
                ('fetch_failed', 'Fetch failed (HTTP error or empty answer)'),
                ('data_checks', 'Failed the data checks (too short or invalid)'),
                ('never_fetched', 'Never fetched'))
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
# The declared scenarios of scripts/cost_sensitivity.py, by a key a marker can name, with
# the label the report gives each one and the anatomy's re-pricing of the SAME trades under
# the same assumption (gross_vs_net.impact_sensitivity / borrow_stress, capacity): group,
# value. 'Y=0.3' is the headline coefficient, so its row repeats the headline and is checked
# against it instead of being shown twice.
COST_SCENARIOS = (('headline', 'headline', ('impact', 0.3)),
                  ('impact_0_6', 'Y=0.6', ('impact', 0.6)), ('impact_1_0', 'Y=1.0', ('impact', 1.0)),
                  ('borrow_1', 'borrow 1%', ('borrow', 0.01)), ('borrow_3', 'borrow 3%', ('borrow', 0.03)),
                  ('capital_10m', '$10M', ('capacity', 10.0)), ('capital_1b', '$1B', ('capacity', 1000.0)),
                  ('capital_5b', '$5B', ('capacity', 5000.0)))
# Ken French daily factors as the evidence block names them, in the order shown.
FACTOR_LABELS = {'Mkt-RF': 'Market', 'SMB': 'Size (SMB)', 'HML': 'Value (HML)', 'RMW': 'Profitability (RMW)',
                 'CMA': 'Investment (CMA)', 'Mom': 'Momentum', 'ST_Rev': 'Short-term reversal',
                 'LT_Rev': 'Long-term reversal'}
# The pre-registered holdout's strategies, as scripts/run_holdout.sh names them for
# scripts/evaluate_holdout.py, with the hypothesis each one tests.
HOLDOUT_ARMS = (('v33_pairs', 'H1', 'v33 pairs (pre-registered design)'),
                ('avellaneda_lee', 'H2', 'Avellaneda–Lee residual reversion'),
                ('v32_pairs', None, 'v32 as published, frozen (descriptive)'))
VARIANT_FAMILY = 'variant_family'    # results/variant_family: the declared family and its tests
# The declared toggles (results/variant_family/declaration.json) by what each one changes.
TOGGLE_LABELS = {'regime_gate_on': 'Regime gate on', 'cusum_gate_on': 'CUSUM entry gate on',
                 'hurst_gate_on': 'Hurst entry gate on', 'no_rolling_corr_floor': 'No 20-day correlation floor',
                 'ref_bars_40': 'z-score window 40 bars', 'ref_bars_90': 'z-score window 90 bars',
                 'ranker_gbm': 'Learned ranker on', 'open_fills': 'Fills at the next open',
                 'all_pairs': 'Pairs across industries', 'universe_300': '300 names, v32\'s size',
                 'reform_every_63': 'Re-formation every 63 days'}
ROBUSTNESS = 'robustness.json'       # {dev}/: scripts/robustness_checks.py


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

    def load_lines(self, path):
        """A JSON-lines file as a list (one object per non-empty line), or None if absent."""
        path = pathlib.Path(path)
        if not path.is_file():
            return None
        self.hashes[self._name(path)] = _sha256(path)
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def load_csv(self, path):
        """A CSV file as a list of dicts (one per row), or None if absent."""
        path = pathlib.Path(path)
        if not path.is_file():
            return None
        self.hashes[self._name(path)] = _sha256(path)
        return list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8'))))


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

    One row per formation (pair selection or re-formation): the index snapshot in force
    and the date it was filed, its members, those with price history, and the index weight
    of the members without prices (mapped to a ticker but not fetched) and of holdings with
    no usable ticker. The two weights together are the study's survivorship gap at that
    date; the three heaviest names of each kind are kept for the data table. Runs on a
    non-point-in-time universe (v32) export no rows and get no section.
    """
    def heaviest(pairs):
        return [[str(name), _r(100 * w, 3)] for name, w in (pairs or [])[:3]]

    rows = []
    for u in res.get('universe_by_formation') or []:
        missing_w = u.get('missing_value_weight')
        unmapped_w = u.get('unmapped_value_weight')
        filed = u.get('snapshot_filed')
        rows.append({
            'formation_date': str(u['formation_date'])[:10], 'snapshot': str(u.get('snapshot'))[:10],
            'snapshot_filed': str(filed)[:10] if filed else None,
            'members': int(u['members']), 'with_prices': int(u['with_prices']), 'missing': int(u['missing']),
            'missing_weight_pct': _r(100 * missing_w, 3) if missing_w is not None else None,
            'unmapped_weight_pct': _r(100 * unmapped_w, 3) if unmapped_w is not None else None,
            'missing_heaviest': heaviest(u.get('missing_heaviest')),
            'unmapped_heaviest': heaviest(u.get('unmapped_heaviest')),
        })
    return rows or None


def _gap_outcome(outcome):
    """The GAP_OUTCOMES class of a symbol's recorded fetch outcome (None: never requested)."""
    if outcome is None:
        return 'never_fetched'
    if outcome == 'not_found':
        return 'not_found'
    if outcome in ('short', 'invalid'):
        return 'data_checks'
    return 'fetch_failed'           # 'empty', 'error:<type>' and anything else the fetch recorded


def survivorship(rows, manifest, snapshots):
    """The survivorship gap at each formation, split by why a member has no price history.

    rows       universe_coverage(): the snapshot in force at each formation and the run's own
               index weight of the members without prices
    manifest   {dev}/price_fetch_manifest.json: cached_symbols and each symbol's fetch outcome
    snapshots  {period: rows of reference/universe/iwv_<period>.csv} (ticker, name, weight)

    A member is mapped (has a ticker) and has no price history when its ticker is not among
    the cached symbols; its index weight is the snapshot's weight summed over its ticker, as
    the run computes it. The split is published only if it reproduces the run's own missing
    weight at every formation (to 0.002 points); otherwise the section is null. For each
    formation it also gives the members without prices among the HEAVIEST_MEMBERS heaviest of
    the snapshot, with their names and fetch outcomes (the run's top-500 screen ranks by dollar
    volume, which a member without prices does not have; index weight stands in for it).
    """
    if not rows or not manifest or not snapshots:
        return None
    cached = {normalise_ticker(s) for s in manifest.get('cached_symbols') or []}
    outcomes = {normalise_ticker(s): o for s, o in (manifest.get('outcomes') or {}).items()}
    out = []
    for row in rows:
        snap = snapshots.get(row['snapshot'])
        if snap is None:
            return None
        weight, name = {}, {}
        for h in snap:
            t = h.get('ticker') or ''
            if t == '':             # a holding without a usable ticker: the unmapped weight
                continue
            weight[t] = weight.get(t, 0.0) + float(h['weight'])
            name.setdefault(t, h.get('name') or t)
        missing = {t: w for t, w in weight.items() if t not in cached}
        split = {k: 0.0 for k, _ in GAP_OUTCOMES}
        count = {k: 0 for k, _ in GAP_OUTCOMES}
        for t, w in missing.items():
            k = _gap_outcome(outcomes.get(t))
            split[k] += 100.0 * w
            count[k] += 1
        total = sum(split.values())
        if row['missing_weight_pct'] is None or abs(total - row['missing_weight_pct']) > 0.002 \
                or len(missing) != row['missing']:
            return None
        heaviest = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))[:HEAVIEST_MEMBERS]
        top_missing = [(t, w) for t, w in heaviest if t not in cached]
        out.append({
            'formation_date': row['formation_date'], 'snapshot': row['snapshot'],
            'missing_weight_pct': _r(total, 4),
            'by_outcome': [{'key': k, 'label': label, 'members': count[k], 'weight_pct': _r(split[k], 4)}
                           for k, label in GAP_OUTCOMES],
            'heaviest_n': len(heaviest),
            'heaviest_missing': len(top_missing),
            'heaviest_missing_weight_pct': _r(100.0 * sum(w for _, w in top_missing), 4),
            'heaviest_missing_names': [[t, name[t], _r(100.0 * w, 3), _gap_outcome(outcomes.get(t))]
                                       for t, w in top_missing],
        })
    return {'heaviest_members': HEAVIEST_MEMBERS, 'outcomes': [label for _, label in GAP_OUTCOMES],
            'formations': out}


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
    """The walk-forward's test windows, their stitched path and the daily series.

    A window's `end` is the date of its last day in the daily series (test_start plus its
    n_days trading days): the export's test_end is the end of the window's 63-day grid slot,
    and the last window runs on to the walk-forward's last day, so its n_days (and end)
    exceed the slot's. Without a daily series `end` is the export's test_end.
    """
    wf = res.get('walk_forward_validation') or {}
    daily = res.get('walk_forward_daily') or []
    day_index = {d['date']: i for i, d in enumerate(daily)}
    windows = []
    for w in wf.get('windows') or []:
        end = w['test_end']
        i0, n = day_index.get(w['test_start']), w.get('n_days')
        if i0 is not None and n and i0 + n - 1 < len(daily):
            end = daily[i0 + n - 1]['date']
        windows.append({
            'n': w['window'], 'train_start': w.get('train_start'), 'train_end': w.get('train_end'),
            'test_start': w['test_start'], 'test_end': w['test_end'], 'end': end, 'n_days': n,
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
        stitched.append({'date': w['end'], 'cum_pct': _r((cum - 1.0) * 100.0, 4)})
    out = {'windows': windows, 'stitched': stitched}
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
    battery_row('oos', 'Walk-forward, net', 'oos_daily')
    if gatev_daily_pct is not None:
        bootstrap_row('gatev', 'Gatev distance method, net', gatev_daily_pct)
    for key, label, src in (('diff_main', 'Main minus Gatev', _get(bench, 'vs_strategy', 'main_backtest')),
                            ('diff_oos', 'Walk-forward minus Gatev', _get(bench, 'vs_strategy', 'walk_forward_oos'))):
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


def _drawdown(r):
    """Maximum drawdown of a daily return series (%), and its length in trading days: from
    the peak to the trough, and from the peak until the peak is regained (None if never)."""
    w = np.cumprod(1.0 + np.asarray(r, dtype=float))
    dd = w / np.maximum.accumulate(w) - 1.0
    trough = int(np.argmin(dd))
    peak = int(np.argmax(w[:trough + 1]))
    back = next((j for j in range(trough, len(w)) if w[j] >= w[peak]), None)
    return 100.0 * float(dd[trough]), trough - peak, (back - peak) if back is not None else None


def _volatility_interval(r, block):
    """Annualised volatility, % a year, with its circular block-bootstrap 95% interval."""
    r = np.asarray(r, dtype=float)
    idx = _circular_block_indices(np.random.default_rng(BOOT_SEED), len(r), int(block), BOOT_RESAMPLES)
    boots = r[idx].std(axis=1, ddof=1) * math.sqrt(PERIODS) * 100
    return [_r(r.std(ddof=1) * math.sqrt(PERIODS) * 100, 6), _r(np.percentile(boots, 2.5), 6),
            _r(np.percentile(boots, 97.5), 6)]


def _mean_interval(mean_daily, t):
    """Annualised mean return, % a year, with the 95% interval of its Newey-West t-statistic."""
    se = abs(mean_daily / t) if t else float('nan')
    return [_r(100 * PERIODS * v, 6) for v in (mean_daily, mean_daily - 1.96 * se, mean_daily + 1.96 * se)]


def performance(res, headline, wf, forest_rows):
    """The standard performance statistics of the main backtest, the walk-forward and the
    Gatev baseline: total and annualised return (Newey-West 95% interval), annualised
    volatility (block-bootstrap 95% interval, the Sharpe ratio's block length), the
    Sharpe ratio, the maximum drawdown and its length, gross exposure and the return on it,
    trades, hit rate, holding period and turnover. Null when a series is missing.

    The main backtest's trade figures are the headline JSON's (the text quotes those).
    """
    perf, sig = res.get('overall_performance') or {}, res.get('significance') or {}
    gatev = _get(res, 'benchmarks', 'distance_method') or {}
    curve = res.get('daily_equity_curve') or []
    if not curve or not gatev.get('daily_returns') or not sig.get('main_backtest') or not sig.get('oos_daily'):
        return None
    main_r = np.array([d['daily_return_pct'] for d in curve]) / 100.0
    gatev_r = np.asarray(gatev['daily_returns'], dtype=float)
    wf_r = np.asarray((wf.get('daily') or {}).get('net') or [], dtype=float) / 100.0
    if not len(wf_r):
        return None
    blocks = {r['key']: re.search(r'block (\d+) days', r['method']) for r in forest_rows}
    out = {}
    for key, r, s in (('main', main_r, sig['main_backtest']), ('gatev', gatev_r, None), ('wf', wf_r, sig['oos_daily'])):
        h = s['hac'] if s else hac_tstat_mean(r)
        block = blocks.get('oos' if key == 'wf' else key)
        if block is None:
            return None
        dd, to_trough, to_back = _drawdown(r)
        out[key] = {'days': len(r), 'total': _r(100.0 * (float(np.prod(1.0 + r)) - 1.0), 6),
                    'ret': _mean_interval(h['mean'], h['tstat']), 'vol': _volatility_interval(r, int(block.group(1))),
                    'max_dd': _r(dd, 6), 'dd_days': [to_trough, to_back]}
    hm, wfv = headline.get('main') or {}, res.get('walk_forward_validation') or {}
    gross = perf.get('avg_gross_exposure_pct_of_equity')
    out['main'].update(trades=hm.get('trades'), hit=hm.get('win_rate_pct'), hold=perf.get('avg_trading_days_held'),
                       turnover=hm.get('annual_turnover_x'), gross=hm.get('avg_gross_exposure_pct'),
                       ret_gross=_r(out['main']['ret'][0] / (gross / 100.0), 6) if gross else None)
    out['wf'].update(days=_get(sig, 'oos_daily', 'n_days', default=out['wf']['days']), trades=wfv.get('total_trades'),
                     hit=wfv.get('win_rate_pct'), hold=None, turnover=None, gross=None, ret_gross=None)
    out['gatev'].update(trades=gatev.get('n_trades'), hit=None, hold=gatev.get('avg_holding_days'), turnover=None,
                        gross=None, ret_gross=None)
    hs = headline.get('significance') or {}
    gr = next((r for r in forest_rows if r['key'] == 'gatev'), {})
    out['main']['sharpe'] = [_get(hs, 'main', k) for k in ('ann_sharpe', 'boot_lo', 'boot_hi')]
    out['wf']['sharpe'] = [_get(hs, 'oos_daily', k) for k in ('ann_sharpe', 'boot_lo', 'boot_hi')]
    out['gatev']['sharpe'] = [_get(headline, 'benchmarks', 'gatev', 'sharpe'), gr.get('lo'), gr.get('hi')]
    return out


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
    series = (('main_backtest', 'main', 'Main backtest'), ('walk_forward_oos', 'walk_forward_oos', 'Walk-forward'))
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
            # gross P&L of the replay: its net P&L plus its costs, over its starting capital
            'gross_pct': _r(100.0 * (p['replayed_net_pnl'] + p['total_cost_dollars'])
                            / float(_get(funds, 'metadata', 'initial_capital_usd', p['profile_key'], default=1e8)), 4)
            if p.get('replayed_net_pnl') is not None and p.get('total_cost_dollars') is not None else None,
            **({'dates': dates} if dates != calendar else {}),
            'cum': _rl(((c['value'] / v0 - 1) * 100 for c in curve), 4) if v0 else [],
        })
    return out


def funnel(res, universe):
    fdr = res.get('fdr_diagnostic') or {}
    traded = len({t['pair'] for t in res.get('all_trades') or []})
    names = [{'stage': 'Names in the universe file', 'n': _get(universe, 'selected')},
             {'stage': 'Names with price history', 'n': _get(res, 'run_config', 'data', 'n_symbols')}]
    # The first three stages are the first formation's; the pairs traded come from every
    # formation that governed trading, so that bar is not a share of the stage above it
    # ('separate').
    pairs = [{'stage': 'Pairs tested (Engle–Granger)', 'n': fdr.get('pairs_tested')},
             {'stage': 'Cointegrated at raw p < 0.05', 'n': fdr.get('significant_raw_p05'),
              'expected': _r(fdr.get('expected_false_positives_at_p05'), 1)},
             {'stage': 'Selected (half-life, quality)', 'n': fdr.get('final_selected_pairs')},
             {'stage': 'Distinct pairs traded, all formations', 'n': traded, 'separate': True}]
    return {'names': [s for s in names if s['n'] is not None], 'pairs': [s for s in pairs if s['n'] is not None],
            'bh_q05': fdr.get('survive_bh_fdr_q05'), 'bh_q10': fdr.get('survive_bh_fdr_q10'),
            'pvalue_hist': fdr.get('pvalue_histogram')}


def cost_scenarios(report, res, anatomy):
    """The declared cost and capacity scenarios, each two ways (fixed shape: see COST_SCENARIOS).

    full    scripts/cost_sensitivity.py: the whole backtest re-run under the scenario.
            Costs enter the equity path, every position is sized as a share of current
            equity (scaled further by the last closed trades' outcomes and the drawdown),
            and an entry is admitted only while gross exposure stays under the 30% cap, so
            a different cost or capital changes which signals are filled: the trade count
            differs between scenarios.
    fixed   the anatomy's re-pricing of the headline run's own trades under the same
            assumption (impact re-priced per execution, borrow re-charged, a book of a
            different size re-priced at its participation): the trades are held fixed.
    Every key is present; values are null when a source is missing. A report that is not
    of this run (its headline row differs from the run's own result) stops the build.
    """
    by_label = {s['label']: s for s in (report or {}).get('scenarios') or []}
    run_effective = _get(res, 'run_config', 'effective') or {}
    if report is not None:
        perf = res.get('overall_performance') or {}
        head = by_label.get('headline') or {}
        same = (head.get('trades') == perf.get('total_trades')
                and head.get('total_return_pct') is not None and perf.get('total_return_pct') is not None
                and abs(head['total_return_pct'] - perf['total_return_pct']) < 5e-4
                and report.get('profile') == run_effective.get('profile')
                and report.get('calendar') == run_effective.get('calendar'))
        if not same:
            raise ValueError('cost_sensitivity.json is not a scenario report of this run (its headline row '
                             f'{head.get("trades")} trades, {head.get("total_return_pct")}%; the run '
                             f'{perf.get("total_trades")} trades, {perf.get("total_return_pct")}%)')
        y03 = by_label.get('Y=0.3')
        if y03 is not None and (y03.get('trades'), y03.get('total_return_pct')) != (head['trades'], head['total_return_pct']):
            raise ValueError('cost_sensitivity.json: the Y=0.3 scenario differs from the headline, which uses Y=0.3')
    gvn = (anatomy or {}).get('gross_vs_net') or {}
    fixed_rows = {
        'impact': {round(float(s['coefficient']), 4): s for s in _get(gvn, 'impact_sensitivity', 'scenarios', default=[])},
        'borrow': {round(float(s['rate']), 4): s for s in _get(gvn, 'borrow_stress', 'scenarios', default=[])},
        'capacity': {round(float(s['aum_musd']), 4): s for s in (anatomy or {}).get('capacity') or []},
    }
    rows = {}
    for key, label, (group, value) in COST_SCENARIOS:
        s = by_label.get(label) or {}
        f = fixed_rows[group].get(round(value, 4)) or {}
        if key == 'headline' and not f:        # the headline itself, unchanged trades
            f = {'sharpe': _get(res, 'overall_performance', 'sharpe_ratio'),
                 'total_return_pct': _get(res, 'overall_performance', 'total_return_pct')}
        cap = s.get('initial_capital')
        rows[key] = {
            'label': label, 'group': group if key != 'headline' else 'headline',
            'capital_musd': _r(cap / 1e6, 0) if cap else None,
            'full': {'ret_pct': _r(s.get('total_return_pct'), 4), 'sharpe': _r(s.get('sharpe'), 4),
                     'trades': s.get('trades'), 'max_dd_pct': _r(s.get('max_drawdown_pct'), 4),
                     'cost_pct': _r(s.get('total_cost_pct_of_capital'), 4),
                     'adv_pct': _r(s.get('avg_max_leg_adv_participation_pct'), 3),
                     'cost_bp': _r(s.get('mean_cost_bp_of_gross_notional'), 2)},
            'fixed': {'ret_pct': _r(f.get('total_return_pct'), 4), 'sharpe': _r(f.get('sharpe'), 4),
                      'net_bp': _r(f.get('net_bp_per_trade', f.get('net_bp')), 2)},
        }
    trades = [r['full']['trades'] for r in rows.values() if r['full']['trades'] is not None]
    return {'available': report is not None, 'order': [k for k, _, _ in COST_SCENARIOS], 'scenarios': rows,
            'trades_min': min(trades) if trades else None, 'trades_max': max(trades) if trades else None}


def half_lives(anatomy):
    """Half-life of each traded pair's spread on its formation window and out of sample
    (anatomy.persistence_detail.traded_pairs.per_pair), in trading days; null if absent."""
    per = _get(anatomy or {}, 'persistence_detail', 'traded_pairs', 'per_pair')
    if not per:
        return None
    rows = [{'pair': p['pair'], 'trades': p.get('trades'), 'f': _r(p.get('formation_half_life'), 2),
             'o': _r(p.get('oos_half_life'), 2), 'p_f': _r(p.get('formation_p'), 4), 'p_o': _r(p.get('oos_p'), 4)}
            for p in per]
    return {'max_half_life': _get(anatomy, 'persistence_detail', 'traded_pairs', 'max_half_life'),
            'pairs': sorted(rows, key=lambda r: r['pair'])}


# ──────────────────────────────────────────────────────────────────────────────
# Facts: the scalars the page quotes in its text (always present; null if unknown)
# ──────────────────────────────────────────────────────────────────────────────

def evidence_facts(res):
    """Numbers of the export's evidence block (v33 exports; null for earlier ones): the
    walk-forward series' power, the Sharpe hurdles for 32 trials, the gross-of-cost daily
    series, the eight-factor attribution and the 1-month T-bill return over the period."""
    ev = res.get('evidence') or {}
    oos, hurdles = ev.get('walk_forward_oos') or {}, _get(ev, 'hurdles', 'hurdles') or {}
    fac = ev.get('factors') or {}
    gross, cash = ev.get('gross_daily') or {}, fac.get('cash') or ev.get('cash') or {}

    def loading(series, name, field):
        return _get(fac, series, 'factors', name, field)

    def alpha_pct(series):
        a = _get(fac, series, 'alpha_ann')
        return _r(100 * a, 2) if a is not None else None
    return {
        'oos_sharpe_se': _r(oos.get('se_ann')), 'oos_mde': _r(oos.get('min_detectable_sr_ann')),
        'oos_ucb': _r(oos.get('upper_bound_ann')), 'oos_critical': _r(oos.get('critical_sr_ann')),
        'hurdle_tests': _get(ev, 'hurdles', 'n_tests'),
        'hurdle_single': _r(_get(hurdles, 'single_test', 'sr_ann')),
        'hurdle_bonferroni': _r(_get(hurdles, 'bonferroni_one_sided', 'sr_ann')),
        'hurdle_hlz': _r(_get(hurdles, 'hlz', 'sr_ann')), 'hurdle_hlz_t': _r(_get(hurdles, 'hlz', 't'), 2),
        'hurdle_cgs': _r(_get(hurdles, 'cgs', 'sr_ann')), 'hurdle_cgs_t': _r(_get(hurdles, 'cgs', 't'), 2),
        'gross_sharpe': _r(gross.get('sharpe')), 'gross_hac_t': _r(gross.get('hac_t'), 3),
        'gross_hac_p': _r(gross.get('hac_p'), 3), 'gross_ret_pct': _r(gross.get('total_return_pct'), 3),
        'tbill_rf_pct': _r(cash.get('tbill_return_pct'), 2),
        'ff_alpha_main_pct': alpha_pct('main'), 'ff_alpha_main_t': _r(_get(fac, 'main', 'alpha_tstat'), 2),
        'ff_r2_main': _r(_get(fac, 'main', 'r2'), 3),
        'ff_alpha_oos_pct': alpha_pct('walk_forward_oos'), 'ff_alpha_oos_t': _r(_get(fac, 'walk_forward_oos', 'alpha_tstat'), 2),
        'ff_r2_oos': _r(_get(fac, 'walk_forward_oos', 'r2'), 3),
        'st_rev_beta_main': _r(loading('main', 'ST_Rev', 'beta'), 4), 'st_rev_t_main': _r(loading('main', 'ST_Rev', 'tstat'), 2),
        'st_rev_t_oos': _r(loading('walk_forward_oos', 'ST_Rev', 'tstat'), 2),
        'mom_t_main': _r(loading('main', 'Mom', 'tstat'), 2), 'mom_t_oos': _r(loading('walk_forward_oos', 'Mom', 'tstat'), 2),
        'mkt_beta_main': _r(loading('main', 'Mkt-RF', 'beta'), 4), 'mkt_t_main': _r(loading('main', 'Mkt-RF', 'tstat'), 2),
        'mkt_t_oos': _r(loading('walk_forward_oos', 'Mkt-RF', 'tstat'), 2),
        'factor_data_end': _get(fac, 'source', 'last_date_used'),
    }


def anatomy_facts(anatomy):
    """Numbers of the evidence layer's anatomy.json the text quotes (null if absent).

    Money in $ thousands or millions (signed: an *_usd_* key keeps the sign of its P&L
    contribution), shares in %, bp of gross notional per trade unless a key says otherwise.
    """
    a = anatomy or {}
    sfd = _get(a, 'shortfall_detail', 'totals') or {}
    er, nulls = a.get('exit_race') or {}, _get(a, 'exit_race', 'nulls') or {}
    decay = {row['period'].split(' ')[0].lower(): row for row in a.get('decay') or []}
    pooled = _get(a, 'persistence_detail', 'clegg', 'pooled_still_cointegrated') or {}
    traded = _get(a, 'persistence_detail', 'traded_pairs') or {}
    cap = {round(float(r['aum_musd'])): r for r in a.get('capacity') or []}
    cash, conc = a.get('cash') or {}, _get(a, 'concentration', 'pairs') or {}
    exp = a.get('exposure') or {}
    side = {g['group']: g for g in _get(a, 'breakdowns', 'by_side', default=[])}
    years = {str(y['year']): y for y in _get(a, 'breakdowns', 'years', default=[])}
    gvn = a.get('gross_vs_net') or {}
    wf0 = next((r for r in gvn.get('walk_forward_cost_curve') or [] if r.get('k') == 0), {})

    def usd_k(x):           # a P&L contribution (a cost is negative)
        return _r(x / 1e3, 1) if x is not None else None

    def pct(x, dp=1):
        return _r(100 * x, dp) if x is not None else None
    of = pooled.get('of')
    expected = pooled.get('expected_at_next_year_base_rates')
    return {
        # implementation shortfall: paper P&L at the signal closes, the one-day delays, gross
        'sf_paper_usd_k': usd_k(_get(sfd, 'paper', 'usd')),
        'sf_entry_delay_usd_k': usd_k(-_get(sfd, 'entry_delay', 'usd')) if _get(sfd, 'entry_delay', 'usd') is not None else None,
        'sf_exit_delay_usd_k': usd_k(-_get(sfd, 'exit_delay', 'usd')) if _get(sfd, 'exit_delay', 'usd') is not None else None,
        'sf_entry_delay_gain_usd_k': usd_k(-_get(sfd, 'entry_delay', 'usd')) if _get(sfd, 'entry_delay', 'usd') is not None else None,
        'sf_exit_delay_loss_usd_k': usd_k(_get(sfd, 'exit_delay', 'usd')),
        'sf_paper_bp': _r(_get(sfd, 'paper', 'bp_of_notional'), 2), 'sf_gross_bp': _r(_get(sfd, 'gross', 'bp_of_notional'), 2),
        'sharpe_break_even_x': _r(gvn.get('sharpe_breakeven_multiple'), 3),
        'wf_gross_sharpe': _r(wf0.get('sharpe'), 2), 'wf_gross_hac_p': _r(wf0.get('hac_p'), 3),
        # exit race: targets among barrier exits against three nulls
        'er_targets': er.get('targets'), 'er_stops': er.get('stops'), 'er_barrier': er.get('barrier_exits'),
        'er_other': er.get('other_exits'), 'er_share_pct': pct(er.get('observed_share')),
        'er_rw_expected': _r(_get(nulls, 'random_walk', 'expected_targets'), 1),
        'er_rw_share_pct': pct(_get(nulls, 'random_walk', 'expected_share')),
        'er_rw_z': _r(_get(nulls, 'random_walk', 'z'), 2), 'er_rw_p': _r(_get(nulls, 'random_walk', 'p_two_sided'), 3),
        'er_ou_expected': _r(_get(nulls, 'ou', 'expected_targets'), 1),
        'er_ou_share_pct': pct(_get(nulls, 'ou', 'expected_share')), 'er_ou_z': _r(_get(nulls, 'ou', 'z'), 2),
        'er_gr_expected': _r(_get(nulls, 'gamblers_ruin', 'expected_targets'), 1),
        'er_half_life': _r(_get(er, 'inputs', 'median_formation_half_life'), 1),
        # in-sample to out-of-sample decay of the same rule on the same pairs
        **{f'decay_{k}_{f}': _r(_get(decay, name, src), dp) for k, name in (('form', 'formation'), ('oos', 'out'),
                                                                            ('engine', 'engine'))
           for f, src, dp in (('bp', 'bp', 2), ('t', 't', 2), ('tc', 't_month_clustered', 2),
                              ('lo', 'lo', 4), ('hi', 'hi', 4))},
        **{f'decay_{k}_n': _get(decay, name, 'n') for k, name in (('form', 'formation'), ('oos', 'out'), ('engine', 'engine'))},
        'decay_pairs': _get(a, 'decay_detail', 'pairs'),
        # cointegration persistence (Clegg 2014) and the traded pairs' half-lives
        'pers_symbols': _get(a, 'persistence_detail', 'clegg', 'symbols'),
        'pers_count': pooled.get('count'), 'pers_of': of, 'pers_pct': pct(pooled.get('share'), 2),
        'pers_lo_pct': pct((pooled.get('ci95') or [None])[0], 2), 'pers_hi_pct': pct((pooled.get('ci95') or [None, None])[1], 2),
        'pers_expected': _r(expected, 1), 'pers_expected_pct': _r(100 * expected / of, 2) if expected and of else None,
        'pers_z': _r(pooled.get('z_vs_next_year_base_rates'), 2), 'pers_p_chance': _r(pooled.get('binom_p_vs_chance'), 3),
        'pers_traded_count': _get(traded, 'oos', 'cointegrated', 'count'),
        'pers_traded_of': _get(traded, 'oos', 'cointegrated', 'of'),
        'pers_traded_pct': pct(_get(traded, 'oos', 'cointegrated', 'share')),
        'hl_formation': _r(_get(traded, 'formation', 'median_half_life'), 1),
        'hl_oos': _r(_get(traded, 'oos', 'median_half_life'), 1),
        'hl_oos_above_max_pct': pct(_get(traded, 'oos', 'share_half_life_above_max')),
        'hl_max': traded.get('max_half_life'),
        # capacity: the same trades re-priced at other book sizes
        **{f'cap_{n}_net_bp': _r(_get(cap, aum, 'net_bp'), 1) for n, aum in (('10m', 10), ('100m', 100), ('1b', 1000), ('5b', 5000))},
        **{f'cap_{n}_impact_bp': _r(_get(cap, aum, 'impact_bp'), 1) for n, aum in (('10m', 10), ('100m', 100), ('1b', 1000), ('5b', 5000))},
        # cash: FRED 3-month T-bill over the backtest's own dates
        'cash_tbill_pct': _r(cash.get('tbill_return_pct'), 2), 'cash_tbill_yield_pct': _r(cash.get('tbill_mean_yield_pct'), 2),
        'cash_plus_pct': _r(cash.get('strategy_plus_cash_return_pct'), 2),
        'cash_excess_sharpe': _r(cash.get('sharpe_if_cash_were_subtracted'), 2),
        # concentration and exposure
        'conc_top5_usd_m': _r(conc['net_usd_top5'] / 1e6, 2) if conc.get('net_usd_top5') is not None else None,
        'conc_bottom5_usd_m': _r(conc['net_usd_bottom5'] / 1e6, 2) if conc.get('net_usd_bottom5') is not None else None,
        'conc_rest_usd_m': _r(conc['net_usd_excluding_top5_and_bottom5'] / 1e6, 2)
        if conc.get('net_usd_excluding_top5_and_bottom5') is not None else None,
        'hedge_mean': _r(_get(exp, 'hedge_ratio', 'mean'), 2), 'hedge_below_1_pct': pct(_get(exp, 'hedge_ratio', 'share_below_1')),
        'beta_long_per_gross': _r(_get(exp, 'net_market_beta_per_gross', 'by_side', 'LONG'), 2),
        'beta_short_per_gross': _r(_get(exp, 'net_market_beta_per_gross', 'by_side', 'SHORT'), 2),
        'market_usd_k': usd_k(_get(exp, 'market_component', 'market_usd')),
        'gross_ex_market_bp': _r(_get(exp, 'market_component', 'gross_ex_market_bp', 'mean'), 1),
        'gross_ex_market_t': _r(_get(exp, 'market_component', 'gross_ex_market_bp', 't'), 2),
        'long_gross_bp': _r(_get(side, 'LONG', 'gross_bp'), 1), 'long_gross_t': _r(_get(side, 'LONG', 'gross_t'), 2),
        'short_gross_bp': _r(_get(side, 'SHORT', 'gross_bp'), 1), 'short_gross_t': _r(_get(side, 'SHORT', 'gross_t'), 2),
        **{f'sharpe_{y}': _r(_get(years, y, 'sharpe'), 2) for y in ('2023', '2024', '2025')},
    }


def holdout_power_facts(res):
    """What the registered holdout can detect, stated from the development returns' shape
    (skew, non-excess kurtosis, lag-1 autocorrelation of the evidence block's power report)
    and from i.i.d. normal returns: the minimum detectable annual Sharpe at 80% power over
    HOLDOUT_SESSIONS days, one-sided at Holm's first step (2.5%) and at 5%, and the power at
    Holm's first step against true Sharpe ratios of 1, 2 and 3 (pairs_trading.power)."""
    m = _get(res, 'evidence', 'main') or {}
    out = {'ho_days': HOLDOUT_SESSIONS}
    keys = ('ho_mde_025', 'ho_mde_05', 'ho_mde_025_normal', 'ho_mde_05_normal') + \
        tuple(f'ho_power_{int(x)}' for x in HOLDOUT_ALTERNATIVES) + tuple(f'ho_power_{int(x)}_normal' for x in HOLDOUT_ALTERNATIVES)
    if not all(m.get(k) is not None for k in ('skew', 'kurtosis', 'rho')):
        return {**out, **{k: None for k in keys}}
    ann, n = math.sqrt(PERIODS), HOLDOUT_SESSIONS
    shape = (m['skew'], m['kurtosis'], m['rho'])
    normal = (0.0, 3.0, 0.0)
    for tag, sh in (('', shape), ('_normal', normal)):
        out[f'ho_mde_025{tag}'] = _r(pw.minimum_detectable_sharpe(0.0, n, *sh, alpha=HOLM_FIRST_ALPHA) * ann, 2)
        out[f'ho_mde_05{tag}'] = _r(pw.minimum_detectable_sharpe(0.0, n, *sh, alpha=0.05) * ann, 2)
        for x in HOLDOUT_ALTERNATIVES:
            out[f'ho_power_{int(x)}{tag}'] = _r(100 * pw.sharpe_ratio_power(0.0, x / ann, n, *sh, alpha=HOLM_FIRST_ALPHA), 0)
    return out


def path_facts(res):
    """The main backtest and the walk-forward over the days they share. Without a model to
    refit (v33) the walk-forward is the same rule on the same pair windows started earlier,
    so any difference over the common days is path dependence: which signals the book can
    take depends on what it already holds."""
    main = {d['date']: d['daily_return_pct'] for d in res.get('daily_equity_curve') or []}
    wf = {d['date']: d['daily_return_pct'] for d in res.get('walk_forward_daily') or []}
    common = sorted(set(main) & set(wf))
    if len(common) < 3:
        return {'common_days': None, 'common_corr': None, 'common_sharpe_main': None, 'common_sharpe_oos': None}
    a = np.array([main[d] for d in common]) / 100.0
    b = np.array([wf[d] for d in common]) / 100.0
    corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None
    return {'common_days': len(common), 'common_corr': _r(corr, 2),
            'common_sharpe_main': _r(_sharpe(a), 2), 'common_sharpe_oos': _r(_sharpe(b), 2)}


def run_facts(res, universe_rows, gap_split=None):
    """Data facts of the run: what the price fetch covered, price-level anchoring to N-PORT,
    the survivorship gap at the first and last formation (split by fetch outcome when the
    run's price manifest is published), the formations that governed trading, and the
    signals the 30% gross cap and the cool-off turned away."""
    data = _get(res, 'run_config', 'data') or {}
    anchor = data.get('price_anchor') or {}
    largest = [r for _, r in anchor.get('largest') or []]
    rej = _get(res, 'overall_performance', 'signal_rejections') or {}
    rows = universe_rows or []
    cached, not_found = data.get('universe_cached_fraction'), data.get('universe_not_found_fraction')
    # a formation governs trading unless the next one replaced it before the first trading day
    # (the initial selection at the cutoff, superseded at the first session after it)
    days = [d['date'] for d in (res.get('walk_forward_daily') or []) + (res.get('daily_equity_curve') or [])]
    dates = sorted({r['formation_date'] for r in rows})
    first_day = min(days) if days else None
    traded = [d for i, d in enumerate(dates) if first_day is None or i + 1 == len(dates) or dates[i + 1] > first_day]
    split = {}
    for tag, row in (('first', (gap_split or {}).get('formations', [None])[0]),
                     ('last', ((gap_split or {}).get('formations') or [None])[-1])):
        by = {o['key']: o for o in (row or {}).get('by_outcome') or []}
        for key, _ in GAP_OUTCOMES:
            split[f'gap_{tag}_{key}_pct'] = _get(by, key, 'weight_pct')
            split[f'gap_{tag}_{key}_n'] = _get(by, key, 'members')
        heavy = [h for h in (row or {}).get('heaviest_missing_names') or []]
        split[f'gap_{tag}_heavy_missing'] = (row or {}).get('heaviest_missing')
        split[f'gap_{tag}_heavy_missing_pct'] = (row or {}).get('heaviest_missing_weight_pct')
        split[f'gap_{tag}_heavy_not_found'] = sum(1 for h in heavy if h[3] == 'not_found') if row else None
        split[f'gap_{tag}_heavy_fetch_failed'] = sum(1 for h in heavy if h[3] == 'fetch_failed') if row else None

    def gap(row):
        if row is None or row['missing_weight_pct'] is None:
            return None
        return _r(row['missing_weight_pct'] + (row['unmapped_weight_pct'] or 0.0), 2)
    first, last = (rows[0], rows[-1]) if rows else (None, None)
    return {
        'anchor_symbols': anchor.get('anchored'), 'anchor_moved': anchor.get('median_ratio_beyond_10pct'),
        'anchor_moved_pct': _r(100 * anchor['median_ratio_beyond_10pct'] / anchor['anchored'], 1)
        if anchor.get('anchored') else None,
        'anchor_max_ratio': _r(max(largest), 1) if largest else None,
        'anchor_min_ratio_inv': _r(1 / min(largest), 0) if largest else None,
        'gap_first_pct': gap(first), 'gap_last_pct': gap(last),
        'gap_first_missing': first['missing'] if first else None, 'gap_first_members': first['members'] if first else None,
        'gap_last_missing': last['missing'] if last else None, 'gap_last_members': last['members'] if last else None,
        'formations': len({r['formation_date'] for r in rows}) or None,
        'formations_traded': len(traded) or None,
        'gap_heavy_members': HEAVIEST_MEMBERS,
        # the price fetch: requested symbols with price history, those the vendor answered 404,
        # and the rest (fetch errors, failed data checks, never fetched); 'coverage_pct' is the
        # fetch-coverage rule's share, which counts 404s and failed data checks as resolved
        'cached_pct': _r(100 * cached, 1) if cached is not None else None,
        'not_found_pct': _r(100 * not_found, 1) if not_found is not None else None,
        'fetch_other_pct': _r(100 * (1 - cached - not_found), 1) if cached is not None and not_found is not None else None,
        **split,
        'rej_cap_signal': rej.get('risk: would'), 'rej_cap_fill': rej.get('gross_exposure_cap'),
        'rej_cooloff': rej.get('cooloff'), 'signals_evaluated': rej.get('evaluated'),
    }

def facts(res, dev, anatomy=None):
    """Scalars quoted in the page's text, from the export `res`, the assembled section `dev`
    and the run's anatomy.json (evidence_facts, anatomy_facts, holdout_power_facts,
    path_facts, run_facts and robustness_facts add theirs; every key is present, null when
    unknown).

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
    pos = [t['position_pct_of_equity'] for t in trades if t.get('position_pct_of_equity') is not None]
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
    beta_oos = market.get('Walk-forward') or {}
    k = lambda usd: _r(usd / 1e3, 1) if usd is not None else None    # noqa: E731  ($ thousands)
    m = lambda usd: _r(usd / 1e6, 2) if usd is not None else None    # noqa: E731  ($ millions)
    forest_rows = {row['key']: row for row in dev['forest']}
    rolled = [(sr, lo, hi) for sr, lo, hi in zip(roll['sharpe'], roll['lo'], roll['hi']) if sr is not None]
    return {
        'capital_musd': _r(capital / 1e6, 0),
        'days': len(daily['dates']), 'flat_days': flat, 'flat_pct': _r(100 * flat / len(daily['dates']), 1),
        'exposure_max_pct': _r(max(daily['exposure']), 2), 'positions_max': max(daily['positions']),
        # marked-to-market gross above the 30% cap, which applies to exposure at entry
        'exposure_days_above_cap': sum(1 for x in daily['exposure'] if x > 30.0),
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
        'gross_usd_m': m(step.get('gross')), 'cost_usd_m': m(costs), 'net_usd_m': m(step.get('net')),
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
        # position size, % of equity at entry: 3-10% before the risk manager's scaling
        'position_min_pct': _r(min(pos), 2) if pos else None, 'position_max_pct': _r(max(pos), 2) if pos else None,
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
        # the last walk-forward window runs on to the walk-forward's last day
        'wf_last_window_days': wf['windows'][-1]['n_days'] if wf['windows'] else None,
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
        'avg_exposure_pct': _r(perf.get('avg_gross_exposure_pct_of_equity'), 1),
        # the fixed-trade cost curve at zero and at twice the modelled costs
        **{f'cost_{tag}x_sharpe': next((row['sharpe'] for row in dev.get('cost_curve') or [] if row['k'] == k_), None)
           for tag, k_ in (('0', 0.0), ('2', 2.0))},
        # the random-pair draws' cumulative-return quantiles on the last day (committed-capital basis)
        **{f'random_{q}_end': (dev['random_band'] or {}).get(q, [None])[-1] if dev.get('random_band') else None
           for q in ('p05', 'p25', 'p50', 'p75', 'p95')},
        # the cost-schedule replay of the same trades: how many each schedule replays (its own
        # daily entry limit), and the sign of its gross P&L (net plus costs)
        **schedule_facts(dev.get('cost_schedules')),
        **evidence_facts(res),
        **anatomy_facts(anatomy),
        **holdout_power_facts(res),
        **{f'wf_{k}': v for k, v in path_facts(res).items()},
        **run_facts(res, dev.get('universe_by_formation'), dev.get('survivorship')),
        **robustness_facts(dev.get('robustness')),
    }


def robustness_facts(rob):
    """The robustness checks' numbers the text quotes (robustness(); null when the run has no
    robustness.json): the 12 start dates (Sharpe range, median, the headline's rank, the
    common days), the two halves as separate runs and inside the continuous run, the VIX and
    dispersion terciles (low and high tercile mean, high minus low), persistence on S1's own
    candidate pairs (first formation and the union of formations) and the second family's
    per-trade t clustered by entry month, entry date and symbol."""
    r = rob or {}
    sd, reg = r.get('start_dates') or {}, r.get('regimes') or {}
    halves = {h['half']: h for h in r.get('halves') or []}
    pers = r.get('persistence') or {}
    s2 = r.get('s2') or {}

    def spread(key, field):
        return _get(sd, key, field)

    def tercile(block, which):
        rows = {x['bucket']: x for x in _get(reg, block, 'net', 'rows', default=[])}
        return _get(rows, which, 'mean_bp')

    def pooled(which, field):
        return _get(pers, which, 'pooled', field)
    out = {
        'start_n': sd.get('n'), 'start_step_days': sd.get('step_days'), 'start_headline_rank': sd.get('headline_rank'),
        'start_common_days': _get(sd, 'common', 'days'),
        **{f'start_sharpe_{f}': spread('sharpe', f) for f in ('min', 'max', 'median', 'mean', 'sd', 'range')},
        **{f'start_common_sharpe_{f}': spread('sharpe_common', f) for f in ('min', 'max', 'median', 'sd')},
        **{f'start_ret_{f}': spread('ret', f) for f in ('min', 'max', 'median')},
        'start_trades_min': spread('trades', 'min'), 'start_trades_max': spread('trades', 'max'),
        **{f'half{i}_{f}': _get(halves, name, src) for i, name in ((1, 'first'), (2, 'second'))
           for f, src in (('sharpe', 'sharpe'), ('ret_pct', 'ret_pct'), ('trades', 'trades'), ('run_off_days', 'run_off_days'),
                          ('inside_sharpe', 'inside_sharpe'), ('inside_ret_pct', 'inside_ret_pct'), ('days', 'days'))},
        **{f'{tag}_{w}_bp': tercile(block, w) for tag, block in (('vix', 'vix'), ('disp', 'dispersion'))
           for w in ('low', 'mid', 'high')},
        **{f'{tag}_diff_{f}': _get(reg, block, 'net', 'diff', f) for tag, block in (('vix', 'vix'), ('disp', 'dispersion'))
           for f in ('mean_bp', 't', 'p')},
        'vix_break_lo': _r((_get(reg, 'vix', 'breakpoints') or [None])[0], 2),
        'vix_break_hi': _r((_get(reg, 'vix', 'breakpoints') or [None, None])[1], 2),
        'pers_s1_formations': pers.get('formations'),
        **{f'pers_{tag}_{f}': pooled(which, f) for tag, which in (('s1', 'first'), ('s1u', 'union'))
           for f in ('count', 'of', 'pct', 'lo_pct', 'hi_pct', 'expected', 'expected_pct', 'z')},
        'pers_s1_symbols': _get(pers, 'first', 'symbols'), 'pers_s1_pairs': _get(pers, 'first', 'pairs'),
        'pers_s1u_symbols': _get(pers, 'union', 'symbols'), 'pers_s1u_pairs': _get(pers, 'union', 'pairs'),
        's2c_trades': s2.get('trades'),
        **{f's2c_{series}_{f}': _get(s2, series, f) for series in ('gross', 'net') for f in ('mean_bp', 'se_bp', 't')},
        **{f's2c_{series}_{tag}_{f}': _get(s2, series, by, f) for series in ('gross', 'net')
           for tag, by in (('month', 'entry_month'), ('date', 'entry_date'), ('symbol', 'symbol'))
           for f in ('clusters', 'se_bp', 't', 'p', 'design_effect')},
    }
    return out


def schedule_facts(schedules):
    """The cost-schedule replay (schedules A-E): the number of schedules, the range of trades
    replayed, how many end with a negative gross P&L, and the range of that gross P&L."""
    s = schedules or []
    gross = [x['gross_pct'] for x in s if x.get('gross_pct') is not None]
    trades = [x['trades'] for x in s if x.get('trades') is not None]
    return {'sched_n': len(s) or None,
            'sched_trades_min': min(trades) if trades else None, 'sched_trades_max': max(trades) if trades else None,
            'sched_gross_negative': sum(1 for g in gross if g < 0) if gross else None,
            'sched_gross_min_pct': min(gross) if gross else None, 'sched_gross_max_pct': max(gross) if gross else None}


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


def residual_summary(doc, dates=None):
    """The numbers of the residual arm the page and the paper show: the net Sharpe with its
    block-bootstrap 95% interval and Newey-West p (the export's significance battery, the
    one the pairs headline carries), total return in %, trades, period and commit; the same
    for the gross-of-cost series (its interval from the same bootstrap here); per-trade gross,
    cost and net in bp with t; the book's size and turnover; and the cumulative net and gross
    paths, on the pairs run's calendar `dates` when the two coincide (else with their own)."""
    s, sig = doc.get('summary') or {}, doc.get('significance') or {}
    ret = s.get('total_return')
    gross_r = np.asarray(doc.get('daily_gross_returns') or [], dtype=float)
    net_r = np.asarray(doc.get('daily_net_returns') or [], dtype=float)
    gross_ci = block_bootstrap_sharpe_ci(gross_r, periods=PERIODS) if gross_r.size > 2 else {}
    gbp, nbp = s.get('gross_bp_per_trade') or {}, s.get('net_bp_per_trade') or {}
    costs = doc.get('costs') or {}
    universe = doc.get('universe') or {}
    own_dates = [str(d)[:10] for d in doc.get('daily_dates') or []]
    paths = None
    if net_r.size and gross_r.size == net_r.size:
        paths = {'net': _rl(_cum_pct(100 * net_r), 4), 'gross': _rl(_cum_pct(100 * gross_r), 4)}
        if own_dates != list(dates or []):
            paths['dates'] = own_dates
    exits = s.get('exit_reasons') or {}

    def scaled(x, k, dp):
        return _r(k * x, dp) if x is not None else None
    return {'sharpe': _r(s.get('sharpe'), 2), 'ret_pct': _r(None if ret is None else 100 * ret, 2),
            'trades': doc.get('total_trades'), 'lo': _r(sig.get('boot_lo'), 2), 'hi': _r(sig.get('boot_hi'), 2),
            'p': _r(sig.get('hac_p'), 3), 'period': [s.get('start'), s.get('end')],
            'commit': _get(doc, 'run_config', 'git_commit'),
            'days': s.get('days'), 'hac_t': _r(sig.get('hac_t'), 2), 'psr_pct': scaled(sig.get('psr'), 100, 1),
            'max_dd_pct': scaled(s.get('max_drawdown'), 100, 2),
            'gross_sharpe': _r(s.get('gross_sharpe'), 2), 'gross_p': _r(s.get('hac_p_gross'), 3),
            'gross_lo': _r(gross_ci.get('lo'), 2), 'gross_hi': _r(gross_ci.get('hi'), 2),
            'gross_bp': _r(gbp.get('mean'), 2), 'gross_t': _r(gbp.get('t'), 2),
            'net_bp': _r(nbp.get('mean'), 2), 'net_t': _r(nbp.get('t'), 2), 'cost_bp': _r(s.get('cost_bp_per_trade'), 2),
            'gross_usd_m': scaled(s.get('gross_pnl'), 1e-6, 2), 'cost_usd_m': scaled(s.get('total_costs'), 1e-6, 2),
            'etf_cost_usd_m': scaled(_get(costs, 'etf', 'total'), 1e-6, 2),
            'win_rate_pct': scaled(s.get('win_rate'), 100, 1),
            'avg_positions': _r(s.get('avg_open_positions'), 0), 'max_positions': s.get('max_open_positions'),
            'avg_gross_x': _r(s.get('avg_gross_exposure'), 2), 'turnover_x': _r(_get(doc, 'turnover', 'annual_turnover'), 1),
            'hold_days': _r(s.get('avg_holding_days'), 1),
            'exits_signal': exits.get('signal'), 'exits_rejected': exits.get('model_rejected'),
            'universe_size': _get(doc, 'params', 'universe_size'), 'rankings': len(universe.get('rankings') or []) or None,
            'symbols_ever': universe.get('symbols_ever_in_universe'),
            'paths': paths}


def v32_section(src, directory):
    """The published v32 run (results/v32_dev): the history this study replaces, and the
    design that runs frozen and descriptive (S3) in the holdout. Its headline numbers and
    the trade-level figures the comparison quotes (gross and cost per trade, flat days, the
    days the regime gate blocked new entries); None if the directory is absent."""
    directory = pathlib.Path(directory)
    if not (directory / 'headline_metrics.json').is_file():
        return None
    head = src.load(directory / 'headline_metrics.json')
    res = src.load(_results_file(directory))
    trades = res.get('all_trades') or []
    gross_bp = np.array([t['spread_return_pct'] * 100.0 for t in trades])
    cost_bp = np.array([t['transaction_costs_dollars'] / t['position_size_dollars'] * 1e4 for t in trades])
    daily = daily_series(res)
    perf = res.get('overall_performance') or {}
    main, oos, sig = head.get('main') or {}, head.get('oos') or {}, head.get('significance') or {}
    t_gross = float(gross_bp.mean() / (gross_bp.std(ddof=1) / math.sqrt(len(gross_bp)))) if len(gross_bp) > 2 else None
    return {
        'run': {'commit': _get(head, 'run_config', 'git_commit'), 'timestamp_utc': _get(head, 'run_config', 'run_timestamp_utc'),
                'version': head.get('version')},
        'main': {'ret_pct': main.get('total_return_pct'), 'sharpe': main.get('sharpe'), 'trades': main.get('trades'),
                 'lo': _get(sig, 'main', 'boot_lo'), 'hi': _get(sig, 'main', 'boot_hi'), 'p': _get(sig, 'main', 'hac_p'),
                 'max_dd_pct': main.get('max_drawdown_pct'), 'avg_exposure_pct': main.get('avg_gross_exposure_pct')},
        'oos': {'sharpe': oos.get('pooled_sharpe'), 'lo': _get(sig, 'oos_daily', 'boot_lo'), 'hi': _get(sig, 'oos_daily', 'boot_hi'),
                'p': _get(sig, 'oos_daily', 'hac_p'), 'ret_pct': oos.get('total_return_pct'),
                'windows_positive': oos.get('windows_positive'), 'windows': oos.get('windows')},
        'gatev_sharpe': _get(head, 'benchmarks', 'gatev', 'sharpe'),
        'random_percentile': _get(head, 'benchmarks', 'random_control', 'strategy_percentile'),
        'pairs_tested': _get(head, 'fdr', 'pairs_tested'), 'pairs_selected': _get(head, 'fdr', 'final_selected_pairs'),
        'bh_q05': _get(head, 'fdr', 'survive_bh_fdr_q05'),
        'ranker_auc': _get(head, 'ranker', 'oos_auc'),
        'gross_bp': _r(gross_bp.mean(), 2) if len(gross_bp) else None, 'gross_t': _r(t_gross, 2),
        'cost_bp': _r(cost_bp.mean(), 2) if len(cost_bp) else None,
        'days': len(daily['dates']), 'flat_days': sum(1 for p in daily['positions'] if p == 0),
        'gate_blocked_days': _get(perf, 'signal_rejections', 'regime_hard_stop_day'),
    }


def trials(lines):
    """One row per run of every trial in results/trial_registry.jsonl, in registry order
    (append-only, so a row's index never changes); a trial registered without a run record
    keeps one row with its run fields null."""
    if lines is None:
        return None
    rows = []
    for e in lines:
        for r in e.get('runs') or [None]:
            r = r or {}
            main, oos = r.get('main') or {}, r.get('oos') or {}
            commit = r.get('git_commit')
            rows.append({
                'name': e.get('name'), 'registered': str(e.get('registered_utc') or '')[:10] or None,
                'note': e.get('note'), 'prereg_commit': e.get('prereg_commit'),
                'dir': r.get('dir'), 'profile': r.get('profile') or r.get('strategy'), 'calendar': r.get('calendar'),
                'commit': commit[:7] if commit else None, 'dirty': r.get('git_dirty'), 'complete': r.get('complete'),
                'period': [main.get('period_start'), main.get('period_end')] if main else None,
                'sharpe': _r(main.get('sharpe')), 'ret_pct': _r(main.get('total_return_pct')),
                'trades': main.get('trades'),
                'oos_sharpe': _r(oos.get('pooled_sharpe')), 'oos_ret_pct': _r(oos.get('total_return_pct')),
            })
    return rows


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


def _variant_label(name):
    """A readable label for a declared variant: 'grid ENTRY_Z=1.5 EXIT_Z=0.25 STOP_Z=1.0' ->
    'Entry 1.5, exit 0.25, stop 1.0'; a toggle by TOGGLE_LABELS (else its own name)."""
    if name.startswith('grid '):
        parts = dict(p.split('=', 1) for p in name[5:].split())
        return ', '.join(f"{k.split('_')[0].lower()} {v}" for k, v in parts.items()).capitalize()
    return TOGGLE_LABELS.get(name, name)


def _spa(x):
    """One SPA test of the family's battery: Hansen's consistent p (with the lower and upper
    p-values), White's Reality Check p, the best variant and its studentized statistic."""
    if not x:
        return None
    return {'p': _r(_get(x, 'pvalues', 'consistent')), 'p_lower': _r(_get(x, 'pvalues', 'lower')),
            'p_upper': _r(_get(x, 'pvalues', 'upper')), 'rc_p': _r(_get(x, 'reality_check', 'pvalue')),
            'best': x.get('best_model'), 'best_label': _variant_label(x.get('best_model') or ''),
            'best_t': _r(x.get('best_tstat'), 3), 'block': x.get('block'), 'reps': x.get('reps')}


def _family_matrix(rows):
    """results/variant_family/daily_returns.csv as (dates, names, T x K array of decimal returns)."""
    if not rows:
        return None
    names = [k for k in rows[0] if k != 'date']
    return ([r['date'] for r in rows], names,
            np.array([[float(r[k]) for k in names] for r in rows], dtype=float))


def snooping(declaration, results, runs=None, family_rows=None, main_r=None):
    """The declared variant family (results/variant_family) and its data-snooping tests.

    declaration   declaration.json: the grid and the toggles, declared before any variant ran
    results       snooping.json (scripts/variant_family.py analyse): SPA and Reality Check
                  against cash and the Gatev series, Romano-Wolf, the model confidence set,
                  the effective number of trials and PBO by CSCV
    runs          runs.json: each variant's Sharpe ratio, return and trades
    family_rows   daily_returns.csv: each variant's daily net returns on the development days
    main_r        the main backtest's daily net returns (decimal)

    The results are published only when runs.json, the daily matrix and snooping.json hold the
    same variants, in the declared order, and the matrix covers the main backtest's days; the
    variant whose daily returns are the main backtest's is the v33 design (`base`). The
    declaration also names a deflated Sharpe ratio with N = the entropy effective rank of the
    variants' correlation matrix and the variants' own Sharpe dispersion; snooping.json holds
    the rank but not the ratio, so it is computed here with pairs_trading.significance, N
    rounded up (dsr_curve's rule) and the trial Sharpe variance of the daily matrix.
    """
    if declaration is None:
        return None
    grid = declaration.get('grid') or {}
    sizes = [len(v) for k, v in grid.items() if isinstance(v, list)]
    out = {'declared_utc': declaration.get('declared_utc'),
           'grid_points': int(np.prod(sizes)) if sizes else 0,
           'toggles': len(declaration.get('toggles') or []), 'results': None}
    fam = (results or {}).get('family') or {}
    matrix = _family_matrix(family_rows)
    if not fam or not runs or matrix is None:
        return out
    dates, names, M = matrix
    declared = list(_get(results, 'declared_family', 'variants', default=[]))
    run_rows = runs.get('variants') or []
    if not (names == declared == list(fam.get('members') or []) == [v['name'] for v in run_rows]) \
            or len(names) != out['grid_points'] + out['toggles']:
        raise ValueError('results/variant_family: runs.json, daily_returns.csv and snooping.json do not hold '
                         'the same declared variants in the same order')
    base = None
    if main_r is not None and len(main_r) == M.shape[0]:
        hits = [k for k, n in enumerate(names) if np.max(np.abs(M[:, k] - main_r)) < 2e-7]
        base = names[hits[0]] if len(hits) == 1 else None
    sharpes = np.array([v['sharpe'] for v in run_rows], dtype=float)
    order = np.argsort(-sharpes, kind='stable')
    rank = {names[k]: i + 1 for i, k in enumerate(order)}
    rw = {row['model']: row for row in _get(fam, 'romano_wolf_vs_zero', 'table', default=[])}
    mcs = fam.get('mcs') or {}
    mcs_p = mcs.get('pvalues') or {}
    variants = [{'name': v['name'], 'label': _variant_label(v['name']),
                 'kind': 'grid' if v['name'].startswith('grid ') else 'toggle', 'base': v['name'] == base,
                 'sharpe': _r(v['sharpe']), 'ret_pct': _r(v['total_return_pct']), 'trades': v['trades'],
                 'max_dd_pct': _r(v['max_drawdown_pct']), 'rank': rank[v['name']],
                 'rw_p': _r(_get(rw, v['name'], 'p_adjusted')), 'mcs_p': _r(mcs_p.get(v['name']))}
                for v in run_rows]
    best, worst = run_rows[order[0]], run_rows[order[-1]]
    eff = fam.get('effective_trials') or {}
    pbo = (results or {}).get('pbo') or {}
    rw_p = [r['rw_p'] for r in variants if r['rw_p'] is not None]
    min_rw = min(variants, key=lambda r: r['rw_p'] if r['rw_p'] is not None else 2.0)
    # the declared deflation: N = the effective rank, rounded up; the variants' Sharpe variance
    # (fixed shape: null without the main backtest's returns on the family's days)
    dsr = {'n_trials': None, 'sd_sr': None, 'sr_star': None, 'dsr_pct': None, 'curve': []}
    if main_r is not None and eff.get('effective_rank') is not None:
        n_eff = int(math.ceil(eff['effective_rank'] - 1e-9))
        var = trial_sharpe_variance(M, PERIODS)
        d = deflated_sharpe_ratio(main_r, n_eff, var, PERIODS)
        dsr = {'n_trials': n_eff, 'sd_sr': _r(math.sqrt(var)), 'sr_star': _r(d['sr_star_ann']),
               'dsr_pct': _r(100 * d['dsr'], 2),
               'curve': [{'n': n, 'dsr': _r(x['dsr']), 'sr_star': _r(x['sr_star_ann'])}
                         for n, x in zip(DSR_TRIALS, _dsr_curve(main_r, DSR_TRIALS, var, PERIODS))]}
    out['results'] = {
        'n': len(names), 'days': len(dates), 'first_day': dates[0], 'last_day': dates[-1],
        'base': base, 'base_label': _variant_label(base) if base else None,
        'base_rank': rank.get(base), 'base_sharpe': _r(run_rows[names.index(base)]['sharpe']) if base else None,
        'variants': variants,
        'positive': int((sharpes > 0).sum()), 'sharpe_median': _r(float(np.median(sharpes))),
        'sharpe_best': _r(best['sharpe']), 'best': best['name'], 'best_label': _variant_label(best['name']),
        'sharpe_worst': _r(worst['sharpe']), 'worst': worst['name'], 'worst_label': _variant_label(worst['name']),
        'ret_best_pct': _r(max(v['total_return_pct'] for v in run_rows)),
        'ret_worst_pct': _r(min(v['total_return_pct'] for v in run_rows)),
        'trades_min': min(v['trades'] for v in run_rows), 'trades_max': max(v['trades'] for v in run_rows),
        'spa_zero': _spa(fam.get('spa_vs_zero')), 'spa_gatev': _spa(fam.get('spa_vs_gatev')),
        'spa_gatev_unit_vol': _spa(fam.get('spa_vs_gatev_unit_vol')),
        'rw_rejected': len(_get(fam, 'romano_wolf_vs_zero', 'rejected', default=[])),
        'rw_alpha': _get(fam, 'romano_wolf_vs_zero', 'alpha'),
        'rw_min_p': min(rw_p) if rw_p else None, 'rw_min_label': min_rw['label'] if rw_p else None,
        'mcs_size_pct': _r(100 * mcs['size'], 0) if mcs.get('size') is not None else None,
        'mcs_included': len(mcs.get('included') or []), 'mcs_excluded': len(mcs.get('excluded') or []),
        'mcs_min_p': _r(min(mcs_p.values()), 4) if mcs_p else None,
        'effective_rank': _r(eff.get('effective_rank'), 2), 'avg_corr': _r(eff.get('avg_correlation'), 3),
        'n_eff_avg_corr': _r(eff.get('n_eff_avg_corr'), 2),
        'pbo_pct': _r(100 * pbo['pbo'], 2) if pbo.get('pbo') is not None else None,
        'pbo_splits': pbo.get('n_combinations'), 'pbo_blocks': pbo.get('n_splits'),
        'pbo_median_logit': _r(pbo.get('median_logit'), 3),
        'pbo_is_best_oos_sharpe': _r(pbo.get('mean_oos_sharpe_of_is_best')),
        'pbo_is_best_loss_pct': _r(100 * pbo['prob_oos_loss_of_is_best'], 2)
        if pbo.get('prob_oos_loss_of_is_best') is not None else None,
        'dsr': dsr,
        'block': _get(fam, 'spa_vs_zero', 'block'), 'reps': _get(fam, 'spa_vs_zero', 'reps'),
    }
    return out


def _spread(x):
    """The range, median, mean and sd of a list of numbers (robustness.json's 'spread' rows)."""
    if not x:
        return None
    return {k: _r(x.get(k)) for k in ('min', 'max', 'median', 'mean', 'sd', 'range')} | {'n': x.get('n')}


# The fixed shape of the robustness section (robustness_checks.py's design): 12 start dates,
# two halves, terciles, three calendar years, five pairs of years of persistence. A run without
# robustness.json gets this shape with every value null, so a page marker names a key that
# every build has; a report of another shape stops the build.
ROBUSTNESS_SHAPE = {'starts': 12, 'halves': 2, 'terciles': 3, 'years': 3, 'persistence_years': 5}


def robustness_skeleton():
    """robustness() for a run without robustness.json: the same keys and list lengths, null values."""
    def row(keys):
        return dict.fromkeys(keys)
    spread = ('min', 'max', 'median', 'mean', 'sd', 'range', 'n')
    start = ('offset', 'start', 'days', 'trades', 'sharpe', 'ret_pct', 'max_dd_pct', 'nw_t', 'common_sharpe',
             'common_ret_pct')
    half = ('half', 'entry', 'last_day', 'days', 'entry_days', 'trades', 'sharpe', 'ret_pct', 'nw_t', 'run_off_days',
            'inside_days', 'inside_sharpe', 'inside_ret_pct')
    bucket = ('bucket', 'days', 'mean_bp', 'sharpe', 't', 'p', 'ret_pct')
    year = ('year', 'next_year', 'correlated', 'coint', 'coint_pct', 'still', 'still_of', 'still_pct', 'base_pct',
            'p_vs_base')
    pooled = ('count', 'of', 'pct', 'lo_pct', 'hi_pct', 'expected', 'expected_pct', 'z')
    cluster = ('clusters', 'se_bp', 't', 'p', 'design_effect')

    def regime(n):
        def series():
            return {'rows': [row(bucket) for _ in range(n)], 'diff': {'of': [], 'mean_bp': None, 't': None, 'p': None},
                    'lags': None}
        return {'breakpoints': [], 'net': series(), 'gross': series()}

    def persistence():
        return {'symbols': None, 'pairs': None,
                'years': [row(year) for _ in range(ROBUSTNESS_SHAPE['persistence_years'])], 'pooled': row(pooled)}

    def clustered():
        return {**{by: row(cluster) for by in ('entry_month', 'entry_date', 'symbol')},
                **row(('mean_bp', 'se_bp', 't', 'p'))}
    return {
        'code_commit': None,
        'start_dates': {'n': None, 'step_days': None, 'window': [], 'common': row(('first', 'last', 'days')),
                        'runs': [row(start) for _ in range(ROBUSTNESS_SHAPE['starts'])],
                        'sharpe': row(spread), 'sharpe_common': row(spread), 'ret': row(spread), 'trades': row(spread),
                        'headline_rank': None, 'reproduces': False},
        'halves': [{**row(half), 'entry': []} for _ in range(ROBUSTNESS_SHAPE['halves'])],
        'regimes': {'days': None, 'vix': regime(ROBUSTNESS_SHAPE['terciles']),
                    'dispersion': regime(ROBUSTNESS_SHAPE['terciles']), 'year': regime(ROBUSTNESS_SHAPE['years'])},
        'persistence': {'formations': None, 'first': persistence(), 'union': persistence()},
        's2': {'trades': None, 'gross': clustered(), 'net': clustered(), 'reproduced': False},
        'available': False,
    }


def robustness(report, results_sha256):
    """The robustness checks of the run (scripts/robustness_checks.py, {dev}/robustness.json):
    the main backtest from 12 start dates and the two halves as separate runs; returns by
    previous-day VIX and sector-dispersion tercile and by year (Newey-West t); cointegration
    persistence on S1's own candidate pairs; and the second family's per-trade edge with
    standard errors clustered by entry month, date and symbol.

    A report computed from another export than the run's (its recorded sha256 of the results
    file differs) is not of this run and stops the build.
    """
    if report is None:
        return robustness_skeleton()
    if _get(report, 'inputs', 'results', 'sha256') != results_sha256:
        raise ValueError('robustness.json was computed from another results export than this run\'s '
                         f"(sha256 {_get(report, 'inputs', 'results', 'sha256')}); re-run "
                         'scripts/robustness_checks.py')
    sd = report.get('start_dates') or {}
    runs = sd.get('runs') or []
    sharpes = [r['sharpe'] for r in runs]
    head = next((r for r in runs if r['offset_trading_days'] == 0), None)
    starts = [{'offset': r['offset_trading_days'], 'start': r['start'], 'days': r['days'], 'trades': r['trades'],
               'sharpe': _r(r['sharpe']), 'ret_pct': _r(r['total_return_pct']), 'max_dd_pct': _r(r['max_drawdown_pct']),
               'nw_t': _r(r.get('nw_t'), 3), 'common_sharpe': _r(_get(r, 'common_window', 'sharpe')),
               'common_ret_pct': _r(_get(r, 'common_window', 'total_return_pct'))} for r in runs]
    halves = [{'half': h['half'], 'entry': h['entry_window'], 'last_day': h['last_day'], 'days': h['days'],
               'entry_days': h.get('entry_days'), 'trades': h['trades'], 'sharpe': _r(h['sharpe']),
               'ret_pct': _r(h['total_return_pct']), 'nw_t': _r(h.get('nw_t'), 3), 'run_off_days': h.get('run_off_days'),
               'inside_days': _get(h, 'main_run_same_days', 'days'),
               'inside_sharpe': _r(_get(h, 'main_run_same_days', 'sharpe')),
               'inside_ret_pct': _r(_get(h, 'main_run_same_days', 'total_return_pct'))}
              for h in sd.get('halves') or []]

    def regime(block):
        if not block:
            return None

        def buckets(series):
            b = block.get(series) or {}
            diff = b.get('last_minus_first') or {}
            return {'rows': [{'bucket': str(x['bucket']), 'days': x['days'], 'mean_bp': _r(x['mean_daily_bp']),
                              'sharpe': _r(x['sharpe']), 't': _r(x['nw_t']), 'p': _r(x['nw_p']),
                              'ret_pct': _r(x.get('return_pct_on_these_days'))} for x in b.get('buckets') or []],
                    'diff': {'of': [str(v) for v in diff.get('buckets') or []], 'mean_bp': _r(diff.get('mean_daily_bp')),
                             't': _r(diff.get('nw_t')), 'p': _r(diff.get('nw_p'))}, 'lags': b.get('nw_lags')}
        return {'breakpoints': _rl(block.get('breakpoints') or [], 6), 'net': buckets('net'), 'gross': buckets('gross')}
    reg = report.get('regimes') or {}
    pers = report.get('persistence') or {}

    def persistence(p):
        if not p:
            return None
        pooled = p.get('pooled_still_cointegrated') or {}
        lo, hi = (pooled.get('ci95') or [None, None])[:2]
        return {'symbols': p.get('symbols'), 'pairs': p.get('pairs'),
                'years': [{'year': y['year'], 'next_year': y['next_year'], 'correlated': y['correlated_pairs'],
                           'coint': y['cointegrated']['count'], 'coint_pct': _r(100 * y['cointegrated']['share'], 4),
                           'still': y['still_cointegrated_next_year']['count'],
                           'still_of': y['still_cointegrated_next_year']['of'],
                           'still_pct': _r(100 * y['still_cointegrated_next_year']['share'], 4),
                           'base_pct': _r(100 * y['still_cointegrated_next_year']['next_year_base_rate'], 4),
                           'p_vs_base': _r(y['still_cointegrated_next_year']['binom_p_vs_next_year_base_rate'])}
                          for y in p.get('years') or []],
                'pooled': {'count': pooled.get('count'), 'of': pooled.get('of'),
                           'pct': _r(100 * pooled['share'], 4) if pooled.get('share') is not None else None,
                           'lo_pct': _r(100 * lo, 4) if lo is not None else None,
                           'hi_pct': _r(100 * hi, 4) if hi is not None else None,
                           'expected': _r(pooled.get('expected_at_next_year_base_rates'), 3),
                           'expected_pct': _r(100 * pooled['expected_at_next_year_base_rates'] / pooled['of'], 4)
                           if pooled.get('of') else None,
                           'z': _r(pooled.get('z_vs_next_year_base_rates'), 4)}}
    s2 = report.get('s2_trade_edge') or {}

    def clustered(series):
        out = {}
        for by in ('entry_month', 'entry_date', 'symbol'):
            c = _get(s2, series, by) or {}
            out[by] = {'clusters': c.get('clusters'), 'se_bp': _r(c.get('se_clustered')), 't': _r(c.get('t_clustered')),
                       'p': _r(c.get('p_clustered')), 'design_effect': _r(c.get('design_effect'))}
        c = _get(s2, series, 'entry_month') or {}
        out.update({'mean_bp': _r(c.get('mean')), 'se_bp': _r(c.get('se_independent')),
                    't': _r(c.get('t_independent')), 'p': _r(c.get('p_independent'))})
        return out
    shape = (len(runs), len(sd.get('halves') or []), len(_get(report, 'regimes', 'vix', 'net', 'buckets', default=[])),
             len(_get(report, 'regimes', 'calendar_year', 'net', 'buckets', default=[])),
             len(_get(report, 'persistence', 'first_formation', 'years', default=[])))
    if shape != tuple(ROBUSTNESS_SHAPE.values()):
        raise ValueError(f'robustness.json has {shape} (starts, halves, terciles, years, persistence years); the page '
                         f'expects {tuple(ROBUSTNESS_SHAPE.values())}')
    return {
        'available': True,
        'code_commit': _get(report, 'code', 'git_commit'),
        'start_dates': {'n': len(runs), 'step_days': _get(sd, 'design', 'step_trading_days'),
                        'window': _get(sd, 'design', 'window'), 'common': sd.get('common_window'),
                        'runs': starts, 'sharpe': _spread(_get(sd, 'spread', 'sharpe')),
                        'sharpe_common': _spread(_get(sd, 'spread', 'sharpe_common_window')),
                        'ret': _spread(_get(sd, 'spread', 'total_return_pct')),
                        'trades': _spread(_get(sd, 'spread', 'trades')),
                        # 1 = the most favourable start; the published run is offset 0
                        'headline_rank': 1 + sum(1 for s in sharpes if head and s > head['sharpe']) if head else None,
                        'reproduces': bool(_get(sd, 'offset_0_reproduces_published_main_backtest', 'verified'))},
        'halves': halves,
        'regimes': {'days': reg.get('days'), 'vix': regime(reg.get('vix')),
                    'dispersion': regime(reg.get('sector_dispersion')), 'year': regime(reg.get('calendar_year'))},
        'persistence': {'formations': len(pers.get('formations') or []),
                        'first': persistence(pers.get('first_formation')),
                        'union': persistence(pers.get('union_of_formations'))},
        's2': {'trades': s2.get('trades'), 'gross': clustered('gross_bp'), 'net': clustered('net_bp'),
               'reproduced': bool(_get(s2, 'export_check', 'reproduced'))} if s2 else None,
    }


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
    price_manifest = src.load(dev / PRICE_MANIFEST)
    universe = src.load(dev / 'universe_meta.json')
    battery = src.load(dev / 'stats_battery.json')
    anatomy = src.load(dev / 'anatomy.json') or {}
    scenarios = src.load(dev / 'cost_sensitivity.json')
    declaration = src.load(results_root / VARIANT_FAMILY / 'declaration.json')
    snoop = src.load(results_root / VARIANT_FAMILY / 'snooping.json')
    family_runs = src.load(results_root / VARIANT_FAMILY / 'runs.json')
    family_rows = src.load_csv(results_root / VARIANT_FAMILY / 'daily_returns.csv')
    rob = src.load(dev / ROBUSTNESS)
    residual = load_residual(src, results_root / 'residual_dev')
    holdout = src.load(results_root / 'holdout2026' / 'evaluation.json')
    known = src.load(results_root / 'validation' / 'synthetic_validation.json')
    registry = src.load_lines(results_root / REGISTRY)
    v32 = v32_section(src, results_root / V32_RUN)

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
    forest_rows = forest(res, gatev['net'] if gatev else None, daily['gross'])
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
        'forest': forest_rows,
        'power': power,
        'dsr_curve': dsr_curve(r_main, battery),
        'waterfall': steps,
        'trades': groups,
        'factors': fac,
        'funnel': funnel(res, universe),
        'universe_by_formation': universe_coverage(res),
        'survivorship': None,
        'performance': performance(res, headline, wf, forest_rows),
        'cost_schedules': cost_schedules(funds, daily['dates']),
        'cost_curve': cost_curve(daily),
        'cost_sensitivity': cost_scenarios(scenarios, res, anatomy),
        'half_lives': half_lives(anatomy),
        # the family is compared with this run's main backtest only on the same days
        'snooping': snooping(declaration, snoop, family_runs, family_rows,
                             r_main if family_rows and [r['date'] for r in family_rows] == daily['dates'] else None),
        'robustness': robustness(rob, _sha256(_results_file(dev))),
        **{key: anatomy[key] for key in ANATOMY_KEYS if anatomy.get(key) is not None},
    }
    rows = dev_out['universe_by_formation']
    if rows and price_manifest:
        snaps = {r['snapshot']: src.load_csv(pathlib.Path(root).joinpath(*UNIVERSE_DIR, f"iwv_{r['snapshot']}.csv"))
                 for r in rows}
        if all(v is not None for v in snaps.values()):
            dev_out['survivorship'] = survivorship(rows, price_manifest, snaps)
    hurdles = _get(evidence, 'hurdles', 'hurdles')
    if hurdles:                                   # reference lines of the forest plot
        power['hurdles'] = {k: _r(_get(hurdles, k, 'sr_ann')) for k in ('single_test', 'bonferroni_one_sided', 'hlz', 'cgs')}
    dev_out['facts'] = facts(res, dev_out, anatomy)

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
        'residual': residual_summary(residual, daily['dates']) if residual else None,
        'validation': validation(known),
        'v32': v32,
        'trials': trials(registry),
        # the registry's size: its trials (one line each) and their runs (the rows of 'trials')
        'registry': {'trials': len(registry), 'runs': len(trials(registry))} if registry is not None else None,
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
                         '(default results/v33_dev)')
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
