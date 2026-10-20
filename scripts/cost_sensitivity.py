#!/usr/bin/env python3
"""Cost robustness of the main backtest: impact coefficient, borrow stress, fund size.

The headline cost assumptions were fixed before any run (study_config, transaction_costs).
This script re-runs the SAME study (same pairs, same schedule, same signals) under cost
scenarios fixed in advance and reports each one's net result. It is a robustness check,
not an optimisation: no scenario feeds back into the design.

  impact     square-root coefficient Y in {0.3 (headline), 0.6, 1.0}: Goyal-Jegadeesh-Wu
             (2025) NYSE / Nasdaq closing-auction estimates and continuous-market levels
             (Kyle-Obizhaeva 2016 ~0.6, Toth et al. 2011 "of order one")
  borrow     every short pays 1% or 3% a year (the median buy-side fee is 0.38%; 3% is
             about the 90th percentile, Muravyev-Pearson-Pollet 2025, Table 1)
  capacity   initial capital $10M / $100M (headline) / $1B / $5B: positions scale with
             equity, so participation and therefore square-root impact grow with size

Each scenario is an exact re-run of the main backtest (costs enter the equity path, so
a linear rescaling of logged costs would only approximate it).

usage: python scripts/cost_sensitivity.py [--profile v33] [--calendar dev] [--out FILE]
"""
import argparse
import json
import logging
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('MPLBACKEND', 'Agg')
os.environ.setdefault('TQDM_DISABLE', '1')

SCENARIOS = (
    # (group, label, cost-model attributes, initial capital)
    ('impact', 'Y=0.3', {'market_impact_coefficient': 0.3}, None),
    ('impact', 'Y=0.6', {'market_impact_coefficient': 0.6}, None),
    ('impact', 'Y=1.0', {'market_impact_coefficient': 1.0}, None),
    ('borrow', 'borrow 1%', {'gc_borrow_rate': 0.01}, None),
    ('borrow', 'borrow 3%', {'gc_borrow_rate': 0.03}, None),
    ('capacity', '$10M', {}, 1e7),
    ('capacity', '$1B', {}, 1e9),
    ('capacity', '$5B', {}, 5e9),
)
log = logging.getLogger('cost_sensitivity')


def _summary(res: dict) -> dict:
    trades = res['trades']
    return {'total_return_pct': round(res['total_return'] * 100, 4),
            'sharpe': round(res['sharpe_ratio'], 4), 'trades': res['total_trades'],
            'max_drawdown_pct': round(res['max_drawdown'] * 100, 4),
            'total_cost_pct_of_capital': round(res['total_cost_impact_pct'] * 100, 4),
            'avg_max_leg_adv_participation_pct': round(res.get('avg_max_leg_adv_participation', 0.0) * 100, 4),
            'mean_cost_bp_of_gross_notional': round(
                1e4 * sum(t['transaction_costs'] for t in trades)
                / max(sum(t['position_size'] for t in trades), 1e-9), 3) if trades else None}


def run(profile: str, calendar: str, system=None) -> dict:
    """All scenarios on one prepared study (`system`: a loaded system, for tests)."""
    if system is None:
        from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
        system = CompleteFixedRussell3000TradingSystem(profile=profile, calendar=calendar)
        system.load_study_data()
    test_spreads, windows, last = system.prepare_study()
    rng = (system.calendar.backtest_start, last)
    base_capital = system.initial_capital
    cm = system.cost_model
    headline = {'market_impact_coefficient': cm.market_impact_coefficient,
                'gc_borrow_rate': cm.gc_borrow_rate, 'initial_capital': base_capital}
    out = {'profile': system.profile.name, 'calendar': system.calendar.name, 'headline': headline,
           'scenarios': []}
    for group, label, attrs, capital in (('headline', 'headline', {}, None),) + SCENARIOS:
        saved = {k: getattr(cm, k) for k in attrs}
        for k, v in attrs.items():
            setattr(cm, k, v)
        if capital is not None:
            system.initial_capital = capital
        t0 = time.time()
        try:
            res = system.run_comprehensive_backtest(test_spreads, pair_windows=windows, date_range=rng)
        finally:
            for k, v in saved.items():
                setattr(cm, k, v)
            system.initial_capital = base_capital
        row = {'group': group, 'label': label, 'cost_model': attrs, 'initial_capital': capital or base_capital,
               **_summary(res), 'seconds': round(time.time() - t0, 1)}
        out['scenarios'].append(row)
        log.warning(f"{label:>10}: return {row['total_return_pct']:+.3f}%, Sharpe {row['sharpe']:+.2f}, "
                    f"{row['trades']} trades, costs {row['total_cost_pct_of_capital']:.3f}% of capital")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--profile', default='v33')
    ap.add_argument('--calendar', default='dev')
    ap.add_argument('--out', default=None, help='default: outputs/cost_sensitivity.json')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    report = run(args.profile, args.calendar)
    out = pathlib.Path(args.out or ROOT / 'outputs' / 'cost_sensitivity.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, allow_nan=False))
    log.warning(f"-> {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
