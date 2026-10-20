#!/usr/bin/env python3
"""Run the declared variant family and the data-snooping tests on it.

The family is declared in results/variant_family/declaration.json BEFORE anything is run:
a 3 x 3 x 3 grid of the hand-set trading thresholds around the base profile plus one-at-a-
time toggles of the design switches that earlier versions tried on this same data. Each
variant is the base study with only its declared change; its main-backtest daily net
returns form one column of a T x K matrix, which feeds

  * Hansen (2005) SPA and White (2000) Reality Check: does ANY variant beat the benchmark?
  * Romano-Wolf stepdown: WHICH variants, if any, with familywise error control?
  * the Hansen-Lunde-Nason model confidence set: which variants are indistinguishable
    from the best?
  * PBO by CSCV, and the deflated Sharpe ratio with an effective number of trials.

Benchmarks: zero (cash: returns are excess of cash) and the Gatev distance method's daily
series from the base run. Nothing here re-chooses the primary design.

Variants that change only trading rules share one prepared study (pair selection,
re-selection schedule); variants that change selection re-run it.

usage:
  python scripts/variant_family.py run       [--out results/variant_family] [--only NAME ...]
  python scripts/variant_family.py analyse   --base-run DIR [--out results/variant_family] [--reps 10000]

`analyse` reads the family matrix written by `run` and the base run's exports (DIR: its
results JSON, for the Gatev benchmark series, and its cost-schedule JSON) and writes
snooping.json: scripts/stats_battery.py's battery on the family plus PBO by CSCV.
"""
import argparse
import dataclasses
import itertools
import json
import logging
import os
import pathlib
import sys
import time

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

DECLARATION = ROOT / 'results' / 'variant_family' / 'declaration.json'
# Profile fields that change which pairs are selected (a variant changing one re-runs selection).
SELECTION_FIELDS = ('universe', 'max_universe', 'same_industry', 'reselect', 'reselect_every',
                    'formation_calendar_days')
log = logging.getLogger('variant_family')


def variants(decl: dict) -> list:
    """The declared variants, in a fixed order: the grid first, then the toggles."""
    grid = decl['grid']
    names = [k for k in grid if k != 'why']
    out = []
    for values in itertools.product(*(grid[n] for n in names)):
        engine = dict(zip(names, values))
        out.append({'name': 'grid ' + ' '.join(f'{k}={v}' for k, v in engine.items()),
                    'engine': engine, 'profile': {}, 'env': {}})
    for t in decl['toggles']:
        out.append({'name': t['name'], 'engine': t.get('engine', {}),
                    'profile': t.get('profile', {}), 'env': t.get('env', {})})
    return out


def _selection_key(profile) -> tuple:
    return tuple(getattr(profile, f) for f in SELECTION_FIELDS)


def run(out_dir: pathlib.Path, only=None) -> None:
    from pairs_trading.study_config import get_calendar, get_profile
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem

    decl = json.loads(DECLARATION.read_text())
    base_profile = get_profile(decl['base']['profile'])
    calendar = get_calendar(decl['base']['calendar'])
    todo = [v for v in variants(decl) if not only or v['name'] in only]
    groups = {}                           # selection key -> variants sharing one prepared study
    for v in todo:
        groups.setdefault(_selection_key(dataclasses.replace(base_profile, **v['profile'])), []).append(v)
    loaded = None                         # price/macro data are loaded once and shared
    series, rows = {}, []
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, group in groups.items():
        group_profile = dataclasses.replace(base_profile, **group[0]['profile'])
        system = CompleteFixedRussell3000TradingSystem(profile=group_profile, calendar=calendar)
        if loaded is None:
            system.load_study_data()
            loaded = system
        else:
            system.share_loaded_data(loaded)
        test_spreads, windows, last = system.prepare_study()
        prepared_profile, prepared_ranker = system.profile, system.rl_agent
        for v in group:
            profile = dataclasses.replace(base_profile, **v['profile'])
            system.profile = profile
            if profile.ranker != prepared_profile.ranker:
                system.rl_agent = system._new_ranker()
                system._train_ranker(system.rl_agent, list(system.spread_data),
                                     end=calendar.model_train_end)
            saved_env = {k: os.environ.get(k) for k in v['env']}
            os.environ.update(v['env'])
            for k, val in v['engine'].items():
                setattr(system, k, val)                # instance attribute shadows the class default
            t0 = time.time()
            try:
                res = system.run_comprehensive_backtest(test_spreads, pair_windows=windows,
                                                        date_range=(calendar.backtest_start, last))
            finally:
                for k in v['engine']:
                    delattr(system, k)
                for k, val in saved_env.items():
                    if val is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = val
                system.profile, system.rl_agent = prepared_profile, prepared_ranker
            series[v['name']] = pd.Series(res['daily_returns'], index=pd.to_datetime(res['daily_dates']))
            rows.append({'name': v['name'], 'sharpe': round(res['sharpe_ratio'], 4),
                         'total_return_pct': round(res['total_return'] * 100, 4),
                         'trades': res['total_trades'],
                         'max_drawdown_pct': round(res['max_drawdown'] * 100, 4),
                         'days': len(res['daily_returns']), 'seconds': round(time.time() - t0, 1)})
            log.warning(f"{v['name']}: Sharpe {res['sharpe_ratio']:+.2f}, {res['total_trades']} trades")
    matrix = pd.DataFrame(series).sort_index().fillna(0.0)
    matrix.index = matrix.index.strftime('%Y-%m-%d')
    matrix.to_csv(out_dir / 'daily_returns.csv', float_format='%.10g', index_label='date')
    (out_dir / 'runs.json').write_text(json.dumps({'base': decl['base'], 'variants': rows}, indent=1))
    log.warning(f"{len(rows)} variants -> {out_dir / 'daily_returns.csv'}")


def analyse(out_dir: pathlib.Path, base_run: pathlib.Path, reps: int = 10_000, seed: int = 42) -> dict:
    """The data-snooping battery on the declared family (see the module docstring)."""
    import importlib.util
    from pairs_trading.significance import pbo_cscv
    spec = importlib.util.spec_from_file_location('stats_battery', ROOT / 'scripts' / 'stats_battery.py')
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    family = pd.read_csv(out_dir / 'daily_returns.csv', index_col=0)
    family.index = [str(d)[:10] for d in family.index]
    published = sb.load_published_series(base_run / 'pairs_trading_results_2023_2025_unbiased.json',
                                         base_run / 'fund_type_comparison.json')
    report = sb.run_battery(published['strategy'], family, n_tests=family.shape[1], reps=reps,
                            seed=seed, benchmark='gatev', benchmark_series=published.get('gatev'))
    try:
        report['pbo'] = pbo_cscv(family.to_numpy(), n_splits=10)
    except ValueError as e:
        report['pbo'] = {'error': str(e)}
    report['declared_family'] = {'declaration': str(DECLARATION.relative_to(ROOT)), 'variants': list(family.columns),
                        'days': int(len(family)), 'base_run': str(base_run)}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('command', choices=('run', 'analyse'))
    ap.add_argument('--out', default=str(ROOT / 'results' / 'variant_family'))
    ap.add_argument('--only', nargs='*', help='run only these variant names (debugging)')
    ap.add_argument('--base-run', help='analyse: the base run\'s export directory')
    ap.add_argument('--reps', type=int, default=10_000)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    out = pathlib.Path(args.out)
    if args.command == 'run':
        run(out, only=args.only)
    else:
        if not args.base_run:
            ap.error('analyse needs --base-run')
        report = analyse(out, pathlib.Path(args.base_run), reps=args.reps)
        (out / 'snooping.json').write_text(json.dumps(report, indent=1, allow_nan=False, default=float))
    return 0


if __name__ == '__main__':
    sys.exit(main())
