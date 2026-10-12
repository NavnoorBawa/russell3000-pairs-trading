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


def _cointegrated_pair(phi, beta=0.6, seed=3):
    """leg2 a random walk; leg1 = beta * leg2 + AR(1)(phi) spread, in log prices."""
    idx = pd.date_range("2021-01-04", periods=N, freq="B")
    local = np.random.default_rng(seed)
    l2 = np.log(80.0) + np.cumsum(local.normal(0, 0.012, N))
    s = np.zeros(N)
    for t in range(1, N):
        s[t] = phi * s[t - 1] + local.normal(0, 0.01)
    l1 = np.log(30.0) + beta * (l2 - l2[0]) + s
    return (pd.DataFrame({"Close": np.exp(l1)}, index=idx),
            pd.DataFrame({"Close": np.exp(l2)}, index=idx))


def test_half_life_finite_for_mean_reverting_spread(selector):
    d1, d2 = _cointegrated_pair(phi=0.9)                      # true HL = -ln2/ln(0.9) ~ 6.6
    hl = selector.calculate_half_life(d1, d2)
    assert 3.0 < hl < 15.0


def test_half_life_uses_the_hedged_spread_not_beta_one(selector):
    """v32: a genuinely cointegrated pair with hedge ratio 0.6 has a short half-life on its
    cointegrating spread; the old beta=1 spread (log p1 - log p2) is a random walk here."""
    d1, d2 = _cointegrated_pair(phi=0.85, beta=0.6)
    assert selector.calculate_half_life(d1, d2) < 15.0
    beta_one = np.log(d1["Close"].to_numpy()) - np.log(d2["Close"].to_numpy())
    y, x = beta_one[1:], beta_one[:-1]
    phi_b1 = np.polyfit(x, y, 1)[0]
    assert -np.log(2) / np.log(phi_b1) > 25.0 if 0 < phi_b1 < 1 else True


def test_half_life_random_walk_much_slower_than_mean_reverting(selector):
    d1_mr, d2_mr = _cointegrated_pair(phi=0.9, seed=7)
    idx = d1_mr.index
    local = np.random.default_rng(11)
    rw1 = pd.DataFrame({"Close": 50.0 * np.exp(np.cumsum(local.normal(0, 0.012, N)))}, index=idx)
    rw2 = pd.DataFrame({"Close": 70.0 * np.exp(np.cumsum(local.normal(0, 0.012, N)))}, index=idx)
    hl_rw = selector.calculate_half_life(rw1, rw2)
    hl_mr = selector.calculate_half_life(d1_mr, d2_mr)
    assert hl_rw > 25.0
    assert hl_rw > hl_mr


def test_cointegration_pvalue_is_bonferroni_over_both_directions(selector):
    d1, d2 = _cointegrated_pair(phi=0.8)
    from statsmodels.tsa.stattools import coint
    l1, l2 = np.log(d1["Close"].to_numpy()), np.log(d2["Close"].to_numpy())
    p12, p21 = coint(l1, l2)[1], coint(l2, l1)[1]
    assert selector.cointegration_pvalue(l1, l2) == pytest.approx(min(1.0, 2 * min(p12, p21)))
    ok, p = selector.test_cointegration(d1, d2)
    assert ok and p < 0.05
