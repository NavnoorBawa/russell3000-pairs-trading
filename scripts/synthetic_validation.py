#!/usr/bin/env python3
"""Known-answer validation of the v32 engine on synthetic markets.

A backtest on real data can only say what a strategy did; it cannot say whether the
code measures what it claims to. This script runs the real engine on markets whose
answer is known in advance (pairs_trading/synthetic.py):

  edge         Planted cointegrated pairs (OU spreads, half-life 5-14 days). A correct
               engine must find a large, positive gross edge here.
  forced_null  The same engine forced to trade correlated pairs whose spread is a
               driftless random walk (leg A = beta * leg B + random walk: not
               cointegrated). There is no edge to find, so the mean gross return per trade must
               be statistically indistinguishable from zero; a significantly positive
               mean means the engine is reading the future (look-ahead). (With the
               edge scenario's +0.03%/day market drift the same pairs gave +2.1 bp,
               t = 0.96 (not significant), against +0.25 bp, t = 0.12, without drift,
               over ~8,300 trades each; driftless, a hedge-ratio error is exposure to
               zero-mean returns.)
  hedge_ratio  The Kalman hedge ratio on planted pairs against the true slope.
  selection    Pair selection on formation data (2020-2022) of a market with planted
               pairs among unrelated names: how many planted pairs are found, how many
               unrelated pairs are admitted; and on a market with NO cointegrated pairs.
               Passes if >= 80% of planted pairs are found and no market admits more than
               5% of its unrelated pairs.

Net results include the full cost model; the gross per-trade statistic is the
look-ahead test because it does not depend on costs. Trades overlap in time, so the
per-trade t-statistic is approximate (it treats trades as independent).

usage: python scripts/synthetic_validation.py [--seeds 5] [--out outputs/synthetic_validation.json]
Runtime: ~45 s per seed on a 4-core CPU. Exit status 0 only if every check passes.
"""
import argparse
import json
import logging
import os
import pathlib
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')       # no progress bars in the report

from pairs_trading.synthetic import build_system, make_market  # noqa: E402

TRADE_RANGE = ('2021-01-01', '2025-12-31')
FORMATION_END = '2022-12-31'


def _trade_stats(trades):
    g = np.array([t['spread_return'] for t in trades], dtype=float)
    if g.size < 2:
        return {'trades': int(g.size), 'mean_gross_bp': float(g.mean() * 1e4) if g.size else None,
                'se_bp': None, 't': None}
    se = g.std(ddof=1) / np.sqrt(g.size)
    return {'trades': int(g.size), 'mean_gross_bp': float(g.mean() * 1e4), 'se_bp': float(se * 1e4),
            't': float(g.mean() / se) if se > 0 else None}


def _backtest(seed, cointegrated, n_pairs=8, drift=0.0003):
    frames, macro, true_beta = make_market(n_pairs=n_pairs, n_noise=0, seed=seed,
                                           cointegrated=cointegrated, drift=drift)
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=TRADE_RANGE)
    return system, res, true_beta


def scenario_edge(seeds):
    rows, betas, trades = [], [], []
    for seed in seeds:
        system, res, true_beta = _backtest(1000 + seed, cointegrated=True)
        trades += res['trades']
        rows.append({'seed': 1000 + seed, 'trades': res['total_trades'],
                     'net_return_pct': round(res['total_return'] * 100, 3),
                     'net_sharpe': round(res['sharpe_ratio'], 3)})
        for (a, b), beta in true_beta.items():
            est = system.get_pair_state(a, b)['beta'].dropna()
            betas.append(abs(float(est.iloc[-252:].median()) - beta))
    pooled = _trade_stats(trades)
    return {'runs': rows, 'pooled_gross_per_trade': pooled,
            'median_net_sharpe': float(np.median([r['net_sharpe'] for r in rows])),
            'hedge_ratio_abs_error_median': float(np.median(betas)),
            'hedge_ratio_abs_error_p90': float(np.percentile(betas, 90)),
            'pass': bool(pooled['t'] is not None and pooled['t'] > 3.0
                         and np.median([r['net_sharpe'] for r in rows]) > 0.5)}


def scenario_forced_null(seeds):
    rows, trades = [], []
    for seed in seeds:
        _, res, _ = _backtest(2000 + seed, cointegrated=False, n_pairs=10, drift=0.0)
        trades += res['trades']
        rows.append({'seed': 2000 + seed, 'trades': res['total_trades'],
                     'net_return_pct': round(res['total_return'] * 100, 3),
                     'net_sharpe': round(res['sharpe_ratio'], 3)})
    pooled = _trade_stats(trades)
    # look-ahead would show up as a significantly POSITIVE gross mean
    return {'runs': rows, 'pooled_gross_per_trade': pooled,
            'pass': bool(pooled['t'] is None or pooled['t'] < 2.5)}


def scenario_selection(seeds):
    from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
    from pairs_trading.pair_selector import FixedPrimeFundPairSelector
    proc = EnhancedRussell3000DataProcessor.__new__(EnhancedRussell3000DataProcessor)
    out = []
    for seed in seeds:
        for cointegrated in (True, False):
            frames, _, true_beta = make_market(n_pairs=6, n_noise=12, seed=3000 + seed,
                                               cointegrated=cointegrated, end=FORMATION_END)
            data = {s: proc._process_indicators(df) for s, df in frames.items()}
            selector = FixedPrimeFundPairSelector()
            found = set(selector.find_quality_pairs(data))
            planted = set(true_beta) if cointegrated else set()
            n_syms = len(data)
            out.append({'seed': 3000 + seed, 'market': 'planted' if cointegrated else 'no_cointegration',
                        'pairs_tested': n_syms * (n_syms - 1) // 2,
                        'planted': len(planted), 'planted_found': len(found & planted),
                        'other_pairs_selected': len(found - planted)})
    planted_rows = [r for r in out if r['market'] == 'planted']
    null_rows = [r for r in out if r['market'] == 'no_cointegration']
    recall = sum(r['planted_found'] for r in planted_rows) / max(1, sum(r['planted'] for r in planted_rows))
    worst_fp_rate = max(r['other_pairs_selected'] / max(1, r['pairs_tested'] - r['planted']) for r in out)
    return {'runs': out, 'planted_recall': recall,
            'unrelated_pairs_selected_per_planted_market':
                float(np.mean([r['other_pairs_selected'] for r in planted_rows])),
            'pairs_selected_per_null_market': float(np.mean([r['other_pairs_selected'] for r in null_rows])),
            'worst_market_false_positive_rate': worst_fp_rate,
            'pass': bool(recall >= 0.8 and worst_fp_rate <= 0.05)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--seeds', type=int, default=5, help='independent markets per scenario')
    ap.add_argument('--out', default=str(ROOT / 'outputs' / 'synthetic_validation.json'))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    os.environ['PAIRS_USE_TRANSFORMER'] = '0'     # the classical engine; the ranker is tested separately
    seeds = list(range(args.seeds))
    t0 = time.time()
    report = {
        'edge': scenario_edge(seeds),
        'forced_null': scenario_forced_null(seeds),
        'selection': scenario_selection(seeds),
    }
    report['all_pass'] = all(v['pass'] for v in report.values() if isinstance(v, dict))
    report['seeds'] = args.seeds
    report['trade_range'] = list(TRADE_RANGE)
    report['elapsed_s'] = round(time.time() - t0, 1)

    e, n, s = report['edge'], report['forced_null'], report['selection']
    pe, pn = e['pooled_gross_per_trade'], n['pooled_gross_per_trade']
    print(f"edge         {pe['trades']:5d} trades | gross {pe['mean_gross_bp']:+.1f} bp/trade "
          f"(t {pe['t']:.1f}) | median net Sharpe {e['median_net_sharpe']:+.2f} | "
          f"{'PASS' if e['pass'] else 'FAIL'}")
    print(f"hedge ratio  |beta_hat - beta| median {e['hedge_ratio_abs_error_median']:.3f}, "
          f"90th pct {e['hedge_ratio_abs_error_p90']:.3f}")
    nt = 'n/a' if pn['t'] is None else f"{pn['t']:+.2f}"
    nm = 'n/a' if pn['mean_gross_bp'] is None else f"{pn['mean_gross_bp']:+.1f}"
    print(f"forced null  {pn['trades']:5d} trades | gross {nm} bp/trade (t {nt}) | "
          f"{'PASS' if n['pass'] else 'FAIL'} (look-ahead would give a large positive t)")
    print(f"selection    planted-pair recall {s['planted_recall']:.0%} | unrelated pairs admitted "
          f"{s['unrelated_pairs_selected_per_planted_market']:.1f}/market (planted), "
          f"{s['pairs_selected_per_null_market']:.1f}/market (none planted), worst "
          f"{s['worst_market_false_positive_rate']:.1%} | {'PASS' if s['pass'] else 'FAIL'}")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False))
    os.replace(tmp, out)
    print(f"{'ALL PASS' if report['all_pass'] else 'FAILURES'} in {report['elapsed_s']} s -> {out}")
    return 0 if report['all_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
