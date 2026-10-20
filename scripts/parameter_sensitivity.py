#!/usr/bin/env python3
"""Parameter sensitivity and Probability of Backtest Overfitting (PBO) for the main backtest.

The trading rule has three hand-set thresholds — entry |z| (ENTRY_Z = 1.8), profit
target |z| (EXIT_Z = 0.5) and stop distance (STOP_Z = 1.5) — chosen across versions on
the same 2020-2025 data the study reports. This script re-runs the main backtest
(classical ranking, PAIRS_USE_TRANSFORMER=0) on the SAME universe and re-selection
schedule for every combination of a grid around those values and reports:

  * each configuration's Sharpe, return, trades and max drawdown;
  * where the shipped configuration ranks among them (a sharp optimum that its
    neighbours do not share is a warning sign);
  * PBO by combinatorially symmetric cross-validation (Bailey, Borwein, Lopez de Prado
    & Zhu 2017): how often the configuration that is best in one half of the period
    ranks at or below the median in the other half. Near 0: picking the best
    configuration generalises; near 0.5 or above: the "best" is noise.

usage:
  python scripts/parameter_sensitivity.py                 # study data (data/ as for main)
  python scripts/parameter_sensitivity.py --synthetic     # hermetic demo on a synthetic market
  python scripts/parameter_sensitivity.py --grid quick    # 2 x 1 x 2 grid instead of 3 x 3 x 3

Writes outputs/parameter_sensitivity.json. On the study data each configuration is one
main-backtest run (minutes each); the Kalman states are computed once and shared.
"""
import argparse
import itertools
import json
import logging
import os
import pathlib
import pickle
import sys
import tempfile
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

GRIDS = {
    'full': {'ENTRY_Z': [1.5, 1.8, 2.1], 'EXIT_Z': [0.25, 0.5, 0.75], 'STOP_Z': [1.0, 1.5, 2.0]},
    'quick': {'ENTRY_Z': [1.8, 2.1], 'EXIT_Z': [0.5], 'STOP_Z': [1.5, 2.0]},
}
SHIPPED = {'ENTRY_Z': 1.8, 'EXIT_Z': 0.5, 'STOP_Z': 1.5}


def _write_synthetic_inputs(root: pathlib.Path) -> None:
    from pairs_trading.synthetic import make_market
    frames, macro, _ = make_market(n_pairs=6, n_noise=6, seed=21)
    (root / 'data').mkdir(parents=True, exist_ok=True)
    with open(root / 'data' / 'enhanced_russell_3000_data.pkl', 'wb') as f:
        pickle.dump(frames, f)
    with open(root / 'data' / 'macro_data.pkl', 'wb') as f:
        pickle.dump(macro, f)
    pd.DataFrame({'Symbol': sorted(frames)}).to_csv(root / 'data' / 'marketcap.csv', index=False)


def run_grid(grid: dict, n_splits: int = 10) -> dict:
    from pairs_trading.significance import pbo_cscv
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem

    system = CompleteFixedRussell3000TradingSystem()
    system.load_study_data()
    test_spreads, pair_windows, last_test = system.prepare_study()

    names = list(grid)
    configs = [dict(zip(names, values)) for values in itertools.product(*(grid[n] for n in names))]
    rows, series = [], {}
    for cfg in configs:
        for k, v in cfg.items():
            setattr(system, k, v)                      # instance attributes shadow the class defaults
        t0 = time.time()
        res = system.run_comprehensive_backtest(test_spreads, pair_windows=pair_windows,
                                                date_range=(system.calendar.backtest_start, last_test))
        label = ' '.join(f'{k}={v}' for k, v in cfg.items())
        series[label] = pd.Series(res['daily_returns'], index=pd.to_datetime(
            [str(pd.Timestamp(d).date()) for d in res['daily_dates']]), dtype=float)
        rows.append({**cfg, 'label': label, 'sharpe': round(res['sharpe_ratio'], 3),
                     'total_return_pct': round(res['total_return'] * 100, 3),
                     'trades': res['total_trades'], 'max_drawdown_pct': round(res['max_drawdown'] * 100, 3),
                     'seconds': round(time.time() - t0, 1)})
        logging.getLogger(__name__).warning(f"{label}: Sharpe {rows[-1]['sharpe']:+.2f}, "
                                            f"{rows[-1]['trades']} trades")
    for k in names:                                    # restore the class defaults
        if k in system.__dict__:
            delattr(system, k)

    # Days a configuration was flat (e.g. its run-off ended earlier) have zero return.
    matrix = pd.DataFrame(series).sort_index().fillna(0.0)
    ranked = sorted(rows, key=lambda r: -r['sharpe'])
    shipped_label = ' '.join(f'{k}={SHIPPED[k]}' for k in names) if all(
        SHIPPED[k] in grid[k] for k in names) else None
    shipped_rank = next((i + 1 for i, r in enumerate(ranked) if r['label'] == shipped_label), None)
    out = {'grid': grid, 'n_configurations': len(configs), 'n_days': int(len(matrix)),
           'configurations': ranked, 'shipped': shipped_label, 'shipped_rank_by_sharpe': shipped_rank,
           'sharpe_range': [ranked[-1]['sharpe'], ranked[0]['sharpe']]}
    try:
        out['pbo'] = pbo_cscv(matrix.to_numpy(), n_splits=n_splits)
    except ValueError as e:
        out['pbo'] = {'error': str(e)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--grid', choices=sorted(GRIDS), default='full')
    ap.add_argument('--splits', type=int, default=10, help='CSCV blocks (even)')
    ap.add_argument('--synthetic', action='store_true',
                    help='run on a synthetic market in a temporary directory (no data needed)')
    ap.add_argument('--out', default=str(ROOT / 'outputs' / 'parameter_sensitivity.json'))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    os.environ['PAIRS_USE_TRANSFORMER'] = '0'
    out_path = pathlib.Path(args.out).resolve()

    cwd = os.getcwd()
    tmp = tempfile.TemporaryDirectory() if args.synthetic else None
    try:
        if tmp is not None:
            _write_synthetic_inputs(pathlib.Path(tmp.name))
            os.chdir(tmp.name)
        report = run_grid(GRIDS[args.grid], n_splits=args.splits)
    finally:
        os.chdir(cwd)
        if tmp is not None:
            tmp.cleanup()
    report['data'] = 'synthetic' if args.synthetic else 'study'

    print(f"{'configuration':<36}{'Sharpe':>8}{'return %':>10}{'trades':>8}{'maxDD %':>9}")
    for r in report['configurations']:
        mark = '  <- shipped' if r['label'] == report['shipped'] else ''
        print(f"{r['label']:<36}{r['sharpe']:>+8.2f}{r['total_return_pct']:>+10.2f}{r['trades']:>8d}"
              f"{r['max_drawdown_pct']:>9.2f}{mark}")
    pbo = report['pbo']
    if 'pbo' in pbo:
        print(f"PBO {pbo['pbo']:.2f} over {pbo['n_combinations']} CSCV splits "
              f"(shipped configuration ranks {report['shipped_rank_by_sharpe']} of "
              f"{report['n_configurations']} by full-period Sharpe)")
    else:
        print(f"PBO not computed: {pbo['error']}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_suffix('.json.tmp')
    tmp_out.write_text(json.dumps(report, indent=2, allow_nan=False))
    os.replace(tmp_out, out_path)
    print(f"-> {out_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
