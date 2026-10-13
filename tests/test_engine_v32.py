"""End-to-end tests of the backtest engine on a synthetic market with a known answer.

The strongest check here is FUTURE PERTURBATION: re-run the engine on a copy of the
market whose prices after date T follow a different path. A causal engine must make
exactly the same decisions, and book exactly the same daily returns, for every date
before T. Any look-ahead — a filter that peeks at a trade's outcome, sizing that sees a
still-open trade's P&L, a cost gate that reads the realised holding period, a universe
or statistic built from later data — breaks this, whatever the "right" answer is.
"""
import numpy as np
import pandas as pd
import pytest

from tests.synthetic_market import build_system, make_market, perturb_after
from pairs_trading.trading_system import (
    CompleteFixedRussell3000TradingSystem, max_drawdown_from_returns, annualised_sharpe,
)

RANGE = ('2023-07-01', '2025-12-31')
CUTOFF = '2024-06-03'


@pytest.fixture(scope='module')
def market():
    return make_market(n_pairs=6, n_noise=2, seed=7)


@pytest.fixture(scope='module')
def base_run(market):
    frames, macro, _ = market
    system = build_system(frames, macro)
    return system, system.run_comprehensive_backtest(system.spread_data, date_range=RANGE)


def _key(t):
    return (t['pair'], str(pd.Timestamp(t['signal_date']).date()), t['action'])


# ── Causality ─────────────────────────────────────────────────────────────────

def test_future_perturbation_leaves_the_past_unchanged(market, base_run):
    frames, macro, _ = market
    _, a = base_run
    b_sys = build_system(perturb_after(frames, CUTOFF), macro)
    b = b_sys.run_comprehensive_backtest(b_sys.spread_data, date_range=RANGE)

    cut = pd.Timestamp(CUTOFF)
    pre_a = [t for t in a['trades'] if pd.Timestamp(t['signal_date']).tz_localize(None) < cut]
    pre_b = [t for t in b['trades'] if pd.Timestamp(t['signal_date']).tz_localize(None) < cut]
    assert len(pre_a) >= 10, "fixture too quiet to test causality"
    assert [_key(t) for t in pre_a] == [_key(t) for t in pre_b], \
        "entry decisions before the cutoff changed when only later prices changed"
    for ta, tb in zip(pre_a, pre_b):
        assert ta['position_size'] == pytest.approx(tb['position_size'], rel=1e-12)
        assert ta['zscore'] == pytest.approx(tb['zscore'], rel=1e-12)
        assert ta['hedge_ratio'] == pytest.approx(tb['hedge_ratio'], rel=1e-12)

    da = [(d, r) for d, r in zip(a['daily_dates'], a['daily_returns']) if pd.Timestamp(d) <= cut]
    db = [(d, r) for d, r in zip(b['daily_dates'], b['daily_returns']) if pd.Timestamp(d) <= cut]
    assert [d for d, _ in da] == [d for d, _ in db]
    np.testing.assert_allclose([r for _, r in da], [r for _, r in db], rtol=0, atol=1e-15)
    # the test must actually exercise trades straddling the cutoff
    assert any(pd.Timestamp(t['exit_date']).tz_localize(None) > cut for t in pre_a)


def test_outcome_labels_are_causal(market):
    """Ranker samples built with data up to T are identical whatever happens after T."""
    frames, macro, _ = market
    a_sys = build_system(frames, macro)
    b_sys = build_system(perturb_after(frames, CUTOFF), macro)
    pairs = sorted(a_sys.spread_data)
    Xa, ya = a_sys.build_outcome_samples(pairs, end=CUTOFF)
    Xb, yb = b_sys.build_outcome_samples(pairs, end=CUTOFF)
    assert ya is not None and len(ya) > 50
    np.testing.assert_array_equal(ya, yb)
    np.testing.assert_allclose(Xa, Xb, rtol=0, atol=0)


# ── Accounting ────────────────────────────────────────────────────────────────

def test_equity_reconciles_with_trade_pnl(base_run):
    system, res = base_run
    total_net = sum(t['pnl_dollar'] for t in res['trades'])
    assert res['final_portfolio_value'] - system.initial_capital == pytest.approx(total_net, rel=1e-9)
    equity = system.initial_capital * np.cumprod(1.0 + np.asarray(res['daily_returns']))
    assert equity[-1] == pytest.approx(res['final_portfolio_value'], rel=1e-9)
    assert res['max_drawdown'] == pytest.approx(max_drawdown_from_returns(res['daily_returns']))
    assert res['sharpe_ratio'] == pytest.approx(annualised_sharpe(res['daily_returns']))


def test_mtm_path_telescopes_to_trade_return(base_run):
    _, res = base_run
    for t in res['trades']:
        assert sum(v for _, v in t['unit_path']) == pytest.approx(t['spread_return'], abs=1e-12)
        gross = t['gross_pnl_pct']
        net = t['net_pnl_pct']
        assert net == pytest.approx(gross - t['transaction_cost_pct'], abs=1e-12)


def test_daily_series_is_marked_to_market(base_run):
    """Most days with an open position must carry P&L (realised-only accounting would
    leave every non-exit day at exactly zero)."""
    _, res = base_run
    open_days = set()
    for t in res['trades']:
        open_days.update(d for d, _ in t['unit_path'])
    by_day = dict(zip(res['daily_dates'], res['daily_returns']))
    nonzero = sum(1 for d in open_days if by_day.get(d, 0.0) != 0.0)
    assert nonzero / len(open_days) > 0.9


def test_trade_timing_contract(base_run):
    _, res = base_run
    for t in res['trades']:
        sig, entry, exit_ = (pd.Timestamp(t[k]) for k in ('signal_date', 'date', 'exit_date'))
        assert sig < entry < exit_, "t+1 fills: signal < entry fill < exit fill"
        if t['exit_reason'] != 'end_of_data':
            assert pd.Timestamp(t['exit_signal_date']) < exit_, "exit fills after its signal bar"
        assert t['exit_reason'] in {'target', 'stop', 'time', 'end_of_data', 'risk_halt'}


def test_no_shared_leg_and_exposure_cap(base_run):
    system, res = base_run
    cap = system.risk_manager.max_total_exposure
    for d in res['daily_dates']:
        day = pd.Timestamp(d)
        live = [t for t in res['trades']
                if pd.Timestamp(t['signal_date']).tz_localize(None) <= day
                < pd.Timestamp(t['exit_date']).tz_localize(None)]
        legs = [s for t in live for s in t['pair'].split('-')]
        assert len(legs) == len(set(legs)), f"a stock is in two open pairs on {d}"
        assert sum(t['position_pct'] for t in live) <= cap + 1e-9


def test_entry_and_exit_use_one_z_definition(base_run):
    """Every entry clears the entry threshold on the beta-locked z, and every profit-target
    exit lands inside the exit band on the SAME frozen scale."""
    system, res = base_run
    for t in res['trades']:
        assert abs(t['zscore']) >= system.ENTRY_Z
        assert (t['action'] == 'LONG') == (t['zscore'] < 0)
        s1, s2 = t['pair'].split('-')
        state = system.get_pair_state(s1, s2)
        i = int(state.index.searchsorted(t['signal_date']))
        sig, _ = system._locked_signal(state, i, system.pair_selector.pair_statistics[t['pair']])
        assert sig['z'] == pytest.approx(t['zscore'], rel=1e-12)
        if t['exit_reason'] == 'target':
            j = int(state.index.searchsorted(t['exit_signal_date']))
            z_exit = (state['lp1'].iat[j] - sig['beta'] * state['lp2'].iat[j] - sig['mean']) / sig['std']
            assert abs(z_exit) < system.EXIT_Z or np.sign(z_exit) != np.sign(t['zscore'])


def test_positions_run_off_after_the_entry_window(market):
    """A position opened near the end of the entry window is resolved on the real bars
    that follow — never dropped (the v31 walk-forward silently discarded them)."""
    frames, macro, _ = market
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2024-03-28'))
    end = pd.Timestamp('2024-03-28')
    late = [t for t in res['trades'] if pd.Timestamp(t['exit_date']).tz_localize(None) > end]
    assert late, "fixture should leave at least one position open at the window end"
    assert all(pd.Timestamp(t['signal_date']).tz_localize(None) <= end for t in res['trades'])
    assert pd.Timestamp(res['daily_dates'][-1]) == max(
        pd.Timestamp(t['exit_date']).tz_localize(None) for t in res['trades'])


def test_known_edge_is_captured(base_run):
    """Planted Ornstein-Uhlenbeck pairs are genuinely mean-reverting: the strategy must
    make money on them before costs, and win more often than it loses."""
    _, res = base_run
    assert res['total_trades'] >= 30
    assert sum(t['gross_pnl_pct'] for t in res['trades']) > 0
    assert res['win_rate'] > 0.5


# ── Spread model ──────────────────────────────────────────────────────────────

def test_kalman_recovers_true_hedge_ratio():
    frames, macro, true_beta = make_market(n_pairs=3, n_noise=0, seed=3, betas=[0.6, 1.0, 1.6])
    system = build_system(frames, macro)
    for pair, beta in true_beta.items():
        state = system.get_pair_state(*pair)
        est = float(state['beta'].iloc[500:].median())
        assert est == pytest.approx(beta, abs=0.15), f"{pair}: beta {est:.3f} vs true {beta}"
    # What a no-intercept filter converges to is the log-price LEVEL ratio, which bears no
    # relation to the hedge ratio: for the beta=0.6 and beta=1.6 legs it is ~0.9 and ~0.9.
    level_ratio = (state['lp1'] / state['lp2']).iloc[500:].median()
    assert abs(level_ratio - 1.6) > 0.5


def test_kalman_state_is_prefix_invariant():
    frames, _, _ = make_market(n_pairs=1, n_noise=0, seed=5)
    p1, p2 = frames['SA00']['Close'], frames['SB00']['Close']
    sys_ = CompleteFixedRussell3000TradingSystem.__new__(CompleteFixedRussell3000TradingSystem)
    full = sys_.calculate_kalman_state(p1, p2)
    pre = sys_.calculate_kalman_state(p1.iloc[:400], p2.iloc[:400])
    np.testing.assert_allclose(full.iloc[:400].to_numpy(), pre.to_numpy(), rtol=0, atol=0, equal_nan=True)
    assert full['beta'].iloc[:29].isna().all() and full['beta'].iloc[29:].notna().all()


# ── Risk halt ─────────────────────────────────────────────────────────────────

def test_risk_halt_flattens_and_keeps_recording(market):
    frames, macro, _ = market
    system = build_system(frames, macro)
    system.risk_manager.max_single_day_loss = 1e-6          # trip on the first losing day
    res = system.run_comprehensive_backtest(system.spread_data, date_range=RANGE)
    assert res['halted_on'] is not None
    halt = pd.Timestamp(res['halted_on'])
    assert all(pd.Timestamp(t['signal_date']).tz_localize(None) <= halt for t in res['trades'])
    assert all(pd.Timestamp(t['exit_date']).tz_localize(None) <= halt + pd.Timedelta(days=5)
               for t in res['trades'])
    # the calendar keeps running after the halt (flat days), so annualisation is honest
    assert pd.Timestamp(res['daily_dates'][-1]) >= pd.Timestamp('2025-12-01')


def _run_with_sizer_probe(system):
    """Run the backtest, snapshotting the position sizer's outcome memory at every
    signal validation (date, recorded outcomes so far)."""
    snaps = []
    original = system.risk_manager.validate_signal

    def probe(pair_key, action, strength, market_data, size, value, date):
        snaps.append((pd.Timestamp(date).tz_localize(None), tuple(system.position_sizer.trade_history)))
        return original(pair_key, action, strength, market_data, size, value, date)

    system.risk_manager.validate_signal = probe
    system.run_comprehensive_backtest(system.spread_data, date_range=RANGE)
    return system, snaps


@pytest.mark.parametrize('cutoff', ['2023-11-01', '2024-06-03', '2025-02-03'])
def test_sizer_never_sees_an_open_trades_outcome(market, cutoff):
    """The position sizer adapts to recent trade outcomes; it may only learn an outcome
    once the trade has closed. If outcomes were recorded at entry (v31), changing prices
    after `cutoff` would change what the sizer 'knew' before `cutoff`."""
    frames, macro, _ = market
    _, a = _run_with_sizer_probe(build_system(frames, macro))
    _, b = _run_with_sizer_probe(build_system(perturb_after(frames, cutoff), macro))
    cut = pd.Timestamp(cutoff)
    pre_a = [s for s in a if s[0] <= cut]
    pre_b = [s for s in b if s[0] <= cut]
    assert len(pre_a) > 20
    assert pre_a == pre_b


def test_decisions_invariant_to_vendor_back_adjustment(market):
    """yfinance back-adjusts a whole history for splits that happen later (even after the
    sample). Rescaling one leg's entire price history by a constant must not change a
    single decision: the signal may depend on relative moves, never on the price level."""
    frames, macro, _ = market
    base = build_system(frames, macro)
    a = base.run_comprehensive_backtest(base.spread_data, date_range=RANGE)
    scaled = {s: df.copy() for s, df in frames.items()}
    for col in ('Open', 'High', 'Low', 'Close'):
        scaled['SB01'][col] = scaled['SB01'][col] / 10.0          # a 10:1 split, back-adjusted
        scaled['SA03'][col] = scaled['SA03'][col] * 3.0           # a 1:3 reverse split
    scaled['SB01']['Volume'] = scaled['SB01']['Volume'] * 10.0
    scaled['SA03']['Volume'] = scaled['SA03']['Volume'] / 3.0
    b_sys = build_system(scaled, macro)
    b = b_sys.run_comprehensive_backtest(b_sys.spread_data, date_range=RANGE)
    assert [_key(t) for t in a['trades']] == [_key(t) for t in b['trades']]
    for ta, tb in zip(a['trades'], b['trades']):
        assert ta['zscore'] == pytest.approx(tb['zscore'], rel=1e-6, abs=1e-9)
        assert ta['spread_return'] == pytest.approx(tb['spread_return'], rel=1e-6, abs=1e-12)
        # Only the per-share commission may differ: a split AFTER the data cannot be undone,
        # so the adjusted share count is off by the split ratio (0.2c/share; with its knock-on
        # through equity-proportional sizing this stays well under 1 bp of equity).
        assert abs(ta["net_pnl_pct"] - tb["net_pnl_pct"]) < 1e-4


@pytest.mark.parametrize('mode', ['pool', 'full'])
def test_reselection_uses_only_data_up_to_each_date(market, monkeypatch, mode):
    """Each quarterly re-selection (re-test of the pool, or the opt-in full search) and
    its re-estimated pair statistics are identical when all later prices change."""
    monkeypatch.setenv('PAIRS_RESELECT', mode)
    frames, macro, _ = market
    dates = pd.bdate_range('2023-01-03', '2025-06-30', tz='America/New_York')
    a_sys = build_system(frames, macro)
    b_sys = build_system(perturb_after(frames, CUTOFF), macro)
    a = a_sys.build_rolling_pair_schedule(list(dates), reselect_every=90)
    b = b_sys.build_rolling_pair_schedule(list(dates), reselect_every=90)
    cut = pd.Timestamp(CUTOFF, tz='America/New_York')
    early = [d for d in a if d <= cut]
    assert len(early) >= 3 and any(a[d] for d in early)
    for d in early:
        assert sorted(a[d]) == sorted(b[d])
        assert a_sys.pair_window_stats[d] == b_sys.pair_window_stats[d]


def test_cusum_and_hurst_gates_are_off_by_default_and_switchable():
    """v32: both gates are statistically near-inert at 30-90 bars and default to off;
    switching them on routes the same window through them again."""
    S = CompleteFixedRussell3000TradingSystem
    assert S.USE_CUSUM_GATE is False and S.USE_HURST_GATE is False
    idx = pd.bdate_range('2022-01-03', periods=200, tz='America/New_York')
    lp2 = np.log(50.0) + np.cumsum(np.random.default_rng(0).normal(0, 0.01, 200))
    jump = np.where(np.arange(200) >= 170, 0.25, 0.0)          # a level break in the spread
    state = pd.DataFrame({'lp1': lp2 + jump, 'lp2': lp2, 'beta': 1.0, 'alpha': 0.0,
                          'spread': jump}, index=idx)
    stats = {'half_life': 20.0}
    s = S.__new__(S)
    sig, why = s._locked_signal(state, 199, stats)
    assert sig is not None and why == ''
    s.USE_CUSUM_GATE = True
    assert s._locked_signal(state, 199, stats) == (None, 'cusum')


def test_adv_participation_uses_each_legs_own_adv():
    """v32 review: participation divided the short leg's notional by the SMALLER leg's ADV.
    beta = 2: $1M long A (ADV $20M) vs $2M short B (ADV $500M) -> worst leg is A at 5%,
    whichever leg is short."""
    S = CompleteFixedRussell3000TradingSystem
    s = S.__new__(S)
    s.initial_capital = 1e8
    base = {'position_size': 3e6, 'trading_days_held': 5}
    t1 = {**base, 'long_notional': 1e6, 'long_adv_dollars': 20e6, 'short_notional': 2e6, 'short_adv_dollars': 500e6}
    t2 = {**base, 'long_notional': 2e6, 'long_adv_dollars': 500e6, 'short_notional': 1e6, 'short_adv_dollars': 20e6}
    for t in (t1, t2):
        m = s._utilisation_metrics([t], [0.0, 0.0], [0.03, 0.03], [1e8, 1e8])
        assert m['avg_max_leg_adv_participation'] == pytest.approx(0.05)


def test_cost_gate_can_bind_and_stays_causal(market, monkeypatch):
    """The 1%-of-equity cost rail never binds on a liquid universe, so test the gate's
    logic with a binding threshold: it must reject some entries, and it must read only the
    ex-ante maximum hold (a gate that used the realised hold would differ under a future
    perturbation)."""
    frames, macro, _ = market
    # ~1 bp of equity: rejects roughly a third of entries on this liquid synthetic market
    monkeypatch.setattr(CompleteFixedRussell3000TradingSystem, 'MAX_COST_PCT_OF_EQUITY', 1e-4)
    a_sys = build_system(frames, macro)
    a = a_sys.run_comprehensive_backtest(a_sys.spread_data, date_range=RANGE)
    b_sys = build_system(perturb_after(frames, CUTOFF), macro)
    b = b_sys.run_comprehensive_backtest(b_sys.spread_data, date_range=RANGE)
    assert a['signal_rejections'].get('cost_gate', 0) > 0, "threshold did not bind; lower it"
    assert a['total_trades'] > 0, "threshold rejects everything; raise it"
    cut = pd.Timestamp(CUTOFF)
    pre = [[_key(t) for t in r['trades'] if pd.Timestamp(t['signal_date']).tz_localize(None) < cut]
           for r in (a, b)]
    assert pre[0] == pre[1] and len(pre[0]) > 0
