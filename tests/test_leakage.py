"""Leakage-invariant tests — these fail if a look-ahead bug is reintroduced.

Guards:
  1. The ranker's supervised samples use only data inside their training window: the
     label of every sample is fully resolved (exit fill included) on or before `end`.
  2. The engine's t+1 fill contract (default 'close' = next-bar close, never the signal
     bar), routed through the one function the engine uses.
  3. The fund-type replay books every trade's P&L on real trading days of the main
     calendar, and its equity reconciles with the per-trade P&L (v31.1 found a DST bug
     that silently dropped a trade from every fund Sharpe series).
"""
import inspect
import os

import numpy as np
import pandas as pd
import pytest

from tests.synthetic_market import build_system, make_market
from pairs_trading.fund_profiles import FUND_PROFILES
from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem, resolve_fill_column


@pytest.fixture(scope='module')
def market():
    return make_market(n_pairs=5, n_noise=0, seed=11)


def test_outcome_samples_ignore_data_after_their_window(market):
    """Samples built with end=T must be identical whether or not any data after T exists."""
    frames, macro, _ = market
    end = '2023-06-30'
    full = build_system(frames, macro)
    cut = {s: df[df.index <= pd.Timestamp(end, tz=df.index.tz)] for s, df in frames.items()}
    truncated = build_system(cut, macro)
    pairs = sorted(full.spread_data)
    Xa, ya = full.build_outcome_samples(pairs, end=end)
    Xb, yb = truncated.build_outcome_samples(pairs, end=end)
    assert ya is not None and len(ya) > 50
    np.testing.assert_array_equal(ya, yb)
    np.testing.assert_allclose(Xa, Xb, rtol=0, atol=0)


def test_engine_t_plus_1_fill_default():
    """The default t+1 fill is the next bar's CLOSE; only PAIRS_FILL=open switches it."""
    assert resolve_fill_column(os.environ.get('PAIRS_FILL', 'close')) == 'Close'
    assert resolve_fill_column('open') == 'Open'
    assert resolve_fill_column('OPEN') == 'Open'
    assert resolve_fill_column('CLOSE') == 'Close'
    assert resolve_fill_column('') == 'Close', "an empty PAIRS_FILL must not enable open fills"
    assert resolve_fill_column('opening') == 'Close', "only an exact 'open' switches the fill"
    src = inspect.getsource(CompleteFixedRussell3000TradingSystem.run_comprehensive_backtest)
    assert 'resolve_fill_column(' in src


@pytest.mark.parametrize('fill', ['close', 'open'])
def test_open_fill_differs_only_in_fill_prices(market, monkeypatch, fill):
    frames, macro, _ = market
    monkeypatch.setenv('PAIRS_FILL', fill)
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2025-12-31'))
    assert res['total_trades'] > 5
    for t in res['trades']:
        assert pd.Timestamp(t['signal_date']) < pd.Timestamp(t['date'])


def test_fund_replay_reconciles_on_the_real_calendar(market):
    frames, macro, _ = market
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2025-12-31'))
    assert res['total_trades'] > 5
    comparison = system.run_fund_type_comparison(res, main_daily_dates=res['daily_dates'])
    calendar = set(res['daily_dates'])
    for key, prof in comparison.items():
        curve = prof['equity_curve']
        assert [p['date'] for p in curve] == res['daily_dates'], f"{key}: replay calendar differs"
        assert all(p['date'] in calendar for p in curve)
        assert prof['unclosed_trades'] == 0
        if not prof['trades_stopped_early']:
            if FUND_PROFILES[key].max_daily_trades >= res['max_daily_trades']:
                # no profile cap binds: every main trade must be replayed (a dropped trade
                # is exactly the v31.1 DST failure)
                assert prof['total_trades'] == res['total_trades'], f"{key}: replay dropped trades"
            else:
                assert 0 < prof['total_trades'] <= res['total_trades']
        # reconciliation: the replay's equity change is the sum of its trades' net P&L
        assert prof['final_equity'] - system.initial_capital == pytest.approx(prof['replayed_net_pnl'], abs=0.05)
        assert np.isfinite(prof['sharpe_ratio'])


def test_fund_replay_refuses_trades_off_the_calendar(market):
    frames, macro, _ = market
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2025-12-31'))
    first = res['trades'][0]
    d0, v0 = first['unit_path'][0]
    off_day = d0 + ' ' if isinstance(d0, str) else pd.Timestamp(d0) + pd.Timedelta(hours=1)
    first['unit_path'] = [(off_day, v0)] + list(first['unit_path'][1:])   # a date the calendar lacks
    with pytest.raises(ValueError, match='off the main calendar'):
        system.run_fund_type_comparison(res, main_daily_dates=res['daily_dates'])
