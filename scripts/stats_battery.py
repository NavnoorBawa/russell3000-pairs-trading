#!/usr/bin/env python3
"""Power, hurdles, deflated Sharpe and data-snooping tests on a finished study run.

Reads the study's JSON exports and reports, for the main-backtest daily returns:

  * the power report (pairs_trading.power.power_report): critical and minimum
    detectable Sharpe, power against SR 0.5 / 1 / 1.5 / 2, minimum track record, the
    one-sided upper confidence bound, tests of SR >= x and Bayes factors;
  * the Sharpe ratios needed to clear the HLZ, Chordia-Goyal-Saretto and Bonferroni
    t-ratio hurdles at the run's length, with IID returns and with the run's lag-1
    autocorrelation (AR(1) long-run variance);
  * the Deflated Sharpe Ratio as a function of the number of trials;

and, for a family of daily return series on common dates, Hansen's SPA and White's
Reality Check against zero and against the Gatev baseline, the Romano-Wolf stepdown,
the Model Confidence Set on volatility-normalised losses, and the effective number of
trials. The family is a CSV given with --family (dates in the first column, one column
per declared variant), or else the series the exports already hold: the strategy, the
Gatev distance method, the random-pair control mean and the fund-cost replays. The
replays re-cost the strategy's own trades, so that default family illustrates the
mechanics; it is not a declared variant family.

usage:
  python scripts/stats_battery.py                                 # outputs/ of the last run
  python scripts/stats_battery.py --results outputs_headline/pairs_trading_results_2023_2025_unbiased.json \\
      --funds outputs_headline/fund_type_comparison.json
  python scripts/stats_battery.py --family outputs/variant_daily_returns.csv --reps 10000

Writes outputs/stats_battery.json (--out). Deterministic given --seed.
"""
import argparse
import json
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading.json_export import _atomic_write_json  # noqa: E402
from pairs_trading.power import power_report  # noqa: E402
from pairs_trading.significance import (  # noqa: E402
    dsr_curve, effective_number_of_trials, sharpe_hurdles,
)
from pairs_trading.snooping import (  # noqa: E402
    model_confidence_set, romano_wolf, sharpe_losses, spa_test,
)

DSR_TRIALS = (1, 2, 5, 10, 27, 32, 100, 300, 1000)


def _series(values, dates) -> pd.Series:
    s = pd.Series([float('nan') if v is None else float(v) for v in values],
                  index=pd.Index([str(d)[:10] for d in dates]))
    return s[~s.index.duplicated(keep='last')]


def load_published_series(results_path, funds_path=None) -> pd.DataFrame:
    """Daily returns (decimal) of the strategy and the baselines in the study exports."""
    with open(results_path) as fh:
        res = json.load(fh)
    curve = res['daily_equity_curve']
    cols = {'strategy': _series([r['daily_return_pct'] / 100.0 for r in curve], [r['date'] for r in curve])}
    bench = res.get('benchmarks') or {}
    gatev = bench.get('distance_method') or {}
    if gatev.get('daily_returns'):
        cols['gatev'] = _series(gatev['daily_returns'], gatev['daily_dates'])
    rnd = bench.get('random_control') or {}
    if rnd.get('mean_daily_returns'):
        cols['random_mean'] = _series(rnd['mean_daily_returns'], rnd['daily_dates'])
    if funds_path is not None and pathlib.Path(funds_path).exists():
        with open(funds_path) as fh:
            funds = json.load(fh)
        for name, prof in (funds.get('equity_curves') or {}).items():
            value = _series([p['value'] for p in prof['curve']], [p['date'] for p in prof['curve']])
            cols[f'fund_{name}'] = value.pct_change(fill_method=None)
    return pd.DataFrame(cols).sort_index()


def run_battery(strategy: pd.Series, family: pd.DataFrame, n_tests: int = 32, reps: int = 10_000,
                seed: int = 42, benchmark: str = 'gatev') -> dict:
    """The full battery; `family` rows with a missing value in any column are dropped."""
    r = strategy.dropna()
    power = power_report(r.to_numpy())
    out = {
        'power': power,
        'hurdles': sharpe_hurdles(len(r), n_tests),
        'hurdles_ar1': sharpe_hurdles(len(r), n_tests, rho=power['rho']),
        'dsr_curve': dsr_curve(r.to_numpy(), DSR_TRIALS),
    }
    fam = family.dropna()
    out['family'] = {
        'members': list(fam.columns), 'n_days': int(len(fam)),
        'first_day': fam.index[0], 'last_day': fam.index[-1],
        'effective_trials': effective_number_of_trials(fam),
        'spa_vs_zero': spa_test(fam, reps=reps, seed=seed),
        'romano_wolf_vs_zero': _stepdown_records(romano_wolf(fam, reps=reps, seed=seed)),
        'mcs': model_confidence_set(sharpe_losses(fam), size=0.10, method='R', reps=reps, seed=seed),
    }
    if benchmark in fam.columns and fam.shape[1] > 1:
        others = fam.drop(columns=benchmark)
        out['family'][f'spa_vs_{benchmark}'] = spa_test(others, benchmark=fam[benchmark].to_numpy(),
                                                       reps=reps, seed=seed)
    return out


def _stepdown_records(rw: dict) -> dict:
    rw = dict(rw)
    rw['table'] = rw['table'].reset_index().to_dict(orient='records')
    return rw


def _summary(out: dict) -> str:
    p = out['power']
    alts = {a['sr_ann']: a for a in p['alternatives']}
    lines = [
        f"main backtest: T={p['n']}  SR={p['sr_ann']:+.2f}  se={p['se_ann']:.2f}  rho={p['rho']:.3f}",
        f"  critical SR {p['critical_sr_ann']:.2f} | MDE (80%) {p['min_detectable_sr_ann']:.2f} | "
        f"one-sided 95% upper bound {p['upper_bound_ann']:.2f}",
        "  " + " | ".join(f"SR {x:g}: power {a['power']:.2f}, p(SR>=x) {a['p_sr_at_least']:.3f}, "
                          f"BF {a['bayes_factor_null_vs_alt']:.1f}" for x, a in alts.items()),
        "  hurdles (IID): " + ", ".join(f"{k} {v['sr_ann']:.2f}" for k, v in out['hurdles']['hurdles'].items()),
        "  hurdles (AR(1)): " + ", ".join(f"{k} {v['sr_ann']:.2f}"
                                          for k, v in out['hurdles_ar1']['hurdles'].items()),
    ]
    fam = out['family']
    spa = fam['spa_vs_zero']
    lines += [
        f"family ({len(fam['members'])} series, {fam['n_days']} days, block {spa['block']}): "
        f"effective rank {fam['effective_trials']['effective_rank']:.2f}",
        f"  SPA vs zero: {spa['pvalues']} | Reality Check {spa['reality_check']['pvalue']:.3f}",
    ]
    for key in [k for k in fam if k.startswith('spa_vs_') and k != 'spa_vs_zero']:
        lines.append(f"  SPA {key[4:].replace('_', ' ')}: {fam[key]['pvalues']} | "
                     f"Reality Check {fam[key]['reality_check']['pvalue']:.3f}")
    lines += [
        f"  Romano-Wolf rejected: {fam['romano_wolf_vs_zero']['rejected']}",
        f"  MCS 90% (Sharpe losses): {fam['mcs']['included']}",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--results', default=str(ROOT / 'outputs' / 'pairs_trading_results_2023_2025_unbiased.json'))
    ap.add_argument('--funds', default=str(ROOT / 'outputs' / 'fund_type_comparison.json'))
    ap.add_argument('--family', help='CSV of daily returns: dates in the first column, one column per variant')
    ap.add_argument('--benchmark', default='gatev', help='family column used as the SPA benchmark')
    ap.add_argument('--n-tests', type=int, default=32, help='trials for the Bonferroni hurdle')
    ap.add_argument('--reps', type=int, default=10_000)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out', default=str(ROOT / 'outputs' / 'stats_battery.json'))
    args = ap.parse_args(argv)

    published = load_published_series(args.results, args.funds)
    family = published
    if args.family:
        family = pd.read_csv(args.family, index_col=0)
        family.index = [str(d)[:10] for d in family.index]
    out = run_battery(published['strategy'], family, n_tests=args.n_tests, reps=args.reps,
                      seed=args.seed, benchmark=args.benchmark)
    out['inputs'] = {'results': args.results, 'funds': args.funds, 'family': args.family,
                     'reps': args.reps, 'seed': args.seed}
    _atomic_write_json(out, args.out)
    print(_summary(out))
    print(f"wrote {args.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
