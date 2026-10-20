"""The evidence layer (pairs_trading/evidence.py) on hand-computable inputs."""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.evidence import (
    COST_MULTIPLES, build_evidence, factor_block, gross_and_costs, headline_evidence,
    power_and_hurdles,
)
from pairs_trading.significance import annualized_sharpe


def _trades():
    # (spread return per $ notional, notional, cost $): gross $ = spread x notional
    rows = [(0.010, 1e6, 600.0), (-0.004, 2e6, 1000.0), (0.002, 1e6, 500.0)]
    return [{'spread_return': s, 'position_size': n, 'transaction_costs': c,
             'pnl_dollar': s * n - c} for s, n, c in rows]


def test_per_trade_gross_edge_and_break_even_cost_multiple():
    out = gross_and_costs({'trades': _trades()})['per_trade']
    gross = 0.010 * 1e6 - 0.004 * 2e6 + 0.002 * 1e6          # +4,000 $
    costs = 600.0 + 1000.0 + 500.0
    assert out['gross_usd'] == pytest.approx(gross) and out['cost_usd'] == pytest.approx(costs)
    assert out['net_usd'] == pytest.approx(gross - costs)
    assert out['breakeven_cost_multiple'] == pytest.approx(gross / costs)
    s = np.array([0.010, -0.004, 0.002])
    assert out['gross_bp'] == pytest.approx(s.mean() * 1e4)
    assert out['gross_t'] == pytest.approx(s.mean() / (s.std(ddof=1) / np.sqrt(3)))
    assert out['cost_bp'] == pytest.approx(np.mean([600 / 1e6, 1000 / 2e6, 500 / 1e6]) * 1e4)


def test_cost_curve_rescales_only_the_costs():
    rng = np.random.default_rng(1)
    g = rng.normal(0.0004, 0.005, 300)
    c = np.abs(rng.normal(0.0002, 0.0001, 300))
    out = gross_and_costs({'daily_gross_returns': list(g), 'daily_cost_returns': list(c)})
    curve = {row['cost_multiple']: row for row in out['cost_curve']}
    assert sorted(curve) == list(COST_MULTIPLES)
    assert curve[0.0]['sharpe'] == pytest.approx(annualized_sharpe(g)) == pytest.approx(out['gross_daily']['sharpe'])
    assert curve[1.0]['sharpe'] == pytest.approx(annualized_sharpe(g - c))
    assert curve[2.0]['total_return_pct'] == pytest.approx((np.prod(1 + g - 2 * c) - 1) * 100)
    assert curve[0.0]['sharpe'] > curve[1.0]['sharpe'] > curve[2.0]['sharpe']


def test_power_and_hurdles_use_the_runs_length_and_trial_count():
    rng = np.random.default_rng(2)
    r = rng.normal(0.0, 0.01, 600)
    out = power_and_hurdles({'daily_returns': list(r),
                             'walk_forward_daily': {'dates': [], 'returns': list(r[:400])}}, n_trials=32)
    assert out['main']['n'] == 600 and out['walk_forward_oos']['n'] == 400
    assert out['main']['min_detectable_sr_ann'] < out['walk_forward_oos']['min_detectable_sr_ann']
    assert out['main']['upper_bound_ann'] > out['main']['sr_ann']
    assert out['hurdles']['n_obs'] == 600 and out['hurdles']['n_tests'] == 32
    rho = out['main']['rho']
    hlz = 3.0 * np.sqrt(252 / 600) * np.sqrt((1 + rho) / (1 - rho))
    assert out['hurdles']['hurdles']['hlz']['sr_ann'] == pytest.approx(hlz)
    assert power_and_hurdles({'daily_returns': [0.001] * 10}, n_trials=1) == {}   # too short


def _factors(n=500, seed=3):
    idx = pd.bdate_range('2023-07-03', periods=n)
    rng = np.random.default_rng(seed)
    f = pd.DataFrame(rng.normal(0, 0.008, (n, 8)), index=idx,
                     columns=['Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom', 'ST_Rev', 'LT_Rev'])
    f['RF'] = 0.0002
    return f


def test_factor_attribution_finds_a_planted_reversal_loading_and_cash():
    f = _factors()
    rng = np.random.default_rng(4)
    excess = 0.5 * f['ST_Rev'].to_numpy() + rng.normal(0, 0.002, len(f))
    total = excess + f['RF'].to_numpy()                      # the engine reports total returns
    dates = [d.date().isoformat() for d in f.index[:-20]] + ['2099-01-02']   # one day past the data
    rets = list(total[:-20]) + [0.0]
    out = factor_block({'daily_dates': dates, 'daily_returns': rets}, f, {'vintage': '202608'})
    main = out['main']
    assert main['factors']['ST_Rev']['beta'] == pytest.approx(0.5, abs=0.03)
    assert abs(main['factors']['Mom']['beta']) < 0.05 and abs(main['alpha_tstat']) < 3
    assert main['days_after_factor_data'] == 1
    assert out['cash']['tbill_return_pct'] == pytest.approx(((1.0002) ** (len(f) - 20) - 1) * 100)
    assert out['source'] == {'vintage': '202608'}


def test_evidence_without_factor_data_says_why_and_headline_picks_the_numbers():
    rng = np.random.default_rng(5)
    g = rng.normal(0.0002, 0.005, 300)
    c = np.full(300, 0.0001)
    res = {'daily_returns': list(g - c), 'daily_gross_returns': list(g), 'daily_cost_returns': list(c),
           'trades': _trades()}
    ev = build_evidence(res, n_trials=32, factors=None, factor_error='offline, no cache')
    assert ev['factors'] == {'unavailable': 'offline, no cache'} and ev['n_trials'] == 32
    h = headline_evidence(ev)
    assert h['main_min_detectable_sharpe'] == ev['main']['min_detectable_sr_ann']
    assert h['breakeven_cost_multiple'] == ev['per_trade']['breakeven_cost_multiple']
    assert h['sharpe_at_zero_cost'] == pytest.approx(annualized_sharpe(g))
    assert h['factor_alpha_t'] is None and h['oos_upper_bound_95'] is None
