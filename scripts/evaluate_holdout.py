#!/usr/bin/env python3
"""The pre-registered test on the 2026 holdout (docs/PREREGISTRATION.md), and its report.

For each strategy k: H0_k mean daily net return <= 0 against H1_k > 0, tested with the
one-sided Newey-West t-test (significance.hac_tstat_mean, its own lag rule; one-sided
p = 1 - Phi(t)), Holm-Bonferroni across the strategies at familywise alpha = 0.05. A
strategy shows an edge out of sample only if its Holm-adjusted p is below alpha.

Also reported for each, whatever the outcome: net and gross return, annualised Sharpe with
its standard error (non-normal, AR(1)) and the Lo (2002) autocorrelation-adjusted Sharpe,
the probabilistic Sharpe ratio, the block-bootstrap 95%
interval, the one-sided 95% upper confidence bound and the minimum detectable Sharpe of a
test this long (power.power_report), trades, and — for the pairs strategies — the Ledoit-Wolf
Sharpe difference against the Gatev distance method and the random-pair percentile from the
run's own benchmark block.

usage: python scripts/evaluate_holdout.py --pairs v33=DIR --pairs v32=DIR --residual FILE
                                          [--out results/holdout2026/evaluation.json]
DIR is a run's output directory (results JSON + headline); FILE the residual arm's JSON.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from scipy import stats

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading.power import power_report  # noqa: E402
from pairs_trading.significance import (  # noqa: E402
    annualized_sharpe, block_bootstrap_sharpe_ci, hac_tstat_mean, lo_annualized_sharpe,
    probabilistic_sharpe_ratio,
)

ALPHA = 0.05
RESULTS_FILE = 'pairs_trading_results_2023_2025_unbiased.json'   # historical name, any period


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


def describe(net, gross=None, trades=None) -> dict:
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
    out['min_detectable_sharpe'] = pw['min_detectable_sr_ann']
    if gross is not None:
        g = np.asarray(gross, dtype=float)
        out['gross_total_return_pct'] = float((np.prod(1.0 + g) - 1.0) * 100)
        out['gross_sharpe'] = annualized_sharpe(g)
    return out


def load_pairs_run(directory: pathlib.Path) -> dict:
    doc = json.loads((directory / RESULTS_FILE).read_text())
    days = doc['daily_equity_curve']
    net = [d['daily_return_pct'] / 100.0 for d in days]
    gross = [(d.get('gross_return_pct') or 0.0) / 100.0 for d in days]
    bench = doc.get('benchmarks') or {}
    return {'dates': [d['date'] for d in days], 'net': net, 'gross': gross,
            'trades': (doc.get('overall_performance') or {}).get('total_trades'),
            'vs_gatev': bench.get('sharpe_diff_vs_gatev'),
            'random_control': (bench.get('vs_strategy') or {}),
            'commit': (doc.get('run_config') or {}).get('git_commit')}


def load_residual_run(path: pathlib.Path) -> dict:
    doc = json.loads(path.read_text())
    return {'dates': doc['daily_dates'], 'net': doc['daily_net_returns'],
            'gross': doc.get('daily_gross_returns'), 'trades': doc.get('total_trades'),
            'commit': (doc.get('run_config') or {}).get('git_commit')}


def evaluate(runs: dict) -> dict:
    """runs: {strategy_id: {'net': [...], 'gross': [...], 'trades': n, ...}}."""
    rows = {k: {**describe(v['net'], v.get('gross'), v.get('trades')),
                **{x: v[x] for x in ('vs_gatev', 'random_control', 'commit', 'dates') if x in v}}
            for k, v in runs.items()}
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
    ap.add_argument('--out', default=str(ROOT / 'results' / 'holdout2026' / 'evaluation.json'))
    args = ap.parse_args(argv)
    runs = {}
    for spec in args.pairs:
        sid, directory = spec.split('=', 1)
        runs[sid] = load_pairs_run(pathlib.Path(directory))
    if args.residual:
        runs['avellaneda_lee'] = load_residual_run(pathlib.Path(args.residual))
    report = evaluate(runs)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, allow_nan=False, default=float))
    for k, r in report['strategies'].items():
        print(f"{k:>16}: {r['days']} days, net {r['total_return_pct']:+.2f}%, Sharpe {r['sharpe']:+.2f}, "
              f"t {r['t']:+.2f}, p(one-sided) {r['p_one_sided']:.3f}, Holm p {r['p_holm']:.3f}"
              f"{'  EDGE' if r['edge_out_of_sample'] else ''}")
    print(f"-> {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
