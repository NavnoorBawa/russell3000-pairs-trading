"""Tests for the core engine math in trading_system.py.

Covers the pure-ish numerical methods (Kalman spread, max drawdown, Hurst, CUSUM)
that the whole backtest rests on. Instantiating the system is cheap (no data load,
no training) so we do it once per module.
"""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem

RNG = np.random.default_rng(0)


@pytest.fixture(scope="module")
def sys():
    return CompleteFixedRussell3000TradingSystem()


# ── Kalman spread ───────────────────────────────────────────────────────────
def test_kalman_spread_length_and_finite(sys):
    idx = pd.date_range("2022-01-03", periods=300, freq="B")
    p1 = pd.Series(100 * np.exp(np.cumsum(RNG.normal(0, 0.01, 300))), index=idx)
    p2 = pd.Series(100 * np.exp(np.cumsum(RNG.normal(0, 0.01, 300))), index=idx)
    spread = sys.calculate_kalman_spread(p1, p2)
    assert len(spread) == 300
    assert np.isfinite(spread.values).all()


def test_kalman_spread_near_zero_for_identical_series(sys):
    idx = pd.date_range("2022-01-03", periods=200, freq="B")
    p = pd.Series(100 * np.exp(np.cumsum(RNG.normal(0, 0.01, 200))), index=idx)
    spread = sys.calculate_kalman_spread(p, p)        # beta -> 1, spread -> 0
    assert np.abs(spread.values).max() < 1e-6


# ── Max drawdown ────────────────────────────────────────────────────────────
def test_max_drawdown_zero_when_monotonic_up(sys):
    dd = sys._calculate_max_drawdown(np.array([0.01, 0.02, 0.005, 0.01]))
    assert dd == pytest.approx(0.0, abs=1e-12)


def test_max_drawdown_known_value(sys):
    # cum = [1.0, 0.7] -> drawdown -0.30
    dd = sys._calculate_max_drawdown(np.array([0.0, -0.30]))
    assert dd == pytest.approx(-0.30, abs=1e-9)


def test_max_drawdown_is_nonpositive(sys):
    dd = sys._calculate_max_drawdown(RNG.normal(0, 0.02, 200))
    assert dd <= 0.0


# ── Hurst exponent ──────────────────────────────────────────────────────────
def test_hurst_mean_reverting_below_half(sys):
    n = 600
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = 0.5 * s[t - 1] + RNG.normal(0, 1.0)    # strong mean reversion
    assert sys._hurst_exponent(s) < 0.5


def test_hurst_trending_above_half(sys):
    # super-diffusive: positively-autocorrelated increments (momentum), so variance of
    # increments grows faster than linearly -> H > 0.5. (Plain drift does NOT do this —
    # deterministic drift adds no variance, leaving H ~ 0.5.)
    n = 600
    inc = np.zeros(n)
    for t in range(1, n):
        inc[t] = 0.8 * inc[t - 1] + RNG.normal(0, 1.0)
    s = np.cumsum(inc)
    assert sys._hurst_exponent(s) > 0.5


def test_hurst_neutral_on_short_input(sys):
    assert sys._hurst_exponent(np.arange(5.0)) == 0.5  # insufficient data -> neutral


# ── CUSUM structural break ──────────────────────────────────────────────────
def test_cusum_no_break_on_stationary(sys):
    s = pd.Series(RNG.normal(0, 1.0, 300))
    assert sys._cusum_break(s) is False


def test_cusum_break_on_diff_regime_shift(sys):
    # CUSUM runs on standardised FIRST DIFFERENCES, so it flags a regime shift in the
    # differences (not a constant-slope ramp, whose diffs are constant -> sigma~0).
    diffs = np.concatenate([RNG.normal(0, 1.0, 150), RNG.normal(4.0, 1.0, 150)])
    s = pd.Series(np.cumsum(diffs))
    assert sys._cusum_break(s) is True
