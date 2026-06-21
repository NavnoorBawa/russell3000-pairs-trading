"""Tests for pairs_trading.significance — the "is the edge real?" layer.

All hermetic: synthetic returns, fixed seeds, no data files or network.
"""
import numpy as np
import pytest

from pairs_trading.significance import (
    annualized_sharpe, probabilistic_sharpe_ratio, deflated_sharpe_ratio,
    hac_tstat_mean, block_bootstrap_sharpe_ci, bootstrap_mean_ci,
    oos_window_test, significance_report,
)

RNG = np.random.default_rng(0)


# ── annualized_sharpe ───────────────────────────────────────────────────────
def test_annualized_sharpe_sign_and_zero_variance():
    pos = np.full(300, 0.001)
    assert annualized_sharpe(pos) > 0           # mean > 0 ... but zero variance
    # constant series has zero std -> guarded to 0.0
    assert annualized_sharpe(np.zeros(300)) == 0.0

def test_annualized_sharpe_matches_formula():
    r = RNG.normal(0.0005, 0.01, 5000)
    expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert annualized_sharpe(r) == pytest.approx(expected, rel=1e-9)


# ── Probabilistic Sharpe Ratio ──────────────────────────────────────────────
def test_psr_in_unit_interval():
    r = RNG.normal(0.0003, 0.01, 800)
    out = probabilistic_sharpe_ratio(r)
    assert 0.0 <= out['psr'] <= 1.0

def test_psr_high_for_strong_positive_sharpe():
    r = RNG.normal(0.002, 0.005, 1000)          # strong, many obs
    assert probabilistic_sharpe_ratio(r)['psr'] > 0.95

def test_psr_near_half_for_zero_mean():
    # demean so the SAMPLE Sharpe is exactly 0 -> PSR(SR>0) must be 0.5 (deterministic,
    # independent of the particular random draw)
    r = RNG.normal(0.0, 0.01, 4000)
    r = r - r.mean()
    assert probabilistic_sharpe_ratio(r)['psr'] == pytest.approx(0.5, abs=0.02)

def test_psr_negative_skew_lowers_confidence():
    base = RNG.normal(0.0004, 0.01, 3000)
    # inject a few large negative shocks -> negative skew, same-ish mean
    skewed = base.copy()
    skewed[:30] -= 0.05
    p_sym = probabilistic_sharpe_ratio(base)['psr']
    p_skew = probabilistic_sharpe_ratio(skewed)['psr']
    assert p_skew < p_sym


# ── Newey-West HAC t-stat ───────────────────────────────────────────────────
def test_hac_noise_not_significant():
    # demean -> mean is exactly ~0 -> t-stat ~0, p ~1 (deterministic guard)
    r = RNG.normal(0.0, 0.01, 600)
    r = r - r.mean()
    out = hac_tstat_mean(r)
    assert abs(out['tstat']) < 1e-6
    assert out['pvalue'] > 0.99

def test_hac_strong_mean_significant_and_sign():
    r = RNG.normal(0.003, 0.005, 600)
    out = hac_tstat_mean(r)
    assert out['tstat'] > 2.0
    assert out['pvalue'] < 0.05
    neg = hac_tstat_mean(-r)
    assert neg['tstat'] < 0                       # sign tracks mean


# ── Bootstrap CIs ───────────────────────────────────────────────────────────
def test_block_bootstrap_ci_brackets_point_and_is_deterministic():
    r = RNG.normal(0.0005, 0.01, 600)
    a = block_bootstrap_sharpe_ci(r, seed=42)
    b = block_bootstrap_sharpe_ci(r, seed=42)
    assert a == b                                 # reproducible for a fixed seed
    assert a['lo'] <= a['point'] <= a['hi']

def test_bootstrap_mean_ci_brackets_mean():
    v = RNG.normal(0.01, 0.02, 50)
    ci = bootstrap_mean_ci(v, seed=1)
    assert ci['lo'] <= ci['point'] <= ci['hi']


# ── Deflated Sharpe Ratio ───────────────────────────────────────────────────
def test_dsr_in_unit_interval_and_below_psr():
    r = RNG.normal(0.0008, 0.01, 700)
    psr = probabilistic_sharpe_ratio(r)['psr']
    dsr = deflated_sharpe_ratio(r, n_trials=27)['dsr']
    assert 0.0 <= dsr <= 1.0
    assert dsr <= psr + 1e-9                      # deflating can only lower confidence

def test_dsr_monotonic_in_trials():
    r = RNG.normal(0.0008, 0.01, 700)
    few = deflated_sharpe_ratio(r, n_trials=5)['dsr']
    many = deflated_sharpe_ratio(r, n_trials=500)['dsr']
    assert many <= few                            # more trials -> stricter -> lower DSR


# ── OOS window test ─────────────────────────────────────────────────────────
def test_oos_window_test_keys_and_counts():
    wins = np.array([0.02, -0.01, 0.03, -0.005, 0.01])
    out = oos_window_test(wins)
    assert out['n'] == 5
    assert out['positive'] == 3
    assert 'pvalue' in out and 'ci_lo' in out and 'ci_hi' in out


# ── Top-level report ────────────────────────────────────────────────────────
def test_significance_report_structure():
    daily = RNG.normal(0.0003, 0.01, 500)
    oos_win = np.array([0.01, -0.02, 0.015, 0.0, -0.01])
    oos_daily = RNG.normal(0.0001, 0.012, 300)
    rep = significance_report(daily, oos_window_returns=oos_win,
                              oos_daily_returns=oos_daily, n_trials=27)
    assert 'main_backtest' in rep
    assert 'oos_daily' in rep
    assert 'oos_windows' in rep
    assert 'psr_gt0' in rep['main_backtest']
    assert 'deflated_sharpe' in rep['main_backtest']
