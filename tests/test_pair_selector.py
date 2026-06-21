"""Tests for pairs_trading.pair_selector core statistics (correlation, half-life)."""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.pair_selector import FixedPrimeFundPairSelector

RNG = np.random.default_rng(0)
N = 480   # > min_common_days (420)


@pytest.fixture
def selector():
    return FixedPrimeFundPairSelector()


def _df_from_returns(returns, idx):
    close = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame({"Close": close, "Returns": returns}, index=idx)


def test_correlation_high_for_correlated_returns(selector):
    idx = pd.date_range("2021-01-04", periods=N, freq="B")
    r1 = RNG.normal(0, 0.01, N)
    r2 = 0.85 * r1 + 0.15 * RNG.normal(0, 0.01, N)
    c = selector.calculate_correlation(_df_from_returns(r1, idx), _df_from_returns(r2, idx))
    assert c > 0.7


def test_correlation_low_for_independent_returns(selector):
    idx = pd.date_range("2021-01-04", periods=N, freq="B")
    r1 = RNG.normal(0, 0.01, N)
    r2 = RNG.normal(0, 0.01, N)
    c = selector.calculate_correlation(_df_from_returns(r1, idx), _df_from_returns(r2, idx))
    assert abs(c) < 0.2


def test_half_life_finite_for_mean_reverting_spread(selector):
    idx = pd.date_range("2021-01-04", periods=N, freq="B")
    phi = 0.9                                   # HL = -ln2/ln(0.9) ~ 6.58
    s = np.zeros(N)
    for t in range(1, N):
        s[t] = phi * s[t - 1] + RNG.normal(0, 0.01)
    p1 = pd.DataFrame({"Close": 100.0 * np.exp(s)}, index=idx)
    p2 = pd.DataFrame({"Close": np.full(N, 100.0)}, index=idx)
    hl = selector.calculate_half_life(p1, p2)
    assert 2.0 < hl < 20.0                       # in the right ballpark, not the 999 sentinel


def test_half_life_random_walk_much_slower_than_mean_reverting(selector):
    # A random walk reverts far slower than an AR(1) with phi=0.9. In finite samples the
    # estimated half-life is large (well above the 25-day max_half_life filter) rather than
    # exactly the 999 sentinel, so assert the meaningful property: rw >> mean-reverting.
    idx = pd.date_range("2021-01-04", periods=N, freq="B")
    local = np.random.default_rng(7)
    rw = np.cumsum(local.normal(0, 0.01, N))
    mr = np.zeros(N)
    for t in range(1, N):
        mr[t] = 0.9 * mr[t - 1] + local.normal(0, 0.01)
    p2 = pd.DataFrame({"Close": np.full(N, 100.0)}, index=idx)
    hl_rw = selector.calculate_half_life(
        pd.DataFrame({"Close": 100.0 * np.exp(rw)}, index=idx), p2)
    hl_mr = selector.calculate_half_life(
        pd.DataFrame({"Close": 100.0 * np.exp(mr)}, index=idx), p2)
    assert hl_rw > 25.0                          # above the max_half_life filter
    assert hl_rw > hl_mr


def test_pair_statistics_starts_empty(selector):
    assert selector.pair_statistics == {}
    assert selector.selected_pairs == []
