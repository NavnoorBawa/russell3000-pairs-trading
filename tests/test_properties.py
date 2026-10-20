"""Property-based tests (Hypothesis) of invariants the rest of the suite checks on a few
fixed examples.

Every property runs under a derandomized profile with a bounded number of examples, so
the suite stays fast and CI is reproducible: the same examples are generated on every run
and on every machine, and nothing is written to a local example database. A
counterexample found while developing a property is kept as an @example.

    Kalman beta / spread / locked z      invariant to rescaling either leg's price level
    annualised Sharpe, Lo Sharpe, PSR,   invariant to scaling the returns by k > 0;
      DSR, HAC t                         antisymmetric under r -> -r
    Politis-White block length           within [1, ceil(min(3 sqrt(n), n/3))]
    one-leg execution cost               >= 0; non-decreasing in shares, in volatility and
                                         in illiquidity (lower ADV)
    a trade's daily mark-to-market path  sums to its gross P&L, day by day
    signals and decisions up to day t    unchanged when only prices after t change
"""
import functools
import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, Phase, example, given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from pairs_trading.significance import (
    annualized_sharpe, deflated_sharpe_ratio, hac_tstat_mean, lo_annualized_sharpe,
    politis_white_block_length, probabilistic_sharpe_ratio,
)
from pairs_trading.synthetic import build_system, make_market, perturb_after, perturb_macro_after
from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

S = CompleteFixedRussell3000TradingSystem


def _profile(max_examples):
    return settings(derandomize=True, database=None, deadline=None, max_examples=max_examples,
                    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


def _bare_system():
    """The engine's pure helpers (Kalman, z-score, exit scan) use no instance state."""
    return S.__new__(S)


def _random_pair(seed, n):
    """Log prices of a cointegrated pair: lp1 = c + 0.9 lp2 + AR(1) spread."""
    rng = np.random.default_rng(seed)
    lp2 = np.cumsum(rng.normal(0, 0.02, n)) + 3.0
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = 0.8 * s[t - 1] + rng.normal(0, 0.01)
    lp1 = 0.2 + 0.9 * lp2 + s
    idx = pd.bdate_range('2021-01-04', periods=n)
    return pd.Series(np.exp(lp1), idx), pd.Series(np.exp(lp2), idx)


# ═══════════════════════════════════════════════════════════════════════════════
# Kalman filter: invariance to the vendor's back-adjustment of a price history
# ═══════════════════════════════════════════════════════════════════════════════

@_profile(60)
@given(seed=st.integers(0, 2 ** 32 - 1), n=st.integers(60, 300),
       c1=st.floats(0.01, 100), c2=st.floats(0.01, 100))
@example(seed=0, n=60, c1=0.01, c2=100.0)
def test_kalman_state_and_signal_invariant_to_rescaling_either_leg(seed, n, c1, c2):
    """A split or dividend back-adjustment multiplies a whole price history by a constant.
    The filter works on log prices centred on their burn-in means, so beta, the residual
    spread and the beta-locked z-score must not move (they did through v31)."""
    p1, p2 = _random_pair(seed, n)
    ts = _bare_system()
    a = ts.calculate_kalman_state(p1, p2)
    b = ts.calculate_kalman_state(c1 * p1, c2 * p2)
    np.testing.assert_allclose(a['beta'], b['beta'], rtol=0, atol=1e-9, equal_nan=True)
    np.testing.assert_allclose(a['spread'], b['spread'], rtol=0, atol=1e-9, equal_nan=True)
    stats = {'half_life': 10.0}
    i = n - 1
    sa, _ = ts._locked_signal(a.dropna(), len(a.dropna()) - 1, stats)
    sb, _ = ts._locked_signal(b.dropna(), len(b.dropna()) - 1, stats)
    assert i >= 59 and sa is not None and sb is not None
    assert sa['z'] == pytest.approx(sb['z'], rel=1e-7, abs=1e-7)
    assert sa['beta'] == pytest.approx(sb['beta'], rel=0, abs=1e-9)


# ═══════════════════════════════════════════════════════════════════════════════
# Sharpe-type statistics: scale invariance and sign antisymmetry
# ═══════════════════════════════════════════════════════════════════════════════

returns = arrays(np.float64, st.integers(30, 400), elements=st.floats(-0.2, 0.2))


def _has_dispersion(r):
    return np.std(r) > 1e-6 and np.std(r) > 1e-8 * np.max(np.abs(r))


@_profile(150)
@given(r=returns, k=st.floats(0.01, 50))
def test_sharpe_statistics_are_invariant_to_scaling_returns(r, k):
    """Doubling the book doubles every return and changes no Sharpe ratio, no PSR/DSR and
    no t-statistic."""
    if not _has_dispersion(r):
        return
    s = k * r
    assert annualized_sharpe(s) == pytest.approx(annualized_sharpe(r), rel=1e-7, abs=1e-9)
    lo_r, lo_s = lo_annualized_sharpe(r), lo_annualized_sharpe(s)
    if np.isfinite(lo_r['sharpe']):
        assert lo_s['sharpe'] == pytest.approx(lo_r['sharpe'], rel=1e-7, abs=1e-9)
    for f in (lambda x: probabilistic_sharpe_ratio(x)['psr'],
              lambda x: probabilistic_sharpe_ratio(x, 0.5, variance_at='null')['psr'],
              lambda x: deflated_sharpe_ratio(x, 20)['dsr'],
              lambda x: hac_tstat_mean(x)['tstat']):
        assert f(s) == pytest.approx(f(r), rel=1e-6, abs=1e-9)


@_profile(150)
@given(r=returns)
def test_sharpe_statistics_flip_sign_with_the_returns(r):
    """Sign conventions: shorting the strategy negates its Sharpe and t-statistic, and the
    PSR of SR > 0 becomes 1 - PSR (skewness flips with the mean, so the variance term
    1 - g3 SR + (g4 - 1)/4 SR^2 is unchanged)."""
    if not _has_dispersion(r):
        return
    assert annualized_sharpe(-r) == pytest.approx(-annualized_sharpe(r), rel=1e-9, abs=1e-12)
    assert hac_tstat_mean(-r)['tstat'] == pytest.approx(-hac_tstat_mean(r)['tstat'], rel=1e-9, abs=1e-12)
    p, q = probabilistic_sharpe_ratio(r), probabilistic_sharpe_ratio(-r)
    assert q['psr'] == pytest.approx(1.0 - p['psr'], abs=1e-9)
    assert q['skew'] == pytest.approx(-p['skew'], rel=1e-9, abs=1e-12)
    assert q['kurtosis'] == pytest.approx(p['kurtosis'], rel=1e-9)


@_profile(200)
@given(r=arrays(np.float64, st.integers(1, 600),
                elements=st.one_of(st.floats(-1, 1), st.just(float('nan')))),
       kind=st.sampled_from(['circular', 'stationary']))
@example(r=np.arange(8.0), kind='circular')
@example(r=np.ones(50), kind='stationary')
def test_block_length_stays_within_its_bounds(r, kind):
    """1 <= b <= ceil(min(3 sqrt(n), n/3)) for n >= 8 finite points; exactly 1 below that."""
    n = int(np.isfinite(r).sum())
    b = politis_white_block_length(r, kind)
    assert np.isfinite(b)
    if n < 8:
        assert b == 1.0
    else:
        assert 1.0 <= b <= max(1.0, math.ceil(min(3 * math.sqrt(n), n / 3)))


# ═══════════════════════════════════════════════════════════════════════════════
# Execution costs
# ═══════════════════════════════════════════════════════════════════════════════

COST = EnhancedPrimeFundTransactionCostModel()
shares_st = st.floats(1, 5e6)
price_st = st.floats(0.5, 2000)
adv_st = st.floats(1e3, 5e8)
vol_st = st.floats(1e-4, 0.25)
COMPONENTS = ('commission', 'bid_ask', 'market_impact', 'total')


def _leg(shares, price, adv, vol):
    return COST.calculate_leg_cost(shares, price, daily_volume_shares=adv, daily_volatility=vol)


def _non_decreasing(lo, hi):
    for k in COMPONENTS:
        assert hi[k] >= lo[k] * (1 - 1e-12) - 1e-12, (k, lo, hi)


@_profile(200)
@given(q=shares_st, dq=st.floats(0, 5e6), price=price_st, adv=adv_st, vol=vol_st)
def test_leg_cost_is_non_negative_and_non_decreasing_in_shares(q, dq, price, adv, vol):
    lo, hi = _leg(q, price, adv, vol), _leg(q + dq, price, adv, vol)
    assert all(lo[k] >= 0 for k in COMPONENTS)
    assert lo['total'] == pytest.approx(lo['commission'] + lo['bid_ask'] + lo['market_impact'])
    _non_decreasing(lo, hi)
    assert _leg(-q, price, adv, vol) == lo                 # a sale costs what a purchase costs


@_profile(200)
@given(q=shares_st, price=price_st, adv=adv_st, vol=vol_st, dvol=st.floats(0, 0.25))
def test_leg_cost_is_non_decreasing_in_volatility(q, price, adv, vol, dvol):
    _non_decreasing(_leg(q, price, adv, vol), _leg(q, price, adv, vol + dvol))


@_profile(200)
@given(q=shares_st, price=price_st, adv=adv_st, shrink=st.floats(1e-3, 1.0), vol=vol_st)
def test_leg_cost_is_non_decreasing_in_illiquidity(q, price, adv, shrink, vol):
    """Less average daily volume means a wider spread bucket and more participation."""
    _non_decreasing(_leg(q, price, adv, vol), _leg(q, price, adv * shrink, vol))


@_profile(100)
@given(q=st.floats(-5e6, 5e6), price=st.one_of(price_st, st.just(0.0), st.just(float('nan'))),
       adv=st.one_of(adv_st, st.none(), st.just(0.0), st.just(float('nan'))),
       vol=st.one_of(vol_st, st.none(), st.just(-0.01), st.just(float('nan'))),
       notional=st.floats(0, 1e8), days=st.integers(-5, 400))
def test_every_cost_is_finite_and_non_negative(q, price, adv, vol, notional, days):
    """Missing or invalid liquidity inputs fall back to defaults; nothing is ever negative."""
    leg = _leg(q, price, adv, vol)
    assert all(np.isfinite(leg[k]) and leg[k] >= 0 for k in COMPONENTS)
    borrow = COST.calculate_borrow_cost(notional, 'X', days)
    carry = COST.calculate_financing_cost(notional, days)
    assert borrow >= 0 and carry >= 0
    assert borrow == pytest.approx(notional * COST.gc_borrow_rate * max(days, 0) / 365)


# ═══════════════════════════════════════════════════════════════════════════════
# Mark-to-market accounting
# ═══════════════════════════════════════════════════════════════════════════════

@st.composite
def trades(draw):
    n = draw(st.integers(2, 40))
    prices = st.floats(1.0, 1000.0)
    c1 = np.array(draw(st.lists(prices, min_size=n, max_size=n)))
    c2 = np.array(draw(st.lists(prices, min_size=n, max_size=n)))
    entry = draw(st.integers(0, n - 1))
    exit_ = draw(st.integers(entry, n - 1))
    q1 = draw(st.floats(-1e6, 1e6))
    q2 = draw(st.floats(-1e6, 1e6))
    e1, e2, x1, x2 = (draw(prices) for _ in range(4))
    return c1, c2, q1, q2, entry, exit_, e1, e2, x1, x2


@_profile(200)
@given(trade=trades())
def test_trade_path_telescopes_to_gross_pnl(trade):
    """The daily marks of a position (fill -> close on the entry day, close -> close in
    between, previous close -> fill on the exit day) sum to q1 (x1 - e1) + q2 (x2 - e2),
    one entry per day from entry to exit; each mark is the change in the position's value."""
    c1, c2, q1, q2, entry, exit_, e1, e2, x1, x2 = trade
    path = S._build_trade_path({'close_ff': c1}, {'close_ff': c2}, q1, q2, entry, exit_, e1, e2, x1, x2)
    assert sorted(path) == list(range(entry, exit_ + 1))
    gross = q1 * (x1 - e1) + q2 * (x2 - e2)
    scale = (abs(q1) + abs(q2)) * 1000.0 * (exit_ - entry + 2)
    assert sum(path.values()) == pytest.approx(gross, abs=1e-12 * scale)
    value = lambda k, p1, p2: q1 * p1 + q2 * p2                    # noqa: E731
    if exit_ > entry:
        for k in range(entry + 1, exit_):
            assert path[k] == pytest.approx(value(k, c1[k], c2[k]) - value(k, c1[k - 1], c2[k - 1]),
                                            abs=1e-12 * scale)
        assert path[entry] == pytest.approx(value(entry, c1[entry], c2[entry]) - value(entry, e1, e2),
                                            abs=1e-12 * scale)


# ═══════════════════════════════════════════════════════════════════════════════
# Causality: nothing dated <= t depends on prices after t
# ═══════════════════════════════════════════════════════════════════════════════

@_profile(40)
@given(seed=st.integers(0, 10_000), n=st.integers(120, 260), cut=st.integers(60, 119),
       shock=st.floats(-0.3, 0.3), hl=st.floats(3.0, 40.0), action=st.sampled_from([0, 1]))
def test_signals_up_to_t_ignore_prices_after_t(seed, n, cut, shock, hl, action):
    """Perturb both legs after row `cut` (a level shock plus noise). The Kalman state, the
    beta-locked signal and the exit scan of every row <= cut are unchanged."""
    p1, p2 = _random_pair(seed, n)
    rng = np.random.default_rng(seed + 1)
    q1, q2 = p1.copy(), p2.copy()
    tail = slice(cut + 1, None)
    q1.iloc[tail] *= np.exp(shock + np.cumsum(rng.normal(0, 0.03, n - cut - 1)))
    q2.iloc[tail] *= np.exp(-shock + np.cumsum(rng.normal(0, 0.03, n - cut - 1)))
    ts = _bare_system()
    a, b = ts.calculate_kalman_state(p1, p2), ts.calculate_kalman_state(q1, q2)
    np.testing.assert_array_equal(a.iloc[:cut + 1].to_numpy(), b.iloc[:cut + 1].to_numpy())
    stats = {'half_life': hl}
    for i in range(30, cut + 1, 7):
        sa, why_a = ts._locked_signal(a, i, stats)
        sb, why_b = ts._locked_signal(b, i, stats)
        assert why_a == why_b
        if sa is not None:
            assert {k: v for k, v in sa.items() if k != 'lk_diffs'} == {k: v for k, v in sb.items() if k != 'lk_diffs'}
            np.testing.assert_array_equal(sa['lk_diffs'], sb['lk_diffs'])
            assert ts._rolling_corr_ok(a, i) == ts._rolling_corr_ok(b, i)
            # the exit rule scanned over rows i+1..cut decides identically
            rows = list(range(i + 1, cut + 1))
            ea = ts._scan_exit(a['lp1'].to_numpy(), a['lp2'].to_numpy(), rows, sa, action, 25)
            eb = ts._scan_exit(b['lp1'].to_numpy(), b['lp2'].to_numpy(), rows, sb, action, 25)
            assert ea == eb


RANGE = ('2023-01-02', '2024-12-31')


@functools.lru_cache(maxsize=None)
def _market(seed):
    return make_market(n_pairs=3, n_noise=0, seed=seed, start='2021-06-01', end='2024-12-31')


@functools.lru_cache(maxsize=None)
def _base_run(seed):
    frames, macro, _ = _market(seed)
    system = build_system(frames, macro)
    return system.run_comprehensive_backtest(system.spread_data, date_range=RANGE)


def _decision(t):
    return (t['pair'], str(pd.Timestamp(t['signal_date']).date()), t['action'], t['position_size'],
            t['zscore'], t['hedge_ratio'])


def _exit_decision(t):
    return (t['pair'], str(pd.Timestamp(t['signal_date']).date()),
            str(pd.Timestamp(t['exit_signal_date']).date()), t['exit_reason'])


# Each example runs the engine twice (~1 s), so shrinking a failure would take minutes:
# the engine property reports the failing example as generated instead.
@settings(derandomize=True, database=None, deadline=None, max_examples=6,
          phases=[Phase.explicit, Phase.generate], suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.sampled_from([3, 8, 21]), day=st.integers(60, 440), pseed=st.integers(0, 1000),
       scale=st.floats(0.01, 0.08))
def test_engine_decisions_up_to_t_ignore_prices_after_t(seed, day, pseed, scale):
    """The whole engine, with a random cutoff and a random alternative future (prices,
    volumes, VIX and sector ETFs): every entry decided on or before the cutoff (its size,
    z-score and hedge ratio), every exit decided on or before it (date and reason), and
    every daily return booked on or before it, are identical."""
    frames, macro, _ = _market(seed)
    cutoff = pd.bdate_range(*RANGE)[day]
    a = _base_run(seed)
    b_sys = build_system(perturb_after(frames, cutoff, seed=pseed, scale=scale),
                         perturb_macro_after(macro, cutoff, seed=pseed + 1, scale=scale))
    b = b_sys.run_comprehensive_backtest(b_sys.spread_data, date_range=RANGE)

    def entries(res):
        return [_decision(t) for t in res['trades']
                if pd.Timestamp(t['signal_date']).tz_localize(None) <= cutoff]

    def exits(res):
        return sorted(_exit_decision(t) for t in res['trades'] if t.get('exit_signal_date') is not None
                      and pd.Timestamp(t['exit_signal_date']).tz_localize(None) <= cutoff)
    assert entries(a) == entries(b)
    assert exits(a) == exits(b)
    da = [(d, r) for d, r in zip(a['daily_dates'], a['daily_returns']) if pd.Timestamp(d) <= cutoff]
    db = [(d, r) for d, r in zip(b['daily_dates'], b['daily_returns']) if pd.Timestamp(d) <= cutoff]
    assert da == db


def test_engine_causality_fixture_is_not_vacuous():
    """The markets used above have decisions before the earliest cutoff the property can
    draw and after the latest one, so every drawn cutoff splits real trading activity."""
    days = pd.bdate_range(*RANGE)
    for seed in (3, 8, 21):
        signals = [pd.Timestamp(t['signal_date']).tz_localize(None) for t in _base_run(seed)['trades']]
        assert sum(s <= days[60] for s in signals) >= 5
        assert sum(s > days[440] for s in signals) >= 5
