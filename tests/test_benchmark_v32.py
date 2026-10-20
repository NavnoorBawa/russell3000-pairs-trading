"""v32 tests for pairs_trading.benchmark — the audit fixes to the Gatev / random baselines.

Hermetic: synthetic prices built in-memory, fixed seeds, no data files or network.
Covers: t+1 execution (bid-ask bounce), crossing exit, block-start re-normalisation,
stops-trading exit, missing bars, cost model and notional scaling, the coverage-screened
and vectorised universe, the random-control distribution, and dated daily series.
"""
import itertools

import numpy as np
import pandas as pd
import pytest

from pairs_trading.benchmark import (
    _candidate_pairs, _sample_symbols, _screen_universe, _simulate_pairs, _trade_costs,
    empirical_percentile, fill_column_from_env, random_control_percentile,
    run_benchmarks, select_distance_pairs, log_benchmark_vs_strategy,
)
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel


# ── helpers ──────────────────────────────────────────────────────────────────

def _arrays(a, b, bar_a=None, bar_b=None, open_a=None, open_b=None):
    """Two-leg block arrays for _simulate_pairs from close paths (NaN = no bar)."""
    close = pd.DataFrame({'A': a, 'B': b}, dtype=float)
    if bar_a is not None:
        close.loc[~np.asarray(bar_a), 'A'] = np.nan
    if bar_b is not None:
        close.loc[~np.asarray(bar_b), 'B'] = np.nan
    has_bar = close.notna().to_numpy()
    close_ff = close.ffill().to_numpy()
    fill = np.where(has_bar, close_ff, np.nan)
    if open_a is not None:
        op = np.column_stack([open_a, open_b]).astype(float)
        fill = np.where(has_bar, op, np.nan)
    return close_ff, has_bar, fill


IA, IB = np.array([0]), np.array([1])


def _bounce_universe(n_sym=8, n_days=252 + 378, seed=0, half_spread=0.004):
    """Stocks that share ONE fundamental (mid) path; closes/opens differ only by an IID
    bid-ask bounce. Any pair P&L beyond the costs is bounce, i.e. not capturable."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2021-01-04', periods=n_days)
    mid = 50 * np.exp(np.cumsum(rng.normal(0, 0.01, n_days)))
    data = {}
    for i in range(n_sym):
        close = mid * (1 + half_spread * rng.standard_normal(n_days))
        op = mid * (1 + half_spread * rng.standard_normal(n_days))
        df = pd.DataFrame({'Open': op, 'High': np.maximum(op, close), 'Low': np.minimum(op, close),
                           'Close': close, 'Volume': np.full(n_days, 5e6)}, index=idx)
        df['Volume_MA'] = 5e6
        df['Volatility_20'] = 0.16
        data[f"B{i}"] = df
    return data, idx


def _factor_universe(n_sym=30, n_days=252 + 300, seed=1, tz='America/New_York'):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2021-01-04', periods=n_days, tz=tz) + pd.Timedelta(hours=16)
    mkt = rng.normal(0.0003, 0.01, n_days)
    ind = rng.normal(0, 0.008, (n_days, 5))
    data = {}
    for i in range(n_sym):
        close = rng.uniform(20, 120) * np.exp(np.cumsum(mkt + ind[:, i % 5] + rng.normal(0, 0.012, n_days)))
        df = pd.DataFrame({'Open': close * np.exp(rng.normal(0, 0.003, n_days)), 'Close': close,
                           'Volume': rng.lognormal(np.log(4e6), 0.3, n_days)}, index=idx)
        df['Volume_MA'] = df['Volume'].rolling(20, min_periods=14).mean()
        df['Volatility_20'] = df['Close'].pct_change(fill_method=None).rolling(20, min_periods=14).std() * np.sqrt(252)
        data[f"F{i:02d}"] = df
    return data, idx


# ── fill convention ──────────────────────────────────────────────────────────

def test_fill_rule_matches_engine(monkeypatch):
    from pairs_trading.trading_system import resolve_fill_column
    for v in ['open', 'OPEN', 'Open', 'close', 'CLOSE', '', 'garbage', 'opn']:
        assert fill_column_from_env(v) == resolve_fill_column(v)
    monkeypatch.setenv('PAIRS_FILL', 'open')
    assert fill_column_from_env() == 'Open'
    monkeypatch.delenv('PAIRS_FILL', raising=False)
    assert fill_column_from_env() == 'Close'


# ── the trading rule ─────────────────────────────────────────────────────────

def test_t_plus_1_entry_and_crossing_exit():
    """d = A/A0 - B/B0 with B flat: signal on t=1 (d=+3% > 2%), fill t=2; d falls to +1%
    (inside the band but NOT crossed: still held); crosses at t=4, fill t=5."""
    a = [100, 103, 102.5, 101, 99.5, 99.0, 99.0, 99.0]
    b = [100] * 8
    close_ff, has_bar, fill = _arrays(a, b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    assert len(tr['pair']) == 1
    assert tr['entry_k'][0] == 2 and tr['exit_k'][0] == 5
    assert tr['dir'][0] == -1                          # A rich -> short A, long B
    assert tr['eA'][0] == 102.5 and tr['xA'][0] == 99.0
    # short 1/102.5 shares of A: P&L = (102.5 - 99.0) / 102.5, booked day by day
    assert gross[:, 0].sum() == pytest.approx(3.5 / 102.5, rel=1e-12)
    assert gross[2, 0] == 0.0 and gross[:2, 0].sum() == 0.0
    assert gross[3, 0] == pytest.approx(1.5 / 102.5)
    assert gross[6:, 0].sum() == 0.0


def test_same_bar_variant_fills_on_the_signal_close():
    a = [100, 103, 102.5, 101, 99.5, 99.0, 99.0, 99.0]
    b = [100] * 8
    close_ff, has_bar, fill = _arrays(a, b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=0)
    assert tr['entry_k'][0] == 1 and tr['exit_k'][0] == 4
    assert gross[:, 0].sum() == pytest.approx((103 - 99.5) / 103)


def test_open_fill_books_the_intraday_move_on_the_fill_day():
    a = [100, 103, 102.5, 101, 99.5, 99.0, 99.0, 99.0]
    b = [100] * 8
    open_a = [100, 100, 104.0, 101, 99.5, 98.0, 99.0, 99.0]
    open_b = [100] * 8
    close_ff, has_bar, fill = _arrays(a, b, open_a=open_a, open_b=open_b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    assert tr['eA'][0] == 104.0 and tr['xA'][0] == 98.0
    assert gross[2, 0] == pytest.approx(-(102.5 - 104.0) / 104.0)   # short from the open
    assert gross[:, 0].sum() == pytest.approx((104.0 - 98.0) / 104.0)


def test_prices_renormalised_at_block_start():
    """A sits 10% above B at the block's first close (a gap opened during formation).
    Normalised at the FORMATION start that is a permanent >2-sigma divergence (instant
    entry, never crosses); re-normalised at the block start (GGR) d = 0 -> no trade."""
    a = [110.0] * 30
    b = [100.0] * 30
    close_ff, has_bar, fill = _arrays(a, b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.01]), execution_lag=1)
    assert len(tr['pair']) == 0 and not gross.any()


def test_position_open_at_block_end_is_closed_at_last_close():
    a = [100, 103, 104, 105, 106]
    b = [100] * 5
    close_ff, has_bar, fill = _arrays(a, b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    assert tr['entry_k'][0] == 2 and tr['exit_k'][0] == 4 and tr['xA'][0] == 106
    assert gross[:, 0].sum() == pytest.approx(-(106 - 104) / 104)


def test_no_entry_whose_fill_is_the_last_bar():
    a = [100, 100, 100, 103, 103]                      # signal on t=3, fill would be t=4 (last)
    b = [100] * 5
    close_ff, has_bar, fill = _arrays(a, b)
    _, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    assert len(tr['pair']) == 0


def test_leg_that_stops_trading_closes_the_pair_at_its_last_real_close():
    a = [100, 103, 102, 101, 100.5, 100.2, 100.1, 100.0]
    b = [100, 100, 100, 99, 98, 98, 98, 98]
    bar_b = [True, True, True, True, False, False, False, False]   # B delisted after t=3
    close_ff, has_bar, fill = _arrays(a, b, bar_b=bar_b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    # entry fill t=2; B has no bar on t=4 -> exit signal on the t=4 close, fill t=5
    assert tr['entry_k'][0] == 2 and tr['exit_k'][0] == 5
    assert tr['xB'][0] == 99.0 and tr['xA'][0] == 100.2
    expected = -(100.2 - 102) / 102 + (99.0 - 100) / 100
    assert gross[:, 0].sum() == pytest.approx(expected)


def test_missing_bar_on_one_leg_keeps_the_other_legs_return():
    """v31 skipped the whole day when either leg lacked a bar, dropping the OTHER leg's
    move. Now the leg without a bar is carried at its last real close."""
    a = [100, 103, 102, 101.0, 100.0, 99.0, 99.0]
    b = [100, 100, 100, 100.0, 100.0, 100.0, 100.0]
    bar_b = [True, True, True, False, True, True, True]
    close_ff, has_bar, fill = _arrays(a, b, bar_b=bar_b)
    gross, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    assert tr['entry_k'][0] == 2
    assert gross[3, 0] == pytest.approx(-(101.0 - 102) / 102)    # A's move booked on t=3
    assert tr['exit_k'][0] == 4                                  # B had no bar -> exit next fill
    assert gross[:, 0].sum() == pytest.approx(-(tr['xA'][0] - 102) / 102 + (tr['xB'][0] - 100) / 100)


def test_entry_cancelled_when_fill_day_has_no_bar():
    a = [100, 103, 103, 103, 103, 103]
    b = [100, 100, 100, 100, 100, 100]
    bar_a = [True, True, False, True, True, True]
    close_ff, has_bar, fill = _arrays(a, b, bar_a=bar_a)
    _, tr = _simulate_pairs(close_ff, has_bar, fill, IA, IB, np.array([0.02]), execution_lag=1)
    # the t=1 signal cannot fill on t=2 (A has no bar); t=2 has no decision (A no bar);
    # the t=3 signal fills on t=4
    assert list(tr['entry_k']) == [4]


def test_bid_ask_bounce_is_not_capturable_with_a_one_day_wait():
    """Pure bid-ask bounce around a common mid: same-bar fills 'earn' the bounce (the
    signal and the fill are the same noisy print); t+1 fills earn nothing gross."""
    rng = np.random.default_rng(7)
    T, hs = 20000, 0.004
    a = 100 * (1 + hs * rng.standard_normal(T))
    b = 100 * (1 + hs * rng.standard_normal(T))
    form = hs * (rng.standard_normal(500) - rng.standard_normal(500))
    thr = np.array([2.0 * form.std(ddof=1)])
    close_ff, has_bar, fill = _arrays(a, b)
    g1, t1 = _simulate_pairs(close_ff, has_bar, fill, IA, IB, thr, execution_lag=1)
    g0, t0 = _simulate_pairs(close_ff, has_bar, fill, IA, IB, thr, execution_lag=0)
    per_trade_lag1 = g1.sum() / len(t1['pair'])
    per_trade_lag0 = g0.sum() / len(t0['pair'])
    se_lag1 = 2 * hs * np.sqrt(2) / np.sqrt(len(t1['pair']))     # sd of a t+1 trade P&L / sqrt(n)
    assert len(t1['pair']) > 300
    assert abs(per_trade_lag1) < 3 * se_lag1                     # zero gross edge
    assert per_trade_lag0 > 20 * se_lag1                          # the same-bar illusion
    assert per_trade_lag0 > 0.01                                  # > 100 bp per trade


def test_bounce_universe_loses_its_costs_end_to_end():
    data, idx = _bounce_universe(seed=0)
    out = run_benchmarks(data, list(data), trade_start=str(idx[252].date()), n_pairs=10,
                         n_random_draws=20)
    d, s = out['distance_method'], out['sensitivity']
    cost_drag_pct = d['n_trades'] * d['avg_round_trip_cost_bps'] / 1e4 / d['n_pairs'] * 100
    gross_pct = s['distance_gross_of_costs']['total_return_pct']
    assert d['n_trades'] > 100
    assert d['total_return_pct'] < 0
    assert abs(gross_pct) < 0.5 * cost_drag_pct                   # gross ~ 0 ...
    assert d['total_return_pct'] == pytest.approx(-cost_drag_pct, abs=0.5 * cost_drag_pct)  # ... net ~ -costs
    same_bar = s['distance_same_bar_fills']
    assert same_bar['total_return_pct'] > 20 and same_bar['sharpe_ratio'] > 3


def test_execution_lag_zero_is_the_labelled_sensitivity():
    data, idx = _bounce_universe(seed=0)
    out0 = run_benchmarks(data, list(data), trade_start=str(idx[252].date()), n_pairs=10,
                          n_random_draws=5, execution_lag=0)
    assert out0['config']['execution_lag'] == 0
    assert 'same-bar' in out0['config']['fill']
    assert out0['distance_method']['total_return_pct'] > 20
    with pytest.raises(ValueError):
        run_benchmarks(data, list(data), trade_start=str(idx[252].date()), execution_lag=2)


# ── costs ────────────────────────────────────────────────────────────────────

def _one_trade():
    return {'pair': np.array([0]), 'dir': np.array([1.0]), 'entry_k': np.array([1]),
            'exit_k': np.array([11]), 'eA': np.array([50.0]), 'eB': np.array([80.0]),
            'xA': np.array([52.0]), 'xB': np.array([79.0])}


def _cost_inputs(T=15):
    days = np.arange(T) + 19000
    adv = np.full((T, 2), 3e6)
    dvol = np.full((T, 2), 0.018)
    return days, adv, dvol


def test_model_costs_match_direct_cost_model_calls():
    cm = EnhancedPrimeFundTransactionCostModel()
    days, adv, dvol = _cost_inputs()
    N = 2_000_000.0
    cost, per_trade = _trade_costs(_one_trade(), IA, IB, ['AAA', 'BBBB'], days, adv, dvol, None,
                                   N, cm, None, (15, 1))
    leg = lambda sh, px: cm.calculate_leg_cost(sh, px, 3e6, 0.018)['total']   # noqa: E731
    entry = leg(N / 50, 50.0) + leg(N / 80, 80.0)
    exit_ = leg(N / 50, 52.0) + leg(N / 80, 79.0)
    carry = cm.calculate_borrow_cost(N, 'BBBB', 10) + cm.calculate_financing_cost(2 * N, 10)
    assert cost[1, 0] == pytest.approx(entry / N)
    assert cost[11, 0] == pytest.approx((exit_ + carry) / N)
    assert per_trade[0] == pytest.approx((entry + exit_ + carry) / N)
    assert cost.sum() == pytest.approx(per_trade[0])


def test_cost_fraction_grows_with_notional_and_flat_override_does_not():
    cm = EnhancedPrimeFundTransactionCostModel()
    days, adv, dvol = _cost_inputs()
    fr = {}
    for N in (2e5, 2e6, 2e7):
        _, per_trade = _trade_costs(_one_trade(), IA, IB, ['AAA', 'BBBB'], days, adv, dvol, None,
                                    N, cm, None, (15, 1))
        fr[N] = per_trade[0]
    assert fr[2e5] < fr[2e6] < fr[2e7]                     # square-root impact
    flat = [_trade_costs(_one_trade(), IA, IB, ['AAA', 'BBBB'], days, adv, dvol, None, N, cm,
                         0.0010, (15, 1))[1][0] for N in (2e5, 2e7)]
    assert flat == [pytest.approx(0.0010)] * 2


def test_run_benchmarks_costs_scale_with_leg_notional():
    data, idx = _factor_universe()
    kw = dict(trade_start=str(idx[252].date()), n_pairs=5, n_random_draws=5)
    small = run_benchmarks(data, list(data), leg_notional=2e5, **kw)
    big = run_benchmarks(data, list(data), leg_notional=2e7, **kw)
    ds, db = small['distance_method'], big['distance_method']
    assert ds['n_trades'] == db['n_trades'] > 0                   # same trades ...
    assert db['avg_round_trip_cost_bps'] > ds['avg_round_trip_cost_bps']   # ... dearer
    assert db['total_return_pct'] < ds['total_return_pct']
    flat = run_benchmarks(data, list(data), cost_roundtrip=0.0010, **kw)
    assert flat['distance_method']['avg_round_trip_cost_bps'] == pytest.approx(10.0)
    assert flat['config']['cost_roundtrip_bps'] == pytest.approx(10.0)


# ── universe and selection ───────────────────────────────────────────────────

def test_vectorised_ssd_matches_bruteforce():
    rng = np.random.default_rng(3)
    norm = np.exp(np.cumsum(rng.normal(0, 0.01, (120, 9)), axis=0))
    ia, ib, ssd, sd = _candidate_pairs(norm, 0.0)
    brute = {}
    for i, j in itertools.combinations(range(9), 2):
        d = norm[:, i] - norm[:, j]
        brute[(i, j)] = (float(np.sum(d * d)), float(d.std(ddof=1)))
    assert len(ia) == 36
    for k in range(len(ia)):
        s_b, sd_b = brute[(ia[k], ib[k])]
        assert ssd[k] == pytest.approx(s_b, rel=1e-9)
        assert sd[k] == pytest.approx(sd_b, rel=1e-7)


def test_coverage_screen_and_seeded_symbol_sample():
    idx = pd.bdate_range('2022-01-03', periods=100)
    px = pd.DataFrame(np.exp(np.random.default_rng(0).normal(0, 0.01, (100, 5)).cumsum(0)),
                      index=idx, columns=list('ABCDE'))
    px.iloc[:50, 2] = np.nan                                      # C: 50% coverage
    px.iloc[:5, 3] = np.nan                                       # D: 95% coverage
    assert _screen_universe(px, 0.9) == ['A', 'B', 'D', 'E']
    cols = [f"S{i:03d}" for i in range(300)]
    s1 = _sample_symbols(cols, 50, 42)
    assert s1 == _sample_symbols(cols, 50, 42) and len(s1) == 50
    assert s1 != cols[:50]                                        # not a first-N cut
    assert _sample_symbols(cols, None, 42) == cols
    pairs = select_distance_pairs(px, n_pairs=10)
    assert all('C' not in p for p in pairs)


def test_screen_applies_to_random_control_and_universe_is_recorded():
    data, idx = _factor_universe(n_sym=12)
    # a name with thin formation coverage: only its last 80 formation bars exist
    thin = data['F00'].copy()
    data['THIN'] = thin.iloc[172:]
    out = run_benchmarks(data, list(data), trade_start=str(idx[252].date()), n_pairs=4,
                         n_random_draws=30)
    cfg = out['config']
    assert cfg['universe_size'] == 13
    assert cfg['effective_universe_size'][0] == 12                # THIN screened out of block 1
    assert all(b['universe'] >= 12 for b in cfg['blocks'] if 'universe' in b)
    capped = run_benchmarks(data, list(data), trade_start=str(idx[252].date()), n_pairs=4,
                            n_random_draws=5, max_symbols=6)
    assert capped['config']['effective_universe_size'] == [6] * capped['config']['n_blocks_used']


# ── random control ───────────────────────────────────────────────────────────

def test_random_control_is_deterministic_and_reports_a_distribution():
    data, idx = _factor_universe()
    kw = dict(trade_start=str(idx[252].date()), n_pairs=5, n_random_draws=40)
    a = run_benchmarks(data, list(data), seed=7, **kw)
    b = run_benchmarks(data, list(data), seed=7, **kw)
    c = run_benchmarks(data, list(data), seed=8, **kw)
    ra = a['random_control']
    assert ra['draw_sharpes'] == b['random_control']['draw_sharpes']
    assert ra['draw_sharpes'] != c['random_control']['draw_sharpes']
    assert a['distance_method']['daily_returns'] == c['distance_method']['daily_returns']
    assert ra['n_draws'] == 40 and len(ra['draw_sharpes']) == 40
    assert ra['redrawn_every_block'] is True
    for key in ('sharpe_distribution', 'total_return_pct_distribution'):
        dist = ra[key]
        for q in ('mean', 'median', 'p5', 'p25', 'p75', 'p95'):
            assert q in dist
        assert dist['p5'] <= dist['p25'] <= dist['median'] <= dist['p75'] <= dist['p95']
    assert 0.0 <= ra['distance_sharpe_percentile'] <= 100.0
    assert len(ra['mean_daily_returns']) == len(ra['daily_dates'])
    qs = ra['cumulative_return_pct_quantiles']
    assert sorted(qs) == ['p05', 'p25', 'p50', 'p75', 'p95']
    assert all(len(v) == len(ra['daily_dates']) for v in qs.values())
    assert all(a <= b + 1e-9 for lo, hi in (('p05', 'p25'), ('p25', 'p50'), ('p50', 'p75'), ('p75', 'p95'))
               for a, b in zip(qs[lo], qs[hi]))
    # the last day's quantiles are the quantiles of the draws' total returns
    assert qs['p50'][-1] == pytest.approx(np.median(ra['draw_total_returns_pct']), abs=1e-3)
    assert qs['p05'][-1] == pytest.approx(np.percentile(ra['draw_total_returns_pct'], 5), abs=1e-3)


def test_percentile_helpers():
    sample = [-1.0, 0.0, 1.0, 2.0]
    assert empirical_percentile(5.0, sample) == 100.0
    assert empirical_percentile(-5.0, sample) == 0.0
    assert empirical_percentile(0.0, sample) == pytest.approx(37.5)     # 1 below + half a tie
    assert np.isnan(empirical_percentile(np.nan, sample))
    assert random_control_percentile(1.5, {'draw_sharpes': sample}) == 75.0
    assert np.isnan(random_control_percentile(1.0, {}))


# ── dated series and strategy comparison ────────────────────────────────────

def test_daily_series_carry_dates_inside_the_trading_period():
    data, idx = _factor_universe()
    start = str(idx[252].date())
    out = run_benchmarks(data, list(data), trade_start=start, trade_end=str(idx[-10].date()),
                         n_pairs=5, n_random_draws=5)
    d = out['distance_method']
    assert len(d['daily_dates']) == len(d['daily_returns']) == d['n_days'] > 0
    assert d['daily_dates'] == sorted(d['daily_dates'])
    assert d['daily_dates'][0] >= start and d['daily_dates'][-1] <= str(idx[-10].date())
    assert all(len(s) == 10 and s[4] == '-' for s in d['daily_dates'])
    assert out['random_control']['daily_dates'] == d['daily_dates']


def test_strategy_comparison_on_common_dates():
    data, idx = _factor_universe()
    kw = dict(trade_start=str(idx[252].date()), n_pairs=5, n_random_draws=30, n_boot=499)
    base = run_benchmarks(data, list(data), **kw)
    d = base['distance_method']
    rng = np.random.default_rng(0)
    # the strategy calendar is shifted: it misses the first 10 benchmark days
    s_dates = d['daily_dates'][10:]
    s_rets = list(rng.normal(0.0004, 0.004, len(s_dates)))
    out = run_benchmarks(data, list(data), strategy_series={
        'same_as_distance': (d['daily_dates'], d['daily_returns']),
        'strategy': (s_dates, s_rets)}, **kw)
    same = out['vs_strategy']['same_as_distance']
    assert same['sharpe_difference_vs_distance']['diff'] == 0.0
    assert same['sharpe_difference_vs_distance']['pvalue'] == 1.0
    st = out['vs_strategy']['strategy']
    assert st['n_common_days'] == len(s_dates)
    assert st['common_start'] == s_dates[0]
    t = st['sharpe_difference_vs_distance']
    assert t['n'] == len(s_dates) and 0.0 < t['pvalue'] <= 1.0 and t['ci_lo'] <= t['diff'] <= t['ci_hi']
    assert 0.0 <= st['strategy_percentile_in_random'] <= 100.0
    # the first series is the headline: flat keys for the headline exporter
    assert out['sharpe_diff_vs_gatev']['strategy'] == 'same_as_distance'
    assert out['sharpe_diff_vs_gatev']['pvalue'] == 1.0
    assert out['random_control']['strategy_percentile'] == same['strategy_percentile_in_random']
    assert 'sharpe_diff_vs_gatev' not in base and 'strategy_percentile' not in base['random_control']
    log_benchmark_vs_strategy(out, strategy_return_pct=1.0, strategy_sharpe=0.5)
    log_benchmark_vs_strategy({}, 0.0, 0.0)
