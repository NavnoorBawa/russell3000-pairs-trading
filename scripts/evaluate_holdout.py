#!/usr/bin/env python3
"""The pre-registered test on the 2026 holdout (docs/PREREGISTRATION.md), and its report.

For each strategy k: H0_k mean daily net return <= 0 against H1_k > 0, tested with the
one-sided Newey-West t-test (significance.hac_tstat_mean, its own lag rule; one-sided
p = 1 - Phi(t)), Holm-Bonferroni across the strategies at familywise alpha = 0.05. A
strategy shows an edge out of sample only if its Holm-adjusted p is below alpha.

Also reported for each, whatever the outcome: net and gross return, annualised Sharpe with
its standard error (non-normal, AR(1)) and the Lo (2002) autocorrelation-adjusted Sharpe,
the probabilistic Sharpe ratio, the block-bootstrap 95%
interval, the one-sided 95% upper confidence bound, the minimum detectable Sharpe of a
test this long (power.power_report) at the level Holm's first step requires (alpha / the
number of strategies) and at alpha, trades and gross exposure, the Ledoit-Wolf Sharpe
difference against the Gatev distance method, the random-pair percentile, and the
point-in-time universe's survivorship gap at each formation. A pairs strategy is compared
with its own run's baselines; the residual strategy, which runs none, with those of the
S1 (v33) run, built on the same point-in-time universe rule. A statistic a series does not
have (a strategy that never trades has no Sharpe standard error) is null.

The inputs are checked before anything is computed, and a failed check exits non-zero
without a report: the calendar, each pairs run's profile and calendar hash against
study_config, complete runs without non-default switches from a clean tree, one commit
for every run (--expect-commit), one price cache for the pairs runs, finite returns on
identical trading dates inside the calendar, and, on the holdout, exactly the three
registered strategies.

usage: python scripts/evaluate_holdout.py --pairs v33=DIR --pairs v32=DIR --residual FILE
                                          [--calendar holdout2026] [--expect-commit SHA]
                                          [--out results/holdout2026/evaluation.json]
DIR is a run's output directory (results JSON + headline); FILE the residual arm's JSON.
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading.benchmark import empirical_percentile  # noqa: E402
from pairs_trading.power import power_report  # noqa: E402
from pairs_trading.significance import (  # noqa: E402
    align_return_series, annualized_sharpe, block_bootstrap_sharpe_ci, hac_tstat_mean,
    lo_annualized_sharpe, probabilistic_sharpe_ratio, sharpe_difference_test,
)
from pairs_trading.study_config import CALENDARS, PROFILES  # noqa: E402

ALPHA = 0.05
RESULTS_FILE = 'pairs_trading_results_2023_2025_unbiased.json'   # historical name, any period
HOLDOUT = 'holdout2026'
REGISTERED = ('v33_pairs', 'avellaneda_lee', 'v32_pairs')       # S1, S2, S3
BASELINE_ARM = 'v33_pairs'          # whose baselines the residual strategy is compared with


def holm(pvalues: dict) -> dict:
    """Holm-Bonferroni adjusted p-values (step-down, monotone), keyed like the input."""
    order = sorted(pvalues, key=lambda k: (pvalues[k], k))
    m, running, out = len(order), 0.0, {}
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvalues[k]))
        out[k] = running
    return out


def one_sided_test(net) -> dict:
    """One-sided HAC t-test of mean > 0 (the pre-registered primary test)."""
    h = hac_tstat_mean(np.asarray(net, dtype=float))
    return {'t': h['tstat'], 'lags': h['lags'], 'p_one_sided': float(1.0 - stats.norm.cdf(h['tstat']))}


def _null_nonfinite(x):
    """NaN/inf -> None, recursively: the report is strict JSON."""
    if isinstance(x, float) and not np.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: _null_nonfinite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_null_nonfinite(v) for v in x]
    return x


def _days(dates) -> list:
    return [str(d)[:10] for d in dates]


def describe(net, gross=None, trades=None, n_tests: int = 1) -> dict:
    """Everything the pre-registration promises to report for one daily net series."""
    r = np.asarray(net, dtype=float)
    out = {'days': int(r.size), 'total_return_pct': float((np.prod(1.0 + r) - 1.0) * 100),
           'sharpe': annualized_sharpe(r), 'trades': trades, **one_sided_test(r)}
    out['sharpe_lo2002'] = lo_annualized_sharpe(r)['sharpe']   # autocorrelation-adjusted
    out['psr'] = probabilistic_sharpe_ratio(r)['psr']
    ci = block_bootstrap_sharpe_ci(r)
    out['bootstrap_ci_95'] = [ci['lo'], ci['hi']]
    pw = power_report(r)
    out['sharpe_se'] = pw['se_ann']                  # non-normal, AR(1) standard error
    out['upper_bound_95'] = pw['upper_bound_ann']
    # A single true edge has to clear Holm's first step: one-sided p < alpha / n_tests.
    out['min_detectable_sharpe'] = power_report(r, alpha=ALPHA / n_tests)['min_detectable_sr_ann']
    out['min_detectable_sharpe_alpha'] = ALPHA / n_tests
    out['min_detectable_sharpe_single_test'] = pw['min_detectable_sr_ann']
    if gross is not None:
        g = np.asarray(gross, dtype=float)
        out['gross_total_return_pct'] = float((np.prod(1.0 + g) - 1.0) * 100)
        out['gross_sharpe'] = annualized_sharpe(g)
    return _null_nonfinite(out)


def compare_with_baselines(dates, net, baselines: dict) -> dict:
    """Ledoit-Wolf Sharpe difference vs the distance method and the random-pair percentile,
    from another run's exported baselines, computed as run_benchmarks does in its own run."""
    common, a, b = align_return_series(_days(dates), net, baselines['distance_dates'],
                                       baselines['distance_returns'])
    vs = {'n_common_days': len(common), 'source': baselines['source'],
          'universe_size': baselines.get('universe_size')}
    if len(common) >= 20:
        t = sharpe_difference_test(a, b, n_boot=5000, seed=42)
        vs.update({k: t[k] for k in ('diff', 'ci_lo', 'ci_hi', 'pvalue')}, distance_sharpe=annualized_sharpe(b))
    # The draws' Sharpes are over the benchmark's calendar: comparable on the same dates only.
    draws = baselines['draw_sharpes']
    same = bool(draws) and _days(dates) == _days(baselines['random_dates'])
    rp = {'percentile': empirical_percentile(annualized_sharpe(np.asarray(net, dtype=float)), draws) if same else None,
          'median_sharpe': float(np.median(draws)) if same else None,
          'n_draws': len(draws), 'source': baselines['source']}
    if not same:
        rp['note'] = 'trading dates differ from the random control calendar'
    return {'vs_gatev': vs, 'random_pair': rp}


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_pairs_run(directory: pathlib.Path) -> dict:
    path, head_path = directory / RESULTS_FILE, directory / 'headline_metrics.json'
    doc = json.loads(path.read_text())
    head = json.loads(head_path.read_text()) if head_path.exists() else {}
    rc = head.get('run_config') or doc.get('run_config') or {}
    study = rc.get('study') or {}
    days = doc['daily_equity_curve']
    perf = doc.get('overall_performance') or {}
    bench = doc.get('benchmarks') or {}
    vs = (bench.get('vs_strategy') or {}).get('main_backtest') or {}
    lw = vs.get('sharpe_difference_vs_distance') or {}
    dist, rand = bench.get('distance_method') or {}, bench.get('random_control') or {}
    universe = (bench.get('config') or {}).get('universe_size')
    return {'dates': [d['date'] for d in days],
            'net': [d['daily_return_pct'] / 100.0 for d in days],
            'gross': [(d.get('gross_return_pct') or 0.0) / 100.0 for d in days],
            'trades': perf.get('total_trades'),
            'exposure': {'avg_gross_pct_of_equity': perf.get('avg_gross_exposure_pct_of_equity'),
                         'max_gross_pct_of_equity': perf.get('max_gross_exposure_pct_of_equity'),
                         'days_with_open_positions': sum(1 for d in days if (d.get('open_positions') or 0) > 0)},
            'vs_gatev': {**{k: lw.get(k) for k in ('diff', 'ci_lo', 'ci_hi', 'pvalue')},
                         'n_common_days': vs.get('n_common_days'), 'distance_sharpe': vs.get('distance_sharpe'),
                         'source': 'own run', 'universe_size': universe},
            'random_pair': {'percentile': vs.get('strategy_percentile_in_random'),
                            'median_sharpe': (vs.get('random_sharpe_distribution') or {}).get('median'),
                            'n_draws': rand.get('n_draws'), 'source': 'own run'},
            'universe_by_formation': doc.get('universe_by_formation'),
            'baselines': {'source': f'{directory.name} run', 'universe_size': universe,
                          'distance_dates': dist.get('daily_dates') or [],
                          'distance_returns': dist.get('daily_returns') or [],
                          'random_dates': rand.get('daily_dates') or [],
                          'draw_sharpes': rand.get('draw_sharpes') or []},
            'provenance': {'git_commit': rc.get('git_commit'), 'git_dirty': rc.get('git_dirty'),
                           'run_timestamp_utc': rc.get('run_timestamp_utc'),
                           'profile': (study.get('profile') or {}).get('name'),
                           'profile_hash': study.get('profile_hash'),
                           'calendar': (study.get('calendar') or {}).get('name'),
                           'calendar_hash': study.get('calendar_hash'),
                           'complete': head.get('complete'),
                           'non_default_switches': head.get('non_default_switches'),
                           'price_cache_sha256': ((rc.get('data') or {}).get('price_cache') or {}).get('sha256')},
            'files': {p.name: _sha256(p) for p in (path, head_path) if p.exists()},
            'commit': rc.get('git_commit')}


def load_residual_run(path: pathlib.Path) -> dict:
    doc = json.loads(path.read_text())
    rc = doc.get('run_config') or {}
    return {'dates': doc['daily_dates'], 'net': doc['daily_net_returns'],
            'gross': doc.get('daily_gross_returns'), 'trades': doc.get('total_trades'),
            'provenance': {'git_commit': rc.get('git_commit'), 'git_dirty': rc.get('git_dirty'),
                           'calendar': ((rc.get('study') or {}).get('calendar') or {}).get('name')},
            'files': {path.name: _sha256(path)},
            'commit': rc.get('git_commit')}


def check_runs(runs: dict, calendar: str = HOLDOUT, expect_commit: str = None) -> list:
    """Why these runs are not the registered test's inputs (empty: they are)."""
    cal = CALENDARS[calendar]
    bad = []
    if not runs:
        return ['no runs given']
    if calendar == HOLDOUT and sorted(runs) != sorted(REGISTERED):
        bad.append(f"strategies {sorted(runs)}, registered {sorted(REGISTERED)}")
    commits = {k: (v.get('provenance') or {}).get('git_commit') for k, v in runs.items()}
    if None in commits.values() or len(set(commits.values())) > 1:
        bad.append(f"the runs are not from one commit: {commits}")
    elif expect_commit and set(commits.values()) != {expect_commit}:
        bad.append(f"the runs are from {commits}, not the expected commit {expect_commit}")
    caches = {k: v['provenance'].get('price_cache_sha256') for k, v in runs.items()
              if 'profile_hash' in (v.get('provenance') or {})}
    if len(set(caches.values())) > 1:
        bad.append(f"the pairs runs read different price caches: {caches}")
    first = None
    for k, v in runs.items():
        p = v.get('provenance') or {}
        pairs = 'profile_hash' in p                  # a pairs run: its study block is complete
        net = np.asarray(v['net'], dtype=float)
        dates = _days(v['dates'])
        if net.size == 0 or not np.all(np.isfinite(net)) or len(dates) != net.size:
            bad.append(f"{k}: {net.size} daily net returns ({len(dates)} dates), not all finite or not one per date")
        if p.get('git_dirty') is not False:
            bad.append(f"{k}: git_dirty is {p.get('git_dirty')}, not false")
        if (pairs or p.get('calendar') is not None) and p.get('calendar') != calendar:
            bad.append(f"{k}: calendar {p.get('calendar')}, not {calendar}")
        if pairs:
            profile = PROFILES.get(p.get('profile'))
            if profile is None or p.get('profile_hash') != profile.config_hash():
                bad.append(f"{k}: profile {p.get('profile')} hash {p.get('profile_hash')} is not study_config's")
            if p.get('calendar_hash') != cal.config_hash():
                bad.append(f"{k}: calendar hash {p.get('calendar_hash')}, study_config's is {cal.config_hash()}")
            if p.get('complete') is not True or p.get('non_default_switches'):
                bad.append(f"{k}: complete {p.get('complete')}, non-default switches "
                           f"{p.get('non_default_switches')}")
        if dates and not (cal.backtest_start <= dates[0] and dates[-1] <= cal.data_end):
            bad.append(f"{k}: trading dates {dates[0]} -> {dates[-1]} outside the calendar's "
                       f"{cal.backtest_start} -> {cal.data_end}")
        if first is None:
            first = (k, dates)
        elif dates != first[1]:
            bad.append(f"{k}: trading dates differ from {first[0]}'s")
    return bad


def evaluate(runs: dict) -> dict:
    """runs: {strategy_id: {'net': [...], 'gross': [...], 'trades': n, ...}}."""
    for k, v in runs.items():
        if not np.all(np.isfinite(np.asarray(v['net'], dtype=float))):
            raise ValueError(f"{k}: the daily net returns are not all finite")
    rows = {k: {**describe(v['net'], v.get('gross'), v.get('trades'), n_tests=len(runs)),
                **{x: v[x] for x in ('exposure', 'vs_gatev', 'random_pair', 'universe_by_formation',
                                     'commit', 'dates') if x in v}}
            for k, v in runs.items()}
    base = (runs.get(BASELINE_ARM) or {}).get('baselines')
    for k, v in runs.items():
        if 'vs_gatev' not in v and base and v.get('dates'):
            rows[k].update(_null_nonfinite(compare_with_baselines(v['dates'], v['net'], base)))
    for row in rows.values():
        dates = row.pop('dates', None)
        if dates:
            row['period'] = [dates[0], dates[-1]]
    adj = holm({k: r['p_one_sided'] for k, r in rows.items()})
    for k, r in rows.items():
        r['p_holm'] = adj[k]
        r['edge_out_of_sample'] = bool(adj[k] < ALPHA)
    return {'alpha': ALPHA, 'test': 'one-sided Newey-West t (mean daily net return > 0), Holm across strategies',
            'strategies': rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--pairs', action='append', default=[], metavar='ID=DIR')
    ap.add_argument('--residual', metavar='FILE')
    ap.add_argument('--calendar', default=HOLDOUT, choices=sorted(CALENDARS))
    ap.add_argument('--expect-commit', metavar='SHA', help='the commit every run must come from')
    ap.add_argument('--out', default=str(ROOT / 'results' / 'holdout2026' / 'evaluation.json'))
    args = ap.parse_args(argv)
    runs = {}
    for spec in args.pairs:
        sid, directory = spec.split('=', 1)
        runs[sid] = load_pairs_run(pathlib.Path(directory))
    if args.residual:
        runs['avellaneda_lee'] = load_residual_run(pathlib.Path(args.residual))
    problems = check_runs(runs, args.calendar, args.expect_commit)
    if problems:
        print('not the registered inputs; no evaluation written:\n  ' + '\n  '.join(problems), file=sys.stderr)
        return 2
    report = evaluate(runs)
    cal, dates = CALENDARS[args.calendar], _days(next(iter(runs.values()))['dates'])
    report['inputs'] = {
        'calendar': args.calendar, 'calendar_hash': cal.config_hash(), 'expect_commit': args.expect_commit,
        'period_matches_calendar': dates[0] == cal.backtest_start and dates[-1] == cal.data_end,
        'runs': {k: {'provenance': v.get('provenance'), 'sha256': v.get('files')} for k, v in runs.items()}}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, allow_nan=False, default=float))
    for k, r in report['strategies'].items():
        print(f"{k:>16}: {r['days']} days, net {r['total_return_pct']:+.2f}%, Sharpe {r['sharpe']:+.2f}, "
              f"t {r['t']:+.2f}, p(one-sided) {r['p_one_sided']:.3f}, Holm p {r['p_holm']:.3f}"
              f"{'  EDGE' if r['edge_out_of_sample'] else ''}")
    if not report['inputs']['period_matches_calendar']:
        print(f"note: trading dates {dates[0]} -> {dates[-1]}, calendar {cal.backtest_start} -> {cal.data_end}")
    print(f"-> {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
