"""pairs_trading/anatomy.py and scripts/anatomy_of_the_null.py.

Hand-computed answers on a one-trade, six-day market (reconstruction, daily cost split,
shortfall waterfall, break-even multiple), closed-form checks (gambler's ruin, Kendall's
correction, the T-bill accrual, the square-root impact at scale), constructed markets for
the persistence table and the market exposure, and an end-to-end run of the real engine on
a synthetic market whose export the anatomy must reproduce trade by trade and day by day.
"""
import importlib.util
import json
import pathlib
import pickle

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from pairs_trading import anatomy as A
from pairs_trading import json_export as je
from pairs_trading.pair_selector import FixedPrimeFundPairSelector
from pairs_trading.synthetic import build_system, make_market
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO / 'tests' / 'fixtures'


def _load_script():
    spec = importlib.util.spec_from_file_location('_script_anatomy', REPO / 'scripts' / 'anatomy_of_the_null.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────────────────────────────────────────────────────────
# A one-trade market with hand-computable answers
# ──────────────────────────────────────────────────────────────────────────────
# Long spread: 10 shares of A long (filled at 102), 20 shares of B short (filled at 50.5).
# Signal d0, entry fill d1, exit signal d3, exit fill d4.
DAYS = pd.bdate_range('2024-03-04', periods=6)
CLOSE_A = [100.0, 102.0, 101.0, 105.0, 104.0, 104.0]
CLOSE_B = [50.0, 50.5, 51.0, 50.0, 49.8, 49.8]
ENTRY_COSTS = {'commission': 0.5, 'bid_ask': 1.5, 'market_impact': 2.5}
COSTS = {'commission': 1.0, 'bid_ask': 3.0, 'market_impact': 5.0, 'borrow': 0.5, 'financing': 0.5}
CAPITAL = 1_000_000.0


def _frame(closes):
    return pd.DataFrame({'Close': closes, 'Open': closes}, index=DAYS.tz_localize('America/New_York'))


def _mini_prices():
    return {'A': _frame(CLOSE_A), 'B': _frame(CLOSE_B)}


def _mini_results(net=24.0, costs=None):
    costs = dict(COSTS if costs is None else costs)
    pv = [CAPITAL, CAPITAL - 4.5, CAPITAL - 24.5, CAPITAL + 35.5, CAPITAL + 24.0, CAPITAL + 24.0]
    trade = {
        'trade_id': 1, 'pair': 'A-B', 'action': 'LONG', 'long_symbol': 'A', 'short_symbol': 'B',
        'signal_date': str(DAYS[0].date()), 'entry_date': str(DAYS[1].date()),
        'exit_signal_date': str(DAYS[3].date()), 'exit_date': str(DAYS[4].date()), 'exit_reason': 'target',
        'hedge_ratio': 1.0, 'zscore': -2.0, 'position_size_dollars': 2000.0,
        'long_notional_dollars': 10 * 102.0, 'short_notional_dollars': 20 * 50.5,
        'net_pnl_dollars': net, 'transaction_costs_dollars': sum(costs.values()),
        'holding_days_calendar': 3, 'trading_days_held': 3,
        'cost_breakdown_dollars': {**costs, 'total_cost': sum(costs.values())},
    }
    return {
        'metadata': {'initial_capital': CAPITAL,
                     'backtest_period': {'start': str(DAYS[0].date()), 'end': str(DAYS[-1].date())}},
        'run_config': {'effective': {'fill': 'close'}, 'data': {'data_start': '2024-01-02'}},
        'walk_forward_validation': {'pair_selection_cutoff': '2024-03-01'},
        'overall_performance': {'sharpe_ratio': None},
        'daily_equity_curve': [{'date': str(d.date()), 'portfolio_value': v} for d, v in zip(DAYS, pv)],
        'all_trades': [trade],
    }


def _mini():
    res = _mini_results()
    trades = A.trade_table(res)
    panel = A.PricePanel(_mini_prices(), A.run_calendar(res, trades))
    rec = A.reconstruct_trades(trades, panel)
    return res, trades, panel, rec


def test_reconstruction_rebuilds_the_daily_path_by_hand():
    _, trades, panel, rec = _mini()
    # shares 10 and 20; daily P&L 10 dA - 20 dB: d2 -10 - 10, d3 +40 + 20, d4 -10 + 4
    assert rec['per_trade']['q_long'].iloc[0] == pytest.approx(10.0)
    assert rec['per_trade']['q_short'].iloc[0] == pytest.approx(20.0)
    np.testing.assert_allclose(rec['daily_gross_usd'], [0, 0, -20, 60, -6, 0], atol=1e-9)
    assert trades['gross_usd'].iloc[0] == pytest.approx(34.0)
    assert rec['check']['verified'] and rec['check']['max_abs_error_usd'] < 1e-9


def test_reconstruction_flags_a_trade_the_prices_do_not_reproduce():
    res = _mini_results(net=45.0)                         # exported gross 55, prices say 34
    trades = A.trade_table(res)
    panel = A.PricePanel(_mini_prices(), A.run_calendar(res, trades))
    check = A.reconstruct_trades(trades, panel)['check']
    assert not check['verified'] and check['trades_outside_tolerance'] == 1
    assert check['max_abs_error_usd'] == pytest.approx(21.0)


def test_daily_cost_split_from_the_equity_curve():
    res, trades, panel, rec = _mini()
    daily = A.daily_series(res, trades, rec, panel)
    assert daily['source'] == 'reconstructed' and daily['check']['verified']
    cost_usd = daily['cost'] * daily['equity_prev']
    np.testing.assert_allclose(cost_usd, [0, 4.5, 0, 0, 5.5, 0], atol=1e-6)
    np.testing.assert_allclose(daily['gross'] - daily['cost'], daily['net'], atol=1e-15)


def test_daily_split_check_fails_when_costs_land_on_a_day_without_fills():
    res = _mini_results()
    res['daily_equity_curve'][2]['portfolio_value'] -= 3.0     # a $3 "cost" on a no-fill day
    for d in res['daily_equity_curve'][3:]:
        d['portfolio_value'] -= 3.0
    trades = A.trade_table(res)
    panel = A.PricePanel(_mini_prices(), A.run_calendar(res, trades))
    daily = A.daily_series(res, trades, A.reconstruct_trades(trades, panel), panel)
    assert not daily['check']['verified']
    assert daily['gross'] is None and daily['cost'] is None          # an unverified split is not used


def test_exported_daily_split_is_used_as_exported():
    res, trades, panel, rec = _mini()
    prev = [CAPITAL] + [d['portfolio_value'] for d in res['daily_equity_curve'][:-1]]
    gross_usd, cost_usd = [0, 0, -20, 60, -6, 0], [0, 4.5, 0, 0, 5.5, 0]
    for d, p, g, c in zip(res['daily_equity_curve'], prev, gross_usd, cost_usd):
        d['gross_return_pct'], d['cost_pct'] = g / p * 100, c / p * 100
    daily = A.daily_series(res, trades, rec, panel)
    assert daily['source'] == 'export' and daily['check']['verified']
    res['daily_equity_curve'][3]['gross_return_pct'] += 0.001
    assert not A.daily_series(res, trades, rec, panel)['check']['verified']


def test_shortfall_waterfall_by_hand_and_closes_on_net():
    res, trades, panel, rec = _mini()
    daily = A.daily_series(res, trades, rec, panel)
    sf = A.implementation_shortfall(trades, panel, rec, daily, CAPITAL)
    usd = {k: v['usd'] for k, v in sf['totals'].items()}
    # paper: 10 (105 - 100) - 20 (50 - 50) = 50; entry delay: 10 (102 - 100) - 20 (50.5 - 50) = 10;
    # exit delay: -(10 (104 - 105) - 20 (49.8 - 50)) = 6; gross 50 - 10 - 6 = 34
    assert usd['paper'] == pytest.approx(50.0) and sf['paper_from_prices_usd'] == pytest.approx(50.0)
    assert usd['entry_delay'] == pytest.approx(10.0) and usd['exit_delay'] == pytest.approx(6.0)
    assert usd['gross'] == pytest.approx(34.0) and usd['net'] == pytest.approx(24.0)
    steps = sf['steps']
    assert [s['key'] for s in steps] == [k for k, _ in A.SHORTFALL_STEPS]
    level = None
    for s in steps:
        if s['key'] in ('paper', 'gross', 'net'):
            assert s['start'] == 0.0
            if level is not None:
                assert s['end'] == pytest.approx(level)
        else:
            assert s['start'] == pytest.approx(level) and s['end'] == pytest.approx(level + s['usd'])
        level = s['end']
    assert steps[0]['end'] == pytest.approx(50.0) and steps[-1]['end'] == pytest.approx(24.0)
    assert sf['totals']['net']['pct_of_capital'] == pytest.approx(24.0 / CAPITAL * 100)
    assert sf['per_trade'][0]['entry_delay_bp'] == pytest.approx(10.0 / 2000.0 * 1e4)


def test_breakeven_multiple_and_cost_curve():
    res, trades, panel, rec = _mini()
    daily = A.daily_series(res, trades, rec, panel)
    gv = A.gross_vs_net(trades, daily)
    assert gv['totals']['breakeven_cost_multiple'] == pytest.approx(3.4)       # 34 / 10
    curve = {row['k']: row for row in gv['cost_curve']}
    net = np.prod(1 + daily['net']) - 1
    assert curve[1.0]['total_return_pct'] == pytest.approx(net * 100)
    assert curve[0.0]['total_return_pct'] == pytest.approx((np.prod(1 + daily['gross']) - 1) * 100)
    assert curve[2.0]['trade_net_usd'] == pytest.approx(34.0 - 2 * 10.0)
    assert gv['sharpe_breakeven_multiple'] == pytest.approx(daily['gross'].mean() / daily['cost'].mean())
    mix = {m['component']: m for m in gv['cost_mix']}
    assert mix['market_impact']['share'] == pytest.approx(0.5)


def _toy_trades(gross, cost, notional=1e6):
    """trade_table rows with the given gross P&L and costs (all costs as half-spread)."""
    rows = []
    for i, (g, c) in enumerate(zip(gross, cost), 1):
        rows.append({'trade_id': i, 'pair': 'X-Y', 'action': 'LONG', 'long_symbol': 'X', 'short_symbol': 'Y',
                     'signal_date': '2024-01-02', 'entry_date': '2024-01-03', 'exit_signal_date': '2024-01-10',
                     'exit_date': '2024-01-11', 'exit_reason': 'time', 'hedge_ratio': 1.0, 'zscore': 2.0,
                     'position_size_dollars': notional, 'long_notional_dollars': notional / 2,
                     'short_notional_dollars': notional / 2, 'net_pnl_dollars': g - c,
                     'transaction_costs_dollars': c, 'holding_days_calendar': 8, 'trading_days_held': 6,
                     'cost_breakdown_dollars': {'bid_ask': c, 'market_impact': 0.0, 'commission': 0.0,
                                                'borrow': 0.0, 'financing': 0.0}})
    return A.trade_table({'all_trades': rows})


def test_breakeven_multiple_is_gross_over_costs_and_undefined_for_a_gross_loss():
    trades = _toy_trades([600.0, -240.0], [300.0, 200.0])
    tot = A.gross_vs_net(trades, {'gross': None})['totals']
    assert tot['breakeven_cost_multiple'] == pytest.approx(0.72)            # 360 / 500
    assert tot['gross_usd'] - 0.72 * tot['cost_usd'] == pytest.approx(0.0)
    loss = A.gross_vs_net(_toy_trades([-100.0], [50.0]), {'gross': None})['totals']
    assert loss['breakeven_cost_multiple'] is None and loss['gross_to_cost_ratio'] == pytest.approx(-2.0)


def test_borrow_stress_replaces_the_modelled_fee():
    res, trades, panel, rec = _mini()
    daily = A.daily_series(res, trades, rec, panel)
    stress = A.gross_vs_net(trades, daily)['borrow_stress']
    # short notional 1010 for 3 calendar days at 3%/yr replaces the booked 0.5
    row = {s['rate']: s for s in stress['scenarios']}[0.03]
    fee = 1010.0 * 0.03 * 3 / 365
    assert row['borrow_usd'] == pytest.approx(fee)
    assert row['net_usd'] == pytest.approx(24.0 - (fee - 0.5))
    assert stress['modelled_rate_median'] == pytest.approx(0.5 / (1010.0 * 3 / 365))


# ──────────────────────────────────────────────────────────────────────────────
# Closed forms
# ──────────────────────────────────────────────────────────────────────────────

def test_kendall_correction_by_hand():
    k = A.kendall_half_life(0.9, 100)
    assert k['phi_kendall'] == pytest.approx(0.9 + 3.7 / 100)
    assert k['half_life'] == pytest.approx(np.log(2) / -np.log(0.9))
    assert k['half_life_kendall'] == pytest.approx(np.log(2) / -np.log(0.937))
    assert k['half_life_kendall'] > k['half_life']
    assert A.kendall_half_life(0.99, 50)['half_life_kendall'] is None        # 0.99 + 3.97/50 >= 1
    assert A.kendall_half_life(float('nan'), 0)['half_life'] is None


def test_spread_ar1_is_the_regression_behind_the_half_life():
    rng = np.random.default_rng(3)
    n = 600
    idx = pd.bdate_range('2021-01-01', periods=n)
    lb = np.cumsum(rng.normal(0, 0.01, n))
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = 0.9 * s[t - 1] + rng.normal(0, 0.01)
    d1 = pd.DataFrame({'Close': np.exp(4 + 0.8 * lb + s)}, index=idx)
    d2 = pd.DataFrame({'Close': np.exp(3 + lb)}, index=idx)
    sel = FixedPrimeFundPairSelector()
    phi, n_ar = sel.spread_ar1(d1, d2)
    assert n_ar == n - 1 and 0.85 < phi < 0.95
    assert sel.calculate_half_life(d1, d2) == pytest.approx(np.log(2) / -np.log(phi))
    phi_short, _ = sel.spread_ar1(d1.iloc[:40], d2.iloc[:40])
    assert np.isnan(phi_short) and sel.calculate_half_life(d1.iloc[:40], d2.iloc[:40]) == 999.0


def test_gamblers_ruin_and_the_simulated_race_agree_without_a_time_stop():
    assert A.gamblers_ruin_target_probability(1.8) == pytest.approx(1.5 / 2.8)
    sim = A.simulate_exit_race(1.8, 0.1, 1000, 1.0, n_paths=4000, rng=np.random.default_rng(1))
    assert sim['time'] < 0.01
    assert sim['target_given_barrier'] == pytest.approx(1.5 / 2.8, abs=0.03)


def test_simulated_race_mean_reversion_and_time_stop():
    rng = np.random.default_rng(2)
    ou = A.simulate_exit_race(1.8, 0.3, 25, phi=0.5, n_paths=4000, rng=rng)
    assert ou['target_given_barrier'] > 0.95
    still = A.simulate_exit_race(1.8, 0.01, 10, 1.0, n_paths=1000, rng=rng)
    assert still['time'] == 1.0 and np.isnan(still['target_given_barrier'])
    # one exit test, on day 2 after the signal: z_2 = 1.8 + N(0, 2 sigma^2)
    one = A.simulate_exit_race(1.8, 1.0, 1, 1.0, n_paths=20000, rng=rng)
    assert one['target'] == pytest.approx(sps.norm.cdf((0.5 - 1.8) / np.sqrt(2)), abs=0.01)
    assert one['stop'] == pytest.approx(sps.norm.sf(1.5 / np.sqrt(2)), abs=0.01)


def test_race_test_by_hand():
    out = A._race_test(61, np.full(126, 0.5))
    assert out['expected_targets'] == pytest.approx(63.0)
    assert out['z'] == pytest.approx((61 - 63) / np.sqrt(126 * 0.25))


def test_impact_repricing_at_scale_by_hand():
    execs = pd.DataFrame([{'shares': 1000.0, 'price': 100.0, 'adv': 1e6, 'dvol': 0.02, 'pit_ratio': 1.0}])
    model = EnhancedPrimeFundTransactionCostModel()
    base = A.execution_impact(execs, cost_model=model)[0]
    assert base == pytest.approx(1e5 * 0.3 * 0.02 * np.sqrt(1e-3))
    assert A.execution_impact(execs, coefficient=0.6, cost_model=model)[0] == pytest.approx(2 * base)
    assert A.execution_impact(execs, scale=100, cost_model=model)[0] / 100 == pytest.approx(10 * base)
    assert A.execution_impact(execs, scale=1e4, cost_model=model)[0] / 1e4 == pytest.approx(1e5 * 50e-4)
    assert model.market_impact_coefficient == 0.3                     # the caller's model is untouched


def test_fred_csv_parsing_and_cash_accrual():
    s = A.parse_fred_csv((FIXTURES / 'fred_dtb3_sample.csv').read_text(), 'DTB3')
    assert s.isna().sum() == 2 and s.loc['2023-07-05'] == 5.20
    with pytest.raises(ValueError):
        A.parse_fred_csv('observation_date,DTB3\n2023-07-05,n/a\n', 'DTB3')
    dates = pd.DatetimeIndex(['2023-06-30', '2023-07-03', '2023-07-05', '2023-07-06'])
    r = A.cash_returns(s, dates)
    i = A.bill_investment_yield
    # each day earns the previous date's (last available) rate over the calendar days elapsed
    expected = [0.0, i(5.15) * 3 / 365, i(5.15) * 2 / 365, i(5.20) * 1 / 365]
    np.testing.assert_allclose(r, expected)
    assert i(5.0) == pytest.approx(365 * 0.05 / (360 - 0.05 * 91))


def test_excess_of_cash_confirms_the_sharpe_has_no_rate_subtracted():
    res, trades, panel, rec = _mini()
    daily = A.daily_series(res, trades, rec, panel)
    from pairs_trading.significance import annualized_sharpe
    res['overall_performance']['sharpe_ratio'] = round(annualized_sharpe(daily['net']), 3)
    dtb3 = pd.Series(5.0, index=pd.bdate_range('2024-01-01', '2024-04-30'))
    cash = A.excess_of_cash(res, daily, dtb3)
    assert cash['sharpe_is_excess_of_cash']
    rc = A.cash_returns(dtb3, daily['dates'])
    assert cash['tbill_return_pct'] == pytest.approx((np.prod(1 + rc) - 1) * 100)
    assert cash['strategy_plus_cash_return_pct'] == pytest.approx((np.prod(1 + daily['net'] + rc) - 1) * 100)
    res['overall_performance']['sharpe_ratio'] = cash['sharpe_if_cash_were_subtracted']
    assert not A.excess_of_cash(res, daily, dtb3)['sharpe_is_excess_of_cash']


def test_market_exposure_by_hand():
    rng = np.random.default_rng(4)
    idx = pd.bdate_range('2023-01-02', periods=300)
    m = rng.normal(0, 0.01, len(idx))
    sectors = {'XLK': pd.Series(100 * np.cumprod(1 + m), index=idx)}
    prices = {'A': pd.DataFrame({'Close': 50 * np.cumprod(1 + 1.5 * m)}, index=idx),
              'B': pd.DataFrame({'Close': 80 * np.cumprod(1 + 0.5 * m)}, index=idx)}
    rows = [{'trade_id': 1, 'pair': 'A-B', 'action': 'LONG', 'long_symbol': 'A', 'short_symbol': 'B',
             'signal_date': str(idx[280].date()), 'entry_date': str(idx[281].date()),
             'exit_signal_date': str(idx[290].date()), 'exit_date': str(idx[291].date()), 'exit_reason': 'time',
             'hedge_ratio': 0.5, 'zscore': -2.0, 'position_size_dollars': 1000.0,
             'long_notional_dollars': 600.0, 'short_notional_dollars': 400.0, 'net_pnl_dollars': 10.0,
             'transaction_costs_dollars': 0.0, 'holding_days_calendar': 14, 'trading_days_held': 10,
             'cost_breakdown_dollars': {}}]
    trades = A.trade_table({'all_trades': rows})
    ex = A.market_exposure(trades, A.PricePanel(prices, idx), A.market_proxy_returns(sectors))
    assert ex['net_dollar_per_gross']['mean'] == pytest.approx(0.2)                    # (600 - 400) / 1000
    assert ex['net_dollar_per_gross']['implied_by_hedge_ratio_mean'] == pytest.approx(0.5 / 1.5)
    assert ex['net_market_beta_per_gross']['mean'] == pytest.approx((600 * 1.5 - 400 * 0.5) / 1000)
    hold = np.prod(1 + m[282:292]) - 1                                          # (entry fill, exit fill]
    assert ex['market_component']['market_usd'] == pytest.approx(700 * hold)


def _two_year_market():
    """Y a random walk; X = Y + OU spread in 2020 and a random-walk spread from 2021; W = Y + its own
    OU spread, listed in 2020 only; Z unrelated. 2020: X-Y, W-Y, W-X cointegrated."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range('2020-01-01', '2021-12-31')
    n, split = len(idx), int((idx < '2021-01-01').sum())
    ly = np.cumsum(rng.normal(0, 0.015, n))
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = (0.6 * s[t - 1] if t < split else s[t - 1]) + rng.normal(0, 0.01)
    w = np.zeros(n)
    for t in range(1, n):
        w[t] = 0.6 * w[t - 1] + rng.normal(0, 0.01)

    def frame(logp, last=None):
        close = pd.Series(np.exp(4 + logp), index=idx)
        df = pd.DataFrame({'Close': close, 'Returns': close.pct_change(fill_method=None)})
        return df.iloc[:last] if last else df

    return {'X': frame(ly + s), 'Y': frame(ly), 'W': frame(ly + w, split),
            'Z': frame(np.cumsum(rng.normal(0, 0.015, n)))}


def test_persistence_tests_the_next_year_on_next_year_data():
    out = A.cointegration_persistence(_two_year_market(), ['W', 'X', 'Y', 'Z'], years=(2020,))
    row = out['years'][0]
    assert row['cointegrated']['count'] == 3 and row['cointegrated']['of'] == 3       # Z screened out
    assert row['still_cointegrated_next_year']['of'] == 1                           # only X-Y testable
    assert row['still_cointegrated_next_year']['count'] == 0                        # its spread is a walk
    assert row['untestable_next_year'] == 2
    assert out['pooled_still_cointegrated']['ci95'][1] > 0.5


def test_pair_tests_do_not_depend_on_the_number_of_workers():
    frames = {s: df[df.index < '2021-01-01'] for s, df in _two_year_market().items()}
    pairs = [('W', 'X'), ('W', 'Y'), ('W', 'Z'), ('X', 'Y'), ('X', 'Z'), ('Y', 'Z')]
    assert A._run_tests(frames, pairs, True, 1, chunk=2) == A._run_tests(frames, pairs, True, 2, chunk=2)


def test_liquid_universe_is_the_selectors_screen():
    frames, macro, _ = make_market(n_pairs=3, n_noise=4, seed=8)
    system = build_system(frames, macro)
    cutoff = pd.Timestamp('2022-12-31', tz='America/New_York')
    train = {s: df[df.index <= cutoff] for s, df in system.processed_data.items()}
    sel = FixedPrimeFundPairSelector()
    sel.max_universe = 4
    sel.find_quality_pairs(train)
    assert A.liquid_universe(system.processed_data, '2022-12-31', sel) == sel.last_quality_symbols
    assert len(sel.last_quality_symbols) == 4


def test_formation_schedule_of_rolling_and_single_selections():
    v32 = _mini_results()
    assert A.formation_schedule(v32) == [(pd.Timestamp('2024-03-01'), pd.Timestamp('2024-01-02'))]
    v33 = {'run_config': {'data': {'data_start': '2020-01-02'},
                          'study': {'profile': {'formation_calendar_days': 1095}}},
           'universe_by_formation': [{'formation_date': '2022-12-31'}, {'formation_date': '2024-01-04'}]}
    assert A.formation_schedule(v33) == [(pd.Timestamp('2022-12-31'), pd.Timestamp('2020-01-02')),
                                         (pd.Timestamp('2024-01-04'), pd.Timestamp('2021-01-05'))]


# ──────────────────────────────────────────────────────────────────────────────
# End to end: the real engine on a synthetic market, then its export
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def synthetic_run(tmp_path_factory):
    frames, macro, _ = make_market(n_pairs=3, n_noise=0, seed=5)
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2025-12-31'))
    res['run_config'] = {'effective': {'fill': 'close'}, 'data': {'data_start': '2020-01-01'}}
    out_dir = tmp_path_factory.mktemp('run')
    path = je.export_testing_results_to_json(res, {'initial_capital': system.initial_capital}, output_dir=str(out_dir))
    exported = json.loads(pathlib.Path(path).read_text())
    exported['walk_forward_validation'] = {'pair_selection_cutoff': '2022-12-31'}
    return system, res, exported, macro, out_dir


def test_reconstruction_reproduces_the_engines_trades_and_daily_paths(synthetic_run):
    system, res, exported, _, _ = synthetic_run
    trades = A.trade_table(exported)
    assert len(trades) > 50
    panel = A.PricePanel(system.processed_data, A.run_calendar(exported, trades))
    rec = A.reconstruct_trades(trades, panel)
    assert rec['check']['verified'], rec['check']
    engine_daily = np.zeros(len(panel.calendar))
    for t in res['trades']:
        for day, unit in t['unit_path']:
            engine_daily[panel.calendar.get_loc(pd.Timestamp(day))] += unit * t['position_size']
    np.testing.assert_allclose(rec['daily_gross_usd'], engine_daily, atol=0.01)
    daily = A.daily_series(exported, trades, rec, panel)
    assert daily['source'] == 'reconstructed' and daily['check']['verified'], daily['check']
    assert daily['check']['implied_cost_usd'] == pytest.approx(res['total_transaction_costs'], abs=1.0)


def test_impact_repricing_reproduces_the_exported_impact(synthetic_run):
    system, _, exported, _, _ = synthetic_run
    trades = A.trade_table(exported)
    panel = A.PricePanel(system.processed_data, A.run_calendar(exported, trades))
    execs = A.execution_table(trades, panel, A.reconstruct_trades(trades, panel))
    assert len(execs) == 4 * len(trades)
    check = A._impact_check(trades, execs, A.execution_impact(execs))
    assert check['verified'], check
    doubled = A._impact_check(trades, execs, A.execution_impact(execs, coefficient=0.6))
    assert not doubled['verified']


def test_signal_windows_recover_the_engines_reference_window(synthetic_run):
    system, _, exported, _, _ = synthetic_run
    trades = A.trade_table(exported)
    panel = A.PricePanel(system.processed_data, A.run_calendar(exported, trades))
    hl = pd.Series(8.0, index=trades.index)                  # build_system's half-life
    w = A.signal_windows(trades, panel, hl)
    assert w['matched'].all()
    assert (w['window'] == 30).all()                          # clamp(int(3 x 8), 30, 90)
    assert (w['sigma_z'] > 0).all()


def test_rule_replay_reproduces_the_engines_trades(synthetic_run):
    system, _, exported, _, _ = synthetic_run
    trades = A.trade_table(exported)
    engine = A.Engine()
    engine.processed_data = system.processed_data
    reproduced = 0
    for (s1, s2), g in trades.groupby(['symbol1', 'symbol2']):
        replay = {(r['signal_date'], r['reason']): r['gross_return'] * 1e4
                  for r in A.rule_trades(engine, s1, s2, 8.0, '2023-07-01', '2025-12-31')}
        reproduced += sum(abs(replay.get((t.signal_date, t.exit_reason), np.inf) - t.gross_bp) < 0.01
                          for t in g.itertuples())
    # the engine's portfolio gates (exposure cap, cool-off) skip a few signals the replay takes
    assert reproduced >= 0.9 * len(trades)


def test_build_anatomy_end_to_end(synthetic_run):
    system, _, exported, macro, _ = synthetic_run
    dtb3 = pd.Series(5.0, index=pd.bdate_range('2023-01-02', '2026-01-02'))
    an = A.build_anatomy(exported, system.processed_data, macro['sectors'], dtb3, None, n_paths=500)
    json.dumps(je._json_safe(an), allow_nan=False)
    assert an['reconstruction']['trades']['verified'] and an['reconstruction']['impact']['verified']
    assert an['shortfall'][-1]['key'] == 'net'
    assert an['shortfall'][-1]['end'] == pytest.approx(float(A.trade_table(exported)['net_usd'].sum()), abs=0.01)
    er = an['exit_race']
    assert er['targets'] + er['stops'] == er['barrier_exits'] and er['expected_targets'] > 0
    # planted OU pairs: the rule earns a large gross edge in sample and out of sample
    assert an['decay'][0]['bp'] > 20 and an['decay'][1]['bp'] > 20
    assert {r['aum_musd'] for r in an['capacity']} == {10.0, 100.0, 1000.0, 5000.0}
    by_aum = {r['aum_musd']: r['net_bp'] for r in an['capacity']}
    assert by_aum[10.0] > by_aum[100.0] > by_aum[1000.0] > by_aum[5000.0]
    assert an['persistence']['windows'][0]['window'] == 'Traded pairs, out of sample'
    assert an['cash']['tbill_return_pct'] > 0
    assert A.summary_lines(an)


def test_script_writes_the_anatomy_offline(synthetic_run, tmp_path):
    system, _, exported, macro, _ = synthetic_run
    script = _load_script()
    results = tmp_path / 'run' / 'pairs_trading_results.json'
    results.parent.mkdir()
    results.write_text(json.dumps(exported))
    prices, macro_path = tmp_path / 'prices.pkl', tmp_path / 'macro.pkl'
    prices.write_bytes(pickle.dumps(system.processed_data))
    macro_path.write_bytes(pickle.dumps(macro))
    fred = tmp_path / 'external' / 'fred'
    fred.mkdir(parents=True)
    raw = (FIXTURES / 'fred_dtb3_sample.csv').read_bytes()
    (fred / 'DTB3.csv').write_bytes(raw)
    argv = ['--results', str(results), '--prices', str(prices), '--macro', str(macro_path),
            '--cache-dir', str(tmp_path / 'external'), '--offline', '--skip-persistence', '--paths', '200']
    assert script.main(argv) == 0
    out = json.loads((results.parent / 'anatomy.json').read_text())
    assert (results.parent / 'anatomy.txt').read_text().startswith('Anatomy of the null')
    assert out['source']['dtb3']['sha256'] and out['source']['results']['path'].endswith('pairs_trading_results.json')
    assert out['source']['price_cache_is_the_runs'] is None
    (fred / 'DTB3.csv.json').write_text(json.dumps({'sha256': '0' * 64}))
    with pytest.raises(ValueError, match='fingerprint'):
        script.main(argv)
    with pytest.raises(FileNotFoundError):
        script.load_fred('DTB3', str(tmp_path / 'empty'), offline=True)
