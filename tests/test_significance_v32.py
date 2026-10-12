"""v32 tests for pairs_trading.significance — the audit fixes.

Hermetic: synthetic returns, fixed seeds. Covers the Ledoit-Wolf Sharpe-difference
test and date alignment, Politis-White block length, the Lo (2002) annualisation, PSR /
DSR edge cases, a null-calibration check of the PSR, the CI labelling in the log, and
the one-sided OOS-window p-values.
"""
import logging

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from pairs_trading.significance import (
    align_return_series, block_bootstrap_sharpe_ci, ci_zero_label, deflated_sharpe_ratio,
    lo_annualized_sharpe, log_significance_report, oos_window_test,
    politis_white_block_length, probabilistic_sharpe_ratio, sharpe_difference_test,
    significance_report,
)


def _ar1(phi, n, rng, sd=0.01, burn=200):
    e = rng.normal(0, sd, n + burn)
    x = np.zeros_like(e)
    for t in range(1, len(e)):
        x[t] = phi * x[t - 1] + e[t]
    return x[burn:]


# ── Ledoit-Wolf Sharpe difference ───────────────────────────────────────────

def test_sharpe_difference_identical_series():
    r = np.random.default_rng(0).normal(0.0005, 0.01, 630)
    out = sharpe_difference_test(r, r.copy())
    assert out['diff'] == 0.0 and out['pvalue'] == 1.0
    assert out['ci_lo'] == out['ci_hi'] == 0.0
    assert out['n'] == 630 and out['block'] >= 1


def test_sharpe_difference_detects_a_clear_difference():
    rng = np.random.default_rng(1)
    common = rng.normal(0, 0.008, 630)
    a = common + rng.normal(0.0015, 0.005, 630)                  # annual SR ~ +2.5
    b = common + rng.normal(-0.0010, 0.005, 630)                 # annual SR ~ -1.7
    out = sharpe_difference_test(a, b, n_boot=999)
    assert out['diff'] > 2.0
    assert out['pvalue'] < 0.01
    assert out['ci_lo'] > 0                                      # CI excludes 0
    assert out['diff'] == pytest.approx(out['sharpe_a'] - out['sharpe_b'])


def test_sharpe_difference_is_symmetric_and_deterministic():
    rng = np.random.default_rng(2)
    a, b = rng.normal(0.0006, 0.01, 500), rng.normal(0.0001, 0.012, 500)
    ab = sharpe_difference_test(a, b, n_boot=999, seed=3)
    ba = sharpe_difference_test(b, a, n_boot=999, seed=3)
    assert ab == sharpe_difference_test(a, b, n_boot=999, seed=3)
    assert ba['diff'] == pytest.approx(-ab['diff'])
    assert ba['pvalue'] == pytest.approx(ab['pvalue'])
    assert ba['ci_lo'] == pytest.approx(-ab['ci_hi'])
    assert ba['ci_hi'] == pytest.approx(-ab['ci_lo'])
    for key in ('diff', 'ci_lo', 'ci_hi', 'pvalue', 'n', 'block', 'se', 'sharpe_a', 'sharpe_b'):
        assert key in ab


def test_sharpe_difference_block_override_and_degenerate_inputs():
    rng = np.random.default_rng(4)
    a, b = rng.normal(0.0005, 0.01, 300), rng.normal(0.0, 0.01, 300)
    out = sharpe_difference_test(a, b, block=7, n_boot=199)
    assert out['block'] == 7 and out['block_method'] == 'fixed'
    short = sharpe_difference_test(a[:10], b[:10])
    assert np.isnan(short['pvalue']) and short['n'] == 10
    flat = sharpe_difference_test(np.zeros(100), b[:100])
    assert np.isnan(flat['pvalue'])
    with pytest.raises(ValueError):
        sharpe_difference_test(a, b[:-1])


def test_align_return_series_pairs_by_date():
    da = ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-05']
    ra = [0.01, 0.02, np.nan, 0.03, 0.04]                         # dup date keeps last
    db = pd.DatetimeIndex(['2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'],
                          tz='America/New_York') + pd.Timedelta(hours=16)
    rb = [-0.1, -0.2, -0.3, -0.4]
    dates, xa, xb = align_return_series(da, ra, list(db), rb)
    assert dates == ['2024-01-03', '2024-01-05']                  # 01-04 dropped (NaN)
    assert list(xa) == [0.02, 0.04] and list(xb) == [-0.1, -0.3]
    assert align_return_series([], [], da, ra)[0] == []
    with pytest.raises(ValueError):
        align_return_series(da, ra[:-1], da, ra)


# ── block length ─────────────────────────────────────────────────────────────

def test_politis_white_small_for_iid_larger_for_persistent_series():
    rng = np.random.default_rng(5)
    iid = [politis_white_block_length(rng.normal(0, 1, 630)) for _ in range(10)]
    ar = [politis_white_block_length(_ar1(0.8, 630, rng)) for _ in range(10)]
    assert max(iid) <= 4.0
    assert min(ar) >= 10.0
    assert politis_white_block_length(np.ones(100)) == 1.0
    assert politis_white_block_length(_ar1(0.99, 100, rng)) <= np.ceil(min(3 * np.sqrt(100), 100 / 3))
    # stationary-bootstrap constant is smaller (D_SB = 2 g^2 > D_CB = 4/3 g^2)
    x = _ar1(0.5, 630, rng)
    assert politis_white_block_length(x, 'stationary') < politis_white_block_length(x, 'circular')


def test_bootstrap_ci_uses_automatic_block_by_default():
    rng = np.random.default_rng(6)
    ci_iid = block_bootstrap_sharpe_ci(rng.normal(0.0005, 0.01, 630))
    ci_ar = block_bootstrap_sharpe_ci(_ar1(0.6, 630, rng) + 0.0005)
    assert ci_iid['block_method'] == 'politis-white' and ci_iid['block'] <= 4
    assert ci_ar['block'] > ci_iid['block']
    fixed = block_bootstrap_sharpe_ci(rng.normal(0, 0.01, 200), block=10)
    assert fixed['block'] == 10 and fixed['block_method'] == 'fixed'
    assert fixed['lo'] <= fixed['point'] <= fixed['hi']


# ── Lo (2002) ────────────────────────────────────────────────────────────────

def test_lo_annualisation():
    rng = np.random.default_rng(7)
    r = rng.normal(0.0005, 0.01, 800)
    no_lags = lo_annualized_sharpe(r, max_lag=0)
    assert no_lags['eta'] == pytest.approx(np.sqrt(252))
    assert no_lags['sharpe'] == pytest.approx(no_lags['iid_sharpe'])
    pos = _ar1(0.3, 800, rng) + 0.0005                            # trending P&L
    neg = _ar1(-0.3, 800, rng) + 0.0005
    lp, ln = lo_annualized_sharpe(pos), lo_annualized_sharpe(neg)
    assert lp['sharpe'] < lp['iid_sharpe']                        # positive autocorr deflates
    assert ln['sharpe'] > ln['iid_sharpe']                        # negative autocorr inflates
    assert lp['lags'] >= 1 and len(lp['autocorr']) == lp['lags']


def test_report_battery_has_lo_sharpe_and_null_variance_psr():
    rng = np.random.default_rng(8)
    rep = significance_report(rng.normal(0.0003, 0.01, 400), n_trials=27)
    b = rep['main_backtest']
    assert {'ann_sharpe', 'ann_sharpe_lo', 'lo_eta', 'lo_lags', 'psr_gt0',
            'psr_gt0_null_variance'} <= set(b)
    assert b['psr_gt0_null_variance']['variance_at'] == 'null'


# ── PSR / DSR edge cases ─────────────────────────────────────────────────────

PSR_KEYS = {'psr', 'sr_ann', 'sr_per_period', 'skew', 'kurtosis', 'n', 'benchmark_ann'}


@pytest.mark.parametrize('r', [[0.01, 0.02], [], np.zeros(50), np.full(30, 0.001)])
def test_psr_degenerate_inputs_return_full_key_set(r):
    out = probabilistic_sharpe_ratio(r)
    assert PSR_KEYS <= set(out)
    assert np.isnan(out['psr'])


def test_log_report_survives_degenerate_series(caplog):
    rep = significance_report(np.zeros(50), oos_window_returns=[0.0, 0.0],
                              oos_daily_returns=[0.0, 0.0, 0.0], n_trials=27)
    with caplog.at_level(logging.INFO, logger='pairs_trading.significance'):
        log_significance_report(rep)                          # used to raise KeyError('skew')
        log_significance_report({'main_backtest': {}, 'oos_windows': {}})
    assert 'n/a' in caplog.text


def test_psr_variance_at_null_and_validation():
    rng = np.random.default_rng(9)
    r = rng.normal(0.0004, 0.01, 500)
    out = probabilistic_sharpe_ratio(r, variance_at='null')
    # at a zero benchmark the null variance is 1: PSR = Phi(SR sqrt(n-1))
    assert out['psr'] == pytest.approx(sps.norm.cdf(out['sr_per_period'] * np.sqrt(499)))
    with pytest.raises(ValueError):
        probabilistic_sharpe_ratio(r, variance_at='plugin')


def test_dsr_with_one_trial_equals_psr_vs_zero():
    r = np.random.default_rng(10).normal(0.0004, 0.01, 600)
    d = deflated_sharpe_ratio(r, n_trials=1)
    assert d['sr_star_ann'] == 0.0
    assert d['dsr'] == pytest.approx(probabilistic_sharpe_ratio(r)['psr'])
    assert d['dsr'] < 1.0                                        # was 1.0 (E[max] = -inf)
    assert deflated_sharpe_ratio(r, n_trials=2)['dsr'] < d['dsr']


def test_psr_null_calibration():
    """Under SR = 0 the one-sided 5% PSR test should reject ~5% of the time for IID
    returns (both variance forms), and over-reject for positively autocorrelated ones
    (the IID assumption the HAC t-stat and Lo annualisation are reported to cover)."""
    rng = np.random.default_rng(11)
    M, T = 1500, 630
    iid = rng.normal(0, 0.01, (M, T))
    rej_est = np.mean([probabilistic_sharpe_ratio(x)['psr'] > 0.95 for x in iid])
    rej_null = np.mean([probabilistic_sharpe_ratio(x, variance_at='null')['psr'] > 0.95 for x in iid])
    assert 0.03 <= rej_est <= 0.07
    assert 0.03 <= rej_null <= 0.07
    e = rng.normal(0, 0.01, (400, T + 100))
    ar = np.zeros_like(e)
    for t in range(1, e.shape[1]):
        ar[:, t] = 0.4 * ar[:, t - 1] + e[:, t]
    rej_ar = np.mean([probabilistic_sharpe_ratio(x)['psr'] > 0.95 for x in ar[:, 100:]])
    assert rej_ar > 0.08


# ── labels and OOS windows ───────────────────────────────────────────────────

def test_ci_zero_label():
    assert ci_zero_label(0.2, 1.5) == '(excludes 0: positive)'
    assert ci_zero_label(-2.4, -0.1) == '(excludes 0: negative)'
    assert 'includes 0' in ci_zero_label(-1.0, 0.5)
    assert ci_zero_label(float('nan'), 1.0) == '(n/a)'


def test_log_labels_a_negative_ci_as_negative(caplog):
    r = np.random.default_rng(12).normal(-0.003, 0.01, 600)
    rep = significance_report(r)
    assert rep['main_backtest']['bootstrap_sharpe_ci']['hi'] < 0
    with caplog.at_level(logging.INFO, logger='pairs_trading.significance'):
        log_significance_report(rep)
    assert 'excludes 0: negative' in caplog.text
    assert 'within noise' not in caplog.text


def test_oos_window_one_sided_pvalues():
    v = np.array([-0.004, -0.002, 0.001, -0.006, -0.003, 0.0, -0.001, 0.002, -0.005, 0.0])
    out = oos_window_test(v)
    assert out['pvalue_mean_lt0'] + out['pvalue_mean_gt0'] == pytest.approx(1.0)
    assert out['pvalue_mean_lt0'] == pytest.approx(out['pvalue'] / 2)
    assert out['pvalue_mean_lt0'] < 0.5 < out['pvalue_mean_gt0']
    assert out['ci_method'] == 't'
    small = oos_window_test([0.01])
    assert {'pvalue_mean_lt0', 'pvalue_mean_gt0', 'ci_lo', 'boot_ci_lo'} <= set(small)
